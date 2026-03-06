"""Module F: Legal restrictions & law display (Owner and Guest views)."""
import logging
import secrets
from datetime import date, datetime, timezone, timedelta, time as dt_time

logger = logging.getLogger(__name__)
from fastapi import APIRouter, Depends, HTTPException, Request, Body
from fastapi.responses import Response
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.models.stay import Stay
from app.models.invitation import Invitation
from app.models.guest import GuestProfile
from app.models.region_rule import RegionRule
from app.models.owner import Property, OwnerProfile, USAT_TOKEN_STAGED, USAT_TOKEN_RELEASED, OccupancyStatus
from app.models.guest_pending_invite import GuestPendingInvite
from app.models.agreement_signature import AgreementSignature
from app.models.region_rule import StayClassification, RiskLevel
from app.schemas.dashboard import OwnerStayView, OwnerInvitationView, GuestStayView, GuestPendingInviteView, JurisdictionStatuteInDashboard, OwnerAuditLogEntry, BillingResponse, BillingInvoiceView, BillingPaymentView, BillingPortalSessionResponse, PortfolioLinkResponse
from app.services.jle import resolve_jurisdiction
from app.services.jurisdiction_sot import get_jurisdiction_for_property
from app.services.audit_log import create_log, CATEGORY_STATUS_CHANGE, CATEGORY_DEAD_MANS_SWITCH, CATEGORY_FAILED_ATTEMPT, CATEGORY_BILLING
from app.services.invitation_cleanup import get_invitation_expire_cutoff
from app.services.billing import sync_subscription_quantities
from app.services.notifications import send_vacate_12h_notice, send_owner_guest_checkout_email, send_guest_checkout_confirmation_email, send_owner_guest_cancelled_stay_email, send_removal_notice_to_guest, send_removal_confirmation_to_owner
from app.schemas.jle import JLEInput
from app.dependencies import get_current_user, require_owner, require_owner_onboarding_complete, require_guest
from app.models.audit_log import AuditLog
from app.services.agreements import fill_guest_signature_in_content, agreement_content_to_pdf
from app.services.dropbox_sign import get_signed_pdf

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/guest/pending-invites", response_model=list[GuestPendingInviteView])
def guest_pending_invites(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_guest),
):
    """List invitations this guest has as pending (saved from login/signup with link; not yet signed)."""
    pendings = (
        db.query(GuestPendingInvite)
        .filter(GuestPendingInvite.user_id == current_user.id)
        .all()
    )
    out = []
    guest_email = (current_user.email or "").strip().lower()
    for p in pendings:
        inv = db.query(Invitation).filter(Invitation.id == p.invitation_id, Invitation.status.in_(["pending", "ongoing"])).first()
        if not inv:
            continue
        prop = db.query(Property).filter(Property.id == inv.property_id).first()
        property_name = (prop.name if prop else None) or (f"{prop.city}, {prop.state}" if prop else None) or "Property"
        owner = db.query(User).filter(User.id == inv.owner_id).first()
        host_name = (owner.full_name if owner else None) or (owner.email if owner else "")
        needs_dropbox = False
        pending_sig_id = None
        accept_now_sig_id = None
        if guest_email:
            sig = (
                db.query(AgreementSignature)
                .filter(
                    AgreementSignature.invitation_code == inv.invitation_code,
                    AgreementSignature.guest_email == guest_email,
                    AgreementSignature.used_by_user_id.is_(None),
                )
                .order_by(AgreementSignature.signed_at.desc())
                .first()
            )
            if sig and getattr(sig, "dropbox_sign_request_id", None):
                if not getattr(sig, "signed_pdf_bytes", None):
                    pdf_bytes = get_signed_pdf(sig.dropbox_sign_request_id)
                    if pdf_bytes:
                        sig.signed_pdf_bytes = pdf_bytes
                        db.commit()
                        db.refresh(sig)
                if not getattr(sig, "signed_pdf_bytes", None):
                    needs_dropbox = True
                    pending_sig_id = sig.id
                elif getattr(sig, "signed_pdf_bytes", None) and getattr(sig, "used_by_user_id", None) is None:
                    accept_now_sig_id = sig.id
        out.append(
            GuestPendingInviteView(
                invitation_code=inv.invitation_code,
                property_name=property_name,
                stay_start_date=inv.stay_start_date,
                stay_end_date=inv.stay_end_date,
                host_name=host_name,
                region_code=inv.region_code,
                needs_dropbox_signature=needs_dropbox,
                pending_signature_id=pending_sig_id,
                accept_now_signature_id=accept_now_sig_id,
            )
        )
    return out


@router.post("/guest/pending-invites", response_model=GuestPendingInviteView)
def guest_add_pending_invite(
    request: Request,
    invitation_code: str = Body(..., embed=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_guest),
):
    """Add an invitation to this guest's pending list. Used when a logged-in guest pastes an invitation link on the dashboard or after login/signup with link. Returns invite details; frontend then shows the agreement modal to view and sign."""
    code = (invitation_code or "").strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="invitation_code is required")
    inv = db.query(Invitation).filter(
        Invitation.invitation_code == code,
        Invitation.status.in_(["pending", "ongoing"]),
        Invitation.token_state != "BURNED",
    ).first()
    if not inv:
        ip = request.client.host if request.client else None
        ua = (request.headers.get("user-agent") or "").strip() or None
        create_log(
            db,
            CATEGORY_FAILED_ATTEMPT,
            "Invalid or expired invitation code",
            f"Guest attempted to add pending invite with invalid or expired code: {code}.",
            property_id=None,
            actor_user_id=current_user.id,
            actor_email=current_user.email,
            ip_address=ip,
            user_agent=ua,
            meta={"invitation_code_attempted": code},
        )
        db.commit()
        raise HTTPException(status_code=400, detail="Invalid or expired invitation code")

    # Reject if this invitation overlaps any existing stay for this guest (block before signing)
    existing_stays = db.query(Stay).filter(Stay.guest_id == current_user.id).all()
    for s in existing_stays:
        if inv.stay_start_date < s.stay_end_date and inv.stay_end_date > s.stay_start_date:
            create_log(
                db,
                CATEGORY_FAILED_ATTEMPT,
                "Add pending invite: overlapping stay",
                f"Guest attempted to add invitation {code} which overlaps with existing stay(s).",
                property_id=inv.property_id,
                invitation_id=inv.id,
                actor_user_id=current_user.id,
                actor_email=current_user.email,
                ip_address=request.client.host if request.client else None,
                user_agent=(request.headers.get("user-agent") or "").strip() or None,
                meta={"invitation_code": code},
            )
            db.commit()
            raise HTTPException(
                status_code=400,
                detail="This invitation overlaps with an existing stay. Only one stay can be accepted at a time.",
            )

    existing = (
        db.query(GuestPendingInvite)
        .filter(GuestPendingInvite.user_id == current_user.id, GuestPendingInvite.invitation_id == inv.id)
        .first()
    )
    if existing:
        prop = db.query(Property).filter(Property.id == inv.property_id).first()
        property_name = (prop.name if prop else None) or (f"{prop.city}, {prop.state}" if prop else None) or "Property"
        owner = db.query(User).filter(User.id == inv.owner_id).first()
        host_name = (owner.full_name if owner else None) or (owner.email if owner else "")
        needs_dropbox, pending_sig_id = False, None
        accept_now_sig_id = None
        guest_email = (current_user.email or "").strip().lower()
        if guest_email:
            sig = (
                db.query(AgreementSignature)
                .filter(
                    AgreementSignature.invitation_code == inv.invitation_code,
                    AgreementSignature.guest_email == guest_email,
                    AgreementSignature.used_by_user_id.is_(None),
                )
                .order_by(AgreementSignature.signed_at.desc())
                .first()
            )
            if sig and getattr(sig, "dropbox_sign_request_id", None):
                if not getattr(sig, "signed_pdf_bytes", None):
                    pdf_bytes = get_signed_pdf(sig.dropbox_sign_request_id)
                    if pdf_bytes:
                        sig.signed_pdf_bytes = pdf_bytes
                        db.commit()
                        db.refresh(sig)
                if not getattr(sig, "signed_pdf_bytes", None):
                    needs_dropbox, pending_sig_id = True, sig.id
                elif getattr(sig, "signed_pdf_bytes", None):
                    accept_now_sig_id = sig.id
        return GuestPendingInviteView(
            invitation_code=inv.invitation_code,
            property_name=property_name,
            stay_start_date=inv.stay_start_date,
            stay_end_date=inv.stay_end_date,
            host_name=host_name,
            region_code=inv.region_code,
            needs_dropbox_signature=needs_dropbox,
            pending_signature_id=pending_sig_id,
            accept_now_signature_id=accept_now_sig_id,
        )
    pending = GuestPendingInvite(user_id=current_user.id, invitation_id=inv.id)
    db.add(pending)
    db.commit()
    prop = db.query(Property).filter(Property.id == inv.property_id).first()
    property_name = (prop.name if prop else None) or (f"{prop.city}, {prop.state}" if prop else None) or "Property"
    owner = db.query(User).filter(User.id == inv.owner_id).first()
    host_name = (owner.full_name if owner else None) or (owner.email if owner else "")
    return GuestPendingInviteView(
        invitation_code=inv.invitation_code,
        property_name=property_name,
        stay_start_date=inv.stay_start_date,
        stay_end_date=inv.stay_end_date,
        host_name=host_name,
        region_code=inv.region_code,
        needs_dropbox_signature=False,
        pending_signature_id=None,
        accept_now_signature_id=None,
    )


@router.get("/owner/invitations", response_model=list[OwnerInvitationView])
def owner_invitations(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Owner view: all invitations (pending, accepted, cancelled) with property name. Pending invites older than the configured window (12h or 5m in test_mode) are marked is_expired."""
    invs = db.query(Invitation).filter(Invitation.owner_id == current_user.id).order_by(Invitation.created_at.desc()).all()
    threshold = get_invitation_expire_cutoff()
    out = []
    for inv in invs:
        prop = db.query(Property).filter(Property.id == inv.property_id).first()
        property_name = (prop.name if prop else None) or (f"{prop.city}, {prop.state}" if prop else None) or "Property"
        is_expired = (
            inv.status == "expired"
            or (
                inv.status == "pending"
                and inv.created_at is not None
                and inv.created_at < threshold
            )
        )
        # Display status: ongoing when unit is occupied (stay exists, or CSV bulk-upload BURNED invite); else pending/cancelled/expired. We do not auto-set invitation.status to accepted when stay is created; this is display-only.
        has_stay = db.query(Stay).filter(Stay.invitation_id == inv.id).first() is not None
        token_state = (getattr(inv, "token_state", None) or "STAGED").upper()
        if inv.status == "cancelled":
            display_status = "cancelled"
        elif inv.status == "expired" or is_expired:
            display_status = "expired"
        elif inv.status == "ongoing" or has_stay or inv.status == "accepted" or (token_state == "BURNED" and inv.status == "pending"):
            display_status = "ongoing"
        else:
            display_status = "pending"
        out.append(
            OwnerInvitationView(
                id=inv.id,
                invitation_code=inv.invitation_code,
                property_id=inv.property_id,
                property_name=property_name,
                guest_name=inv.guest_name,
                guest_email=inv.guest_email,
                stay_start_date=inv.stay_start_date,
                stay_end_date=inv.stay_end_date,
                region_code=inv.region_code,
                status=display_status,
                token_state=getattr(inv, "token_state", None) or "STAGED",
                created_at=inv.created_at,
                is_expired=is_expired,
            )
        )
    return out


@router.post("/owner/invitations/{invitation_id}/cancel")
def owner_cancel_invitation(
    request: Request,
    invitation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Cancel a pending invitation (set status to cancelled). Accepted invitations cannot be cancelled."""
    inv = db.query(Invitation).filter(
        Invitation.id == invitation_id,
        Invitation.owner_id == current_user.id,
    ).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Invitation not found")
    if inv.status not in ("pending", "ongoing"):
        raise HTTPException(status_code=400, detail="Only pending or ongoing invitations can be cancelled.")
    inv.status = "cancelled"
    prev_token = getattr(inv, "token_state", None) or "STAGED"
    inv.token_state = "REVOKED"
    db.commit()
    prop = db.query(Property).filter(Property.id == inv.property_id).first()
    property_name = (prop.name if prop else None) or (f"{prop.city}, {prop.state}" if prop else None) or "Property"
    ip = request.client.host if request.client else None
    ua = (request.headers.get("user-agent") or "").strip() or None
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "Invitation cancelled",
        f"Invite ID {inv.invitation_code} token_state {prev_token} -> REVOKED (owner cancelled). Property {property_name}, guest {inv.guest_name or inv.guest_email or '—'}.",
        property_id=inv.property_id,
        invitation_id=inv.id,
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=ip,
        user_agent=ua,
        meta={"invitation_code": inv.invitation_code, "token_state_previous": prev_token, "token_state_new": "REVOKED"},
    )
    db.commit()
    return {"status": "success", "message": "Invitation cancelled."}


@router.post("/owner/properties/{property_id}/confirm-vacant")
def owner_confirm_vacant(
    request: Request,
    property_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Confirm that a vacant unit is still vacant (vacant-unit monitoring response). Clears response deadline so the property is not flipped to UNCONFIRMED."""
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="No owner profile")
    prop = db.query(Property).filter(
        Property.id == property_id,
        Property.owner_profile_id == profile.id,
        Property.deleted_at.is_(None),
    ).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    if (getattr(prop, "occupancy_status", None) or "").lower() != OccupancyStatus.vacant.value:
        raise HTTPException(status_code=400, detail="Property is not vacant. Confirm vacancy only for vacant units.")
    now = datetime.now(timezone.utc)
    prop.vacant_monitoring_confirmed_at = now
    prop.vacant_monitoring_response_due_at = None
    db.add(prop)
    property_name = (prop.name or "").strip() or (f"{prop.city}, {prop.state}".strip(", ") if (prop.city or prop.state) else f"Property {property_id}")
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "Owner confirmed still vacant",
        f"Owner confirmed unit still vacant for {property_name} (vacant monitoring).",
        property_id=prop.id,
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=request.client.host if request.client else None,
        user_agent=(request.headers.get("user-agent") or "").strip() or None,
    )
    db.commit()
    return {"status": "success", "message": "Vacancy confirmed. Next prompt will be sent at the next interval."}


@router.get("/owner/stays", response_model=list[OwnerStayView])
def owner_stays(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Owner view: guest name, stay dates, region, legal classification, max stay, risk, applicable laws."""
    stays = db.query(Stay).filter(Stay.owner_id == current_user.id).all()
    out = []
    for s in stays:
        guest = db.query(User).filter(User.id == s.guest_id).first()
        guest_profile = db.query(GuestProfile).filter(GuestProfile.user_id == s.guest_id).first()
        guest_name = (guest_profile.full_legal_name if guest_profile else None) or (guest.full_name if guest else None) or (guest.email if guest else "Unknown")

        prop = db.query(Property).filter(Property.id == s.property_id).first()
        property_name = (prop.name if prop else None) or (f"{prop.city}, {prop.state}" if prop else None) or "Property"

        rule = db.query(RegionRule).filter(RegionRule.region_code == s.region_code).first()
        jle = resolve_jurisdiction(
            db,
            JLEInput(
                region_code=s.region_code,
                stay_duration_days=s.intended_stay_duration_days,
                owner_occupied=True,  # would come from property
                property_type=None,
                guest_has_permanent_address=True,
            ),
        )
        max_days = rule.max_stay_days if rule else 0
        classification = (jle.legal_classification if jle else None) or (rule.stay_classification_label if rule else None) or StayClassification.guest
        risk = (jle.risk_level if jle else None) or (rule.risk_level if rule else None) or RiskLevel.low
        statutes = (jle.applicable_statutes if jle else []) or ([rule.statute_reference] if rule and rule.statute_reference else [])

        # Status confirmation: 48h after lease end = deadline; if no response by then, status flips to UNCONFIRMED
        checked_out = getattr(s, "checked_out_at", None) is not None
        cancelled = getattr(s, "cancelled_at", None) is not None
        conf_resp = getattr(s, "occupancy_confirmation_response", None)
        dms_on = bool(getattr(s, "dead_mans_switch_enabled", 0))
        confirmation_deadline_at = datetime.combine(
            s.stay_end_date + timedelta(days=2), dt_time.min, tzinfo=timezone.utc
        ) if s.stay_end_date else None
        now = datetime.now(timezone.utc)
        needs_conf = (
            not checked_out and not cancelled
            and dms_on
            and conf_resp is None
            and confirmation_deadline_at is not None
            and now < confirmation_deadline_at
            and s.stay_end_date <= (date.today() + timedelta(days=2))  # in prompt window (48h before or after)
        )
        # Also show confirm UI when property is UNCONFIRMED (past deadline) and this stay triggered it
        prop_status = (getattr(prop, "occupancy_status", None) or "unknown") if prop else "unknown"
        show_confirm_ui = needs_conf or (
            prop_status == OccupancyStatus.unconfirmed.value
            and not checked_out and not cancelled
            and dms_on
            and conf_resp is None
            and s.stay_end_date < date.today()  # stay ended
        )

        invite_id_val = None
        token_state_val = None
        if getattr(s, "invitation_id", None):
            inv = db.query(Invitation).filter(Invitation.id == s.invitation_id).first()
            if inv:
                invite_id_val = inv.invitation_code
                token_state_val = getattr(inv, "token_state", None) or "BURNED"
        out.append(
            OwnerStayView(
                stay_id=s.id,
                property_id=s.property_id,
                invite_id=invite_id_val,
                token_state=token_state_val,
                guest_name=guest_name,
                property_name=property_name,
                stay_start_date=s.stay_start_date,
                stay_end_date=s.stay_end_date,
                region_code=s.region_code,
                legal_classification=classification,
                max_stay_allowed_days=max_days,
                risk_indicator=risk,
                applicable_laws=statutes,
                revoked_at=getattr(s, "revoked_at", None),
                checked_in_at=getattr(s, "checked_in_at", None),
                checked_out_at=getattr(s, "checked_out_at", None),
                cancelled_at=getattr(s, "cancelled_at", None),
                usat_token_released_at=getattr(s, "usat_token_released_at", None),
                dead_mans_switch_enabled=dms_on,
                needs_occupancy_confirmation=needs_conf,
                show_occupancy_confirmation_ui=show_confirm_ui,
                confirmation_deadline_at=confirmation_deadline_at if show_confirm_ui else None,
                occupancy_confirmation_response=conf_resp,
            )
        )
    return out


@router.post("/owner/stays/{stay_id}/revoke")
def revoke_stay(
    request: Request,
    stay_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Revoke a stay (Kill Switch): set revoked_at, guest must vacate in 12 hours. Invite token -> REVOKED. Sends email to guest."""
    stay = db.query(Stay).filter(Stay.id == stay_id, Stay.owner_id == current_user.id).first()
    if not stay:
        raise HTTPException(status_code=404, detail="Stay not found")
    if stay.revoked_at:
        return {"status": "success", "message": "Stay was already revoked."}
    now = datetime.now(timezone.utc)
    stay.revoked_at = now
    vacate_by = now + timedelta(hours=12)
    vacate_by_iso = vacate_by.strftime("%Y-%m-%d %H:%M UTC")
    invite_code = None
    prev_token = None
    if getattr(stay, "invitation_id", None):
        inv = db.query(Invitation).filter(Invitation.id == stay.invitation_id).first()
        if inv:
            prev_token = getattr(inv, "token_state", None) or "BURNED"
            inv.token_state = "REVOKED"
            invite_code = inv.invitation_code
            db.add(inv)
    db.commit()
    ip = request.client.host if request.client else None
    ua = (request.headers.get("user-agent") or "").strip() or None
    log_meta = {"vacate_by": vacate_by_iso}
    if invite_code and prev_token is not None:
        log_meta["invitation_code"] = invite_code
        log_meta["token_state_previous"] = prev_token
        log_meta["token_state_new"] = "REVOKED"
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "Stay revoked",
        f"Stay {stay.id} revoked by owner. Guest must vacate by {vacate_by_iso}." + (f" Invite ID {invite_code} token_state -> REVOKED." if invite_code else ""),
        property_id=stay.property_id,
        stay_id=stay.id,
        invitation_id=getattr(stay, "invitation_id", None),
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=ip,
        user_agent=ua,
        meta=log_meta,
    )
    db.commit()
    guest = db.query(User).filter(User.id == stay.guest_id).first()
    guest_email = (guest.email if guest else "").strip()
    guest_name = (guest.full_name if guest else None) or guest_email or "Guest"
    prop = db.query(Property).filter(Property.id == stay.property_id).first()
    property_name = (prop.name if prop else None) or (f"{prop.city}, {prop.state}" if prop else None) or "the property"
    if guest_email:
        send_vacate_12h_notice(guest_email, guest_name, property_name, vacate_by_iso, stay.region_code or "")
    return {"status": "success", "message": "Stay revoked. Guest must vacate within 12 hours. Email sent."}


@router.post("/owner/stays/{stay_id}/initiate-removal")
def initiate_removal(
    request: Request,
    stay_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Initiate formal removal for an overstayed guest: revoke USAT token, send emails to guest and owner, log action."""
    stay = db.query(Stay).filter(Stay.id == stay_id, Stay.owner_id == current_user.id).first()
    if not stay:
        raise HTTPException(status_code=404, detail="Stay not found")

    # Only allow initiate-removal for overstayed guests
    today = date.today()
    if stay.stay_end_date >= today:
        raise HTTPException(status_code=400, detail="Guest is not in overstay. Initiate removal is only for overstayed guests.")
    if getattr(stay, "checked_out_at", None):
        raise HTTPException(status_code=400, detail="Guest has already checked out.")

    prop = db.query(Property).filter(Property.id == stay.property_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    now = datetime.now(timezone.utc)
    ip = request.client.host if request.client else None
    ua = (request.headers.get("user-agent") or "").strip() or None

    # Revoke USAT token for this stay
    usat_revoked = False
    if stay.usat_token_released_at is not None:
        stay.usat_token_released_at = None
        usat_revoked = True

    # Also revoke the property-level USAT token if it was released
    if prop.usat_token_state == USAT_TOKEN_RELEASED:
        prop.usat_token_state = USAT_TOKEN_STAGED
        prop.usat_token_released_at = None
        usat_revoked = True

    # Mark stay as revoked if not already
    already_revoked = stay.revoked_at is not None
    if not already_revoked:
        stay.revoked_at = now

    # Update occupancy status to reflect overstay/removal
    occ_prev = getattr(prop, "occupancy_status", None) or "unknown"

    db.add(stay)
    db.add(prop)
    db.commit()

    # Get guest and owner info for emails
    guest = db.query(User).filter(User.id == stay.guest_id).first()
    guest_email = (guest.email if guest else "").strip()
    guest_name = (guest.full_name if guest else None) or guest_email or "Guest"
    property_name = (prop.name if prop else None) or (f"{prop.city}, {prop.state}" if prop else None) or "the property"
    owner_email = current_user.email

    # Send emails
    if guest_email:
        send_removal_notice_to_guest(guest_email, guest_name, property_name, stay.region_code or "")
    if owner_email:
        send_removal_confirmation_to_owner(owner_email, guest_name, property_name, stay.region_code or "")

    # Create audit log
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "Removal initiated",
        f"Owner initiated formal removal for stay {stay.id} (guest: {guest_name}, property: {property_name}). USAT token revoked. Guest and owner notified.",
        property_id=stay.property_id,
        stay_id=stay.id,
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=ip,
        user_agent=ua,
        meta={
            "guest_name": guest_name,
            "guest_email": guest_email,
            "property_name": property_name,
            "usat_revoked": usat_revoked,
            "was_already_revoked": already_revoked,
            "occupancy_status_previous": occ_prev,
        },
    )
    db.commit()

    return {
        "status": "success",
        "message": "Removal initiated. USAT token revoked. Guest and owner notified via email.",
        "usat_revoked": usat_revoked,
    }


@router.post("/owner/stays/{stay_id}/confirm-occupancy")
def confirm_occupancy_status(
    request: Request,
    stay_id: int,
    action: str = Body(..., embed=True),  # vacated | renewed | holdover
    new_lease_end_date: str | None = Body(None, embed=True),  # required when action=renewed
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Owner explicitly confirms unit status: Unit Vacated, Lease Renewed (requires new_lease_end_date), or Holdover.
    Required when property is UNCONFIRMED or when stay is in confirmation window (48h before → 48h after lease end)."""
    stay = db.query(Stay).filter(Stay.id == stay_id, Stay.owner_id == current_user.id).first()
    if not stay:
        raise HTTPException(status_code=404, detail="Stay not found")
    action = (action or "").strip().lower()
    if action not in ("vacated", "renewed", "holdover"):
        raise HTTPException(status_code=400, detail="action must be vacated, renewed, or holdover")
    if action == "renewed" and not new_lease_end_date:
        raise HTTPException(status_code=400, detail="new_lease_end_date is required when action is renewed")

    prop = db.query(Property).filter(Property.id == stay.property_id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")

    prev_status = getattr(prop, "occupancy_status", None) or "unknown"
    now = datetime.now(timezone.utc)
    ip = request.client.host if request.client else None
    ua = (request.headers.get("user-agent") or "").strip() or None

    if action == "vacated":
        stay.checked_out_at = now
        stay.occupancy_confirmation_response = "vacated"
        stay.occupancy_confirmation_responded_at = now
        prop.occupancy_status = OccupancyStatus.vacant.value
        if getattr(prop, "shield_mode_enabled", 0) == 1:
            prop.shield_mode_enabled = 0  # Unit status update: vacated → Shield off; billing prorated
        if prop.usat_token_state == USAT_TOKEN_RELEASED:
            prop.usat_token_state = USAT_TOKEN_STAGED
            prop.usat_token_released_at = None
        invite_code = None
        if getattr(stay, "invitation_id", None):
            inv = db.query(Invitation).filter(Invitation.id == stay.invitation_id).first()
            if inv:
                prev_token = getattr(inv, "token_state", None) or "BURNED"
                inv.token_state = "EXPIRED"
                invite_code = inv.invitation_code
                db.add(inv)
        db.add(stay)
        db.add(prop)
        db.commit()
        vacated_meta = {"occupancy_status_previous": prev_status, "occupancy_status_new": OccupancyStatus.vacant.value, "action": "vacated"}
        if invite_code:
            vacated_meta["invitation_code"] = invite_code
            vacated_meta["token_state_previous"] = prev_token
            vacated_meta["token_state_new"] = "EXPIRED"
        create_log(
            db,
            CATEGORY_STATUS_CHANGE,
            "Owner confirmed: Unit Vacated",
            f"Stay {stay.id}: Owner confirmed unit vacated. Previous status: {prev_status}." + (f" Invite ID {invite_code} token_state -> EXPIRED." if invite_code else ""),
            property_id=stay.property_id,
            stay_id=stay.id,
            invitation_id=getattr(stay, "invitation_id", None),
            actor_user_id=current_user.id,
            actor_email=current_user.email,
            ip_address=ip,
            user_agent=ua,
            meta=vacated_meta,
        )
        db.commit()
        try:
            profile = db.query(OwnerProfile).filter(OwnerProfile.id == prop.owner_profile_id).first()
            if profile:
                sync_subscription_quantities(db, profile)
        except Exception:
            pass
        return {"status": "success", "message": "Unit marked as vacated.", "occupancy_status": "vacant"}

    if action == "renewed":
        try:
            new_end = date.fromisoformat(new_lease_end_date.strip())
        except (ValueError, AttributeError):
            raise HTTPException(status_code=400, detail="new_lease_end_date must be YYYY-MM-DD")
        if new_end <= stay.stay_end_date:
            raise HTTPException(status_code=400, detail="new_lease_end_date must be after current stay end date")
        stay.stay_end_date = new_end
        stay.occupancy_confirmation_response = "renewed"
        stay.occupancy_confirmation_responded_at = now
        # Update intended duration to match extended stay
        new_duration_days = (new_end - stay.stay_start_date).days
        stay.intended_stay_duration_days = new_duration_days
        # Renewal: ensure invite token is BURNED (e.g. if stay had expired and token was EXPIRED, renewal brings it back to active)
        invite_code = None
        prev_token = None
        if getattr(stay, "invitation_id", None):
            inv = db.query(Invitation).filter(Invitation.id == stay.invitation_id).first()
            if inv:
                prev_token = getattr(inv, "token_state", None) or "BURNED"
                inv.token_state = "BURNED"
                invite_code = inv.invitation_code
                db.add(inv)
        # If new lease end is > 48h away, turn off DMS (owner renewed out of the 48h window)
        today = date.today()
        cutoff = today + timedelta(days=2)
        if new_end > cutoff and getattr(stay, "dead_mans_switch_enabled", 0) == 1:
            stay.dead_mans_switch_enabled = 0
            stay.dead_mans_switch_triggered_at = None
            create_log(
                db,
                CATEGORY_DEAD_MANS_SWITCH,
                "Dead Man's Switch turned off (lease extended beyond 48h)",
                f"Stay {stay.id}: Owner extended lease to {new_end.isoformat()} (>48h away). DMS disabled for this stay.",
                property_id=stay.property_id,
                stay_id=stay.id,
                actor_user_id=current_user.id,
                actor_email=current_user.email,
                ip_address=ip,
                user_agent=ua,
                meta={"new_lease_end_date": new_end.isoformat(), "new_duration_days": new_duration_days},
            )
        prop.occupancy_status = OccupancyStatus.occupied.value
        db.add(stay)
        db.add(prop)
        db.commit()
        renewed_meta = {"occupancy_status_previous": prev_status, "occupancy_status_new": OccupancyStatus.occupied.value, "action": "renewed", "new_lease_end_date": new_end.isoformat()}
        if invite_code:
            renewed_meta["invitation_code"] = invite_code
            renewed_meta["token_state_previous"] = prev_token
            renewed_meta["token_state_new"] = "BURNED"
        create_log(
            db,
            CATEGORY_STATUS_CHANGE,
            "Owner confirmed: Lease Renewed",
            f"Stay {stay.id}: Owner renewed lease to {new_end.isoformat()}. Previous status: {prev_status}." + (f" Invite ID {invite_code} token_state {prev_token} -> BURNED." if invite_code else ""),
            property_id=stay.property_id,
            stay_id=stay.id,
            invitation_id=getattr(stay, "invitation_id", None),
            actor_user_id=current_user.id,
            actor_email=current_user.email,
            ip_address=ip,
            user_agent=ua,
            meta=renewed_meta,
        )
        db.commit()
        return {"status": "success", "message": "Lease renewed.", "occupancy_status": "occupied", "new_lease_end_date": new_end.isoformat()}

    # holdover
    stay.occupancy_confirmation_response = "holdover"
    stay.occupancy_confirmation_responded_at = now
    prop.occupancy_status = OccupancyStatus.occupied.value
    db.add(stay)
    db.add(prop)
    db.commit()
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "Owner confirmed: Holdover",
        f"Stay {stay.id}: Owner confirmed holdover (guest still in unit). Previous status: {prev_status}.",
        property_id=stay.property_id,
        stay_id=stay.id,
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=ip,
        user_agent=ua,
        meta={"occupancy_status_previous": prev_status, "occupancy_status_new": OccupancyStatus.occupied.value, "action": "holdover"},
    )
    db.commit()
    return {"status": "success", "message": "Holdover confirmed.", "occupancy_status": "occupied"}


@router.get("/guest/stays", response_model=list[GuestStayView])
def guest_stays(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_guest),
):
    """Guest view: property, approved stay dates, region classification, legal notice and laws. All jurisdiction content from Jurisdiction SOT (same as live property page)."""
    stays = db.query(Stay).filter(Stay.guest_id == current_user.id).all()
    out = []
    for s in stays:
        prop = db.query(Property).filter(Property.id == s.property_id).first()
        property_name = (prop.name if prop else None) or (f"{prop.city}, {prop.state}" if prop else None) or "Property"
        region_code = (prop.region_code if prop else None) or s.region_code
        # Prefer Jurisdiction SOT (DB) for classification, statutes, removal text — same source as live page and agreements
        jinfo = get_jurisdiction_for_property(db, prop.zip_code if prop else None, region_code)
        if jinfo is not None:
            classification = jinfo.stay_classification.value
            statute = jinfo.statutes[0].citation if jinfo.statutes else None
            explanation = jinfo.statutes[0].plain_english if jinfo.statutes and jinfo.statutes[0].plain_english else None
            laws = [st.citation + (f": {st.plain_english}" if st.plain_english else "") for st in jinfo.statutes]
            legal_notice = jinfo.removal_guest_text or "This stay does not grant tenancy or homestead rights."
            jurisdiction_state_name = jinfo.name
            jurisdiction_statutes = [JurisdictionStatuteInDashboard(citation=st.citation, plain_english=st.plain_english) for st in jinfo.statutes]
            removal_guest_text = jinfo.removal_guest_text
            removal_tenant_text = jinfo.removal_tenant_text
        else:
            rule = db.query(RegionRule).filter(RegionRule.region_code == s.region_code).first()
            classification = rule.stay_classification_label.value if rule else "guest"
            statute = rule.statute_reference if rule else None
            explanation = rule.plain_english_explanation if rule else None
            laws = [rule.statute_reference] if rule and rule.statute_reference else []
            legal_notice = "This stay does not grant tenancy or homestead rights."
            jurisdiction_state_name = None
            jurisdiction_statutes = []
            removal_guest_text = None
            removal_tenant_text = None
        # Owner tokens are not shared with guests; guest never sees USAT token.
        usat_token = None
        revoked_at = getattr(s, "revoked_at", None)
        vacate_by = (revoked_at + timedelta(hours=12)).isoformat() if revoked_at else None
        checked_out_at = getattr(s, "checked_out_at", None)
        cancelled_at = getattr(s, "cancelled_at", None)
        invite_id_val = None
        token_state_val = None
        if getattr(s, "invitation_id", None):
            inv = db.query(Invitation).filter(Invitation.id == s.invitation_id).first()
            if inv:
                invite_id_val = inv.invitation_code
                token_state_val = getattr(inv, "token_state", None) or "BURNED"
        out.append(
            GuestStayView(
                stay_id=s.id,
                invite_id=invite_id_val,
                token_state=token_state_val,
                property_live_slug=prop.live_slug if prop else None,
                property_name=property_name,
                approved_stay_start_date=s.stay_start_date,
                approved_stay_end_date=s.stay_end_date,
                region_code=s.region_code,
                region_classification=classification,
                legal_notice=legal_notice,
                statute_reference=statute,
                plain_english_explanation=explanation,
                applicable_laws=laws,
                jurisdiction_state_name=jurisdiction_state_name,
                jurisdiction_statutes=jurisdiction_statutes,
                removal_guest_text=removal_guest_text,
                removal_tenant_text=removal_tenant_text,
                usat_token=usat_token,
                revoked_at=revoked_at,
                vacate_by=vacate_by,
                checked_in_at=getattr(s, "checked_in_at", None),
                checked_out_at=checked_out_at,
                cancelled_at=cancelled_at,
            )
        )
    return out


@router.post("/guest/stays/{stay_id}/check-in")
def guest_check_in(
    request: Request,
    stay_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_guest),
):
    """Guest records check-in: sets checked_in_at and property occupancy to OCCUPIED. Stay must be on or after start date, not already checked in/out/cancelled."""
    stay = db.query(Stay).filter(Stay.id == stay_id, Stay.guest_id == current_user.id).first()
    if not stay:
        raise HTTPException(status_code=404, detail="Stay not found")
    if getattr(stay, "checked_in_at", None):
        return {"status": "success", "message": "Already checked in."}
    if getattr(stay, "checked_out_at", None):
        raise HTTPException(status_code=400, detail="Cannot check in to a stay you have already checked out of.")
    if getattr(stay, "cancelled_at", None):
        raise HTTPException(status_code=400, detail="Cannot check in to a cancelled stay.")
    today = date.today()
    if stay.stay_start_date > today:
        raise HTTPException(status_code=400, detail="Check-in is only available on or after your stay start date.")
    now = datetime.now(timezone.utc)
    stay.checked_in_at = now
    db.add(stay)
    prop = db.query(Property).filter(Property.id == stay.property_id).first()
    if prop:
        prop.occupancy_status = OccupancyStatus.occupied.value
        if getattr(prop, "shield_mode_enabled", 0) == 1:
            prop.shield_mode_enabled = 0
        db.add(prop)
    db.commit()
    ip = request.client.host if request.client else None
    ua = (request.headers.get("user-agent") or "").strip() or None
    guest_user = db.query(User).filter(User.id == stay.guest_id).first()
    guest_profile = db.query(GuestProfile).filter(GuestProfile.user_id == stay.guest_id).first()
    guest_name = (guest_profile.full_legal_name if guest_profile else None) or (guest_user.full_name if guest_user else None) or (guest_user.email if guest_user else None) or "Guest"
    property_name = (prop.name if prop else None) or (f"{prop.city}, {prop.state}".strip(", ") if prop and (prop.city or prop.state) else None) or f"property {stay.property_id}"
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "Guest checked in",
        f"{guest_name} checked in at {property_name}. Occupancy set to occupied.",
        property_id=stay.property_id,
        stay_id=stay.id,
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=ip,
        user_agent=ua,
        meta={"occupancy_status_new": "occupied", "guest_name": guest_name, "guest_id": stay.guest_id},
    )
    db.commit()

    # Dev/test only: turn DMS on 2 min after check-in (from invitation preference). In prod, DMS turns on 48h before lease end (stay_timer).
    try:
        from app.config import get_settings
        from app.database import SessionLocal
        from app.services.stay_timer import run_dead_mans_switch_job
        _settings = get_settings()
        scheduler = getattr(request.app.state, "scheduler", None)
        dms_test = getattr(_settings, "dms_test_mode", False)
        if scheduler and dms_test:
            stay_id = stay.id
            run_at = now + timedelta(minutes=2)

            def _turn_dms_on_2min_after_checkin(sid: int):
                _db = SessionLocal()
                logger.info("DMS 2min-after-checkin job started for stay_id=%s", sid)
                try:
                    _stay = _db.query(Stay).filter(Stay.id == sid).first()
                    if not _stay:
                        logger.info("DMS 2min-after-checkin job: stay_id=%s not found, skipped", sid)
                        return
                    if getattr(_stay, "dead_mans_switch_enabled", 0) == 1:
                        logger.info(
                            "DMS 2min-after-checkin job: stay_id=%s already has DMS on, skipped",
                            sid,
                        )
                    elif getattr(_stay, "dead_mans_switch_enabled", 0) == 0:
                        inv = None
                        if getattr(_stay, "invitation_id", None):
                            inv = _db.query(Invitation).filter(Invitation.id == _stay.invitation_id).first()
                        # In test mode always turn DMS on after 2 min so testing works. Otherwise only if invitation had DMS enabled.
                        turn_on = getattr(_settings, "dms_test_mode", False) or (
                            inv and getattr(inv, "dead_mans_switch_enabled", 0)
                        )
                        if not turn_on:
                            if not inv:
                                logger.info(
                                    "DMS 2min-after-checkin job: stay_id=%s has no invitation, skipped (DMS not turned on)",
                                    sid,
                                )
                            else:
                                logger.info(
                                    "DMS 2min-after-checkin job: stay_id=%s invitation has DMS off, skipped",
                                    sid,
                                )
                        else:
                            _stay.dead_mans_switch_enabled = 1
                            _db.add(_stay)
                            _db.commit()
                            logger.info(
                                "DMS 2min-after-checkin job: turned DMS on for stay_id=%s (test_mode=%s, inv_dms=%s)",
                                sid,
                                getattr(_settings, "dms_test_mode", False),
                                getattr(inv, "dead_mans_switch_enabled", 0) if inv else None,
                            )
                    if getattr(_settings, "dms_test_mode", False):
                        logger.info("DMS 2min-after-checkin job: running run_dead_mans_switch_job (test mode)")
                        run_dead_mans_switch_job(_db)
                except Exception as e:
                    logger.exception(
                        "DMS 2min-after-checkin job: stay_id=%s failed: %s",
                        sid,
                        e,
                    )
                finally:
                    _db.close()
                    logger.info("DMS 2min-after-checkin job finished for stay_id=%s", sid)

            logger.info(
                "DMS 2min-after-checkin: scheduling job for stay_id=%s, run_at=%s",
                stay_id,
                run_at.isoformat(),
            )
            scheduler.add_job(_turn_dms_on_2min_after_checkin, "date", run_date=run_at, args=[stay_id])
        else:
            logger.info(
                "DMS 2min-after-checkin: not scheduling for stay_id=%s (dms_test_mode=%s, scheduler=%s)",
                stay.id,
                dms_test,
                scheduler is not None,
            )
    except Exception as e:
        logger.warning("DMS 2min-after-checkin: failed to schedule job for stay_id=%s: %s", stay.id, e)

    return {"status": "success", "message": "You are checked in. Your stay is now active."}


@router.get("/guest/stays/{stay_id}/signed-agreement-pdf")
def guest_stay_signed_agreement_pdf(
    stay_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_guest),
):
    """Return the signed guest agreement PDF for this stay. Guest must own the stay. Returns 404 if no signed agreement (e.g. stay created before signing flow)."""
    stay = db.query(Stay).filter(Stay.id == stay_id, Stay.guest_id == current_user.id).first()
    if not stay:
        raise HTTPException(status_code=404, detail="Stay not found")
    inv = (
        db.query(Invitation)
        .filter(
            Invitation.property_id == stay.property_id,
            Invitation.stay_start_date == stay.stay_start_date,
            Invitation.stay_end_date == stay.stay_end_date,
            Invitation.status == "accepted",
        )
        .first()
    )
    if not inv:
        raise HTTPException(status_code=404, detail="No signed agreement found for this stay.")
    sig = (
        db.query(AgreementSignature)
        .filter(
            AgreementSignature.invitation_code == inv.invitation_code,
            AgreementSignature.used_by_user_id == current_user.id,
        )
        .order_by(AgreementSignature.signed_at.desc())
        .first()
    )
    if not sig:
        raise HTTPException(status_code=404, detail="No signed agreement found for this stay.")
    # When this stay was signed via Dropbox, always prefer the PDF from Dropbox (overwrites any old self-generated bytes)
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
            detail="Document not yet signed in Dropbox. Please complete signing in the link we sent you.",
        )
    if sig.signed_pdf_bytes:
        return Response(
            content=sig.signed_pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="DocuStay-Signed-{sig.invitation_code}.pdf"'},
        )
    # Legacy: stay signed in-app (no Dropbox); generate from stored content
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


@router.post("/guest/stays/{stay_id}/end")
def guest_end_stay(
    request: Request,
    stay_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_guest),
):
    """Let the guest end an ongoing stay (set end date to today). Revoked stays can still be ended so the guest can record checkout."""
    stay = db.query(Stay).filter(Stay.id == stay_id, Stay.guest_id == current_user.id).first()
    if not stay:
        raise HTTPException(status_code=404, detail="Stay not found")
    today = date.today()
    if stay.stay_start_date > today:
        raise HTTPException(status_code=400, detail="Cannot end a future stay.")
    if stay.stay_end_date < today:
        raise HTTPException(status_code=400, detail="This stay has already ended.")
    if getattr(stay, "checked_out_at", None):
        raise HTTPException(status_code=400, detail="You have already checked out of this stay.")
    stay.stay_end_date = today
    stay.checked_out_at = datetime.now(timezone.utc)
    invite_code = None
    if getattr(stay, "invitation_id", None):
        inv = db.query(Invitation).filter(Invitation.id == stay.invitation_id).first()
        if inv:
            prev_token = getattr(inv, "token_state", None) or "BURNED"
            inv.token_state = "EXPIRED"
            invite_code = inv.invitation_code
            db.add(inv)
    db.add(stay)
    db.flush()
    # If no other checked-in active stay at this property, set occupancy to vacant
    other_active = (
        db.query(Stay)
        .filter(
            Stay.property_id == stay.property_id,
            Stay.id != stay.id,
            Stay.checked_in_at.isnot(None),
            Stay.checked_out_at.is_(None),
            Stay.cancelled_at.is_(None),
        )
        .first()
    )
    occ_prev = None
    if not other_active:
        prop = db.query(Property).filter(Property.id == stay.property_id).first()
        if prop:
            occ_prev = getattr(prop, "occupancy_status", None) or "unknown"
            if prop.usat_token_state == USAT_TOKEN_RELEASED:
                prop.usat_token_state = USAT_TOKEN_STAGED
                prop.usat_token_released_at = None
            prop.occupancy_status = OccupancyStatus.vacant.value
            db.add(prop)
    db.commit()
    ip = request.client.host if request.client else None
    ua = (request.headers.get("user-agent") or "").strip() or None
    log_meta = {}
    if occ_prev is not None:
        log_meta["occupancy_status_previous"] = occ_prev
        log_meta["occupancy_status_new"] = "vacant"
    if invite_code:
        log_meta["invitation_code"] = invite_code
        log_meta["token_state_previous"] = prev_token
        log_meta["token_state_new"] = "EXPIRED"
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "Guest checked out",
        f"Guest checked out of stay {stay.id} (property {stay.property_id}). End date set to {today.isoformat()}." + (f" Invite ID {invite_code} token_state -> EXPIRED." if invite_code else "") + (f" Occupancy status: {occ_prev} -> vacant." if occ_prev is not None else ""),
        property_id=stay.property_id,
        stay_id=stay.id,
        invitation_id=getattr(stay, "invitation_id", None),
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=ip,
        user_agent=ua,
        meta=log_meta if log_meta else None,
    )
    db.commit()
    # Notify owner and guest about checkout
    owner = db.query(User).filter(User.id == stay.owner_id).first()
    property_obj = db.query(Property).filter(Property.id == stay.property_id).first()
    guest_name = (current_user.full_name or "").strip() or "Guest"
    property_name = (property_obj.name if property_obj else None) or "your property"
    # Email to owner
    if owner and owner.email:
        send_owner_guest_checkout_email(
            owner.email,
            guest_name,
            property_name,
            today.isoformat(),
        )
    # Email to guest (checkout confirmation)
    if current_user.email:
        send_guest_checkout_confirmation_email(
            current_user.email,
            guest_name,
            property_name,
            today.isoformat(),
        )
    return {"status": "success", "message": "Stay ended."}


@router.post("/guest/stays/{stay_id}/cancel")
def guest_cancel_stay(
    request: Request,
    stay_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_guest),
):
    """Let the guest cancel a future stay (set end date to day before start so the stay is no longer upcoming)."""
    stay = db.query(Stay).filter(Stay.id == stay_id, Stay.guest_id == current_user.id).first()
    if not stay:
        raise HTTPException(status_code=404, detail="Stay not found")
    today = date.today()
    if stay.stay_start_date <= today:
        raise HTTPException(status_code=400, detail="Only future stays can be cancelled. Use checkout to end an ongoing stay.")
    if getattr(stay, "cancelled_at", None):
        raise HTTPException(status_code=400, detail="This stay has already been cancelled.")
    original_start = stay.stay_start_date
    # Set end date to day before start so the stay is effectively cancelled and shows as past
    stay.stay_end_date = original_start - timedelta(days=1)
    stay.cancelled_at = datetime.now(timezone.utc)
    invite_code = None
    if getattr(stay, "invitation_id", None):
        inv = db.query(Invitation).filter(Invitation.id == stay.invitation_id).first()
        if inv:
            prev_token = getattr(inv, "token_state", None) or "BURNED"
            inv.token_state = "REVOKED"
            invite_code = inv.invitation_code
            db.add(inv)
    db.add(stay)
    db.flush()
    # If no other active stay at this property, revoke USAT and set status to VACANT
    other_active = (
        db.query(Stay)
        .filter(
            Stay.property_id == stay.property_id,
            Stay.id != stay.id,
            Stay.checked_out_at.is_(None),
            Stay.cancelled_at.is_(None),
        )
        .first()
    )
    occ_prev = None
    if not other_active:
        prop = db.query(Property).filter(Property.id == stay.property_id).first()
        if prop:
            occ_prev = getattr(prop, "occupancy_status", None) or "unknown"
            if prop.usat_token_state == USAT_TOKEN_RELEASED:
                prop.usat_token_state = USAT_TOKEN_STAGED
                prop.usat_token_released_at = None
            prop.occupancy_status = OccupancyStatus.vacant.value
            db.add(prop)
    db.commit()
    ip = request.client.host if request.client else None
    ua = (request.headers.get("user-agent") or "").strip() or None
    log_meta = {"original_start_date": str(original_start)}
    if occ_prev is not None:
        log_meta["occupancy_status_previous"] = occ_prev
        log_meta["occupancy_status_new"] = "vacant"
    if invite_code:
        log_meta["invitation_code"] = invite_code
        log_meta["token_state_previous"] = prev_token
        log_meta["token_state_new"] = "REVOKED"
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "Stay cancelled by guest",
        f"Guest cancelled stay {stay.id} (property {stay.property_id}). Original start was {original_start.isoformat()}." + (f" Invite ID {invite_code} token_state -> REVOKED." if invite_code else "") + (f" Occupancy status: {occ_prev} -> vacant." if occ_prev else ""),
        property_id=stay.property_id,
        stay_id=stay.id,
        invitation_id=getattr(stay, "invitation_id", None),
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=ip,
        user_agent=ua,
        meta=log_meta,
    )
    db.commit()
    # Notify owner that guest cancelled
    owner = db.query(User).filter(User.id == stay.owner_id).first()
    property_obj = db.query(Property).filter(Property.id == stay.property_id).first()
    if owner and owner.email:
        guest_name = (current_user.full_name or "").strip() or "Guest"
        property_name = (property_obj.name if property_obj else None) or "your property"
        send_owner_guest_cancelled_stay_email(
            owner.email,
            guest_name,
            property_name,
            original_start.isoformat(),
        )
    return {"status": "success", "message": "Stay cancelled."}


def _parse_optional_utc(s: str | None) -> datetime | None:
    if not s or not s.strip():
        return None
    try:
        d = datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d
    except (ValueError, TypeError):
        return None


@router.get("/owner/billing", response_model=BillingResponse)
def owner_billing(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """List Stripe invoices and payments for the current owner. Returns empty lists if Stripe is not configured or no customer yet.
    can_invite is False until the onboarding invoice has been paid (when one was charged)."""
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile:
        return BillingResponse(invoices=[], payments=[], can_invite=True, current_unit_count=0, current_shield_count=0)
    from app.services.billing import _count_units_and_shield
    _units, _shield = _count_units_and_shield(db, profile)
    if not profile.stripe_customer_id:
        can_invite = profile.onboarding_billing_completed_at is None or profile.onboarding_invoice_paid_at is not None
        return BillingResponse(invoices=[], payments=[], can_invite=can_invite, current_unit_count=_units, current_shield_count=_shield)

    from app.config import get_settings
    settings = get_settings()
    if not (settings.stripe_secret_key or "").strip():
        return BillingResponse(invoices=[], payments=[], current_unit_count=_units, current_shield_count=_shield)

    import stripe
    stripe.api_key = settings.stripe_secret_key
    invoices: list[BillingInvoiceView] = []
    payments: list[BillingPaymentView] = []
    try:
        for inv in stripe.Invoice.list(customer=profile.stripe_customer_id, limit=100).auto_paging_iter():
            # Auto-finalize drafts so user gets a payable invoice; skip if finalize fails
            if inv.status == "draft":
                try:
                    inv = stripe.Invoice.finalize_invoice(inv.id)
                except stripe.StripeError:
                    continue
            # Never expose draft to the client
            if inv.status == "draft":
                continue
            created_dt = datetime.fromtimestamp(inv.created, tz=timezone.utc) if inv.created else datetime.now(timezone.utc)
            amount_due = getattr(inv, "amount_due", 0) or 0
            amount_paid = getattr(inv, "amount_paid", 0) or 0
            desc = getattr(inv, "description", None) or None
            if not desc and getattr(inv, "lines", None) and getattr(inv.lines, "data", None) and len(inv.lines.data) > 0:
                desc = getattr(inv.lines.data[0], "description", None)
            invoices.append(
                BillingInvoiceView(
                    id=inv.id,
                    number=getattr(inv, "number", None) or None,
                    description=desc,
                    amount_due_cents=amount_due,
                    amount_paid_cents=amount_paid,
                    currency=(inv.currency or "usd").upper(),
                    status=inv.status or "open",
                    created=created_dt,
                    hosted_invoice_url=getattr(inv, "hosted_invoice_url", None) or None,
                )
            )
            if inv.status == "paid" and amount_paid > 0:
                paid_at = datetime.fromtimestamp(inv.status_transitions.paid_at, tz=timezone.utc) if getattr(inv, "status_transitions", None) and getattr(inv.status_transitions, "paid_at", None) else created_dt
                payments.append(
                    BillingPaymentView(
                        invoice_id=inv.id,
                        amount_cents=amount_paid,
                        currency=(inv.currency or "usd").upper(),
                        paid_at=paid_at,
                        description=desc,
                    )
                )
            # Self-heal: if webhook missed invoice.paid, set onboarding_invoice_paid_at and record in audit log so it shows in Logs (skip when stripe_skip_onboarding_self_heal for re-testing)
            meta = getattr(inv, "metadata", None) or {}
            if not settings.stripe_skip_onboarding_self_heal and inv.status == "paid" and meta.get("onboarding_units") and profile.onboarding_invoice_paid_at is None:
                profile.onboarding_invoice_paid_at = datetime.now(timezone.utc)
                user = db.query(User).filter(User.id == profile.user_id).first()
                create_log(
                    db,
                    CATEGORY_BILLING,
                    "Invoice paid",
                    f"Invoice {getattr(inv, 'number', inv.id)} paid: ${amount_paid / 100:.2f} {(inv.currency or 'usd').upper()}.",
                    property_id=None,
                    actor_user_id=user.id if user else None,
                    actor_email=user.email if user else None,
                    meta={"stripe_invoice_id": inv.id, "amount_paid_cents": amount_paid, "currency": (inv.currency or "usd").upper(), "self_heal": True},
                )
                db.commit()
    except stripe.StripeError:
        can_invite = profile.onboarding_billing_completed_at is None or profile.onboarding_invoice_paid_at is not None
        return BillingResponse(invoices=[], payments=[], can_invite=can_invite, current_unit_count=_units, current_shield_count=_shield)

    # Sort invoices by created desc, payments by paid_at desc
    invoices.sort(key=lambda x: x.created, reverse=True)
    payments.sort(key=lambda x: x.paid_at, reverse=True)
    # Recompute unit counts (may have changed) and can_invite (may have been set by self-heal above)
    _units, _shield = _count_units_and_shield(db, profile)
    can_invite = profile.onboarding_billing_completed_at is None or profile.onboarding_invoice_paid_at is not None
    return BillingResponse(invoices=invoices, payments=payments, can_invite=can_invite, current_unit_count=_units, current_shield_count=_shield)


@router.post("/owner/billing/portal-session", response_model=BillingPortalSessionResponse)
def create_billing_portal_session(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Create a Stripe Customer Billing Portal session. Redirect the user to the returned URL to pay invoices.
    After payment (including Klarna or other redirect methods), Stripe redirects back to our app (return_url).
    This avoids the issue where paying via Klarna leaves the user stuck on pay.test.klarna.com with no way back."""
    from app.config import get_settings
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile or not profile.stripe_customer_id:
        raise HTTPException(status_code=404, detail="No billing customer. Add a property first.")
    settings = get_settings()
    if not (settings.stripe_secret_key or "").strip():
        raise HTTPException(status_code=501, detail="Stripe is not configured")
    base = (settings.stripe_identity_return_url or settings.frontend_base_url or "").strip().split("#")[0].rstrip("/")
    if not base:
        raise HTTPException(status_code=501, detail="Billing return URL not configured. Set STRIPE_IDENTITY_RETURN_URL or FRONTEND_BASE_URL in .env.")
    # Land on Billing tab so we can refetch and show updated status (frontend detects payment return via query params)
    return_url = f"{base}/#dashboard/billing"
    import stripe
    stripe.api_key = settings.stripe_secret_key
    try:
        session = stripe.billing_portal.Session.create(
            customer=profile.stripe_customer_id,
            return_url=return_url,
        )
        return BillingPortalSessionResponse(url=session.url)
    except stripe.StripeError as e:
        raise HTTPException(status_code=502, detail=f"Stripe error: {e}")


@router.get("/owner/portfolio-link", response_model=PortfolioLinkResponse)
def owner_portfolio_link(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Get or create the current owner's portfolio slug and URL. Used in Settings to view/copy portfolio link."""
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Owner profile not found")
    slug = getattr(profile, "portfolio_slug", None)
    if not slug:
        for _ in range(20):
            slug = secrets.token_urlsafe(8).replace("+", "-").replace("/", "_")[:16]
            if db.query(OwnerProfile).filter(OwnerProfile.portfolio_slug == slug).first() is None:
                profile.portfolio_slug = slug
                db.add(profile)
                db.commit()
                break
        else:
            slug = f"p-{profile.id}-{secrets.token_hex(4)}"
            profile.portfolio_slug = slug
            db.add(profile)
            db.commit()
    return PortfolioLinkResponse(portfolio_slug=slug, portfolio_url=f"portfolio/{slug}")


@router.get("/owner/logs", response_model=list[OwnerAuditLogEntry])
def owner_logs(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
    from_ts: str | None = None,
    to_ts: str | None = None,
    category: str | None = None,
    search: str | None = None,
):
    """Append-only audit logs for the owner's properties. Filter by time range (ISO UTC), category, and search (title/message). Includes 'Property deleted' logs (property_id may be null after delete)."""
    from sqlalchemy import or_

    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile:
        return []
    property_ids = [p.id for p in profile.properties]

    from_dt = _parse_optional_utc(from_ts)
    to_dt = _parse_optional_utc(to_ts)

    # Logs for owner's properties, "Property deleted" by this owner, or billing logs for this owner
    if property_ids:
        q = db.query(AuditLog).filter(
            or_(
                AuditLog.property_id.in_(property_ids),
                (
                    (AuditLog.property_id.is_(None))
                    & (AuditLog.title == "Property deleted")
                    & (AuditLog.actor_user_id == current_user.id)
                ),
                (AuditLog.category == CATEGORY_BILLING) & (AuditLog.actor_user_id == current_user.id),
            )
        )
    else:
        q = db.query(AuditLog).filter(
            or_(
                (AuditLog.title == "Property deleted") & (AuditLog.actor_user_id == current_user.id),
                (AuditLog.category == CATEGORY_BILLING) & (AuditLog.actor_user_id == current_user.id),
            )
        )
    if from_dt is not None:
        q = q.filter(AuditLog.created_at >= from_dt)
    if to_dt is not None:
        q = q.filter(AuditLog.created_at <= to_dt)
    if category and category.strip():
        q = q.filter(AuditLog.category == category.strip())
    if search and search.strip():
        term = f"%{search.strip()}%"
        q = q.filter(
            (AuditLog.title.ilike(term)) | (AuditLog.message.ilike(term))
        )
    q = q.order_by(AuditLog.created_at.desc())
    rows = q.all()

    # Resolve property names for display (from DB for existing properties, from meta for "Property deleted")
    prop_ids = {r.property_id for r in rows if r.property_id}
    props = {}
    if prop_ids:
        for p in db.query(Property).filter(Property.id.in_(prop_ids)).all():
            props[p.id] = p.name or f"{p.city}, {p.state}"

    def _property_name(r) -> str | None:
        if r.property_id:
            return props.get(r.property_id)
        if r.title == "Property deleted" and r.meta and isinstance(r.meta, dict):
            return r.meta.get("property_name")
        return None

    def _safe_created_at(r):
        """Legacy rows may have null created_at; response model requires datetime."""
        if r.created_at is not None:
            return r.created_at
        return datetime.now(timezone.utc)

    return [
        OwnerAuditLogEntry(
            id=r.id,
            property_id=r.property_id,
            stay_id=r.stay_id,
            invitation_id=r.invitation_id,
            category=r.category or "—",
            title=r.title or "—",
            message=r.message or "—",
            actor_user_id=r.actor_user_id,
            actor_email=r.actor_email,
            ip_address=r.ip_address,
            created_at=_safe_created_at(r),
            property_name=_property_name(r),
        )
        for r in rows
    ]
