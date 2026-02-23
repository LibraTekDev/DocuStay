"""Module H: Notification service (Mailgun/SendGrid email, optional SMS)."""
from app.config import get_settings

# Clear settings cache so we use latest .env when sending (fixes server vs script using different config)
def _get_fresh_settings():
    get_settings.cache_clear()
    return get_settings()


def send_email(to_email: str, subject: str, html_content: str, text_content: str | None = None) -> bool:
    """Send email via Mailgun (preferred) or SendGrid. Returns True if sent (or skipped when unconfigured)."""
    # Use fresh settings when called from send_verification_email (cache was cleared there)
    settings = get_settings()
    has_key = bool(settings.mailgun_api_key)
    has_domain = bool(settings.mailgun_domain)
    if has_key and has_domain:
        print(f"[Email] Calling Mailgun API: to={to_email} subject={subject} domain={settings.mailgun_domain}", flush=True)
        return _send_email_mailgun(to_email, subject, html_content, text_content=text_content, settings=settings)
    if settings.sendgrid_api_key:
        return _send_email_sendgrid(to_email, subject, html_content, text_content=text_content, settings=settings)
    print(
        f"[Email] NOT SENT: to={to_email} subject={subject}. MAILGUN_API_KEY={'set' if has_key else 'MISSING'} MAILGUN_DOMAIN={'set' if has_domain else 'MISSING'}. "
        "Set both in .env and restart the server.",
        flush=True,
    )
    return False


MAILGUN_US_BASE = "https://api.mailgun.net"
MAILGUN_EU_BASE = "https://api.eu.mailgun.net"


def _send_email_mailgun(to_email: str, subject: str, html_content: str, text_content: str | None = None, settings=None):
    if settings is None:
        settings = get_settings()
    try:
        import httpx

        base = (settings.mailgun_base_url or MAILGUN_US_BASE).strip().rstrip("/")
        domain = (settings.mailgun_domain or "").strip().lower()
        from_addr = (settings.mailgun_from_email or "").strip()
        from_domain = from_addr.split("@")[-1].lower() if "@" in from_addr else ""
        if domain and from_domain != domain:
            from_addr = f"noreply@{domain}"
            print(f"[Mailgun] Using from={from_addr} (must match domain {domain} for delivery)", flush=True)
        from_email = f"{settings.mailgun_from_name} <{from_addr}>"
        url = f"{base}/v3/{domain}/messages"
        data = {
            "from": from_email,
            "to": to_email,
            "subject": subject,
            "text": text_content or "",
            "html": html_content or "",
        }
        with httpx.Client(timeout=10.0) as client:
            r = client.post(url, auth=("api", settings.mailgun_api_key), data=data)
            ok = 200 <= r.status_code < 300
            if ok:
                try:
                    msg_id = (r.json() or {}).get("id", "")
                except Exception:
                    msg_id = ""
                print(
                    f"[Mailgun] API success: to={to_email} status={r.status_code} id={msg_id}",
                    flush=True,
                )
                print(
                    "[Mailgun] If you do not receive the email: (1) Check spam/junk. "
                    "(2) If using a Mailgun SANDBOX domain, add this address in Dashboard > Sending > Authorized recipients.",
                    flush=True,
                )
                return True
            if r.status_code == 401 and base == MAILGUN_US_BASE:
                print("[Mailgun] 401 with US endpoint. Retrying with EU endpoint...", flush=True)
                url_eu = f"{MAILGUN_EU_BASE}/v3/{domain}/messages"
                r2 = client.post(url_eu, auth=("api", settings.mailgun_api_key), data=data)
                if 200 <= r2.status_code < 300:
                    print(f"[Mailgun] API success (EU): to={to_email}. If email not received, check spam or add recipient in Mailgun sandbox.", flush=True)
                    return True
                print(f"[Mailgun] EU request failed: status={r2.status_code} body={r2.text}", flush=True)
                return False
            err_body = r.text
            print(f"[Mailgun] API failed: status={r.status_code} to={to_email} body={err_body[:500]}", flush=True)
            return False
    except Exception as e:
        print(f"[Mailgun] Exception: to={to_email} error={type(e).__name__}: {e}", flush=True)
        return False


def _send_email_sendgrid(to_email: str, subject: str, html_content: str, text_content: str | None = None, settings=None) -> bool:
    if settings is None:
        settings = get_settings()
    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail

        message = Mail(
            from_email=(settings.sendgrid_from_email, settings.sendgrid_from_name),
            to_emails=to_email,
            subject=subject,
            html_content=html_content,
            plain_text_content=text_content or "",
        )
        sg = SendGridAPIClient(settings.sendgrid_api_key)
        sg.send(message)
        return True
    except Exception:
        return False


def send_verification_email(to_email: str, code: str) -> bool:
    """Send 6-digit verification code email for signup. Uses same Mailgun path as test-email (send_email -> _send_email_mailgun)."""
    # Use fresh settings so UI flow sees same .env as script (avoids stale cache when server started before .env had Mailgun)
    _get_fresh_settings()
    s = get_settings()
    domain = (s.mailgun_domain or "").strip() or "(none)"
    from_addr = (getattr(s, "mailgun_from_email", None) or "").strip() or "(none)"
    print(f"[Verification] Sending code to {to_email} domain={domain} from={from_addr} code_len={len(code) if code else 0}", flush=True)
    subject = "[DocuStay] Your verification code"
    text_content = f"Your DocuStay verification code is: {code}. It expires in 10 minutes."
    html_content = f"""
    <p>Hello,</p>
    <p>Your DocuStay verification code is: <strong style="font-size:1.2em;letter-spacing:0.2em;">{code}</strong></p>
    <p>This code expires in 10 minutes. If you did not request this, you can ignore this email.</p>
    <p>— DocuStay</p>
    """
    print(f"[Verification] Calling send_email (Mailgun if configured) for {to_email}", flush=True)
    ok = send_email(to_email, subject, html_content, text_content=text_content)
    if ok:
        print(f"[Verification] Sent successfully to {to_email}. If not received, check spam and Mailgun sandbox (add recipient in dashboard).", flush=True)
    return ok


def send_owner_welcome_email(to_email: str, full_name: str | None = None) -> bool:
    """Send welcome email when owner successfully signs up (after email verification)."""
    name = (full_name or "").strip() or "there"
    subject = "[DocuStay] Welcome – your account is verified"
    text = f"Hi {name}, welcome to DocuStay. Your account is verified and you can now sign in and manage your properties."
    html = f"""
    <p>Hi {name},</p>
    <p>Welcome to <strong>DocuStay</strong>. Your account is verified and you're all set.</p>
    <p>You can now sign in to create properties, send invitations, and manage temporary stays with legal clarity.</p>
    <p>— DocuStay</p>
    """
    return send_email(to_email, subject, html, text_content=text)


def send_guest_signup_welcome_email(to_email: str, full_name: str | None = None) -> bool:
    """Send welcome email when a guest signs up (no stay yet – e.g. no invite or invite not yet accepted)."""
    name = (full_name or "").strip() or "there"
    subject = "[DocuStay] Welcome – your account is ready"
    text = f"Hi {name}, welcome to DocuStay. Your guest account is ready. Sign in to add invitation links from your hosts and manage your stays."
    html = f"""
    <p>Hi {name},</p>
    <p>Welcome to <strong>DocuStay</strong>. Your guest account is ready.</p>
    <p>Sign in to add invitation links from your hosts, view and sign agreements, and manage your temporary stays with legal clarity.</p>
    <p>— DocuStay</p>
    """
    return send_email(to_email, subject, html, text_content=text)


def send_guest_welcome_email(
    to_email: str,
    full_name: str | None = None,
    property_name: str = "the property",
    stay_end_date: str | None = None,
) -> bool:
    """Send welcome email when guest successfully signs up with an accepted invite (stay created)."""
    name = (full_name or "").strip() or "there"
    end_line = f" Your authorized stay ends on <strong>{stay_end_date}</strong>." if stay_end_date else ""
    subject = "[DocuStay] Welcome – you're registered"
    text = f"Hi {name}, welcome to DocuStay. You're registered for {property_name}.{end_line}"
    html = f"""
    <p>Hi {name},</p>
    <p>Welcome to <strong>DocuStay</strong>. You're successfully registered for <strong>{property_name}</strong>.</p>
    <p>{end_line or "You can sign in to view your stay details and authorization."}</p>
    <p>— DocuStay</p>
    """
    return send_email(to_email, subject, html, text_content=text)


def send_guest_stay_added_email(
    to_email: str,
    full_name: str | None,
    property_name: str,
    stay_end_date: str,
) -> bool:
    """Notify existing guest when they accept a new invitation (stay added)."""
    name = (full_name or "").strip() or "there"
    subject = "[DocuStay] New stay added – " + property_name
    html = f"""
    <p>Hi {name},</p>
    <p>A new stay has been added to your account at <strong>{property_name}</strong>.</p>
    <p><strong>Authorized end date:</strong> {stay_end_date}</p>
    <p>Sign in to view your stay details.</p>
    <p>— DocuStay</p>
    """
    return send_email(to_email, subject, html)


def send_stay_ending_soon(
    to_email: str,
    guest_name: str,
    stay_end_date: str,
    region_code: str,
    is_owner: bool,
    property_name: str = "Property",
) -> bool:
    """Friendly reminder when a guest's stay is coming to an end (within configured days)."""
    if is_owner:
        subject = f"[DocuStay] Reminder: {guest_name}'s stay ends soon – {region_code}"
        intro = f"A stay for <strong>{guest_name}</strong> at <strong>{property_name}</strong> is coming to an end."
    else:
        subject = f"[DocuStay] Reminder: your stay ends soon – {region_code}"
        intro = f"Your authorized stay at <strong>{property_name}</strong> is coming to an end."
    html = f"""
    <p>Hello,</p>
    <p>{intro}</p>
    <p><strong>End date:</strong> {stay_end_date}</p>
    <p><strong>Region:</strong> {region_code}</p>
    <p>Please ensure checkout by this date to stay within your authorized period.</p>
    <p>— DocuStay</p>
    """
    return send_email(to_email, subject, html)


def send_overstay_alert(
    to_email: str,
    guest_name: str,
    stay_end_date: str,
    region_code: str,
    is_owner: bool,
    property_name: str = "Property",
) -> bool:
    """Alert when a stay has passed its end date (overstay triggered)."""
    if is_owner:
        subject = f"[DocuStay] Overstay alert: {guest_name} – {region_code}"
        body = (
            f"The authorized stay for <strong>{guest_name}</strong> at <strong>{property_name}</strong> "
            f"ended on <strong>{stay_end_date}</strong>. The guest may still be at the property."
        )
    else:
        subject = f"[DocuStay] Overstay notice: your stay has ended – {region_code}"
        body = (
            f"Your authorized stay at <strong>{property_name}</strong> ended on <strong>{stay_end_date}</strong>. "
            "Please vacate and complete checkout to avoid legal complications."
        )
    html = f"""
    <p>Hello,</p>
    <p>{body}</p>
    <p><strong>Region:</strong> {region_code}</p>
    <p>— DocuStay</p>
    """
    return send_email(to_email, subject, html)


def send_vacate_12h_notice(
    to_email: str,
    guest_name: str,
    property_name: str,
    vacate_by_iso: str,
    region_code: str = "",
) -> bool:
    """Email to guest when owner revokes stay (Kill Switch): must vacate within 12 hours."""
    subject = "[DocuStay] Urgent: You must vacate the property within 12 hours"
    html = f"""
    <p>Hello {guest_name},</p>
    <p>Your stay authorization at <strong>{property_name}</strong> has been revoked by the property owner.</p>
    <p><strong>You must vacate the property within 12 hours.</strong></p>
    <p><strong>Vacate by:</strong> {vacate_by_iso}</p>
    <p>Please remove all belongings and complete checkout by this time to avoid further action.</p>
    <p>— DocuStay</p>
    """
    text = f"Hello {guest_name}, your stay at {property_name} has been revoked. You must vacate within 12 hours. Vacate by: {vacate_by_iso}. — DocuStay"
    return send_email(to_email, subject, html, text_content=text)


def send_removal_notice_to_guest(
    to_email: str,
    guest_name: str,
    property_name: str,
    region_code: str = "",
) -> bool:
    """Email to guest when owner initiates formal removal for overstay."""
    subject = "[DocuStay] NOTICE: Removal Initiated – You must vacate immediately"
    html = f"""
    <p>Hello {guest_name},</p>
    <p>The property owner has initiated formal removal proceedings for <strong>{property_name}</strong>.</p>
    <p><strong>Your utility access (USAT token) has been revoked.</strong></p>
    <p>You are in overstay status and must vacate the property immediately. Continued presence may result in law enforcement involvement.</p>
    <p>Please remove all belongings and vacate as soon as possible to avoid further legal action.</p>
    <p>— DocuStay</p>
    """
    text = f"Hello {guest_name}, the owner has initiated removal for {property_name}. Your USAT token has been revoked. You must vacate immediately. — DocuStay"
    return send_email(to_email, subject, html, text_content=text)


def send_removal_confirmation_to_owner(
    owner_email: str,
    guest_name: str,
    property_name: str,
    region_code: str = "",
) -> bool:
    """Email to owner confirming removal has been initiated."""
    subject = f"[DocuStay] Removal Initiated – {guest_name} at {property_name}"
    html = f"""
    <p>Hello,</p>
    <p>You have initiated formal removal for <strong>{guest_name}</strong> at <strong>{property_name}</strong>.</p>
    <p><strong>Actions taken:</strong></p>
    <ul>
        <li>Guest's USAT token has been revoked (utility access disabled)</li>
        <li>Guest has been notified via email to vacate immediately</li>
        <li>All actions logged for legal documentation</li>
    </ul>
    <p>If the guest does not vacate, you may contact local law enforcement with the documentation from your DocuStay dashboard.</p>
    <p>— DocuStay</p>
    """
    text = f"Hello, you have initiated removal for {guest_name} at {property_name}. USAT token revoked. Guest notified. — DocuStay"
    return send_email(owner_email, subject, html, text_content=text)


def send_owner_guest_checkout_email(
    owner_email: str,
    guest_name: str,
    property_name: str,
    stay_end_date: str,
) -> bool:
    """Email to owner when a guest completes checkout (ends their stay)."""
    subject = f"[DocuStay] Guest checked out – {guest_name} at {property_name}"
    html = f"""
    <p>Hello,</p>
    <p><strong>{guest_name}</strong> has completed checkout for their stay at <strong>{property_name}</strong>.</p>
    <p><strong>Checkout date:</strong> {stay_end_date}</p>
    <p>The stay is now ended and all statuses have been updated.</p>
    <p>— DocuStay</p>
    """
    return send_email(owner_email, subject, html)


def send_guest_checkout_confirmation_email(
    guest_email: str,
    guest_name: str,
    property_name: str,
    stay_end_date: str,
) -> bool:
    """Email to guest confirming their checkout."""
    subject = f"[DocuStay] Checkout Confirmed – {property_name}"
    html = f"""
    <p>Hello {guest_name},</p>
    <p>Your checkout from <strong>{property_name}</strong> has been confirmed.</p>
    <p><strong>Checkout date:</strong> {stay_end_date}</p>
    <p>Thank you for using DocuStay. Your stay record has been updated.</p>
    <p>— DocuStay</p>
    """
    return send_email(guest_email, subject, html)


def send_owner_guest_cancelled_stay_email(
    owner_email: str,
    guest_name: str,
    property_name: str,
    stay_start_date: str,
) -> bool:
    """Email to owner when a guest cancels a future stay."""
    subject = f"[DocuStay] Guest cancelled stay – {guest_name} at {property_name}"
    html = f"""
    <p>Hello,</p>
    <p><strong>{guest_name}</strong> has cancelled their upcoming stay at <strong>{property_name}</strong> (was scheduled to start {stay_start_date}).</p>
    <p>The stay is no longer active.</p>
    <p>— DocuStay</p>
    """
    return send_email(owner_email, subject, html)


def send_stay_legal_warning(
    to_email: str,
    guest_name: str,
    stay_end_date: str,
    region_code: str,
    statute_ref: str,
    is_owner: bool,
) -> bool:
    """Module G: Legal warning email (region, statute, tenancy risk)."""
    subject = f"[DocuStay] Legal notice: stay approaching limit – {region_code}"
    html = f"""
    <p>Hello,</p>
    <p>This is a legal notice regarding the stay for <strong>{guest_name}</strong>.</p>
    <p><strong>Stay end date:</strong> {stay_end_date}</p>
    <p><strong>Region:</strong> {region_code}</p>
    <p><strong>Applicable law:</strong> {statute_ref}</p>
    <p>Continued occupancy beyond the authorized period may create tenancy rights. Please ensure checkout by the end date.</p>
    <p>— DocuStay</p>
    """
    return send_email(to_email, subject, html)


def send_dead_mans_switch_48h_before(
    owner_email: str,
    guest_name: str,
    property_name: str,
    stay_end_date: str,
) -> bool:
    """Dead Man's Switch: 48 hours before lease end – 'Renewal or Vacancy?'"""
    subject = f"[DocuStay] Dead Man's Switch – {guest_name}'s stay ends in 2 days"
    html = f"""
    <p>Hello,</p>
    <p><strong>Dead Man's Switch alert:</strong> The stay for <strong>{guest_name}</strong> at <strong>{property_name}</strong> ends in 2 days.</p>
    <p><strong>Lease end date:</strong> {stay_end_date}</p>
    <p>Please confirm in DocuStay: has the guest renewed or moved out? If you do not update the stay (checkout or renew) within 48 hours after the end date, the system will automatically set the property to vacant and activate protective measures (utility lock, trespass detection, authority letters).</p>
    <p>— DocuStay</p>
    """
    return send_email(owner_email, subject, html)


def send_dead_mans_switch_urgent_today(
    owner_email: str,
    guest_name: str,
    property_name: str,
    stay_end_date: str,
) -> bool:
    """Dead Man's Switch: on lease end date – 'Has she renewed?'"""
    subject = f"[DocuStay] URGENT – {guest_name}'s stay ends TODAY"
    html = f"""
    <p>Hello,</p>
    <p><strong>Dead Man's Switch – urgent:</strong> The stay for <strong>{guest_name}</strong> at <strong>{property_name}</strong> ends <strong>today</strong> ({stay_end_date}).</p>
    <p>Please update DocuStay: mark checkout if the guest has left, or extend the stay if renewed. If no action is taken within 48 hours, the system will automatically set the property to vacant and activate protective measures.</p>
    <p>— DocuStay</p>
    """
    return send_email(owner_email, subject, html)


def send_dead_mans_switch_auto_executed(
    owner_email: str,
    guest_name: str,
    property_name: str,
    stay_end_date: str,
) -> bool:
    """Dead Man's Switch: after auto-execution – notify owner what was done."""
    subject = f"[DocuStay] Dead Man's Switch executed – {property_name}"
    html = f"""
    <p>Hello,</p>
    <p><strong>Dead Man's Switch has been automatically executed</strong> for the stay of <strong>{guest_name}</strong> at <strong>{property_name}</strong> (lease end was {stay_end_date}). No response was received within 48 hours after the end date.</p>
    <p>The system has automatically:</p>
    <ul>
        <li>Set occupancy status to UNCONFIRMED (no response by deadline)</li>
        <li>Triggered Active Enforcement (Shield Mode activated)</li>
        <li>Activated utility lock (USAT token staged)</li>
        <li>Armed trespass detection</li>
        <li>Logged authority letters and police Live-Share for your records</li>
    </ul>
    <p>You can review and adjust settings in your DocuStay dashboard.</p>
    <p>— DocuStay</p>
    """
    return send_email(owner_email, subject, html)


def send_shield_mode_activated_email(
    owner_email: str,
    property_name: str,
    *,
    triggered_by_dead_mans_switch: bool = False,
    last_day_of_stay: bool = False,
    guest_name: str | None = None,
) -> bool:
    """Notify owner when Shield Mode is activated (on last day of stay or by Dead Man's Switch)."""
    if triggered_by_dead_mans_switch:
        subject = f"[DocuStay] Shield Mode activated – {property_name}"
        html = f"""
    <p>Hello,</p>
    <p><strong>Shield Mode has been automatically activated</strong> for <strong>{property_name}</strong>.</p>
    <p>This was triggered by the Dead Man's Switch (no response received within 48 hours after the stay end date). Your property is now in <strong>Active Enforcement</strong>: occupancy set to vacant, utility lock on, trespass detection armed.</p>
    <p>You can turn Shield Mode off anytime in your DocuStay dashboard.</p>
    <p>— DocuStay</p>
    """
    elif last_day_of_stay:
        guest = f" ({guest_name})" if guest_name else ""
        subject = f"[DocuStay] Shield Mode activated – {property_name}"
        html = f"""
    <p>Hello,</p>
    <p><strong>Shield Mode has been automatically activated</strong> for <strong>{property_name}</strong>.</p>
    <p>Today is the last day of your guest's stay{guest}. Shield Mode is now on to protect the property. DocuStay is actively monitoring and enforcing.</p>
    <p>You can turn Shield Mode off anytime in your DocuStay dashboard.</p>
    <p>— DocuStay</p>
    """
    else:
        subject = f"[DocuStay] Shield Mode activated – {property_name}"
        html = f"""
    <p>Hello,</p>
    <p><strong>Shield Mode has been activated</strong> for <strong>{property_name}</strong>.</p>
    <p>DocuStay is now actively monitoring and enforcing for this property. You can turn it off anytime in your dashboard.</p>
    <p>— DocuStay</p>
    """
    return send_email(owner_email, subject, html)


def send_sms(to_phone: str, body: str) -> bool:
    """Optional SMS via Twilio."""
    if not settings.twilio_account_sid or not settings.twilio_auth_token:
        return False
    try:
        from twilio.rest import Client
        client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        client.messages.create(body=body, from_=settings.twilio_from_phone_number, to=to_phone)
        return True
    except Exception:
        return False
