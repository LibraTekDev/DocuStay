"""Public API (no auth): live property page by slug – evidence view; verify portal."""
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models.owner import Property, OwnerProfile
from app.services.privacy_lanes import is_tenant_lane_invitation, is_tenant_lane_stay, filter_tenant_lane_from_ledger_rows
from app.models.unit import Unit
from app.models.user import User
from app.models.stay import Stay
from app.models.guest import GuestProfile
from app.models.audit_log import AuditLog
from app.models.event_ledger import EventLedger
from app.models.invitation import Invitation
from app.models.owner_poa_signature import OwnerPOASignature
from app.models.agreement_signature import AgreementSignature
from app.services.agreements import agreement_content_to_pdf, fill_guest_signature_in_content, poa_content_with_signature
from app.services.dropbox_sign import get_signed_pdf
from app.services.audit_log import create_log, CATEGORY_VERIFY_ATTEMPT, CATEGORY_FAILED_ATTEMPT
from app.services.event_ledger import create_ledger_event, ledger_event_to_display, ACTION_VERIFY_ATTEMPT_VALID, ACTION_VERIFY_ATTEMPT_FAILED
from app.schemas.public import (
    LivePropertyPagePayload,
    LivePropertyInfo,
    LiveOwnerInfo,
    LiveCurrentGuestInfo,
    LiveStaySummary,
    LiveInvitationSummary,
    LiveLogEntry,
    JurisdictionWrap,
    JurisdictionStatuteView,
    PortfolioPagePayload,
    PortfolioOwnerInfo,
    PortfolioPropertyItem,
    VerifyRequest,
    VerifyResponse,
)

router = APIRouter(prefix="/public", tags=["public"])


def _is_active_stay(s: Stay) -> bool:
    """True if stay is checked in and not checked out/cancelled (current guest)."""
    if getattr(s, "checked_in_at", None) is None:
        return False
    if getattr(s, "checked_out_at", None) is not None:
        return False
    if getattr(s, "cancelled_at", None) is not None:
        return False
    return True


@router.get("/live/{slug}", response_model=LivePropertyPagePayload)
def get_live_property_page(slug: str, db: Session = Depends(get_db)):
    """
    Public live property page by unique slug (no auth).
    Returns property info, owner contact, and either current guest + logs
    or last stay, upcoming stays, and mode/status + logs.
    """
    if not slug or not slug.strip():
        raise HTTPException(status_code=404, detail="Not found")
    slug = slug.strip()
    prop = db.query(Property).filter(Property.live_slug == slug, Property.deleted_at.is_(None)).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    profile = db.query(OwnerProfile).filter(OwnerProfile.id == prop.owner_profile_id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Property not found")
    owner_user = db.query(User).filter(User.id == profile.user_id).first()
    owner_name = (owner_user.full_name if owner_user else None) or None
    owner_email = (owner_user.email if owner_user else "") or ""
    owner_phone = getattr(owner_user, "phone", None) if owner_user else None
    owner_info = LiveOwnerInfo(full_name=owner_name, email=owner_email, phone=owner_phone)

    token_state = getattr(prop, "usat_token_state", None) or "staged"
    prop_info = LivePropertyInfo(
        name=prop.name,
        street=prop.street,
        city=prop.city,
        state=prop.state,
        zip_code=prop.zip_code,
        region_code=prop.region_code,
        occupancy_status=getattr(prop, "occupancy_status", None) or "unknown",
        shield_mode_enabled=bool(getattr(prop, "shield_mode_enabled", 0)),
        token_state=token_state,
        tax_id=getattr(prop, "tax_id", None) or None,
        apn=getattr(prop, "apn", None) or None,
    )

    # Jurisdictional wrap: applicable law for this property (zip → region → statutes)
    jurisdiction_wrap = None
    from app.services.jurisdiction_sot import get_jurisdiction_for_property
    jinfo = get_jurisdiction_for_property(db, prop.zip_code, prop.region_code)
    if jinfo:
        jurisdiction_wrap = JurisdictionWrap(
            state_name=jinfo.name,
            applicable_statutes=[
                JurisdictionStatuteView(citation=s.citation, plain_english=s.plain_english)
                for s in jinfo.statutes
            ],
            removal_guest_text=jinfo.removal_guest_text,
            removal_tenant_text=jinfo.removal_tenant_text,
            agreement_type=jinfo.agreement_type,
        )

    # POA for Authority layer
    poa_signed_at: datetime | None = None
    poa_signature_id: int | None = None
    if profile and profile.user_id:
        poa_sig = (
            db.query(OwnerPOASignature)
            .filter(OwnerPOASignature.used_by_user_id == profile.user_id)
            .first()
        )
        if poa_sig:
            poa_signed_at = poa_sig.signed_at
            poa_signature_id = poa_sig.id

    today = date.today()
    # Current stay: active (not checked out, not cancelled) and not in the past only by end date
    current_stays = [
        s
        for s in db.query(Stay).filter(Stay.property_id == prop.id).all()
        if _is_active_stay(s)
    ]
    # Prefer the one that is "ongoing" (start <= today <= end or end in future)
    current_stay = None
    for s in current_stays:
        if s.stay_end_date >= today and s.stay_start_date <= today:
            current_stay = s
            break
    if not current_stay and current_stays:
        # Overstay: end date passed but not checked out
        current_stay = max(current_stays, key=lambda x: (x.stay_end_date, x.id))

    # Logs for this property from event ledger (exclude tenant-lane: owners/managers/public must never see tenant guest activity)
    log_rows = (
        db.query(EventLedger)
        .filter(EventLedger.property_id == prop.id)
        .order_by(EventLedger.created_at.desc())
        .limit(100)
    ).all()
    log_rows = filter_tenant_lane_from_ledger_rows(db, log_rows)
    logs = []
    for r in log_rows:
        cat, title, msg = ledger_event_to_display(r)
        logs.append(
            LiveLogEntry(
                category=cat,
                title=title,
                message=msg,
                created_at=r.created_at if r.created_at is not None else datetime.now(timezone.utc),
            )
        )

    # Invitations for this property – invite states indicate stay status (STAGED→pending, BURNED→accepted/stay, EXPIRED→ended, REVOKED→cancelled)
    inv_rows = (
        db.query(Invitation)
        .filter(Invitation.property_id == prop.id)
        .order_by(Invitation.created_at.desc())
        .limit(50)
    ).all()
    invitations = []
    for inv in inv_rows:
        # Tenant-invited guest names are private; show "Guest" on public page
        guest_label = None
        if not is_tenant_lane_invitation(db, inv):
            guest_label = (inv.guest_name or inv.guest_email or "").strip() or None
        if guest_label is None:
            guest_label = "Guest"
        invitations.append(
            LiveInvitationSummary(
                invitation_code=inv.invitation_code,
                guest_label=guest_label,
                stay_start_date=inv.stay_start_date,
                stay_end_date=inv.stay_end_date,
                status=inv.status or "pending",
                token_state=getattr(inv, "token_state", None) or "STAGED",
            )
        )

    if current_stay:
        authorization_state = "REVOKED" if getattr(current_stay, "revoked_at", None) else "ACTIVE"
        if is_tenant_lane_stay(db, current_stay):
            guest_name = "Guest"  # Tenant-invited guest names are private
        else:
            guest = db.query(User).filter(User.id == current_stay.guest_id).first()
            guest_profile = db.query(GuestProfile).filter(GuestProfile.user_id == current_stay.guest_id).first()
            guest_name = (guest_profile.full_legal_name if guest_profile else None) or (guest.full_name if guest else None) or (guest.email if guest else "Guest")
        return LivePropertyPagePayload(
            has_current_guest=True,
            property=prop_info,
            owner=owner_info,
            current_guest=LiveCurrentGuestInfo(
                guest_name=guest_name,
                stay_start_date=current_stay.stay_start_date,
                stay_end_date=current_stay.stay_end_date,
                checked_out_at=getattr(current_stay, "checked_out_at", None),
                dead_mans_switch_enabled=bool(getattr(current_stay, "dead_mans_switch_enabled", 0)),
            ),
            last_stay=None,
            upcoming_stays=[],
            invitations=invitations,
            logs=logs,
            authorization_state=authorization_state,
            record_id=slug,
            generated_at=datetime.now(timezone.utc),
            poa_signed_at=poa_signed_at,
            poa_signature_id=poa_signature_id,
            jurisdiction_wrap=jurisdiction_wrap,
        )

    # No current guest: last stay (most recent ended) and upcoming
    all_stays = db.query(Stay).filter(Stay.property_id == prop.id).order_by(Stay.stay_end_date.desc()).all()
    last_stay = None
    for s in all_stays:
        if getattr(s, "checked_out_at", None) is not None or s.stay_end_date < today:
            if is_tenant_lane_stay(db, s):
                gn = "Guest"
            else:
                guest = db.query(User).filter(User.id == s.guest_id).first()
                gp = db.query(GuestProfile).filter(GuestProfile.user_id == s.guest_id).first()
                gn = (gp.full_legal_name if gp else None) or (guest.full_name if guest else None) or (guest.email if guest else "Guest")
            last_stay = LiveStaySummary(
                guest_name=gn,
                stay_start_date=s.stay_start_date,
                stay_end_date=s.stay_end_date,
                checked_out_at=getattr(s, "checked_out_at", None),
            )
            break

    upcoming = []
    for s in all_stays:
        if s.stay_start_date > today and getattr(s, "cancelled_at", None) is None:
            if is_tenant_lane_stay(db, s):
                gn = "Guest"
            else:
                guest = db.query(User).filter(User.id == s.guest_id).first()
                gp = db.query(GuestProfile).filter(GuestProfile.user_id == s.guest_id).first()
                gn = (gp.full_legal_name if gp else None) or (guest.full_name if guest else None) or (guest.email if guest else "Guest")
            upcoming.append(
                LiveStaySummary(
                    guest_name=gn,
                    stay_start_date=s.stay_start_date,
                    stay_end_date=s.stay_end_date,
                    checked_out_at=None,
                )
            )
    upcoming.sort(key=lambda x: x.stay_start_date)

    occ = getattr(prop, "occupancy_status", None) or "unknown"
    authorization_state = "NONE"
    if occ in ("occupied", "unknown", "unconfirmed") or last_stay:
        authorization_state = "EXPIRED"

    return LivePropertyPagePayload(
        has_current_guest=False,
        property=prop_info,
        owner=owner_info,
        current_guest=None,
        last_stay=last_stay,
        upcoming_stays=upcoming,
        invitations=invitations,
        logs=logs,
        authorization_state=authorization_state,
        record_id=slug,
        generated_at=datetime.now(timezone.utc),
        poa_signed_at=poa_signed_at,
        poa_signature_id=poa_signature_id,
        jurisdiction_wrap=jurisdiction_wrap,
    )


def _normalize_address(s: str) -> str:
    """Collapse whitespace and lowercase for address comparison."""
    if not s:
        return ""
    return " ".join(s.lower().strip().split())


def _build_verify_record(
    db: Session,
    inv: Invitation,
    prop: Property,
    stay: Stay | None,
    valid: bool,
    reason: str,
    token_id: str,
    now: datetime,
) -> VerifyResponse:
    """Build full VerifyResponse with property, guest, dates, status, and signed agreement info."""
    prop_parts = [prop.street, prop.city, prop.state, (prop.zip_code or "").strip()]
    prop_full = ", ".join(p for p in prop_parts if p)
    token_state = getattr(inv, "token_state", None) or "STAGED"
    today = date.today()

    # Guest name
    if stay:
        guest = db.query(User).filter(User.id == stay.guest_id).first()
        guest_profile = db.query(GuestProfile).filter(GuestProfile.user_id == stay.guest_id).first()
        guest_name = (guest_profile.full_legal_name if guest_profile else None) or (guest.full_name if guest else None) or (guest.email if guest else "Guest")
    else:
        guest_name = inv.guest_name or inv.guest_email or "Guest"

    # Stay dates
    stay_start_date = stay.stay_start_date if stay else inv.stay_start_date
    stay_end_date = stay.stay_end_date if stay else inv.stay_end_date
    checked_in_at = getattr(stay, "checked_in_at", None) if stay else None
    checked_out_at = getattr(stay, "checked_out_at", None) if stay else None
    revoked_at = getattr(stay, "revoked_at", None) if stay else None
    cancelled_at = getattr(stay, "cancelled_at", None) if stay else None

    # Status
    if not stay:
        if token_state in ("CANCELLED", "REVOKED"):
            status = "CANCELLED"
        elif token_state == "EXPIRED":
            status = "EXPIRED"
        else:
            status = "PENDING"
    elif revoked_at:
        status = "REVOKED"
    elif cancelled_at:
        status = "CANCELLED"
    elif checked_out_at:
        status = "COMPLETED"
    elif stay_end_date < today:
        status = "EXPIRED"
    elif checked_in_at:
        status = "ACTIVE"
    else:
        status = "PENDING"

    # Signed agreement
    sig = (
        db.query(AgreementSignature)
        .filter(AgreementSignature.invitation_code == inv.invitation_code)
        .order_by(AgreementSignature.signed_at.desc())
        .first()
    )
    signed_agreement_available = False
    signed_agreement_url = None
    if sig and (sig.signed_pdf_bytes or getattr(sig, "dropbox_sign_request_id", None)):
        signed_agreement_available = True
        signed_agreement_url = f"/public/verify/{token_id}/signed-agreement"

    # POA
    profile = db.query(OwnerProfile).filter(OwnerProfile.id == prop.owner_profile_id).first()
    poa_signed_at = None
    if profile and profile.user_id:
        poa_sig = (
            db.query(OwnerPOASignature)
            .filter(OwnerPOASignature.used_by_user_id == profile.user_id)
            .first()
        )
        if poa_sig:
            poa_signed_at = poa_sig.signed_at

    # Audit entries
    log_rows = (
        db.query(AuditLog)
        .filter(AuditLog.property_id == prop.id)
        .order_by(AuditLog.created_at.desc())
        .limit(20)
    ).all()
    audit_entries = [
        LiveLogEntry(
            category=r.category or "—",
            title=r.title or "—",
            message=r.message or "—",
            created_at=r.created_at if r.created_at is not None else now,
        )
        for r in log_rows
    ]

    occ = getattr(prop, "occupancy_status", None) or "unknown"
    if valid and (occ or "").lower() == "unknown":
        occ = "occupied"

    return VerifyResponse(
        valid=valid,
        reason=reason,
        property_name=prop.name,
        property_address=prop_full,
        occupancy_status=occ,
        token_state=token_state,
        stay_start_date=stay_start_date,
        stay_end_date=stay_end_date,
        guest_name=guest_name,
        poa_signed_at=poa_signed_at,
        live_slug=prop.live_slug,
        generated_at=now,
        audit_entries=audit_entries,
        status=status,
        checked_in_at=checked_in_at,
        checked_out_at=checked_out_at,
        revoked_at=revoked_at,
        cancelled_at=cancelled_at,
        signed_agreement_available=signed_agreement_available,
        signed_agreement_url=signed_agreement_url,
    )


@router.post("/verify", response_model=VerifyResponse)
def post_verify(
    body: VerifyRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Public verify: check if token (Invitation ID) has an active authorization. Property address is optional;
    when provided it must match the property associated with the token. No auth. Every attempt is logged.
    """
    now = datetime.now(timezone.utc)
    token_id = (body.token_id or "").strip()
    property_address = (body.property_address or "").strip() if body.property_address else ""
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")

    if not token_id:
        create_log(
            db,
            CATEGORY_FAILED_ATTEMPT,
            "Verify attempt – missing token",
            "token_id empty",
            ip_address=ip_address,
            user_agent=user_agent,
            meta={"result": "invalid", "reason": "missing_input"},
        )
        db.commit()
        return VerifyResponse(
            valid=False,
            reason="Token ID is required.",
            generated_at=now,
        )

    # 1. Look up invitation by token_id (invitation_code), case-insensitive
    inv = (
        db.query(Invitation)
        .filter(func.lower(Invitation.invitation_code) == token_id.lower())
        .first()
    )
    if not inv:
        create_log(
            db,
            CATEGORY_FAILED_ATTEMPT,
            "Verify attempt – no match",
            f"Token not found: {token_id[:20]}…",
            ip_address=ip_address,
            user_agent=user_agent,
            meta={"result": "invalid", "reason": "token_not_found", "token_id_prefix": token_id[:32]},
        )
        db.commit()
        return VerifyResponse(
            valid=False,
            reason="Token not found.",
            generated_at=now,
        )

    # 2. Resolve property
    prop = db.query(Property).filter(Property.id == inv.property_id, Property.deleted_at.is_(None)).first()
    if not prop:
        create_log(
            db,
            CATEGORY_FAILED_ATTEMPT,
            "Verify attempt – property not found",
            f"Property missing for invitation {inv.id}",
            property_id=inv.property_id,
            invitation_id=inv.id,
            ip_address=ip_address,
            user_agent=user_agent,
            meta={"result": "invalid", "reason": "property_not_found"},
        )
        db.commit()
        return VerifyResponse(
            valid=False,
            reason="Property not found.",
            generated_at=now,
        )

    # 3. Match address when provided (normalized)
    prop_parts = [prop.street, prop.city, prop.state, (prop.zip_code or "").strip()]
    prop_full = ", ".join(p for p in prop_parts if p)
    if property_address:
        norm_prop = _normalize_address(prop_full)
        norm_submitted = _normalize_address(property_address)
        if norm_prop != norm_submitted:
            # Allow submitted to contain property address (e.g. extra lines) or vice versa
            if norm_prop not in norm_submitted and norm_submitted not in norm_prop:
                create_log(
                    db,
                    CATEGORY_FAILED_ATTEMPT,
                    "Identity Conflict",
                    "Address does not match property for this token.",
                    property_id=prop.id,
                    invitation_id=inv.id,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    meta={
                        "result": "invalid",
                        "reason": "address_mismatch",
                        "token_id_prefix": token_id[:32],
                    },
                )
                db.commit()
                return VerifyResponse(
                    valid=False,
                    reason="Address does not match the property for this token.",
                    generated_at=now,
                )

    # 4. Stay and validity
    stay = db.query(Stay).filter(Stay.invitation_id == inv.id).first()
    today = date.today()
    token_state = getattr(inv, "token_state", None) or "STAGED"

    # Determine validity and reason
    valid = False
    reason = ""
    if token_state != "BURNED":
        create_log(
            db,
            CATEGORY_VERIFY_ATTEMPT,
            "Verify attempt – token not active",
            f"Invitation token_state={token_state}, expected BURNED",
            property_id=prop.id,
            invitation_id=inv.id,
            ip_address=ip_address,
            user_agent=user_agent,
            meta={"result": "invalid", "reason": "token_not_burned", "token_state": token_state},
        )
        db.commit()
        if token_state in ("CANCELLED", "REVOKED"):
            reason_msg = "Status: CANCELLED — Assignment or invitation was cancelled."
        elif token_state == "EXPIRED":
            reason_msg = "Status: EXPIRED — Invitation or stay has ended."
        else:
            reason_msg = "Status: PENDING — Invitation not yet accepted."
        return _build_verify_record(
            db, inv, prop, stay,
            valid=False,
            reason=reason_msg,
            token_id=token_id,
            now=now,
        )

    if not stay:
        create_log(
            db,
            CATEGORY_VERIFY_ATTEMPT,
            "Verify attempt – no stay",
            "No stay linked to this invitation",
            property_id=prop.id,
            invitation_id=inv.id,
            ip_address=ip_address,
            user_agent=user_agent,
            meta={"result": "invalid", "reason": "no_stay"},
        )
        db.commit()
        return _build_verify_record(
            db, inv, prop, None,
            valid=False,
            reason="Status: PENDING — Agreement signed; stay record not yet created.",
            token_id=token_id,
            now=now,
        )

    if getattr(stay, "revoked_at", None) is not None:
        create_log(
            db,
            CATEGORY_VERIFY_ATTEMPT,
            "Verify attempt – stay revoked",
            "Stay has been revoked",
            property_id=prop.id,
            stay_id=stay.id,
            invitation_id=inv.id,
            ip_address=ip_address,
            user_agent=user_agent,
            meta={"result": "invalid", "reason": "stay_revoked"},
        )
        db.commit()
        return _build_verify_record(
            db, inv, prop, stay,
            valid=False,
            reason="Status: REVOKED — Authorization was revoked.",
            token_id=token_id,
            now=now,
        )

    if getattr(stay, "checked_out_at", None) is not None:
        create_log(
            db,
            CATEGORY_VERIFY_ATTEMPT,
            "Verify attempt – guest checked out",
            "Guest has checked out",
            property_id=prop.id,
            stay_id=stay.id,
            invitation_id=inv.id,
            ip_address=ip_address,
            user_agent=user_agent,
            meta={"result": "invalid", "reason": "stay_checked_out"},
        )
        db.commit()
        return _build_verify_record(
            db, inv, prop, stay,
            valid=False,
            reason="Status: COMPLETED — Guest checked out.",
            token_id=token_id,
            now=now,
        )

    if getattr(stay, "cancelled_at", None) is not None:
        create_log(
            db,
            CATEGORY_VERIFY_ATTEMPT,
            "Verify attempt – stay cancelled",
            "Stay was cancelled",
            property_id=prop.id,
            stay_id=stay.id,
            invitation_id=inv.id,
            ip_address=ip_address,
            user_agent=user_agent,
            meta={"result": "invalid", "reason": "stay_cancelled"},
        )
        db.commit()
        return _build_verify_record(
            db, inv, prop, stay,
            valid=False,
            reason="Status: CANCELLED — Stay was cancelled.",
            token_id=token_id,
            now=now,
        )

    if stay.stay_end_date < today:
        create_log(
            db,
            CATEGORY_VERIFY_ATTEMPT,
            "Verify attempt – stay ended",
            "Stay end date has passed",
            property_id=prop.id,
            stay_id=stay.id,
            invitation_id=inv.id,
            ip_address=ip_address,
            user_agent=user_agent,
            meta={"result": "invalid", "reason": "stay_ended"},
        )
        db.commit()
        return _build_verify_record(
            db, inv, prop, stay,
            valid=False,
            reason="Status: EXPIRED — Stay end date has passed.",
            token_id=token_id,
            now=now,
        )

    # 5. Valid: log success and build response
    create_log(
        db,
        CATEGORY_VERIFY_ATTEMPT,
        "Verify attempt – valid",
        "Token and address match; active authorization confirmed.",
        property_id=prop.id,
        stay_id=stay.id,
        invitation_id=inv.id,
        ip_address=ip_address,
        user_agent=user_agent,
        meta={"result": "valid", "reason": "valid"},
    )
    create_ledger_event(
        db,
        ACTION_VERIFY_ATTEMPT_VALID,
        target_object_type="Stay",
        target_object_id=stay.id,
        property_id=prop.id,
        stay_id=stay.id,
        invitation_id=inv.id,
        meta={"result": "valid", "reason": "valid"},
        ip_address=ip_address,
        user_agent=user_agent,
    )
    db.commit()

    return _build_verify_record(
        db, inv, prop, stay,
        valid=True,
        reason="",
        token_id=token_id,
        now=now,
    )


@router.get("/verify/{token}/signed-agreement")
def get_verify_signed_agreement_pdf(
    token: str,
    db: Session = Depends(get_db),
):
    """
    Public: return signed guest agreement PDF for the invitation identified by token (invitation code).
    No auth; for use by the verify page when signed_agreement_available is true.
    """
    token = (token or "").strip()
    if not token:
        raise HTTPException(status_code=404, detail="Token required")
    inv = (
        db.query(Invitation)
        .filter(func.lower(Invitation.invitation_code) == token.lower())
        .first()
    )
    if not inv:
        raise HTTPException(status_code=404, detail="Token not found")
    sig = (
        db.query(AgreementSignature)
        .filter(AgreementSignature.invitation_code == inv.invitation_code)
        .order_by(AgreementSignature.signed_at.desc())
        .first()
    )
    if not sig:
        raise HTTPException(status_code=404, detail="No signed agreement found for this token.")
    # Dropbox: prefer PDF from Dropbox
    if getattr(sig, "dropbox_sign_request_id", None):
        pdf_bytes = get_signed_pdf(sig.dropbox_sign_request_id)
        if pdf_bytes:
            sig.signed_pdf_bytes = pdf_bytes
            db.commit()
            return Response(
                content=pdf_bytes,
                media_type="application/pdf",
                headers={"Content-Disposition": f'inline; filename="DocuStay-Signed-{sig.invitation_code}.pdf"'},
            )
        raise HTTPException(
            status_code=404,
            detail="Document not yet signed. Please complete signing in the link we sent you.",
        )
    if sig.signed_pdf_bytes:
        return Response(
            content=sig.signed_pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="DocuStay-Signed-{sig.invitation_code}.pdf"'},
        )
    # Legacy: in-app signing; generate from stored content
    date_str = sig.signed_at.strftime("%Y-%m-%d") if sig.signed_at else ""
    content = fill_guest_signature_in_content(sig.document_content, sig.typed_signature, date_str, getattr(sig, "ip_address", None))
    pdf_bytes = agreement_content_to_pdf(sig.document_title, content)
    sig.signed_pdf_bytes = pdf_bytes
    db.commit()
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="DocuStay-Signed-{sig.invitation_code}.pdf"'},
    )


@router.get("/live/{slug}/poa")
def get_live_property_poa_pdf(slug: str, db: Session = Depends(get_db)):
    """
    Public: return signed Master POA PDF for the property identified by live slug.
    No auth; for use by "View POA" on the live evidence page.
    """
    if not slug or not slug.strip():
        raise HTTPException(status_code=404, detail="Not found")
    slug = slug.strip()
    prop = db.query(Property).filter(Property.live_slug == slug, Property.deleted_at.is_(None)).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    profile = db.query(OwnerProfile).filter(OwnerProfile.id == prop.owner_profile_id).first()
    if not profile or not profile.user_id:
        raise HTTPException(status_code=404, detail="POA not available")
    sig = (
        db.query(OwnerPOASignature)
        .filter(OwnerPOASignature.used_by_user_id == profile.user_id)
        .first()
    )
    if not sig:
        raise HTTPException(status_code=404, detail="POA not on file for this property")

    if sig.signed_pdf_bytes:
        return Response(
            content=sig.signed_pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": 'inline; filename="DocuStay-Master-POA-Signed.pdf"'},
        )
    if getattr(sig, "dropbox_sign_request_id", None):
        pdf_bytes = get_signed_pdf(sig.dropbox_sign_request_id)
        if pdf_bytes:
            sig.signed_pdf_bytes = pdf_bytes
            db.commit()
            return Response(
                content=pdf_bytes,
                media_type="application/pdf",
                headers={"Content-Disposition": 'inline; filename="DocuStay-Master-POA-Signed.pdf"'},
            )
    date_str = sig.signed_at.strftime("%Y-%m-%d") if sig.signed_at else ""
    content_with_sig = poa_content_with_signature(sig.document_content, sig.typed_signature, date_str)
    pdf_bytes = agreement_content_to_pdf(sig.document_title, content_with_sig)
    sig.signed_pdf_bytes = pdf_bytes
    db.commit()
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": 'inline; filename="DocuStay-Master-POA-Signed.pdf"'},
    )


@router.get("/portfolio/{slug}", response_model=PortfolioPagePayload)
def get_portfolio_page(slug: str, db: Session = Depends(get_db)):
    """
    Public portfolio page by owner's unique slug (no auth).
    Returns owner basic info and list of active properties (public details only).
    """
    if not slug or not slug.strip():
        raise HTTPException(status_code=404, detail="Portfolio not found")
    slug = slug.strip()
    profile = db.query(OwnerProfile).filter(OwnerProfile.portfolio_slug == slug).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Portfolio not found")
    owner_user = db.query(User).filter(User.id == profile.user_id).first()
    owner_name = (owner_user.full_name if owner_user else None) or None
    owner_email = (owner_user.email if owner_user else "") or ""
    owner_phone = getattr(owner_user, "phone", None) if owner_user else None
    owner_state = getattr(owner_user, "state", None) if owner_user else None
    owner_info = PortfolioOwnerInfo(
        full_name=owner_name,
        email=owner_email,
        phone=owner_phone,
        state=owner_state,
    )
    properties = (
        db.query(Property)
        .filter(Property.owner_profile_id == profile.id, Property.deleted_at.is_(None))
        .order_by(Property.created_at.asc())
        .all()
    )
    property_items = []
    for p in properties:
        unit_count = None
        if getattr(p, "is_multi_unit", False):
            unit_count = db.query(Unit).filter(Unit.property_id == p.id).count() or 0
        property_items.append(
            PortfolioPropertyItem(
                id=p.id,
                name=p.name,
                city=p.city,
                state=p.state,
                region_code=p.region_code,
                property_type_label=getattr(p, "property_type_label", None) or (p.property_type.value if p.property_type else None),
                bedrooms=getattr(p, "bedrooms", None),
                is_multi_unit=getattr(p, "is_multi_unit", False),
                unit_count=unit_count,
            )
        )
    return PortfolioPagePayload(owner=owner_info, properties=property_items)
