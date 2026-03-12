"""Module F: Legal restrictions & law display (Owner and Guest views)."""
import logging
import secrets
from datetime import date, datetime, timezone, timedelta, time as dt_time

logger = logging.getLogger(__name__)
from fastapi import APIRouter, Depends, HTTPException, Request, Body
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy import or_
from pydantic import BaseModel, Field
from app.database import get_db
from app.models.user import User, UserRole
from app.models.stay import Stay
from app.models.invitation import Invitation
from app.models.guest import GuestProfile, PurposeOfStay, RelationshipToOwner
from app.models.region_rule import RegionRule
from app.models.owner import Property, OwnerProfile, USAT_TOKEN_STAGED, USAT_TOKEN_RELEASED, OccupancyStatus
from app.models.guest_pending_invite import GuestPendingInvite
from app.models.agreement_signature import AgreementSignature
from app.models.region_rule import StayClassification, RiskLevel
from app.schemas.dashboard import OwnerStayView, OwnerInvitationView, GuestStayView, GuestPendingInviteView, JurisdictionStatuteInDashboard, OwnerAuditLogEntry, BillingResponse, BillingInvoiceView, BillingPaymentView, BillingPortalSessionResponse, PortfolioLinkResponse
from app.services.jle import resolve_jurisdiction
from app.services.jurisdiction_sot import get_jurisdiction_for_property
from app.services.audit_log import create_log, CATEGORY_STATUS_CHANGE, CATEGORY_PRESENCE, CATEGORY_DEAD_MANS_SWITCH, CATEGORY_FAILED_ATTEMPT, CATEGORY_BILLING, CATEGORY_SHIELD_MODE
from app.services.event_ledger import (
    create_ledger_event,
    ledger_event_to_display,
    get_actor_email,
    _CATEGORY_TO_ACTION_TYPES,
    ACTION_PROPERTY_DELETED,
    ACTION_BILLING_INVOICE_PAID,
    ACTION_BILLING_INVOICE_CREATED,
    ACTION_GUEST_INVITE_CANCELLED,
    ACTION_GUEST_INVITE_CREATED,
    ACTION_CONFIRMED_STILL_VACANT,
    ACTION_STAY_REVOKED,
    ACTION_UNIT_VACATED,
    ACTION_DMS_DISABLED,
    ACTION_LEASE_RENEWED,
    ACTION_HOLDOVER_CONFIRMED,
    ACTION_GUEST_CHECK_IN,
    ACTION_GUEST_CHECK_OUT,
    ACTION_TENANT_CHECK_OUT,
    ACTION_TENANT_ASSIGNMENT_CANCELLED,
    ACTION_STAY_CANCELLED,
    ACTION_PRESENCE_STATUS_CHANGED,
    ACTION_AWAY_ACTIVATED,
    ACTION_AWAY_ENDED,
    ACTION_BILLING_INVOICE_PAID,
    ACTION_SHIELD_MODE_ON,
    ACTION_SHIELD_MODE_OFF,
)
from app.services.invitation_cleanup import get_invitation_expire_cutoff
from app.services.billing import sync_subscription_quantities
from app.services.notifications import send_vacate_12h_notice, send_owner_guest_checkout_email, send_guest_checkout_confirmation_email, send_owner_guest_cancelled_stay_email, send_removal_notice_to_guest, send_removal_confirmation_to_owner, send_dead_mans_switch_enabled_notification, send_shield_mode_turned_on_notification, send_shield_mode_turned_off_notification, send_dms_turned_off_notification
from app.schemas.jle import JLEInput
from app.dependencies import get_current_user, require_owner, require_owner_onboarding_complete, require_guest, require_tenant, require_guest_or_tenant, require_owner_or_manager, require_property_manager, require_property_manager_identity_verified, get_context_mode
from app.models.audit_log import AuditLog
from app.models.event_ledger import EventLedger
from app.services.agreements import fill_guest_signature_in_content, agreement_content_to_pdf
from app.services.dropbox_sign import get_signed_pdf
from app.models.unit import Unit
from app.models.tenant_assignment import TenantAssignment
from app.models.property_manager_assignment import PropertyManagerAssignment
from app.models.resident_presence import ResidentPresence, PresenceStatus
from app.models.stay_presence import StayPresence, PresenceAwayPeriod
from app.services.permissions import can_access_unit, can_access_property, can_confirm_occupancy, can_perform_action, Action, get_owner_personal_mode_units, get_manager_personal_mode_units
from app.services.privacy_lanes import (
    is_tenant_lane_invitation,
    is_tenant_lane_stay,
    filter_property_lane_invitations_for_owner,
    filter_property_lane_stays_for_owner,
    filter_property_lane_invitations_for_manager,
    filter_property_lane_stays_for_manager,
    filter_tenant_lane_from_ledger_rows,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class TenantGuestInvitationCreate(BaseModel):
    unit_id: int = Field(..., gt=0, description="Unit ID (required)")
    guest_name: str = Field("", description="Guest full name")
    checkin_date: str = Field("", description="Start date (YYYY-MM-DD)")
    checkout_date: str = Field("", description="End date (YYYY-MM-DD)")


class BulkShieldModeRequest(BaseModel):
    property_ids: list[int] = Field(..., description="Property IDs to update")
    shield_mode_enabled: bool = Field(..., description="True to turn Shield ON, False to turn OFF")


@router.get("/guest/pending-invites", response_model=list[GuestPendingInviteView])
def guest_pending_invites(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_guest_or_tenant),
):
    """List invitations this guest/tenant has as pending (saved from dashboard paste or login/signup with link; not yet signed)."""
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
        unit_label_val = None
        if getattr(inv, "unit_id", None):
            unit_row = db.query(Unit).filter(Unit.id == inv.unit_id).first()
            if unit_row:
                unit_label_val = unit_row.unit_label
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
            if sig:
                if getattr(sig, "dropbox_sign_request_id", None):
                    if not getattr(sig, "signed_pdf_bytes", None):
                        pdf_bytes = get_signed_pdf(sig.dropbox_sign_request_id)
                        if pdf_bytes:
                            sig.signed_pdf_bytes = pdf_bytes
                            db.commit()
                            db.refresh(sig)
                    if not getattr(sig, "signed_pdf_bytes", None):
                        needs_dropbox = True
                        pending_sig_id = sig.id
                    elif getattr(sig, "used_by_user_id", None) is None:
                        accept_now_sig_id = sig.id
                elif getattr(sig, "signed_pdf_bytes", None) and getattr(sig, "used_by_user_id", None) is None:
                    accept_now_sig_id = sig.id
        out.append(
            GuestPendingInviteView(
                invitation_code=inv.invitation_code,
                property_name=property_name,
                unit_label=unit_label_val,
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
    current_user: User = Depends(require_guest_or_tenant),
):
    """Add an invitation to this guest's or tenant's pending list. Used when a logged-in guest or tenant pastes an invitation link on the dashboard or after login/signup with link. Returns invite details; frontend then shows the agreement modal to view and sign."""
    code = (invitation_code or "").strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="invitation_code is required")
    inv = db.query(Invitation).filter(
        Invitation.invitation_code == code,
        Invitation.status.in_(["pending", "ongoing"]),
        or_(
            Invitation.invitation_kind == "tenant",
            Invitation.token_state != "BURNED",
        ),
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
            if sig:
                if getattr(sig, "dropbox_sign_request_id", None):
                    if not getattr(sig, "signed_pdf_bytes", None):
                        pdf_bytes = get_signed_pdf(sig.dropbox_sign_request_id)
                        if pdf_bytes:
                            sig.signed_pdf_bytes = pdf_bytes
                            db.commit()
                            db.refresh(sig)
                    if not getattr(sig, "signed_pdf_bytes", None):
                        needs_dropbox, pending_sig_id = True, sig.id
                    elif getattr(sig, "used_by_user_id", None) is None:
                        accept_now_sig_id = sig.id
                elif getattr(sig, "signed_pdf_bytes", None) and getattr(sig, "used_by_user_id", None) is None:
                    accept_now_sig_id = sig.id
        unit_label_val = None
        if getattr(inv, "unit_id", None):
            unit_row = db.query(Unit).filter(Unit.id == inv.unit_id).first()
            if unit_row:
                unit_label_val = unit_row.unit_label
        return GuestPendingInviteView(
            invitation_code=inv.invitation_code,
            property_name=property_name,
            unit_label=unit_label_val,
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
    unit_label_val = None
    if getattr(inv, "unit_id", None):
        unit_row = db.query(Unit).filter(Unit.id == inv.unit_id).first()
        if unit_row:
            unit_label_val = unit_row.unit_label
    owner = db.query(User).filter(User.id == inv.owner_id).first()
    host_name = (owner.full_name if owner else None) or (owner.email if owner else "")
    # Check for an existing completed signature so the frontend can accept directly without re-signing
    needs_dropbox = False
    pending_sig_id = None
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
        if sig:
            if getattr(sig, "dropbox_sign_request_id", None):
                if not getattr(sig, "signed_pdf_bytes", None):
                    pdf_bytes = get_signed_pdf(sig.dropbox_sign_request_id)
                    if pdf_bytes:
                        sig.signed_pdf_bytes = pdf_bytes
                        db.commit()
                        db.refresh(sig)
                if not getattr(sig, "signed_pdf_bytes", None):
                    needs_dropbox = True
                    pending_sig_id = sig.id
                elif getattr(sig, "used_by_user_id", None) is None:
                    accept_now_sig_id = sig.id
            elif getattr(sig, "signed_pdf_bytes", None) and getattr(sig, "used_by_user_id", None) is None:
                accept_now_sig_id = sig.id
    return GuestPendingInviteView(
        invitation_code=inv.invitation_code,
        property_name=property_name,
        unit_label=unit_label_val,
        stay_start_date=inv.stay_start_date,
        stay_end_date=inv.stay_end_date,
        host_name=host_name,
        region_code=inv.region_code,
        needs_dropbox_signature=needs_dropbox,
        pending_signature_id=pending_sig_id,
        accept_now_signature_id=accept_now_sig_id,
    )


@router.get("/owner/invitations", response_model=list[OwnerInvitationView])
def owner_invitations(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
    context_mode: str = Depends(get_context_mode),
):
    """Owner view: invitations with property name. Business mode: returns [] (no guest data). Personal mode: property-lane invitations only (owner/manager-invited; NEVER tenant-invited guest data)."""
    if context_mode == "business":
        return []
    all_invs = db.query(Invitation).filter(Invitation.owner_id == current_user.id).order_by(Invitation.created_at.desc()).all()
    invs = filter_property_lane_invitations_for_owner(db, all_invs, current_user.id)
    return _invitations_to_owner_views(invs, db, get_invitation_expire_cutoff)


def _invitations_to_owner_views(invs: list, db: Session, get_invitation_expire_cutoff_fn) -> list:
    """Build OwnerInvitationView list from invitation list. Shared by owner and manager."""
    threshold = get_invitation_expire_cutoff_fn()
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


@router.get("/manager/invitations", response_model=list[OwnerInvitationView])
def manager_invitations(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_property_manager_identity_verified),
    context_mode: str = Depends(get_context_mode),
):
    """Manager view: invitations. Business mode: returns [] (no guest data for privacy). Personal mode: only invitations the manager created (property lane); NEVER tenant-invited guest data."""
    if context_mode == "business":
        return []
    personal_unit_ids = get_manager_personal_mode_units(db, current_user.id)
    if not personal_unit_ids:
        return []
    units = db.query(Unit).filter(Unit.id.in_(personal_unit_ids)).all()
    property_ids = list({u.property_id for u in units})
    if not property_ids:
        return []
    all_invs = (
        db.query(Invitation)
        .filter(Invitation.property_id.in_(property_ids))
        .order_by(Invitation.created_at.desc())
        .all()
    )
    invs = filter_property_lane_invitations_for_manager(db, all_invs, current_user.id)
    return _invitations_to_owner_views(invs, db, get_invitation_expire_cutoff)


@router.post("/owner/invitations/{invitation_id}/cancel")
def owner_cancel_invitation(
    request: Request,
    invitation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Cancel a pending invitation. Owner or the inviter can cancel. Owner cannot cancel tenant-invited invitations (tenant lane)."""
    inv = db.query(Invitation).filter(Invitation.id == invitation_id).first()
    if not inv:
        raise HTTPException(status_code=404, detail="Invitation not found")
    is_inviter = getattr(inv, "invited_by_user_id", None) == current_user.id
    is_owner = inv.owner_id == current_user.id
    is_tenant_lane = is_tenant_lane_invitation(db, inv)
    if is_tenant_lane and is_owner and not is_inviter:
        raise HTTPException(status_code=403, detail="Tenant-invited guest data is private to the tenant. Only the tenant who created the invitation can cancel it.")
    if not is_owner and not is_inviter:
        raise HTTPException(status_code=403, detail="Only the property owner or the person who created the invitation can cancel it")
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
    create_ledger_event(
        db,
        ACTION_GUEST_INVITE_CANCELLED,
        target_object_type="Invitation",
        target_object_id=inv.id,
        property_id=inv.property_id,
        invitation_id=inv.id,
        actor_user_id=current_user.id,
        meta={"invitation_code": inv.invitation_code, "token_state_previous": prev_token, "token_state_new": "REVOKED"},
        ip_address=ip,
        user_agent=ua,
    )
    db.commit()
    return {"status": "success", "message": "Invitation cancelled."}


@router.post("/owner/properties/{property_id}/confirm-vacant")
def owner_confirm_vacant(
    request: Request,
    property_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
):
    """Confirm that a vacant unit is still vacant (vacant-unit monitoring response). Owner or assigned manager can confirm."""
    if not can_access_property(db, current_user, property_id, "business"):
        raise HTTPException(status_code=403, detail="You do not have access to this property")
    prop = db.query(Property).filter(
        Property.id == property_id,
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
    create_ledger_event(
        db,
        ACTION_CONFIRMED_STILL_VACANT,
        target_object_type="Property",
        target_object_id=prop.id,
        property_id=prop.id,
        actor_user_id=current_user.id,
        meta={"property_name": property_name},
        ip_address=request.client.host if request.client else None,
        user_agent=(request.headers.get("user-agent") or "").strip() or None,
    )
    db.commit()
    return {"status": "success", "message": "Vacancy confirmed. Next prompt will be sent at the next interval."}


@router.post("/properties/bulk-shield-mode")
def bulk_shield_mode(
    request: Request,
    data: BulkShieldModeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_or_manager),
):
    """Bulk update Shield Mode for multiple properties. Owner or assigned manager can update. Each property is verified via can_access_property."""
    if not data.property_ids:
        return {"status": "success", "updated_count": 0, "message": "No properties selected."}
    ip = request.client.host if request.client else None
    ua = (request.headers.get("user-agent") or "").strip() or None
    turned_by = "property manager" if current_user.role == UserRole.property_manager else "property owner"
    updated_count = 0
    owner_profiles_to_sync = set()
    for property_id in data.property_ids:
        if not can_access_property(db, current_user, property_id, "business"):
            continue
        prop = db.query(Property).filter(Property.id == property_id, Property.deleted_at.is_(None)).first()
        if not prop:
            continue
        new_val = 1 if data.shield_mode_enabled else 0
        old_val = getattr(prop, "shield_mode_enabled", 0) or 0
        if new_val == old_val:
            continue
        prop.shield_mode_enabled = new_val
        property_name = (prop.name or "").strip() or (f"{prop.city}, {prop.state}".strip(", ") if (prop.city or prop.state) else f"Property {property_id}")
        create_log(
            db,
            CATEGORY_SHIELD_MODE,
            "Shield Mode turned off" if new_val == 0 else "Shield Mode turned on",
            f"{turned_by.title()} turned {'off' if new_val == 0 else 'on'} Shield Mode for {property_name} (bulk).",
            property_id=prop.id,
            actor_user_id=current_user.id,
            actor_email=current_user.email,
            ip_address=ip,
            user_agent=ua,
            meta={"property_id": property_id, "property_name": property_name},
        )
        create_ledger_event(
            db,
            ACTION_SHIELD_MODE_OFF if new_val == 0 else ACTION_SHIELD_MODE_ON,
            target_object_type="Property",
            target_object_id=prop.id,
            property_id=prop.id,
            actor_user_id=current_user.id,
            meta={"property_id": property_id, "property_name": property_name},
            ip_address=ip,
            user_agent=ua,
        )
        if getattr(prop, "owner_profile_id", None):
            owner_profiles_to_sync.add(prop.owner_profile_id)
        owner_user = None
        if getattr(prop, "owner_profile_id", None):
            prof = db.query(OwnerProfile).filter(OwnerProfile.id == prop.owner_profile_id).first()
            owner_user = db.query(User).filter(User.id == prof.user_id).first() if prof else None
        owner_email = (owner_user.email or "").strip() if owner_user else ""
        manager_emails = [
            (u.email or "").strip()
            for a in db.query(PropertyManagerAssignment).filter(PropertyManagerAssignment.property_id == prop.id).all()
            for u in [db.query(User).filter(User.id == a.user_id).first()]
            if u and (u.email or "").strip()
        ]
        try:
            if new_val == 1:
                send_shield_mode_turned_on_notification(owner_email, manager_emails, property_name, turned_on_by=turned_by)
            else:
                send_shield_mode_turned_off_notification(owner_email, manager_emails, property_name, turned_off_by=turned_by)
        except Exception as e:
            print(f"[Dashboard] Shield mode notification failed for property {property_id}: {e}", flush=True)
        updated_count += 1
    db.commit()
    for profile_id in owner_profiles_to_sync:
        profile = db.query(OwnerProfile).filter(OwnerProfile.id == profile_id).first()
        if profile:
            try:
                sync_subscription_quantities(db, profile)
            except Exception as e:
                print(f"[Dashboard] Subscription sync failed after bulk Shield: {e}", flush=True)
    return {"status": "success", "updated_count": updated_count, "message": f"Shield Mode turned {'on' if data.shield_mode_enabled else 'off'} for {updated_count} propert{'y' if updated_count == 1 else 'ies'}."}


@router.get("/owner/stays", response_model=list[OwnerStayView])
def owner_stays(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
    context_mode: str = Depends(get_context_mode),
):
    """Owner view: guest stays. Business mode: returns [] (no guest data). Personal mode: property-lane stays only (owner/manager-invited; NEVER tenant-invited guest stays)."""
    if context_mode == "business":
        return []
    # Load stays by owner_id and also by invitation ownership (covers all stays for this owner's invitations)
    stays_by_owner = db.query(Stay).filter(Stay.owner_id == current_user.id).all()
    inv_ids = [r[0] for r in db.query(Invitation.id).filter(Invitation.owner_id == current_user.id).all()]
    stays_by_inv = db.query(Stay).filter(Stay.invitation_id.in_(inv_ids)).all() if inv_ids else []
    seen_ids = {s.id for s in stays_by_owner}
    stays = list(stays_by_owner)
    for s in stays_by_inv:
        if s.id not in seen_ids:
            seen_ids.add(s.id)
            stays.append(s)
    stays = filter_property_lane_stays_for_owner(db, stays, current_user.id)
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
                invitation_only=False,
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

    # Include BURNED and EXPIRED invitations that have no Stay so they show in Stays section (CSV tenants, or invites where Stay was never created).
    # Exclude: (1) invitation_id already linked to a Stay, (2) status='accepted', (3) any Stay exists for same property + dates (covers old Stays created without invitation_id).
    invitation_ids_with_stay = {s.invitation_id for s in stays if getattr(s, "invitation_id", None) is not None}
    stay_key = {(s.property_id, s.stay_start_date, s.stay_end_date) for s in stays}
    q = db.query(Invitation).filter(
        Invitation.owner_id == current_user.id,
        Invitation.token_state.in_(["BURNED", "EXPIRED"]),
        Invitation.status != "accepted",
    )
    if invitation_ids_with_stay:
        q = q.filter(~Invitation.id.in_(invitation_ids_with_stay))
    invs_no_stay = filter_property_lane_invitations_for_owner(db, q.all(), current_user.id)
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    for inv in invs_no_stay:
        if (inv.property_id, inv.stay_start_date, inv.stay_end_date) in stay_key:
            continue
        prop = db.query(Property).filter(Property.id == inv.property_id).first()
        if prop is None or getattr(prop, "deleted_at", None) is not None:
            continue  # skip if property missing or soft-deleted
        if profile is None or prop.owner_profile_id != profile.id:
            continue  # ensure property belongs to this owner
        property_name = (prop.name or "").strip() or (f"{getattr(prop, 'city', '')}, {getattr(prop, 'state', '')}".strip(", ")) or "Property"
        region = (getattr(inv, "region_code", None) or "").strip() or (getattr(prop, "region_code", None) or "") or "US"
        start = inv.stay_start_date
        end = inv.stay_end_date
        duration_days = (end - start).days if start and end else 0
        rule = db.query(RegionRule).filter(RegionRule.region_code == region).first()
        jle = resolve_jurisdiction(
            db,
            JLEInput(
                region_code=region,
                stay_duration_days=duration_days,
                owner_occupied=True,
                property_type=None,
                guest_has_permanent_address=True,
            ),
        )
        max_days = rule.max_stay_days if rule else 0
        classification = (jle.legal_classification if jle else None) or (rule.stay_classification_label if rule else None) or StayClassification.guest
        risk = (jle.risk_level if jle else None) or (rule.risk_level if rule else None) or RiskLevel.low
        statutes = (jle.applicable_statutes if jle else []) or ([rule.statute_reference] if rule and rule.statute_reference else [])
        token_state = (getattr(inv, "token_state", None) or "BURNED").upper()
        is_expired = token_state == "EXPIRED"
        # For EXPIRED (no Stay row), show as completed so past stays appear
        checked_out_dt = datetime.combine(end, dt_time.min, tzinfo=timezone.utc) if is_expired and end else None
        out.append(
            OwnerStayView(
                stay_id=-inv.id,
                property_id=inv.property_id,
                invite_id=inv.invitation_code,
                token_state=token_state,
                invitation_only=True,
                guest_name=(inv.guest_name or "").strip() or "Tenant (pending sign-up)",
                property_name=property_name,
                stay_start_date=start,
                stay_end_date=end,
                region_code=region,
                legal_classification=classification,
                max_stay_allowed_days=max_days,
                risk_indicator=risk,
                applicable_laws=statutes,
                revoked_at=None,
                checked_in_at=None,
                checked_out_at=checked_out_dt,
                cancelled_at=None,
                usat_token_released_at=None,
                dead_mans_switch_enabled=bool(getattr(inv, "dead_mans_switch_enabled", 0)),
                needs_occupancy_confirmation=False,
                show_occupancy_confirmation_ui=False,
                confirmation_deadline_at=None,
                occupancy_confirmation_response=None,
            )
        )

    return out


def _manager_property_ids(db: Session, user_id: int) -> list[int]:
    """Property IDs assigned to this manager."""
    rows = db.query(PropertyManagerAssignment.property_id).filter(
        PropertyManagerAssignment.user_id == user_id,
    ).distinct().all()
    return [r[0] for r in rows]


@router.get("/manager/stays", response_model=list[OwnerStayView])
def manager_stays(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_property_manager_identity_verified),
    context_mode: str = Depends(get_context_mode),
):
    """Manager view: stays. Business mode: returns [] (no guest data for privacy). Personal mode: only stays for guests the manager invited (property lane); NEVER tenant-invited guest stays."""
    if context_mode == "business":
        return []
    personal_unit_ids = get_manager_personal_mode_units(db, current_user.id)
    if not personal_unit_ids:
        return []
    units = db.query(Unit).filter(Unit.id.in_(personal_unit_ids)).all()
    property_ids = list({u.property_id for u in units})
    if not property_ids:
        return []
    stays = db.query(Stay).filter(Stay.property_id.in_(property_ids)).all()
    inv_ids = [r[0] for r in db.query(Invitation.id).filter(
        Invitation.property_id.in_(property_ids),
    ).all()]
    stays_by_inv = db.query(Stay).filter(Stay.invitation_id.in_(inv_ids)).all() if inv_ids else []
    seen_ids = {s.id for s in stays}
    for s in stays_by_inv:
        if s.id not in seen_ids:
            seen_ids.add(s.id)
            stays.append(s)
    stays = filter_property_lane_stays_for_manager(db, stays, current_user.id)
    out = []
    for s in stays:
        guest = db.query(User).filter(User.id == s.guest_id).first()
        guest_profile = db.query(GuestProfile).filter(GuestProfile.user_id == s.guest_id).first()
        guest_name = (guest_profile.full_legal_name if guest_profile else None) or (guest.full_name if guest else None) or (guest.email if guest else "Unknown")
        prop = db.query(Property).filter(Property.id == s.property_id).first()
        property_name = (prop.name if prop else None) or (f"{prop.city}, {prop.state}" if prop else None) or "Property"
        rule = db.query(RegionRule).filter(RegionRule.region_code == s.region_code).first()
        jle = resolve_jurisdiction(db, JLEInput(region_code=s.region_code, stay_duration_days=s.intended_stay_duration_days, owner_occupied=True, property_type=None, guest_has_permanent_address=True))
        max_days = rule.max_stay_days if rule else 0
        classification = (jle.legal_classification if jle else None) or (rule.stay_classification_label if rule else None) or StayClassification.guest
        risk = (jle.risk_level if jle else None) or (rule.risk_level if rule else None) or RiskLevel.low
        statutes = (jle.applicable_statutes if jle else []) or ([rule.statute_reference] if rule and rule.statute_reference else [])
        checked_out = getattr(s, "checked_out_at", None) is not None
        cancelled = getattr(s, "cancelled_at", None) is not None
        conf_resp = getattr(s, "occupancy_confirmation_response", None)
        dms_on = bool(getattr(s, "dead_mans_switch_enabled", 0))
        confirmation_deadline_at = datetime.combine(s.stay_end_date + timedelta(days=2), dt_time.min, tzinfo=timezone.utc) if s.stay_end_date else None
        now = datetime.now(timezone.utc)
        needs_conf = (not checked_out and not cancelled and dms_on and conf_resp is None and confirmation_deadline_at and now < confirmation_deadline_at and s.stay_end_date <= (date.today() + timedelta(days=2)))
        prop_status = (getattr(prop, "occupancy_status", None) or "unknown") if prop else "unknown"
        show_confirm_ui = needs_conf or (prop_status == OccupancyStatus.unconfirmed.value and not checked_out and not cancelled and dms_on and conf_resp is None and s.stay_end_date < date.today())
        invite_id_val = None
        token_state_val = None
        if getattr(s, "invitation_id", None):
            inv = db.query(Invitation).filter(Invitation.id == s.invitation_id).first()
            if inv:
                invite_id_val = inv.invitation_code
                token_state_val = getattr(inv, "token_state", None) or "BURNED"
        out.append(OwnerStayView(
            stay_id=s.id, property_id=s.property_id, invite_id=invite_id_val, token_state=token_state_val, invitation_only=False,
            guest_name=guest_name, property_name=property_name, stay_start_date=s.stay_start_date, stay_end_date=s.stay_end_date,
            region_code=s.region_code, legal_classification=classification, max_stay_allowed_days=max_days, risk_indicator=risk, applicable_laws=statutes,
            revoked_at=getattr(s, "revoked_at", None), checked_in_at=getattr(s, "checked_in_at", None), checked_out_at=getattr(s, "checked_out_at", None), cancelled_at=getattr(s, "cancelled_at", None),
            usat_token_released_at=getattr(s, "usat_token_released_at", None), dead_mans_switch_enabled=dms_on,
            needs_occupancy_confirmation=needs_conf, show_occupancy_confirmation_ui=show_confirm_ui, confirmation_deadline_at=confirmation_deadline_at if show_confirm_ui else None, occupancy_confirmation_response=conf_resp,
        ))
    invitation_ids_with_stay = {s.invitation_id for s in stays if getattr(s, "invitation_id", None) is not None}
    stay_key = {(s.property_id, s.stay_start_date, s.stay_end_date) for s in stays}
    q = db.query(Invitation).filter(
        Invitation.property_id.in_(property_ids),
        Invitation.token_state.in_(["BURNED", "EXPIRED"]),
        Invitation.status != "accepted",
    )
    if invitation_ids_with_stay:
        q = q.filter(~Invitation.id.in_(invitation_ids_with_stay))
    invs_for_invitation_only = filter_property_lane_invitations_for_manager(db, q.all(), current_user.id)
    for inv in invs_for_invitation_only:
        if (inv.property_id, inv.stay_start_date, inv.stay_end_date) in stay_key:
            continue
        prop = db.query(Property).filter(Property.id == inv.property_id).first()
        if not prop or getattr(prop, "deleted_at", None):
            continue
        property_name = (prop.name or "").strip() or (f"{getattr(prop, 'city', '')}, {getattr(prop, 'state', '')}".strip(", ")) or "Property"
        region = (getattr(inv, "region_code", None) or "").strip() or (getattr(prop, "region_code", None) or "") or "US"
        start, end = inv.stay_start_date, inv.stay_end_date
        duration_days = (end - start).days if start and end else 0
        rule = db.query(RegionRule).filter(RegionRule.region_code == region).first()
        jle = resolve_jurisdiction(db, JLEInput(region_code=region, stay_duration_days=duration_days, owner_occupied=True, property_type=None, guest_has_permanent_address=True))
        max_days = rule.max_stay_days if rule else 0
        classification = (jle.legal_classification if jle else None) or (rule.stay_classification_label if rule else None) or StayClassification.guest
        risk = (jle.risk_level if jle else None) or (rule.risk_level if rule else None) or RiskLevel.low
        statutes = (jle.applicable_statutes if jle else []) or ([rule.statute_reference] if rule and rule.statute_reference else [])
        token_state = (getattr(inv, "token_state", None) or "BURNED").upper()
        is_expired = token_state == "EXPIRED"
        checked_out_dt = datetime.combine(end, dt_time.min, tzinfo=timezone.utc) if is_expired and end else None
        out.append(OwnerStayView(
            stay_id=-inv.id, property_id=inv.property_id, invite_id=inv.invitation_code, token_state=token_state, invitation_only=True,
            guest_name=(inv.guest_name or "").strip() or "Tenant (pending sign-up)", property_name=property_name, stay_start_date=start, stay_end_date=end,
            region_code=region, legal_classification=classification, max_stay_allowed_days=max_days, risk_indicator=risk, applicable_laws=statutes,
            revoked_at=None, checked_in_at=None, checked_out_at=checked_out_dt, cancelled_at=None, usat_token_released_at=None,
            dead_mans_switch_enabled=bool(getattr(inv, "dead_mans_switch_enabled", 0)), needs_occupancy_confirmation=False, show_occupancy_confirmation_ui=False, confirmation_deadline_at=None, occupancy_confirmation_response=None,
        ))
    return out


@router.post("/owner/stays/{stay_id}/revoke")
def revoke_stay(
    request: Request,
    stay_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Revoke a stay (Kill Switch): set revoked_at, guest must vacate in 12 hours. Owner cannot revoke tenant-invited guest stays (tenant lane)."""
    stay = db.query(Stay).filter(Stay.id == stay_id, Stay.owner_id == current_user.id).first()
    if not stay:
        raise HTTPException(status_code=404, detail="Stay not found")
    if is_tenant_lane_stay(db, stay):
        raise HTTPException(status_code=403, detail="Tenant-invited guest stays are private to the tenant. Only the tenant who invited can revoke.")
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
    revoke_message = f"Stay {stay.id} revoked by owner. Guest must vacate by {vacate_by_iso}." + (f" Invite ID {invite_code} token_state → REVOKED." if invite_code else "")
    log_meta["message"] = revoke_message
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "Stay revoked",
        revoke_message,
        property_id=stay.property_id,
        stay_id=stay.id,
        invitation_id=getattr(stay, "invitation_id", None),
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=ip,
        user_agent=ua,
        meta=log_meta,
    )
    create_ledger_event(
        db,
        ACTION_STAY_REVOKED,
        target_object_type="Stay",
        target_object_id=stay.id,
        property_id=stay.property_id,
        stay_id=stay.id,
        invitation_id=getattr(stay, "invitation_id", None),
        actor_user_id=current_user.id,
        meta=log_meta,
        ip_address=ip,
        user_agent=ua,
    )
    db.commit()
    guest = db.query(User).filter(User.id == stay.guest_id).first()
    guest_email = (guest.email if guest else "").strip()
    guest_name = (guest.full_name if guest else None) or guest_email or "Guest"
    prop = db.query(Property).filter(Property.id == stay.property_id).first()
    property_name = (prop.name if prop else None) or (f"{prop.city}, {prop.state}" if prop else None) or "the property"
    prop_parts = [prop.street, prop.city, prop.state, (prop.zip_code or "").strip()] if prop else []
    property_address = ", ".join(p for p in prop_parts if p) if prop else ""
    if guest_email:
        send_vacate_12h_notice(
            guest_email,
            guest_name,
            property_name,
            vacate_by_iso,
            stay.region_code or "",
            property_address=property_address,
            stay_start_date=stay.stay_start_date.isoformat() if stay.stay_start_date else "",
            stay_end_date=stay.stay_end_date.isoformat() if stay.stay_end_date else "",
            revoked_at=now.strftime("%Y-%m-%d %H:%M UTC"),
            invite_code=invite_code or "",
        )
    return {"status": "success", "message": "Stay revoked. Guest must vacate within 12 hours. Email sent."}


@router.post("/owner/stays/{stay_id}/initiate-removal")
def initiate_removal(
    request: Request,
    stay_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Initiate formal removal for an overstayed guest. Owner cannot initiate removal for tenant-invited guest stays (tenant lane)."""
    stay = db.query(Stay).filter(Stay.id == stay_id, Stay.owner_id == current_user.id).first()
    if not stay:
        raise HTTPException(status_code=404, detail="Stay not found")
    if is_tenant_lane_stay(db, stay):
        raise HTTPException(status_code=403, detail="Tenant-invited guest stays are private to the tenant. Only the tenant who invited can initiate removal.")

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
    prop_parts = [prop.street, prop.city, prop.state, (prop.zip_code or "").strip()] if prop else []
    property_address = ", ".join(p for p in prop_parts if p) if prop else ""
    invite_code = ""
    if getattr(stay, "invitation_id", None):
        inv = db.query(Invitation).filter(Invitation.id == stay.invitation_id).first()
        if inv:
            invite_code = inv.invitation_code or ""

    # Send emails
    if guest_email:
        send_removal_notice_to_guest(
            guest_email,
            guest_name,
            property_name,
            stay.region_code or "",
            property_address=property_address,
            stay_start_date=stay.stay_start_date.isoformat() if stay.stay_start_date else "",
            stay_end_date=stay.stay_end_date.isoformat() if stay.stay_end_date else "",
            revoked_at=now.strftime("%Y-%m-%d %H:%M UTC"),
            invite_code=invite_code,
        )
    if owner_email:
        send_removal_confirmation_to_owner(
            owner_email,
            guest_name,
            property_name,
            stay.region_code or "",
            property_address=property_address,
            stay_start_date=stay.stay_start_date.isoformat() if stay.stay_start_date else "",
            stay_end_date=stay.stay_end_date.isoformat() if stay.stay_end_date else "",
            revoked_at=now.strftime("%Y-%m-%d %H:%M UTC"),
            invite_code=invite_code,
        )

    # Create audit log and event ledger (guest authorization change – visible in activity logs)
    removal_message = (
        f"Owner initiated formal removal for stay {stay.id} (guest: {guest_name}, property: {property_name}). "
        "USAT token revoked. Guest and owner notified."
    )
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "Removal initiated",
        removal_message,
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
    create_ledger_event(
        db,
        ACTION_STAY_REVOKED,
        target_object_type="Stay",
        target_object_id=stay.id,
        property_id=stay.property_id,
        stay_id=stay.id,
        actor_user_id=current_user.id,
        meta={
            "message": removal_message,
            "guest_name": guest_name,
            "property_name": property_name,
            "usat_revoked": usat_revoked,
        },
        ip_address=ip,
        user_agent=ua,
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
    current_user: User = Depends(require_owner_or_manager),
):
    """Owner or assigned manager confirms unit status. Cannot confirm for tenant-invited guest stays (tenant lane)."""
    stay = db.query(Stay).filter(Stay.id == stay_id).first()
    if not stay:
        raise HTTPException(status_code=404, detail="Stay not found")
    if is_tenant_lane_stay(db, stay):
        raise HTTPException(status_code=403, detail="Tenant-invited guest stays are private to the tenant. Only the tenant can confirm occupancy.")
    if not can_confirm_occupancy(db, current_user, stay):
        raise HTTPException(status_code=403, detail="You do not have permission to confirm occupancy for this stay")
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
            owner_profile = db.query(OwnerProfile).filter(OwnerProfile.id == prop.owner_profile_id).first()
            owner_user = db.query(User).filter(User.id == owner_profile.user_id).first() if owner_profile else None
            owner_email = (owner_user.email or "").strip() if owner_user else ""
            manager_emails = [
                (u.email or "").strip()
                for a in db.query(PropertyManagerAssignment).filter(PropertyManagerAssignment.property_id == prop.id).all()
                for u in [db.query(User).filter(User.id == a.user_id).first()]
                if u and (u.email or "").strip()
            ]
            property_name = (prop.name or "").strip() or (f"{prop.city}, {prop.state}".strip(", ") if (prop.city or prop.state) else "Property")
            try:
                send_shield_mode_turned_off_notification(owner_email, manager_emails, property_name, turned_off_by="system (unit vacated)")
            except Exception:
                pass
        if prop.usat_token_state == USAT_TOKEN_RELEASED:
            prop.usat_token_state = USAT_TOKEN_STAGED
            prop.usat_token_released_at = None
        unit_id = getattr(stay, "unit_id", None)
        if unit_id:
            unit = db.query(Unit).filter(Unit.id == unit_id).first()
            if unit:
                unit.occupancy_status = OccupancyStatus.vacant.value
                db.add(unit)
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
        # DMS turned off when stay ends (vacated)
        if getattr(stay, "dead_mans_switch_enabled", 0) == 1:
            owner_profile = db.query(OwnerProfile).filter(OwnerProfile.id == prop.owner_profile_id).first()
            owner_user = db.query(User).filter(User.id == owner_profile.user_id).first() if owner_profile else None
            owner_email = (owner_user.email or "").strip() if owner_user else ""
            manager_emails = [
                (u.email or "").strip()
                for a in db.query(PropertyManagerAssignment).filter(PropertyManagerAssignment.property_id == prop.id).all()
                for u in [db.query(User).filter(User.id == a.user_id).first()]
                if u and (u.email or "").strip()
            ]
            guest_user = db.query(User).filter(User.id == stay.guest_id).first()
            guest_profile = db.query(GuestProfile).filter(GuestProfile.user_id == stay.guest_id).first()
            guest_name = (guest_profile.full_legal_name if guest_profile else None) or (guest_user.full_name if guest_user else None) or (guest_user.email if guest_user else None) or "Guest"
            property_name = (prop.name or "").strip() or (f"{prop.city}, {prop.state}".strip(", ") if (prop.city or prop.state) else "Property")
            try:
                send_dms_turned_off_notification(owner_email, manager_emails, property_name, guest_name, stay.stay_end_date.isoformat(), reason="unit vacated")
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
            owner_profile = db.query(OwnerProfile).filter(OwnerProfile.id == prop.owner_profile_id).first()
            owner_user = db.query(User).filter(User.id == owner_profile.user_id).first() if owner_profile else None
            owner_email = (owner_user.email or "").strip() if owner_user else ""
            manager_emails = [
                (u.email or "").strip()
                for a in db.query(PropertyManagerAssignment).filter(PropertyManagerAssignment.property_id == prop.id).all()
                for u in [db.query(User).filter(User.id == a.user_id).first()]
                if u and (u.email or "").strip()
            ]
            guest_user = db.query(User).filter(User.id == stay.guest_id).first()
            guest_profile = db.query(GuestProfile).filter(GuestProfile.user_id == stay.guest_id).first()
            guest_name = (guest_profile.full_legal_name if guest_profile else None) or (guest_user.full_name if guest_user else None) or (guest_user.email if guest_user else None) or "Guest"
            property_name = (prop.name or "").strip() or (f"{prop.city}, {prop.state}".strip(", ") if (prop.city or prop.state) else "Property")
            try:
                send_dms_turned_off_notification(owner_email, manager_emails, property_name, guest_name, new_end.isoformat(), reason="lease extended beyond 48h")
            except Exception:
                pass
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
    current_user: User = Depends(require_guest_or_tenant),
):
    """Guest/tenant view: property, approved stay dates, region classification, legal notice and laws. All jurisdiction content from Jurisdiction SOT (same as live property page)."""
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
        unit_label_val = None
        if getattr(s, "unit_id", None):
            unit_row = db.query(Unit).filter(Unit.id == s.unit_id).first()
            if unit_row:
                unit_label_val = unit_row.unit_label
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
                unit_label=unit_label_val,
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


@router.get("/guest/logs", response_model=list[OwnerAuditLogEntry])
def guest_logs(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_guest_or_tenant),
    from_ts: str | None = None,
    to_ts: str | None = None,
    category: str | None = None,
    search: str | None = None,
    stay_id: int | None = None,
):
    """Activity logs (audit trail) for the guest's stays only. Optional stay_id restricts to one stay. Guests can view their audit trail."""
    from sqlalchemy import desc, cast, String

    stays = db.query(Stay).filter(Stay.guest_id == current_user.id).all()
    stay_ids = [s.id for s in stays]
    if not stay_ids:
        return []
    if stay_id is not None and stay_id not in stay_ids:
        return []
    q = db.query(EventLedger).filter(EventLedger.stay_id.in_(stay_ids))
    if stay_id is not None:
        q = q.filter(EventLedger.stay_id == stay_id)
    from_dt = _parse_optional_utc(from_ts)
    to_dt = _parse_optional_utc(to_ts)
    if from_dt is not None:
        q = q.filter(EventLedger.created_at >= from_dt)
    if to_dt is not None:
        q = q.filter(EventLedger.created_at <= to_dt)
    if category and category.strip():
        action_types = _CATEGORY_TO_ACTION_TYPES.get(category.strip(), [])
        if action_types:
            q = q.filter(EventLedger.action_type.in_(action_types))
    if search and search.strip():
        term = f"%{search.strip()}%"
        q = q.filter((EventLedger.action_type.ilike(term)) | (cast(EventLedger.meta, String).ilike(term)))
    rows = q.order_by(desc(EventLedger.created_at)).limit(200).all()
    prop_ids = {r.property_id for r in rows if r.property_id}
    props = {p.id: (p.name or f"{p.city}, {p.state}") for p in db.query(Property).filter(Property.id.in_(prop_ids)).all()} if prop_ids else {}
    out = []
    for r in rows:
        cat, title, msg = ledger_event_to_display(r)
        actor_email = get_actor_email(db, r.actor_user_id)
        out.append(
            OwnerAuditLogEntry(
                id=r.id, property_id=r.property_id, stay_id=r.stay_id, invitation_id=r.invitation_id,
                category=cat, title=title, message=msg,
                actor_user_id=r.actor_user_id, actor_email=actor_email, ip_address=r.ip_address,
                created_at=r.created_at if r.created_at else datetime.now(timezone.utc),
                property_name=props.get(r.property_id) if r.property_id else None,
            )
        )
    return out


@router.post("/guest/stays/{stay_id}/check-in")
def guest_check_in(
    request: Request,
    stay_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_guest_or_tenant),
):
    """Guest/tenant records check-in: sets checked_in_at and property occupancy to OCCUPIED. Stay must be on or after start date, not already checked in/out/cancelled."""
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
            owner_profile = db.query(OwnerProfile).filter(OwnerProfile.id == prop.owner_profile_id).first()
            owner_user = db.query(User).filter(User.id == owner_profile.user_id).first() if owner_profile else None
            owner_email = (owner_user.email or "").strip() if owner_user else ""
            manager_emails = [
                (u.email or "").strip()
                for a in db.query(PropertyManagerAssignment).filter(PropertyManagerAssignment.property_id == prop.id).all()
                for u in [db.query(User).filter(User.id == a.user_id).first()]
                if u and (u.email or "").strip()
            ]
            property_name = (prop.name or "").strip() or (f"{prop.city}, {prop.state}".strip(", ") if (prop.city or prop.state) else "Property")
            try:
                send_shield_mode_turned_off_notification(owner_email, manager_emails, property_name, turned_off_by="system (guest checked in)")
            except Exception:
                pass
        db.add(prop)
    unit_id = getattr(stay, "unit_id", None)
    if unit_id:
        unit = db.query(Unit).filter(Unit.id == unit_id).first()
        if unit:
            unit.occupancy_status = OccupancyStatus.occupied.value
            db.add(unit)
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
    create_ledger_event(
        db,
        ACTION_GUEST_CHECK_IN,
        property_id=stay.property_id,
        unit_id=unit_id,
        stay_id=stay.id,
        actor_user_id=current_user.id,
        ip_address=ip,
        user_agent=ua,
        meta={
            "message": f"{guest_name} checked in at {property_name}. Occupancy set to occupied.",
            "guest_name": guest_name,
            "guest_id": stay.guest_id,
        },
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
    current_user: User = Depends(require_guest_or_tenant),
):
    """Return the signed guest agreement PDF for this stay. Guest/tenant must own the stay. Returns 404 if no signed agreement (e.g. stay created before signing flow)."""
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
    current_user: User = Depends(require_guest_or_tenant),
):
    """Let the guest/tenant end an ongoing stay (set end date to today). Revoked stays can still be ended so the guest can record checkout."""
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
        unit_id = getattr(stay, "unit_id", None)
        if unit_id:
            unit = db.query(Unit).filter(Unit.id == unit_id).first()
            if unit:
                unit.occupancy_status = OccupancyStatus.vacant.value
                db.add(unit)
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
    guest_user = db.query(User).filter(User.id == stay.guest_id).first()
    guest_profile = db.query(GuestProfile).filter(GuestProfile.user_id == stay.guest_id).first()
    _guest_name = (guest_profile.full_legal_name if guest_profile else None) or (guest_user.full_name if guest_user else None) or (guest_user.email if guest_user else None) or "Guest"
    _prop = db.query(Property).filter(Property.id == stay.property_id).first()
    _property_name = (_prop.name if _prop else None) or (f"{_prop.city}, {_prop.state}".strip(", ") if _prop and (_prop.city or _prop.state) else None) or f"property {stay.property_id}"
    checkout_meta = dict(log_meta) if log_meta else {}
    checkout_meta["message"] = f"Guest checked out of stay {stay.id} ({_property_name}). End date set to {today.isoformat()}."
    checkout_meta["guest_name"] = _guest_name
    create_ledger_event(
        db,
        ACTION_GUEST_CHECK_OUT,
        property_id=stay.property_id,
        unit_id=getattr(stay, "unit_id", None),
        stay_id=stay.id,
        invitation_id=getattr(stay, "invitation_id", None),
        actor_user_id=current_user.id,
        ip_address=ip,
        user_agent=ua,
        meta=checkout_meta,
    )
    db.commit()
    # Notify owner and guest about checkout; DMS turned off when stay ends
    owner = db.query(User).filter(User.id == stay.owner_id).first()
    property_obj = db.query(Property).filter(Property.id == stay.property_id).first()
    guest_name = (current_user.full_name or "").strip() or "Guest"
    property_name = (property_obj.name if property_obj else None) or "your property"
    if getattr(stay, "dead_mans_switch_enabled", 0) == 1 and property_obj:
        owner_profile = db.query(OwnerProfile).filter(OwnerProfile.id == property_obj.owner_profile_id).first()
        owner_user = db.query(User).filter(User.id == owner_profile.user_id).first() if owner_profile else None
        owner_email = (owner_user.email or "").strip() if owner_user else ""
        manager_emails = [
            (u.email or "").strip()
            for a in db.query(PropertyManagerAssignment).filter(PropertyManagerAssignment.property_id == stay.property_id).all()
            for u in [db.query(User).filter(User.id == a.user_id).first()]
            if u and (u.email or "").strip()
        ]
        prop_name = (property_obj.name or "").strip() or (f"{property_obj.city}, {property_obj.state}".strip(", ") if property_obj and (property_obj.city or property_obj.state) else "Property")
        try:
            send_dms_turned_off_notification(owner_email, manager_emails, prop_name, guest_name, today.isoformat(), reason="guest checked out")
        except Exception:
            pass
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
    current_user: User = Depends(require_guest_or_tenant),
):
    """Let the guest/tenant cancel a future stay (set end date to day before start so the stay is no longer upcoming)."""
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
        unit_id = getattr(stay, "unit_id", None)
        if unit_id:
            unit = db.query(Unit).filter(Unit.id == unit_id).first()
            if unit:
                unit.occupancy_status = OccupancyStatus.vacant.value
                db.add(unit)
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


@router.get("/tenant/unit")
def tenant_unit(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_tenant),
):
    """Return the tenant's assigned unit, plus invitation info and live_slug for the Current stay card (match guest dashboard). Only ongoing assignments (end_date is None or end_date >= today)."""
    today = date.today()
    ta = (
        db.query(TenantAssignment)
        .join(Unit)
        .filter(
            TenantAssignment.user_id == current_user.id,
            (TenantAssignment.end_date.is_(None)) | (TenantAssignment.end_date >= today),
        )
        .order_by(TenantAssignment.start_date.desc())
        .first()
    )
    if not ta:
        return {
            "unit": None, "property": None, "invite_id": None, "token_state": None,
            "stay_start_date": None, "stay_end_date": None, "live_slug": None, "region_code": None,
            "jurisdiction_state_name": None, "jurisdiction_statutes": [], "removal_guest_text": None, "removal_tenant_text": None,
        }
    unit = db.query(Unit).filter(Unit.id == ta.unit_id).first()
    prop = db.query(Property).filter(Property.id == unit.property_id).first() if unit else None
    address = ", ".join(filter(None, [prop.street, prop.city, prop.state])) if prop else ""
    # Tenant invitation for this unit (BURNED tenant invite used to assign)
    tenant_inv = (
        db.query(Invitation)
        .filter(Invitation.unit_id == ta.unit_id, Invitation.invitation_kind == "tenant")
        .order_by(Invitation.created_at.desc())
        .first()
    )
    invite_id = tenant_inv.invitation_code if tenant_inv else None
    token_state = getattr(tenant_inv, "token_state", None) if tenant_inv else None
    stay_start = (tenant_inv.stay_start_date if tenant_inv else ta.start_date)
    stay_end = (tenant_inv.stay_end_date if tenant_inv else ta.end_date)
    live_slug = getattr(prop, "live_slug", None) if prop else None
    region_code = getattr(prop, "region_code", None) if prop else None
    # Jurisdiction SOT for APPLICABLE LAW (same as guest dashboard and live property page)
    jurisdiction_state_name = None
    jurisdiction_statutes = []
    removal_guest_text = None
    removal_tenant_text = None
    if prop:
        jinfo = get_jurisdiction_for_property(db, getattr(prop, "zip_code", None), region_code)
        if jinfo is not None:
            jurisdiction_state_name = jinfo.name
            jurisdiction_statutes = [JurisdictionStatuteInDashboard(citation=st.citation, plain_english=st.plain_english) for st in jinfo.statutes]
            removal_guest_text = jinfo.removal_guest_text
            removal_tenant_text = jinfo.removal_tenant_text
    return {
        "unit": {"id": unit.id, "unit_label": unit.unit_label, "occupancy_status": unit.occupancy_status} if unit else None,
        "property": {"id": prop.id, "name": prop.name, "address": address} if prop else None,
        "invite_id": invite_id,
        "token_state": token_state,
        "stay_start_date": stay_start.isoformat() if stay_start else None,
        "stay_end_date": stay_end.isoformat() if stay_end else None,
        "live_slug": live_slug,
        "region_code": region_code,
        "jurisdiction_state_name": jurisdiction_state_name,
        "jurisdiction_statutes": jurisdiction_statutes,
        "removal_guest_text": removal_guest_text,
        "removal_tenant_text": removal_tenant_text,
    }


@router.post("/tenant/cancel-future-assignment")
def tenant_cancel_future_assignment(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_tenant),
):
    """Let the tenant cancel their future unit assignment (effective before start date). Sets assignment end_date to day before start and marks the tenant invitation as cancelled."""
    today = date.today()
    ta = (
        db.query(TenantAssignment)
        .join(Unit)
        .filter(TenantAssignment.user_id == current_user.id)
        .order_by(TenantAssignment.start_date.desc())
        .first()
    )
    if not ta:
        raise HTTPException(status_code=404, detail="No assignment found")
    # Use same "effective" start as tenant unit display: invitation stay_start if present, else assignment start_date
    tenant_inv = (
        db.query(Invitation)
        .filter(Invitation.unit_id == ta.unit_id, Invitation.invitation_kind == "tenant")
        .order_by(Invitation.created_at.desc())
        .first()
    )
    effective_start = tenant_inv.stay_start_date if tenant_inv else ta.start_date
    if effective_start <= today:
        raise HTTPException(
            status_code=400,
            detail="Only future assignments can be cancelled. Your stay has already started.",
        )
    original_start = effective_start
    ta.end_date = original_start - timedelta(days=1)
    db.add(ta)
    db.flush()
    # Mark the tenant invitation as cancelled (tenant self-cancel; DocuStay does not revoke tenants)
    invite_code = None
    if tenant_inv:
        invite_code = tenant_inv.invitation_code
        tenant_inv.token_state = "CANCELLED"
        db.add(tenant_inv)
    unit = db.query(Unit).filter(Unit.id == ta.unit_id).first()
    prop = db.query(Property).filter(Property.id == unit.property_id).first() if unit else None
    occ_prev = None
    if unit:
        occ_prev = getattr(unit, "occupancy_status", None) or "unknown"
        unit.occupancy_status = OccupancyStatus.vacant.value
        db.add(unit)
    if prop:
        prop.occupancy_status = OccupancyStatus.vacant.value
        db.add(prop)
        occ_prev = occ_prev or getattr(prop, "occupancy_status", None)
    db.commit()
    ip = request.client.host if request.client else None
    ua = (request.headers.get("user-agent") or "").strip() or None
    log_message = (
        f"Tenant cancelled future assignment (unit_id={ta.unit_id}, original start {original_start.isoformat()})."
        + (f" Invite ID {invite_code} token_state -> CANCELLED." if invite_code else "")
        + (f" Occupancy -> vacant." if occ_prev else "")
    )
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "Tenant cancelled future assignment",
        log_message,
        property_id=prop.id if prop else None,
        stay_id=None,
        invitation_id=tenant_inv.id if tenant_inv else None,
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=ip,
        user_agent=ua,
        meta={"original_start_date": str(original_start), "unit_id": ta.unit_id},
    )
    if prop:
        create_ledger_event(
            db,
            ACTION_TENANT_ASSIGNMENT_CANCELLED,
            target_object_type="TenantAssignment",
            target_object_id=ta.id,
            property_id=prop.id,
            unit_id=ta.unit_id,
            invitation_id=tenant_inv.id if tenant_inv else None,
            actor_user_id=current_user.id,
            meta={"message": log_message, "unit_id": ta.unit_id, "tenant_email": current_user.email},
            ip_address=ip,
            user_agent=ua,
        )
    db.commit()
    return {"status": "success", "message": "Future stay cancelled."}


@router.post("/tenant/end-assignment")
def tenant_end_assignment(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_tenant),
):
    """Let the tenant end their ongoing assignment (checkout): set end_date to today. Only allowed when today is within [start_date, end_date]."""
    today = date.today()
    ta = (
        db.query(TenantAssignment)
        .join(Unit)
        .filter(TenantAssignment.user_id == current_user.id)
        .order_by(TenantAssignment.start_date.desc())
        .first()
    )
    if not ta:
        raise HTTPException(status_code=404, detail="No assignment found")
    if ta.start_date > today:
        raise HTTPException(status_code=400, detail="Your stay has not started yet. You can cancel it instead.")
    if ta.end_date is not None and ta.end_date < today:
        raise HTTPException(status_code=400, detail="This assignment has already ended.")
    ta.end_date = today
    db.add(ta)
    db.flush()
    unit = db.query(Unit).filter(Unit.id == ta.unit_id).first()
    prop = db.query(Property).filter(Property.id == unit.property_id).first() if unit else None
    if unit:
        unit.occupancy_status = OccupancyStatus.vacant.value
        db.add(unit)
    if prop:
        prop.occupancy_status = OccupancyStatus.vacant.value
        db.add(prop)
    db.commit()
    ip = request.client.host if request.client else None
    ua = (request.headers.get("user-agent") or "").strip() or None
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "Tenant ended assignment (checkout)",
        f"Tenant ended assignment (unit_id={ta.unit_id}, end_date set to {today.isoformat()}). Unit/property set to vacant.",
        property_id=prop.id if prop else None,
        stay_id=None,
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=ip,
        user_agent=ua,
        meta={"unit_id": ta.unit_id, "end_date": str(today)},
    )
    create_ledger_event(
        db,
        ACTION_TENANT_CHECK_OUT,
        property_id=prop.id if prop else None,
        unit_id=ta.unit_id,
        actor_user_id=current_user.id,
        ip_address=ip,
        user_agent=ua,
        meta={
            "message": f"Tenant ended assignment (unit_id={ta.unit_id}, end_date set to {today.isoformat()}). Unit/property set to vacant.",
            "unit_id": ta.unit_id,
            "end_date": str(today),
        },
    )
    db.commit()
    return {"status": "success", "message": "Checkout complete. Your stay has ended."}


def _parse_date(s: str) -> date | None:
    """Parse date from YYYY-MM-DD or MM/DD/YYYY. Returns None if invalid."""
    if not s or not s.strip():
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


@router.post("/tenant/invitations")
def tenant_create_invitation(
    request: Request,
    data: TenantGuestInvitationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_tenant),
):
    """Create a guest invitation for the tenant's assigned unit only."""
    try:
        guest_name = (data.guest_name or "").strip()
        if not guest_name:
            raise HTTPException(status_code=400, detail="Guest name is required.")
        if not data.checkin_date or not data.checkout_date:
            raise HTTPException(status_code=400, detail="Start and end dates are required.")
        start = _parse_date(data.checkin_date)
        end = _parse_date(data.checkout_date)
        if not start:
            raise HTTPException(status_code=400, detail="Invalid start date. Use YYYY-MM-DD format.")
        if not end:
            raise HTTPException(status_code=400, detail="Invalid end date. Use YYYY-MM-DD format.")
        if end <= start:
            raise HTTPException(status_code=400, detail="End date must be after start date.")
        if start < date.today():
            raise HTTPException(status_code=400, detail="Check-in date cannot be in the past.")

        unit_id = data.unit_id
        if not unit_id or unit_id <= 0:
            raise HTTPException(status_code=400, detail="Invalid unit. Please refresh the page and try again.")
        if not can_perform_action(db, current_user, Action.INVITE_GUEST, unit_id=unit_id, mode="business"):
            raise HTTPException(status_code=403, detail="You do not have access to invite guests for this unit.")

        unit = db.query(Unit).filter(Unit.id == unit_id).first()
        if not unit:
            raise HTTPException(status_code=404, detail="Unit not found.")
        prop = db.query(Property).filter(Property.id == unit.property_id).first()
        if not prop:
            raise HTTPException(status_code=404, detail="Property not found.")
        if prop.deleted_at is not None:
            raise HTTPException(status_code=400, detail="Cannot create invitation for an inactive property.")

        ta = (
            db.query(TenantAssignment)
            .filter(TenantAssignment.unit_id == unit_id, TenantAssignment.user_id == current_user.id)
            .order_by(TenantAssignment.start_date.desc())
            .first()
        )
        if not ta:
            raise HTTPException(status_code=403, detail="You are not assigned to this unit.")
        # Use same effective stay dates as tenant_unit display (tenant invitation if available, else assignment)
        tenant_inv = (
            db.query(Invitation)
            .filter(Invitation.unit_id == unit_id, Invitation.invitation_kind == "tenant")
            .order_by(Invitation.created_at.desc())
            .first()
        )
        effective_start = tenant_inv.stay_start_date if tenant_inv else ta.start_date
        effective_end = tenant_inv.stay_end_date if tenant_inv else ta.end_date
        if start < effective_start:
            raise HTTPException(
                status_code=400,
                detail=f"Guest check-in cannot be before your stay starts ({effective_start.isoformat()}).",
            )
        if effective_end is not None and end > effective_end:
            raise HTTPException(
                status_code=400,
                detail=f"Guest check-out cannot be after your stay ends ({effective_end.isoformat()}).",
            )

        owner_profile = db.query(OwnerProfile).filter(OwnerProfile.id == prop.owner_profile_id).first()
        owner_user_id = owner_profile.user_id if owner_profile else None
        if not owner_user_id:
            raise HTTPException(status_code=500, detail="Property configuration error. Please contact support.")

        code = "INV-" + secrets.token_hex(4).upper()
        inv = Invitation(
            invitation_code=code,
            owner_id=owner_user_id,
            property_id=prop.id,
            unit_id=unit_id,
            invited_by_user_id=current_user.id,
            guest_name=guest_name,
            guest_email=None,
            stay_start_date=start,
            stay_end_date=end,
            purpose_of_stay=PurposeOfStay.travel,
            relationship_to_owner=RelationshipToOwner.friend,
            region_code=prop.region_code or "US",
            status="pending",
            token_state="STAGED",
            invitation_kind="guest",
            dead_mans_switch_enabled=1,
            dead_mans_switch_alert_email=1,
            dead_mans_switch_alert_sms=0,
            dead_mans_switch_alert_dashboard=1,
            dead_mans_switch_alert_phone=0,
        )
        db.add(inv)
        db.commit()
        db.refresh(inv)

        ip = request.client.host if request.client else None
        ua = (request.headers.get("user-agent") or "").strip() or None
        create_log(
            db,
            CATEGORY_STATUS_CHANGE,
            "Tenant guest invitation created",
            f"Tenant created guest invite {code} for unit {unit_id}, guest {guest_name}, {start}–{end}.",
            property_id=prop.id,
            invitation_id=inv.id,
            actor_user_id=current_user.id,
            actor_email=current_user.email,
            ip_address=ip,
            user_agent=ua,
            meta={"invitation_code": code, "token_state": "STAGED", "guest_name": guest_name},
        )
        create_ledger_event(
            db,
            ACTION_GUEST_INVITE_CREATED,
            target_object_type="Invitation",
            target_object_id=inv.id,
            property_id=prop.id,
            unit_id=unit_id,
            invitation_id=inv.id,
            actor_user_id=current_user.id,
            meta={
                "invitation_code": code,
                "token_state": "STAGED",
                "guest_name": guest_name,
                "stay_start_date": str(start),
                "stay_end_date": str(end),
                "invited_by_role": "tenant",
            },
            ip_address=ip,
            user_agent=ua,
        )
        property_name = (prop.name or "").strip() or (f"{getattr(prop, 'city', '')}, {getattr(prop, 'state', '')}".strip(", ")) or f"Property {prop.id}"
        owner_profile = db.query(OwnerProfile).filter(OwnerProfile.id == prop.owner_profile_id).first()
        owner_user = db.query(User).filter(User.id == owner_profile.user_id).first() if owner_profile else None
        owner_email = (owner_user.email or "").strip() if owner_user else ""
        manager_emails = [
            (u.email or "").strip()
            for a in db.query(PropertyManagerAssignment).filter(PropertyManagerAssignment.property_id == prop.id).all()
            for u in [db.query(User).filter(User.id == a.user_id).first()]
            if u and (u.email or "").strip()
        ]
        try:
            send_dead_mans_switch_enabled_notification(owner_email, manager_emails, property_name, guest_name, str(end))
        except Exception as e:
            logger.warning("DMS enabled notification failed: %s", e)
        db.commit()
        return {"invitation_code": code}
    except HTTPException:
        raise
    except Exception:
        logger.exception("tenant_create_invitation unexpected error")
        raise HTTPException(status_code=500, detail="Failed to create invitation. Please try again.")


@router.get("/tenant/invitations", response_model=list[OwnerInvitationView])
def tenant_invitations(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_tenant),
):
    """List invitations created by this tenant (invited_by_user_id)."""
    invs = (
        db.query(Invitation)
        .filter(Invitation.invited_by_user_id == current_user.id)
        .order_by(Invitation.created_at.desc())
        .all()
    )
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


@router.get("/tenant/guest-history", response_model=list[OwnerStayView])
def tenant_guest_history(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_tenant),
):
    """Stays for guests invited by this tenant (invited_by_user_id on invitation)."""
    inv_ids = [r[0] for r in db.query(Invitation.id).filter(Invitation.invited_by_user_id == current_user.id).all()]
    if not inv_ids:
        return []
    stays = db.query(Stay).filter(Stay.invitation_id.in_(inv_ids)).all()
    out = []
    for s in stays:
        guest = db.query(User).filter(User.id == s.guest_id).first()
        guest_profile = db.query(GuestProfile).filter(GuestProfile.user_id == s.guest_id).first()
        guest_name = (guest_profile.full_legal_name if guest_profile else None) or (guest.full_name if guest else None) or (guest.email if guest else "Unknown")
        prop = db.query(Property).filter(Property.id == s.property_id).first()
        property_name = (prop.name if prop else None) or (f"{prop.city}, {prop.state}" if prop else None) or "Property"
        rule = db.query(RegionRule).filter(RegionRule.region_code == s.region_code).first()
        jle = resolve_jurisdiction(db, JLEInput(region_code=s.region_code, stay_duration_days=s.intended_stay_duration_days, owner_occupied=True, property_type=None, guest_has_permanent_address=True))
        max_days = rule.max_stay_days if rule else 0
        classification = (jle.legal_classification if jle else None) or (rule.stay_classification_label if rule else None) or StayClassification.guest
        risk = (jle.risk_level if jle else None) or (rule.risk_level if rule else None) or RiskLevel.low
        statutes = (jle.applicable_statutes if jle else []) or ([rule.statute_reference] if rule and rule.statute_reference else [])
        checked_out = getattr(s, "checked_out_at", None) is not None
        cancelled = getattr(s, "cancelled_at", None) is not None
        conf_resp = getattr(s, "occupancy_confirmation_response", None)
        dms_on = bool(getattr(s, "dead_mans_switch_enabled", 0))
        confirmation_deadline_at = datetime.combine(s.stay_end_date + timedelta(days=2), dt_time.min, tzinfo=timezone.utc) if s.stay_end_date else None
        now = datetime.now(timezone.utc)
        needs_conf = (not checked_out and not cancelled and dms_on and conf_resp is None and confirmation_deadline_at and now < confirmation_deadline_at and s.stay_end_date <= (date.today() + timedelta(days=2)))
        prop_status = (getattr(prop, "occupancy_status", None) or "unknown") if prop else "unknown"
        show_confirm_ui = needs_conf or (prop_status == OccupancyStatus.unconfirmed.value and not checked_out and not cancelled and dms_on and conf_resp is None and s.stay_end_date < date.today())
        invite_id_val = None
        token_state_val = None
        if getattr(s, "invitation_id", None):
            inv = db.query(Invitation).filter(Invitation.id == s.invitation_id).first()
            if inv:
                invite_id_val = inv.invitation_code
                token_state_val = getattr(inv, "token_state", None) or "BURNED"
        out.append(OwnerStayView(
            stay_id=s.id, property_id=s.property_id, invite_id=invite_id_val, token_state=token_state_val, invitation_only=False,
            guest_name=guest_name, property_name=property_name, stay_start_date=s.stay_start_date, stay_end_date=s.stay_end_date,
            region_code=s.region_code, legal_classification=classification, max_stay_allowed_days=max_days, risk_indicator=risk, applicable_laws=statutes,
            revoked_at=getattr(s, "revoked_at", None), checked_in_at=getattr(s, "checked_in_at", None), checked_out_at=getattr(s, "checked_out_at", None), cancelled_at=getattr(s, "cancelled_at", None),
            usat_token_released_at=getattr(s, "usat_token_released_at", None), dead_mans_switch_enabled=dms_on,
            needs_occupancy_confirmation=needs_conf, show_occupancy_confirmation_ui=show_confirm_ui, confirmation_deadline_at=confirmation_deadline_at if show_confirm_ui else None, occupancy_confirmation_response=conf_resp,
        ))
    invitation_ids_with_stay = {s.invitation_id for s in stays if getattr(s, "invitation_id", None) is not None}
    q = db.query(Invitation).filter(Invitation.invited_by_user_id == current_user.id, Invitation.token_state.in_(["BURNED", "EXPIRED"]))
    if invitation_ids_with_stay:
        q = q.filter(~Invitation.id.in_(invitation_ids_with_stay))
    for inv in q.all():
        prop = db.query(Property).filter(Property.id == inv.property_id).first()
        if not prop or getattr(prop, "deleted_at", None):
            continue
        property_name = (prop.name or "").strip() or (f"{getattr(prop, 'city', '')}, {getattr(prop, 'state', '')}".strip(", ")) or "Property"
        region = (getattr(inv, "region_code", None) or "").strip() or (getattr(prop, "region_code", None) or "") or "US"
        start, end = inv.stay_start_date, inv.stay_end_date
        duration_days = (end - start).days if start and end else 0
        rule = db.query(RegionRule).filter(RegionRule.region_code == region).first()
        jle = resolve_jurisdiction(db, JLEInput(region_code=region, stay_duration_days=duration_days, owner_occupied=True, property_type=None, guest_has_permanent_address=True))
        max_days = rule.max_stay_days if rule else 0
        classification = (jle.legal_classification if jle else None) or (rule.stay_classification_label if rule else None) or StayClassification.guest
        risk = (jle.risk_level if jle else None) or (rule.risk_level if rule else None) or RiskLevel.low
        statutes = (jle.applicable_statutes if jle else []) or ([rule.statute_reference] if rule and rule.statute_reference else [])
        token_state = (getattr(inv, "token_state", None) or "BURNED").upper()
        is_expired = token_state == "EXPIRED"
        checked_out_dt = datetime.combine(end, dt_time.min, tzinfo=timezone.utc) if is_expired and end else None
        out.append(OwnerStayView(
            stay_id=-inv.id, property_id=inv.property_id, invite_id=inv.invitation_code, token_state=token_state, invitation_only=True,
            guest_name=(inv.guest_name or "").strip() or "Guest (pending sign-up)", property_name=property_name, stay_start_date=start, stay_end_date=end,
            region_code=region, legal_classification=classification, max_stay_allowed_days=max_days, risk_indicator=risk, applicable_laws=statutes,
            revoked_at=None, checked_in_at=None, checked_out_at=checked_out_dt, cancelled_at=None, usat_token_released_at=None,
            dead_mans_switch_enabled=bool(getattr(inv, "dead_mans_switch_enabled", 0)), needs_occupancy_confirmation=False, show_occupancy_confirmation_ui=False, confirmation_deadline_at=None, occupancy_confirmation_response=None,
        ))
    return out


@router.get("/presence")
def get_presence(
    unit_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get current presence for a unit. Requires tenant or owner/manager in personal mode."""
    if not can_perform_action(db, current_user, Action.SET_PRESENCE, unit_id=unit_id):
        raise HTTPException(status_code=403, detail="You do not have access to view presence for this unit")
    pres = db.query(ResidentPresence).filter(
        ResidentPresence.user_id == current_user.id,
        ResidentPresence.unit_id == unit_id,
    ).first()
    if not pres:
        # Default: away. If primary residence (owner_occupied), default present unless owner changes it.
        default_status = "away"
        unit = db.query(Unit).filter(Unit.id == unit_id).first()
        if unit and current_user.role == UserRole.owner:
            prop = db.query(Property).filter(Property.id == unit.property_id).first()
            if prop and prop.owner_occupied:
                default_status = "present"
        return {"status": default_status, "unit_id": unit_id, "away_started_at": None, "away_ended_at": None, "guests_authorized_during_away": False}
    return {
        "status": pres.status.value,
        "unit_id": unit_id,
        "away_started_at": pres.away_started_at.isoformat() if pres.away_started_at else None,
        "away_ended_at": pres.away_ended_at.isoformat() if pres.away_ended_at else None,
        "guests_authorized_during_away": bool(pres.guests_authorized_during_away),
    }


@router.post("/presence")
def set_presence(
    request: Request,
    unit_id: int = Body(..., embed=True),
    status: str = Body(..., embed=True),
    guests_authorized_during_away: bool | None = Body(None, embed=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Set presence/away status for a unit. Requires tenant or owner/manager in personal mode only (not business mode)."""
    if status not in ("present", "away"):
        raise HTTPException(status_code=400, detail="status must be 'present' or 'away'")
    if not can_perform_action(db, current_user, Action.SET_PRESENCE, unit_id=unit_id):
        raise HTTPException(status_code=403, detail="You do not have access to set presence for this unit")
    unit = db.query(Unit).filter(Unit.id == unit_id).first()
    if not unit:
        raise HTTPException(status_code=404, detail="Unit not found")
    property_id = unit.property_id

    pres = db.query(ResidentPresence).filter(
        ResidentPresence.user_id == current_user.id,
        ResidentPresence.unit_id == unit_id,
    ).first()
    status_enum = PresenceStatus.present if status == "present" else PresenceStatus.away
    now = datetime.now(timezone.utc)
    prev_status = pres.status if pres else None

    if pres:
        pres.status = status_enum
        pres.updated_at = now
        if status == "away":
            pres.away_started_at = now
            pres.away_ended_at = None
            pres.guests_authorized_during_away = bool(guests_authorized_during_away) if guests_authorized_during_away is not None else False
        else:
            pres.away_ended_at = now
            if guests_authorized_during_away is not None:
                pres.guests_authorized_during_away = bool(guests_authorized_during_away)
    else:
        pres = ResidentPresence(
            user_id=current_user.id,
            unit_id=unit_id,
            status=status_enum,
            away_started_at=now if status == "away" else None,
            away_ended_at=None,
            guests_authorized_during_away=bool(guests_authorized_during_away) if guests_authorized_during_away is not None else False,
        )
        db.add(pres)

    if prev_status != status_enum:
        actor_label = (
            "Manager" if current_user.role == UserRole.property_manager
            else "Owner" if current_user.role == UserRole.owner
            else "Tenant"
        )
        unit_label = getattr(unit, "unit_label", None) or f"Unit {unit_id}"
        log_message = f"{actor_label} {current_user.email or 'Unknown'} set presence to {status} for {unit_label}."
        # When Away is activated, the system records: resident temporarily absent, guests authorized during period, start timestamp
        if status == "away":
            away_ts = pres.away_started_at.isoformat() if pres.away_started_at else None
            guests_ok = "Yes" if pres.guests_authorized_during_away else "No"
            audit_message = (
                f"{log_message} "
                f"Resident is temporarily absent. "
                f"Guests authorized during this period: {guests_ok}. "
                f"Absence started at: {away_ts or '—'}."
            )
        else:
            audit_message = log_message
        create_log(
            db,
            CATEGORY_PRESENCE,
            "Presence status changed",
            audit_message,
            property_id=property_id,
            actor_user_id=current_user.id,
            actor_email=current_user.email,
            ip_address=request.client.host if request.client else None,
            meta={
                "status": status,
                "unit_id": unit_id,
                "away_started_at": pres.away_started_at.isoformat() if pres.away_started_at else None,
                "away_ended_at": pres.away_ended_at.isoformat() if pres.away_ended_at else None,
                "guests_authorized_during_away": pres.guests_authorized_during_away,
            },
        )
        # Event ledger: when away is activated, record resident temporarily absent, guests authorized, and start timestamp
        if status == "away":
            away_ts = pres.away_started_at.isoformat() if pres.away_started_at else None
            guests_ok = "Yes" if pres.guests_authorized_during_away else "No"
            ledger_message = (
                f"{log_message} "
                f"Resident is temporarily absent. "
                f"Guests authorized during this period: {guests_ok}. "
                f"Absence started at: {away_ts or '—'}."
            )
            create_ledger_event(
                db,
                ACTION_AWAY_ACTIVATED,
                property_id=property_id,
                unit_id=unit_id,
                actor_user_id=current_user.id,
                ip_address=request.client.host if request.client else None,
                meta={
                    "message": ledger_message,
                    "status": status,
                    "unit_label": unit_label,
                    "resident_temporarily_absent": True,
                    "guests_authorized_during_away": pres.guests_authorized_during_away,
                    "away_started_at": away_ts,
                },
            )
        elif status == "present":
            ledger_message = f"{log_message} Resident returned; away status ended."
            create_ledger_event(
                db,
                ACTION_AWAY_ENDED,
                property_id=property_id,
                unit_id=unit_id,
                actor_user_id=current_user.id,
                ip_address=request.client.host if request.client else None,
                meta={"message": ledger_message, "status": status, "unit_label": unit_label},
            )
            # Full timeline: append completed away period to history
            if pres.away_started_at is not None:
                db.add(PresenceAwayPeriod(
                    resident_presence_id=pres.id,
                    stay_id=None,
                    away_started_at=pres.away_started_at,
                    away_ended_at=now,
                    guests_authorized_during_away=pres.guests_authorized_during_away,
                ))
        else:
            create_ledger_event(
                db,
                ACTION_PRESENCE_STATUS_CHANGED,
                property_id=property_id,
                unit_id=unit_id,
                actor_user_id=current_user.id,
                ip_address=request.client.host if request.client else None,
                meta={"message": log_message, "status": status, "unit_label": unit_label},
            )

    db.commit()
    db.refresh(pres)
    return {
        "status": "success",
        "presence": status,
        "unit_id": unit_id,
        "away_started_at": pres.away_started_at.isoformat() if pres.away_started_at else None,
        "away_ended_at": pres.away_ended_at.isoformat() if pres.away_ended_at else None,
        "guests_authorized_during_away": pres.guests_authorized_during_away,
    }


@router.get("/guest/presence")
def get_stay_presence(
    stay_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get presence for an ongoing stay. Guest only; stay must be checked in and not checked out."""
    stay = db.query(Stay).filter(Stay.id == stay_id).first()
    if not stay:
        raise HTTPException(status_code=404, detail="Stay not found")
    if stay.guest_id != current_user.id:
        raise HTTPException(status_code=403, detail="You do not have access to this stay")
    if not stay.checked_in_at or stay.checked_out_at:
        raise HTTPException(status_code=400, detail="Presence is only available for an ongoing stay after check-in")
    pres = db.query(StayPresence).filter(StayPresence.stay_id == stay_id).first()
    if not pres:
        return {
            "status": "present",
            "stay_id": stay_id,
            "away_started_at": None,
            "away_ended_at": None,
            "guests_authorized_during_away": False,
        }
    return {
        "status": pres.status.value,
        "stay_id": stay_id,
        "away_started_at": pres.away_started_at.isoformat() if pres.away_started_at else None,
        "away_ended_at": pres.away_ended_at.isoformat() if pres.away_ended_at else None,
        "guests_authorized_during_away": bool(pres.guests_authorized_during_away),
    }


@router.post("/guest/presence")
def set_stay_presence(
    request: Request,
    stay_id: int = Body(..., embed=True),
    status: str = Body(..., embed=True),
    guests_authorized_during_away: bool | None = Body(None, embed=True),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Set present/away for an ongoing stay. Guest only; stay must be checked in and not checked out."""
    if status not in ("present", "away"):
        raise HTTPException(status_code=400, detail="status must be 'present' or 'away'")
    stay = db.query(Stay).filter(Stay.id == stay_id).first()
    if not stay:
        raise HTTPException(status_code=404, detail="Stay not found")
    if stay.guest_id != current_user.id:
        raise HTTPException(status_code=403, detail="You do not have access to this stay")
    if not stay.checked_in_at or stay.checked_out_at:
        raise HTTPException(status_code=400, detail="Presence is only available for an ongoing stay after check-in")
    property_id = stay.property_id
    unit_id = stay.unit_id
    unit_label = None
    if unit_id:
        unit = db.query(Unit).filter(Unit.id == unit_id).first()
        unit_label = getattr(unit, "unit_label", None) if unit else None
    unit_label = unit_label or (f"Unit {unit_id}" if unit_id else "Property")

    pres = db.query(StayPresence).filter(StayPresence.stay_id == stay_id).first()
    status_enum = PresenceStatus.present if status == "present" else PresenceStatus.away
    now = datetime.now(timezone.utc)
    prev_status = pres.status if pres else None

    if pres:
        pres.status = status_enum
        pres.updated_at = now
        if status == "away":
            pres.away_started_at = now
            pres.away_ended_at = None
            pres.guests_authorized_during_away = bool(guests_authorized_during_away) if guests_authorized_during_away is not None else False
        else:
            pres.away_ended_at = now
            if guests_authorized_during_away is not None:
                pres.guests_authorized_during_away = bool(guests_authorized_during_away)
    else:
        pres = StayPresence(
            stay_id=stay_id,
            status=status_enum,
            away_started_at=now if status == "away" else None,
            away_ended_at=None,
            guests_authorized_during_away=bool(guests_authorized_during_away) if guests_authorized_during_away is not None else False,
        )
        db.add(pres)

    if prev_status != status_enum:
        log_message = f"Guest {current_user.email or 'Unknown'} set presence to {status} for stay {stay_id} ({unit_label})."
        # When Away is activated, the system records: resident temporarily absent, guests authorized during period, start timestamp
        if status == "away":
            away_ts = pres.away_started_at.isoformat() if pres.away_started_at else None
            guests_ok = "Yes" if pres.guests_authorized_during_away else "No"
            audit_message = (
                f"{log_message} "
                f"Resident is temporarily absent. "
                f"Guests authorized during this period: {guests_ok}. "
                f"Absence started at: {away_ts or '—'}."
            )
        else:
            audit_message = log_message
        create_log(
            db,
            CATEGORY_PRESENCE,
            "Presence status changed",
            audit_message,
            property_id=property_id,
            actor_user_id=current_user.id,
            actor_email=current_user.email,
            ip_address=request.client.host if request.client else None,
            meta={
                "status": status,
                "stay_id": stay_id,
                "unit_id": unit_id,
                "away_started_at": pres.away_started_at.isoformat() if pres.away_started_at else None,
                "away_ended_at": pres.away_ended_at.isoformat() if pres.away_ended_at else None,
                "guests_authorized_during_away": pres.guests_authorized_during_away,
            },
        )
        if status == "away":
            away_ts = pres.away_started_at.isoformat() if pres.away_started_at else None
            guests_ok = "Yes" if pres.guests_authorized_during_away else "No"
            ledger_message = (
                f"{log_message} "
                f"Guest is temporarily absent. "
                f"Guests authorized during this period: {guests_ok}. "
                f"Absence started at: {away_ts or '—'}."
            )
            create_ledger_event(
                db,
                ACTION_AWAY_ACTIVATED,
                property_id=property_id,
                unit_id=unit_id,
                stay_id=stay_id,
                actor_user_id=current_user.id,
                ip_address=request.client.host if request.client else None,
                meta={
                    "message": ledger_message,
                    "status": status,
                    "unit_label": unit_label,
                    "resident_temporarily_absent": True,
                    "guests_authorized_during_away": pres.guests_authorized_during_away,
                    "away_started_at": away_ts,
                },
            )
        elif status == "present":
            ledger_message = f"{log_message} Guest returned; away status ended."
            create_ledger_event(
                db,
                ACTION_AWAY_ENDED,
                property_id=property_id,
                unit_id=unit_id,
                stay_id=stay_id,
                actor_user_id=current_user.id,
                ip_address=request.client.host if request.client else None,
                meta={"message": ledger_message, "status": status, "unit_label": unit_label},
            )
            if pres.away_started_at is not None:
                db.add(PresenceAwayPeriod(
                    resident_presence_id=None,
                    stay_id=stay_id,
                    away_started_at=pres.away_started_at,
                    away_ended_at=now,
                    guests_authorized_during_away=pres.guests_authorized_during_away,
                ))

    db.commit()
    db.refresh(pres)
    return {
        "status": "success",
        "presence": status,
        "stay_id": stay_id,
        "away_started_at": pres.away_started_at.isoformat() if pres.away_started_at else None,
        "away_ended_at": pres.away_ended_at.isoformat() if pres.away_ended_at else None,
        "guests_authorized_during_away": pres.guests_authorized_during_away,
    }


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
    if current_user.role == UserRole.property_manager:
        raise HTTPException(status_code=403, detail="Property managers cannot modify billing. Contact the property owner.")
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


@router.get("/owner/personal-mode-units")
def owner_personal_mode_units(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Unit IDs where this owner has Personal Mode (lives as resident). Used for Mode Switcher."""
    unit_ids = get_owner_personal_mode_units(db, current_user.id)
    db.commit()  # commit any new Units created for single-unit properties so set_presence can use them
    return {"unit_ids": unit_ids}


@router.get("/owner/properties/{property_id}/personal-mode-unit")
def owner_property_personal_mode_unit(
    property_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Unit ID for this property if owner can set presence. Returns null if owner does not own this property."""
    unit_ids = get_owner_personal_mode_units(db, current_user.id)
    db.commit()  # commit any new Units created for single-unit properties so set_presence can use them
    for uid in unit_ids:
        u = db.query(Unit).filter(Unit.id == uid, Unit.property_id == property_id).first()
        if u:
            return {"unit_id": u.id}
    return {"unit_id": None}


@router.get("/manager/personal-mode-units")
def manager_personal_mode_units(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_property_manager_identity_verified),
):
    """Unit IDs where this manager has Personal Mode (lives on-site). Used for Mode Switcher."""
    unit_ids = get_manager_personal_mode_units(db, current_user.id)
    return {"unit_ids": unit_ids}


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
    property_id: int | None = None,
):
    """Activity logs for all owned properties. Filter by time range (ISO UTC), category, search, and optional property_id. When property_id is set, only logs for that property are returned. Tracks tenant invitations, guest invitations, guest authorization changes, presence/away status, and system events."""
    from sqlalchemy import or_

    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile:
        return []
    owner_property_ids = [p.id for p in profile.properties]
    if property_id is not None and property_id not in owner_property_ids:
        return []  # Owner doesn't own this property

    from_dt = _parse_optional_utc(from_ts)
    to_dt = _parse_optional_utc(to_ts)

    billing_actions = _CATEGORY_TO_ACTION_TYPES.get("billing", [])

    # When property_id is set: only that property's logs
    if property_id is not None:
        q = db.query(EventLedger).filter(EventLedger.property_id == property_id)
    elif owner_property_ids:
        q = db.query(EventLedger).filter(
            or_(
                EventLedger.property_id.in_(owner_property_ids),
                (EventLedger.action_type == ACTION_PROPERTY_DELETED) & (EventLedger.actor_user_id == current_user.id),
                (EventLedger.action_type.in_(billing_actions)) & (EventLedger.actor_user_id == current_user.id),
            )
        )
    else:
        q = db.query(EventLedger).filter(
            or_(
                (EventLedger.action_type == ACTION_PROPERTY_DELETED) & (EventLedger.actor_user_id == current_user.id),
                (EventLedger.action_type.in_(billing_actions)) & (EventLedger.actor_user_id == current_user.id),
            )
        )
    if from_dt is not None:
        q = q.filter(EventLedger.created_at >= from_dt)
    if to_dt is not None:
        q = q.filter(EventLedger.created_at <= to_dt)
    if category and category.strip():
        action_types = _CATEGORY_TO_ACTION_TYPES.get(category.strip(), [])
        if action_types:
            q = q.filter(EventLedger.action_type.in_(action_types))
    if search and search.strip():
        from sqlalchemy import cast, String
        term = f"%{search.strip()}%"
        q = q.filter(
            (EventLedger.action_type.ilike(term)) | (cast(EventLedger.meta, String).ilike(term))
        )
    from sqlalchemy import desc
    q = q.order_by(desc(EventLedger.created_at))
    rows = q.all()
    rows = filter_tenant_lane_from_ledger_rows(db, rows)

    prop_ids = {r.property_id for r in rows if r.property_id}
    props = {p.id: p.name or f"{p.city}, {p.state}" for p in db.query(Property).filter(Property.id.in_(prop_ids)).all()} if prop_ids else {}

    def _property_name(r) -> str | None:
        if r.property_id:
            return props.get(r.property_id)
        if r.action_type == ACTION_PROPERTY_DELETED and r.meta and isinstance(r.meta, dict):
            return r.meta.get("property_name")
        return None

    out = []
    for r in rows:
        cat, title, msg = ledger_event_to_display(r)
        actor_email = get_actor_email(db, r.actor_user_id)
        out.append(
            OwnerAuditLogEntry(
                id=r.id,
                property_id=r.property_id,
                stay_id=r.stay_id,
                invitation_id=r.invitation_id,
                category=cat,
                title=title,
                message=msg,
                actor_user_id=r.actor_user_id,
                actor_email=actor_email,
                ip_address=r.ip_address,
                created_at=r.created_at if r.created_at else datetime.now(timezone.utc),
                property_name=_property_name(r),
            )
        )
    return out


@router.get("/manager/logs", response_model=list[OwnerAuditLogEntry])
def manager_logs(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_property_manager_identity_verified),
    from_ts: str | None = None,
    to_ts: str | None = None,
    category: str | None = None,
    search: str | None = None,
    property_id: int | None = None,
):
    """Event ledger for properties assigned to this manager. Optional property_id restricts to that property (must be one the manager is assigned to)."""
    from sqlalchemy import desc, cast, String

    property_ids = _manager_property_ids(db, current_user.id)
    if not property_ids:
        return []
    if property_id is not None and property_id not in property_ids:
        return []
    from_dt = _parse_optional_utc(from_ts)
    to_dt = _parse_optional_utc(to_ts)
    q = db.query(EventLedger).filter(EventLedger.property_id.in_(property_ids))
    if property_id is not None:
        q = q.filter(EventLedger.property_id == property_id)
    if from_dt is not None:
        q = q.filter(EventLedger.created_at >= from_dt)
    if to_dt is not None:
        q = q.filter(EventLedger.created_at <= to_dt)
    if category and category.strip():
        action_types = _CATEGORY_TO_ACTION_TYPES.get(category.strip(), [])
        if action_types:
            q = q.filter(EventLedger.action_type.in_(action_types))
    if search and search.strip():
        term = f"%{search.strip()}%"
        q = q.filter((EventLedger.action_type.ilike(term)) | (cast(EventLedger.meta, String).ilike(term)))
    rows = q.order_by(desc(EventLedger.created_at)).all()
    rows = filter_tenant_lane_from_ledger_rows(db, rows)

    prop_ids = {r.property_id for r in rows if r.property_id}
    props = {p.id: p.name or f"{p.city}, {p.state}" for p in db.query(Property).filter(Property.id.in_(prop_ids)).all()} if prop_ids else {}

    out = []
    for r in rows:
        cat, title, msg = ledger_event_to_display(r)
        actor_email = get_actor_email(db, r.actor_user_id)
        out.append(
            OwnerAuditLogEntry(
                id=r.id, property_id=r.property_id, stay_id=r.stay_id, invitation_id=r.invitation_id,
                category=cat, title=title, message=msg,
                actor_user_id=r.actor_user_id, actor_email=actor_email, ip_address=r.ip_address,
                created_at=r.created_at if r.created_at else datetime.now(timezone.utc),
                property_name=props.get(r.property_id) if r.property_id else None,
            )
        )
    return out


@router.get("/tenant/logs", response_model=list[OwnerAuditLogEntry])
def tenant_logs(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_tenant),
    from_ts: str | None = None,
    to_ts: str | None = None,
    category: str | None = None,
    search: str | None = None,
    property_id: int | None = None,
):
    """Activity logs for: (1) the tenant's assigned property, (2) events where tenant is the actor, (3) events for invitations the tenant created."""
    from sqlalchemy import desc, cast, String, or_

    tenant_property_id = None
    ta = (
        db.query(TenantAssignment)
        .filter(TenantAssignment.user_id == current_user.id)
        .order_by(TenantAssignment.start_date.desc())
        .first()
    )
    if ta:
        unit = db.query(Unit).filter(Unit.id == ta.unit_id).first()
        if unit:
            tenant_property_id = unit.property_id
    if property_id is not None and tenant_property_id is not None and property_id != tenant_property_id:
        return []
    invitation_ids = [r[0] for r in db.query(Invitation.id).filter(Invitation.invited_by_user_id == current_user.id).all()]
    conditions = [
        EventLedger.actor_user_id == current_user.id,
    ]
    if tenant_property_id is not None:
        conditions.append(EventLedger.property_id == tenant_property_id)
    if invitation_ids:
        conditions.append(EventLedger.invitation_id.in_(invitation_ids))
    if not conditions:
        return []
    from_dt = _parse_optional_utc(from_ts)
    to_dt = _parse_optional_utc(to_ts)
    q = db.query(EventLedger).filter(or_(*conditions))
    if property_id is not None and tenant_property_id is not None:
        q = q.filter(EventLedger.property_id == property_id)
    if from_dt is not None:
        q = q.filter(EventLedger.created_at >= from_dt)
    if to_dt is not None:
        q = q.filter(EventLedger.created_at <= to_dt)
    if category and category.strip():
        action_types = _CATEGORY_TO_ACTION_TYPES.get(category.strip(), [])
        if action_types:
            q = q.filter(EventLedger.action_type.in_(action_types))
    if search and search.strip():
        term = f"%{search.strip()}%"
        q = q.filter((EventLedger.action_type.ilike(term)) | (cast(EventLedger.meta, String).ilike(term)))
    rows = q.order_by(desc(EventLedger.created_at)).limit(500).all()
    prop_ids = {r.property_id for r in rows if r.property_id}
    props = {p.id: p.name or f"{p.city}, {p.state}" for p in db.query(Property).filter(Property.id.in_(prop_ids)).all()} if prop_ids else {}
    out = []
    for r in rows:
        cat, title, msg = ledger_event_to_display(r)
        actor_email = get_actor_email(db, r.actor_user_id)
        out.append(
            OwnerAuditLogEntry(
                id=r.id, property_id=r.property_id, stay_id=r.stay_id, invitation_id=r.invitation_id,
                category=cat, title=title, message=msg,
                actor_user_id=r.actor_user_id, actor_email=actor_email, ip_address=r.ip_address,
                created_at=r.created_at if r.created_at else datetime.now(timezone.utc),
                property_name=props.get(r.property_id) if r.property_id else None,
            )
        )
    return out


@router.get("/manager/billing", response_model=BillingResponse)
def manager_billing(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_property_manager_identity_verified),
):
    """Read-only billing for the owner of properties this manager is assigned to."""
    property_ids = _manager_property_ids(db, current_user.id)
    if not property_ids:
        return BillingResponse(invoices=[], payments=[], can_invite=False, current_unit_count=0, current_shield_count=0)
    props = db.query(Property).filter(Property.id.in_(property_ids)).all()
    owner_profile_ids = list({p.owner_profile_id for p in props})
    if not owner_profile_ids:
        return BillingResponse(invoices=[], payments=[], can_invite=False, current_unit_count=0, current_shield_count=0)
    profile = db.query(OwnerProfile).filter(OwnerProfile.id == owner_profile_ids[0]).first()
    if not profile:
        return BillingResponse(invoices=[], payments=[], can_invite=False, current_unit_count=0, current_shield_count=0)
    from app.services.billing import _count_units_and_shield
    _units, _shield = _count_units_and_shield(db, profile)
    if not profile.stripe_customer_id:
        return BillingResponse(invoices=[], payments=[], can_invite=False, current_unit_count=_units, current_shield_count=_shield)
    from app.config import get_settings
    import stripe
    settings = get_settings()
    if not (settings.stripe_secret_key or "").strip():
        return BillingResponse(invoices=[], payments=[], current_unit_count=_units, current_shield_count=_shield)
    stripe.api_key = settings.stripe_secret_key
    invoices: list[BillingInvoiceView] = []
    payments: list[BillingPaymentView] = []
    try:
        for inv in stripe.Invoice.list(customer=profile.stripe_customer_id, limit=100).auto_paging_iter():
            if inv.status == "draft":
                try:
                    inv = stripe.Invoice.finalize_invoice(inv.id)
                except stripe.StripeError:
                    continue
            if inv.status == "draft":
                continue
            created_dt = datetime.fromtimestamp(inv.created, tz=timezone.utc) if inv.created else datetime.now(timezone.utc)
            amount_due = getattr(inv, "amount_due", 0) or 0
            amount_paid = getattr(inv, "amount_paid", 0) or 0
            desc = getattr(inv, "description", None) or None
            if not desc and getattr(inv, "lines", None) and getattr(inv.lines, "data", None) and len(inv.lines.data) > 0:
                desc = getattr(inv.lines.data[0], "description", None)
            invoices.append(BillingInvoiceView(
                id=inv.id, number=getattr(inv, "number", None) or None, description=desc, amount_due_cents=amount_due, amount_paid_cents=amount_paid,
                currency=(inv.currency or "usd").upper(), status=inv.status or "open", created=created_dt, hosted_invoice_url=getattr(inv, "hosted_invoice_url", None) or None,
            ))
            if inv.status == "paid" and amount_paid > 0:
                paid_at = datetime.fromtimestamp(inv.status_transitions.paid_at, tz=timezone.utc) if getattr(inv, "status_transitions", None) and getattr(inv.status_transitions, "paid_at", None) else created_dt
                payments.append(BillingPaymentView(invoice_id=inv.id, amount_cents=amount_paid, currency=(inv.currency or "usd").upper(), paid_at=paid_at, description=desc))
    except stripe.StripeError:
        pass
    invoices.sort(key=lambda x: x.created, reverse=True)
    payments.sort(key=lambda x: x.paid_at, reverse=True)
    return BillingResponse(invoices=invoices, payments=payments, can_invite=False, current_unit_count=_units, current_shield_count=_shield)
