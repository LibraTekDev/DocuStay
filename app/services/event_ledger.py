"""Event Ledger service. Single source of truth for all platform events.
Every meaningful action writes here; all activity views read from here.

Activity logs are visible to:
- Owners: for all owned properties (GET /dashboard/owner/logs; optional property_id).
- Property managers: for the properties they manage (GET /dashboard/manager/logs; optional property_id).

Logged actions include:
- Tenant invitations (manager/owner invites tenant to register).
- Tenant assignments (tenant accepts invitation; tenant assignment cancelled by tenant). DocuStay does not revoke or expire tenants.
- Guest invitations (owner/manager/tenant creates invite; guest invite accepted/revoked/cancelled).
- Guest authorization changes (stay revoked, formal removal initiated, check-in, check-out).
- Presence/away status changes (away activated/ended; resident temporarily absent, guests authorized, start timestamp).
- System activity events (Shield Mode, Dead Man's Switch, occupancy confirmed, DMS alerts, overstay, billing, agreements).

Logs create an auditable record of property activity."""
from __future__ import annotations

import enum
from datetime import date, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.models.event_ledger import EventLedger

# Column limits (match model)
_ACTION_TYPE_LEN = 64
_TARGET_OBJECT_TYPE_LEN = 64
_IP_LEN = 64
_USER_AGENT_LEN = 500

# Action types (canonical event names)
ACTION_PROPERTY_CREATED = "PropertyCreated"
ACTION_PROPERTY_UPDATED = "PropertyUpdated"
ACTION_PROPERTY_DELETED = "PropertyDeleted"
ACTION_PROPERTY_REACTIVATED = "PropertyReactivated"
ACTION_MANAGER_ASSIGNED = "ManagerAssigned"
ACTION_MANAGER_INVITED = "ManagerInvited"
ACTION_MANAGER_INVITE_ACCEPTED = "ManagerInviteAccepted"
ACTION_MANAGER_INVITATION_EXPIRED = "ManagerInvitationExpired"
ACTION_TENANT_INVITED = "TenantInvited"
ACTION_TENANT_ACCEPTED = "TenantAccepted"
ACTION_TENANT_ASSIGNMENT_CANCELLED = "TenantAssignmentCancelled"
ACTION_GUEST_INVITE_CREATED = "GuestInviteCreated"
ACTION_GUEST_INVITE_ACCEPTED = "GuestInviteAccepted"
ACTION_GUEST_INVITE_REVOKED = "GuestInviteRevoked"
ACTION_GUEST_INVITE_CANCELLED = "GuestInviteCancelled"
ACTION_GUEST_CHECK_IN = "GuestCheckIn"
ACTION_GUEST_CHECK_OUT = "GuestCheckOut"
ACTION_TENANT_CHECK_OUT = "TenantCheckOut"
ACTION_STAY_CANCELLED = "StayCancelled"
ACTION_STAY_REVOKED = "StayRevoked"
ACTION_STAY_CREATED = "StayCreated"
ACTION_AWAY_ACTIVATED = "AwayActivated"
ACTION_AWAY_ENDED = "AwayEnded"
ACTION_PRESENCE_STATUS_CHANGED = "PresenceStatusChanged"
ACTION_SHIELD_MODE_ON = "ShieldModeOn"
ACTION_SHIELD_MODE_OFF = "ShieldModeOff"
ACTION_DMS_48H_ALERT = "DMS48hAlert"
ACTION_DMS_AUTO_EXECUTED = "DMSAutoExecuted"
ACTION_DMS_DISABLED = "DMSDisabled"
ACTION_OVERSTAY_OCCURRED = "OverstayOccurred"
ACTION_UNIT_VACATED = "UnitVacated"
ACTION_LEASE_RENEWED = "LeaseRenewed"
ACTION_HOLDOVER_CONFIRMED = "HoldoverConfirmed"
ACTION_VACANT_MONITORING_NO_RESPONSE = "VacantMonitoringNoResponse"
ACTION_CONFIRMED_STILL_VACANT = "ConfirmedStillVacant"
ACTION_BILLING_INVOICE_PAID = "BillingInvoicePaid"
ACTION_BILLING_INVOICE_CREATED = "BillingInvoiceCreated"
ACTION_BILLING_INVOICE_PAYMENT_FAILED = "BillingInvoicePaymentFailed"
ACTION_AGREEMENT_SIGNED = "AgreementSigned"
ACTION_MASTER_POA_SIGNED = "MasterPOASigned"
ACTION_AGREEMENT_SIGN_FAILED = "AgreementSignFailed"
ACTION_VERIFY_ATTEMPT_VALID = "VerifyAttemptValid"
ACTION_VERIFY_ATTEMPT_FAILED = "VerifyAttemptFailed"
ACTION_EMAIL_VERIFICATION_FAILED = "EmailVerificationFailed"
ACTION_ACCEPT_INVITE_FAILED = "AcceptInviteFailed"
ACTION_LOGIN_FAILED = "LoginFailed"
ACTION_USER_LOGGED_IN = "UserLoggedIn"
ACTION_USER_ROLE_CHANGED = "UserRoleChanged"
ACTION_INVITATION_EXPIRED = "InvitationExpired"
ACTION_INVITATION_CREATED = "InvitationCreated"
ACTION_OWNERSHIP_PROOF_UPLOADED = "OwnershipProofUploaded"
ACTION_INVITATION_CREATED_CSV = "InvitationCreatedCSV"


def _sanitize_json_value(v: Any) -> Any:
    """Convert to JSON-serializable value."""
    if v is None:
        return None
    if isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, enum.Enum):
        return getattr(v, "value", str(v))
    if isinstance(v, dict):
        return {str(k): _sanitize_json_value(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_sanitize_json_value(x) for x in v]
    return str(v)


def _sanitize_meta(meta: dict[str, Any] | None) -> dict[str, Any] | None:
    if meta is None:
        return None
    try:
        return {str(k): _sanitize_json_value(v) for k, v in meta.items()}
    except Exception:
        return {"_error": "meta_serialization", "raw_keys": list(meta.keys())[:10]}


# Mapping: action_type -> (category, title) for backward-compatible display
_ACTION_DISPLAY: dict[str, tuple[str, str]] = {
    ACTION_PROPERTY_CREATED: ("status_change", "Property registered"),
    ACTION_PROPERTY_UPDATED: ("status_change", "Property updated"),
    ACTION_PROPERTY_DELETED: ("status_change", "Property deleted"),
    ACTION_PROPERTY_REACTIVATED: ("status_change", "Property reactivated"),
    ACTION_MANAGER_ASSIGNED: ("tenant_assignment", "Manager assigned"),
    ACTION_TENANT_INVITED: ("status_change", "Invitation created (manager invite tenant)"),
    ACTION_TENANT_ACCEPTED: ("status_change", "Tenant assignment accepted"),
    ACTION_TENANT_ASSIGNMENT_CANCELLED: ("status_change", "Tenant assignment cancelled"),
    ACTION_GUEST_INVITE_CREATED: ("status_change", "Invitation created"),
    ACTION_GUEST_INVITE_ACCEPTED: ("status_change", "Invitation accepted"),
    ACTION_GUEST_INVITE_REVOKED: ("status_change", "Invitation revoked"),
    ACTION_GUEST_INVITE_CANCELLED: ("status_change", "Invitation cancelled"),
    ACTION_GUEST_CHECK_IN: ("status_change", "Guest checked in"),
    ACTION_GUEST_CHECK_OUT: ("status_change", "Guest checked out"),
    ACTION_TENANT_CHECK_OUT: ("status_change", "Tenant checked out"),
    ACTION_STAY_CANCELLED: ("status_change", "Stay cancelled by guest"),
    ACTION_STAY_REVOKED: ("status_change", "Stay revoked"),
    ACTION_STAY_CREATED: ("status_change", "Stay created"),
    ACTION_AWAY_ACTIVATED: ("presence", "Away status activated"),
    ACTION_AWAY_ENDED: ("presence", "Away status ended"),
    ACTION_PRESENCE_STATUS_CHANGED: ("presence", "Presence status changed"),
    ACTION_SHIELD_MODE_ON: ("shield_mode", "Shield Mode turned on"),
    ACTION_SHIELD_MODE_OFF: ("shield_mode", "Shield Mode turned off"),
    ACTION_DMS_48H_ALERT: ("dead_mans_switch", "Dead Man's Switch: 48h before lease end"),
    ACTION_DMS_AUTO_EXECUTED: ("dead_mans_switch", "Dead Man's Switch: auto-executed"),
    ACTION_DMS_DISABLED: ("dead_mans_switch", "Dead Man's Switch turned off"),
    ACTION_OVERSTAY_OCCURRED: ("status_change", "Overstay occurred"),
    ACTION_UNIT_VACATED: ("status_change", "Owner confirmed: Unit Vacated"),
    ACTION_LEASE_RENEWED: ("status_change", "Owner confirmed: Lease Renewed"),
    ACTION_HOLDOVER_CONFIRMED: ("status_change", "Owner confirmed: Holdover"),
    ACTION_VACANT_MONITORING_NO_RESPONSE: ("status_change", "Vacant monitoring: no response – status UNCONFIRMED"),
    ACTION_CONFIRMED_STILL_VACANT: ("status_change", "Owner confirmed still vacant"),
    ACTION_BILLING_INVOICE_PAID: ("billing", "Invoice paid"),
    ACTION_BILLING_INVOICE_CREATED: ("billing", "Onboarding invoice created"),
    ACTION_BILLING_INVOICE_PAYMENT_FAILED: ("billing", "Payment failed"),
    ACTION_AGREEMENT_SIGNED: ("guest_signature", "Agreement signed"),
    ACTION_MASTER_POA_SIGNED: ("status_change", "Master POA signed"),
    ACTION_AGREEMENT_SIGN_FAILED: ("failed_attempt", "Agreement sign failed"),
    ACTION_VERIFY_ATTEMPT_VALID: ("verify_attempt", "Verify attempt – valid"),
    ACTION_VERIFY_ATTEMPT_FAILED: ("failed_attempt", "Verify attempt – failed"),
    ACTION_EMAIL_VERIFICATION_FAILED: ("failed_attempt", "Email verification failed"),
    ACTION_ACCEPT_INVITE_FAILED: ("failed_attempt", "Accept invite failed"),
    ACTION_LOGIN_FAILED: ("failed_attempt", "Login failed"),
    ACTION_USER_LOGGED_IN: ("status_change", "User logged in"),
    ACTION_USER_ROLE_CHANGED: ("status_change", "User role changed"),
    ACTION_INVITATION_EXPIRED: ("status_change", "Invitation expired (not accepted in time)"),
    ACTION_MANAGER_INVITATION_EXPIRED: ("status_change", "Manager invitation expired (link not used in time)"),
    ACTION_INVITATION_CREATED: ("status_change", "Invitation created"),
    ACTION_OWNERSHIP_PROOF_UPLOADED: ("status_change", "Ownership proof uploaded"),
    ACTION_INVITATION_CREATED_CSV: ("status_change", "Invitation created (CSV occupied)"),
}

_CATEGORY_TO_ACTION_TYPES: dict[str, list[str]] = {
    k: [a for a in _ACTION_DISPLAY if _ACTION_DISPLAY[a][0] == k]
    for k in {"status_change", "guest_signature", "failed_attempt", "shield_mode", "dead_mans_switch", "billing", "verify_attempt", "presence", "tenant_assignment"}
}


def get_actor_email(db: Session, actor_user_id: int | None) -> str | None:
    """Resolve actor email from user id for display."""
    if not actor_user_id:
        return None
    from app.models.user import User
    u = db.query(User).filter(User.id == actor_user_id).first()
    return u.email if u else None


def ledger_event_to_display(entry: EventLedger) -> tuple[str, str, str]:
    """Map ledger entry to (category, title, message) for OwnerAuditLogEntry / LiveLogEntry."""
    cat, title = _ACTION_DISPLAY.get(
        entry.action_type or "",
        ("status_change", entry.action_type or "—"),
    )
    # Message: use meta if available, else generic from title
    meta = entry.meta or {}
    if isinstance(meta, dict) and meta.get("message"):
        msg = str(meta["message"])
    else:
        msg = title
    return (cat, title, msg)


def create_ledger_event(
    db: Session,
    action_type: str,
    *,
    target_object_type: str | None = None,
    target_object_id: int | None = None,
    property_id: int | None = None,
    unit_id: int | None = None,
    stay_id: int | None = None,
    invitation_id: int | None = None,
    actor_user_id: int | None = None,
    previous_value: dict[str, Any] | None = None,
    new_value: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> EventLedger:
    """Append one immutable ledger event. All timestamps are UTC (server_default)."""
    action = (action_type or "")[:_ACTION_TYPE_LEN].strip() or "Unknown"
    target_type = (target_object_type or "")[:_TARGET_OBJECT_TYPE_LEN].strip() or None
    ip = (ip_address[: _IP_LEN] if ip_address else None) or None
    ua = (str(user_agent)[: _USER_AGENT_LEN] if user_agent else None) or None
    safe_meta = _sanitize_meta(meta)
    safe_prev = _sanitize_meta(previous_value)
    safe_new = _sanitize_meta(new_value)

    entry = EventLedger(
        action_type=action,
        target_object_type=target_type,
        target_object_id=target_object_id,
        property_id=property_id,
        unit_id=unit_id,
        stay_id=stay_id,
        invitation_id=invitation_id,
        actor_user_id=actor_user_id,
        previous_value=safe_prev,
        new_value=safe_new,
        meta=safe_meta,
        ip_address=ip,
        user_agent=ua,
    )
    db.add(entry)
    db.flush()
    return entry
