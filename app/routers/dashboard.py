"""Module F: Legal restrictions & law display (Owner and Guest views)."""
from datetime import date, datetime, timezone, timedelta, time as dt_time
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
from app.schemas.dashboard import OwnerStayView, OwnerInvitationView, GuestStayView, GuestPendingInviteView, OwnerAuditLogEntry
from app.services.jle import resolve_jurisdiction
from app.services.audit_log import create_log, CATEGORY_STATUS_CHANGE, CATEGORY_DEAD_MANS_SWITCH, CATEGORY_FAILED_ATTEMPT
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
    for p in pendings:
        inv = db.query(Invitation).filter(Invitation.id == p.invitation_id, Invitation.status == "pending").first()
        if not inv:
            continue
        prop = db.query(Property).filter(Property.id == inv.property_id).first()
        property_name = (prop.name if prop else None) or (f"{prop.city}, {prop.state}" if prop else None) or "Property"
        owner = db.query(User).filter(User.id == inv.owner_id).first()
        host_name = (owner.full_name if owner else None) or (owner.email if owner else "")
        out.append(
            GuestPendingInviteView(
                invitation_code=inv.invitation_code,
                property_name=property_name,
                stay_start_date=inv.stay_start_date,
                stay_end_date=inv.stay_end_date,
                host_name=host_name,
                region_code=inv.region_code,
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
    inv = db.query(Invitation).filter(Invitation.invitation_code == code, Invitation.status == "pending").first()
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
        return GuestPendingInviteView(
            invitation_code=inv.invitation_code,
            property_name=property_name,
            stay_start_date=inv.stay_start_date,
            stay_end_date=inv.stay_end_date,
            host_name=host_name,
            region_code=inv.region_code,
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
    )


PENDING_INVITATION_EXPIRE_HOURS = 12


@router.get("/owner/invitations", response_model=list[OwnerInvitationView])
def owner_invitations(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Owner view: all invitations (pending, accepted, cancelled) with property name. Pending invites older than 12h are marked is_expired."""
    invs = db.query(Invitation).filter(Invitation.owner_id == current_user.id).order_by(Invitation.created_at.desc()).all()
    threshold = datetime.now(timezone.utc) - timedelta(hours=PENDING_INVITATION_EXPIRE_HOURS)
    out = []
    for inv in invs:
        prop = db.query(Property).filter(Property.id == inv.property_id).first()
        property_name = (prop.name if prop else None) or (f"{prop.city}, {prop.state}" if prop else None) or "Property"
        is_expired = (
            inv.status == "pending"
            and inv.created_at is not None
            and inv.created_at < threshold
        )
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
                status=inv.status,
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
    if inv.status != "pending":
        raise HTTPException(status_code=400, detail="Only pending invitations can be cancelled.")
    inv.status = "cancelled"
    db.commit()
    prop = db.query(Property).filter(Property.id == inv.property_id).first()
    property_name = (prop.name if prop else None) or (f"{prop.city}, {prop.state}" if prop else None) or "Property"
    ip = request.client.host if request.client else None
    ua = (request.headers.get("user-agent") or "").strip() or None
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "Invitation cancelled",
        f"Owner cancelled invitation {inv.invitation_code} for property {property_name}, guest {inv.guest_name or inv.guest_email or '—'}.",
        property_id=inv.property_id,
        invitation_id=inv.id,
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=ip,
        user_agent=ua,
        meta={"invitation_code": inv.invitation_code},
    )
    db.commit()
    return {"status": "success", "message": "Invitation cancelled."}


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

        out.append(
            OwnerStayView(
                stay_id=s.id,
                property_id=s.property_id,
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
    """Revoke a stay (Kill Switch): set revoked_at, guest must vacate in 12 hours. Sends email to guest."""
    stay = db.query(Stay).filter(Stay.id == stay_id, Stay.owner_id == current_user.id).first()
    if not stay:
        raise HTTPException(status_code=404, detail="Stay not found")
    if stay.revoked_at:
        return {"status": "success", "message": "Stay was already revoked."}
    now = datetime.now(timezone.utc)
    stay.revoked_at = now
    vacate_by = now + timedelta(hours=12)
    vacate_by_iso = vacate_by.strftime("%Y-%m-%d %H:%M UTC")
    db.commit()
    ip = request.client.host if request.client else None
    ua = (request.headers.get("user-agent") or "").strip() or None
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "Stay revoked",
        f"Stay {stay.id} revoked by owner. Guest must vacate by {vacate_by_iso}.",
        property_id=stay.property_id,
        stay_id=stay.id,
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=ip,
        user_agent=ua,
        meta={"vacate_by": vacate_by_iso},
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
        if prop.usat_token_state == USAT_TOKEN_RELEASED:
            prop.usat_token_state = USAT_TOKEN_STAGED
            prop.usat_token_released_at = None
        db.add(stay)
        db.add(prop)
        db.commit()
        create_log(
            db,
            CATEGORY_STATUS_CHANGE,
            "Owner confirmed: Unit Vacated",
            f"Stay {stay.id}: Owner confirmed unit vacated. Previous status: {prev_status}.",
            property_id=stay.property_id,
            stay_id=stay.id,
            actor_user_id=current_user.id,
            actor_email=current_user.email,
            ip_address=ip,
            user_agent=ua,
            meta={"occupancy_status_previous": prev_status, "occupancy_status_new": OccupancyStatus.vacant.value, "action": "vacated"},
        )
        db.commit()
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
        prop.occupancy_status = OccupancyStatus.occupied.value
        db.add(stay)
        db.add(prop)
        db.commit()
        create_log(
            db,
            CATEGORY_STATUS_CHANGE,
            "Owner confirmed: Lease Renewed",
            f"Stay {stay.id}: Owner renewed lease to {new_end.isoformat()}. Previous status: {prev_status}.",
            property_id=stay.property_id,
            stay_id=stay.id,
            actor_user_id=current_user.id,
            actor_email=current_user.email,
            ip_address=ip,
            user_agent=ua,
            meta={"occupancy_status_previous": prev_status, "occupancy_status_new": OccupancyStatus.occupied.value, "action": "renewed", "new_lease_end_date": new_end.isoformat()},
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
    """Guest view: property, approved stay dates, region classification, legal notice and laws."""
    stays = db.query(Stay).filter(Stay.guest_id == current_user.id).all()
    out = []
    for s in stays:
        prop = db.query(Property).filter(Property.id == s.property_id).first()
        property_name = (prop.name if prop else None) or (f"{prop.city}, {prop.state}" if prop else None) or "Property"
        rule = db.query(RegionRule).filter(RegionRule.region_code == s.region_code).first()
        classification = rule.stay_classification_label.value if rule else "guest"
        statute = rule.statute_reference if rule else None
        explanation = rule.plain_english_explanation if rule else None
        laws = [rule.statute_reference] if rule and rule.statute_reference else []
        # Only show USAT token to this guest if the owner explicitly released it to this stay (per-guest release).
        usat_token = None
        released_at = getattr(s, "usat_token_released_at", None)
        if prop and prop.usat_token and released_at is not None:
            usat_token = prop.usat_token
        revoked_at = getattr(s, "revoked_at", None)
        vacate_by = (revoked_at + timedelta(hours=12)).isoformat() if revoked_at else None
        checked_out_at = getattr(s, "checked_out_at", None)
        cancelled_at = getattr(s, "cancelled_at", None)
        out.append(
            GuestStayView(
                stay_id=s.id,
                property_name=property_name,
                approved_stay_start_date=s.stay_start_date,
                approved_stay_end_date=s.stay_end_date,
                region_code=s.region_code,
                region_classification=classification,
                legal_notice="This stay does not grant tenancy or homestead rights.",
                statute_reference=statute,
                plain_english_explanation=explanation,
                applicable_laws=laws,
                usat_token=usat_token,
                revoked_at=revoked_at,
                vacate_by=vacate_by,
                checked_out_at=checked_out_at,
                cancelled_at=cancelled_at,
            )
        )
    return out


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
    if sig.signed_pdf_bytes:
        return Response(
            content=sig.signed_pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="DocuStay-Signed-{sig.invitation_code}.pdf"'},
        )
    if sig.dropbox_sign_request_id:
        pdf_bytes = get_signed_pdf(sig.dropbox_sign_request_id)
        if pdf_bytes:
            sig.signed_pdf_bytes = pdf_bytes
            db.commit()
            return Response(
                content=pdf_bytes,
                media_type="application/pdf",
                headers={"Content-Disposition": f'inline; filename="DocuStay-Signed-{sig.invitation_code}.pdf"'},
            )
    date_str = sig.signed_at.strftime("%Y-%m-%d") if sig.signed_at else ""
    content = fill_guest_signature_in_content(sig.document_content, sig.typed_signature, date_str)
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
    db.add(stay)
    db.flush()
    # If no other active stay at this property, revoke USAT (utility lock) so occupancy is effectively vacant
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
    log_meta = {}
    if occ_prev is not None:
        log_meta = {"occupancy_status_previous": occ_prev, "occupancy_status_new": "vacant"}
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "Guest checked out",
        f"Guest checked out of stay {stay.id} (property {stay.property_id}). End date set to {today.isoformat()}." + (f" Occupancy status: {occ_prev} -> vacant." if occ_prev is not None else ""),
        property_id=stay.property_id,
        stay_id=stay.id,
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
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "Stay cancelled by guest",
        f"Guest cancelled stay {stay.id} (property {stay.property_id}). Original start was {original_start.isoformat()}." + (f" Occupancy status: {occ_prev} -> vacant." if occ_prev else ""),
        property_id=stay.property_id,
        stay_id=stay.id,
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

    # Logs for owner's current properties, OR "Property deleted" logs by this owner (property_id set to null after delete)
    if property_ids:
        q = db.query(AuditLog).filter(
            or_(
                AuditLog.property_id.in_(property_ids),
                (
                    (AuditLog.property_id.is_(None))
                    & (AuditLog.title == "Property deleted")
                    & (AuditLog.actor_user_id == current_user.id)
                ),
            )
        )
    else:
        q = db.query(AuditLog).filter(
            AuditLog.title == "Property deleted",
            AuditLog.actor_user_id == current_user.id,
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
