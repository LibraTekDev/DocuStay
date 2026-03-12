"""Permission helpers for role-based access control. All checks are property/unit-scoped.

KEY RULE: Ask "What lane does this data belong to?" — not "Who owns the property?"
Permissions follow the lane (property/management, tenant, guest), not ownership status.
Ownership does NOT override privacy scope. Tenant-invited guest data stays in tenant lane.

Permission structure: User + Property/Unit + Role + Mode + Action
- User: the authenticated user
- Property/Unit: the resource being accessed
- Role: owner, property_manager, tenant, guest
- Mode: business (portfolio/management) or personal (resident)
- Action: the requested operation (VIEW_BILLING, INVITE_GUEST, SET_PRESENCE, etc.)

Personal vs Business Mode: Users can switch modes, but privacy rules still apply.
Switching to personal mode does NOT unlock tenant-private information.
"""
from enum import Enum
from sqlalchemy.orm import Session
from app.models.user import User, UserRole
from app.models.owner import OwnerProfile, Property, OccupancyStatus
from app.models.unit import Unit
from app.models.property_manager_assignment import PropertyManagerAssignment
from app.models.tenant_assignment import TenantAssignment
from app.models.resident_mode import ResidentMode
from app.models.resident_mode import ResidentModeType


class Action(str, Enum):
    """Actions that can be evaluated against User + Property/Unit + Role + Mode."""
    VIEW_BILLING = "view_billing"
    MODIFY_BILLING = "modify_billing"
    INVITE_GUEST = "invite_guest"
    SET_PRESENCE = "set_presence"
    VIEW_LOGS = "view_logs"
    CONFIRM_OCCUPANCY = "confirm_occupancy"
    CONFIRM_VACANT = "confirm_vacant"
    REVOKE_STAY = "revoke_stay"
    INITIATE_REMOVAL = "initiate_removal"
    VIEW_TENANT_GUEST_HISTORY = "view_tenant_guest_history"
    INVITE_TENANT = "invite_tenant"


def can_perform_action(
    db: Session,
    user: User,
    action: Action,
    property_id: int | None = None,
    unit_id: int | None = None,
    mode: str = "business",
) -> bool:
    """Evaluate User + Property/Unit + Role + Mode + Action. Returns True if allowed."""
    if action == Action.VIEW_BILLING:
        if user.role == UserRole.owner:
            return db.query(OwnerProfile).filter(OwnerProfile.user_id == user.id).first() is not None
        if user.role == UserRole.property_manager:
            if property_id is None:
                return False
            return db.query(PropertyManagerAssignment).filter(
                PropertyManagerAssignment.property_id == property_id,
                PropertyManagerAssignment.user_id == user.id,
            ).first() is not None
        return False

    if action == Action.MODIFY_BILLING:
        if user.role != UserRole.owner:
            return False
        return db.query(OwnerProfile).filter(OwnerProfile.user_id == user.id).first() is not None

    if action == Action.INVITE_GUEST:
        if unit_id is None:
            return False
        return can_invite_guest(db, user, unit_id, mode)

    if action == Action.SET_PRESENCE:
        if unit_id is None:
            return False
        # Only personal mode: Tenant OR (Owner/Manager + personal + unit access)
        if user.role == UserRole.tenant:
            return db.query(TenantAssignment).filter(
                TenantAssignment.unit_id == unit_id,
                TenantAssignment.user_id == user.id,
            ).first() is not None
        return can_access_unit(db, user, unit_id, "personal")

    if action == Action.VIEW_LOGS:
        if property_id is None:
            return False
        return can_view_audit_logs(db, user, property_id)

    if action in (Action.CONFIRM_OCCUPANCY, Action.CONFIRM_VACANT, Action.REVOKE_STAY, Action.INITIATE_REMOVAL):
        # Stay-scoped: use can_confirm_occupancy or similar at endpoint with stay object
        return False

    if action == Action.VIEW_TENANT_GUEST_HISTORY:
        pid = property_id
        if pid is None and unit_id is not None:
            unit = db.query(Unit).filter(Unit.id == unit_id).first()
            pid = unit.property_id if unit else None
        if pid is None:
            return False
        return can_access_property(db, user, pid, "business") and user.role in (
            UserRole.owner,
            UserRole.property_manager,
        )

    if action == Action.INVITE_TENANT:
        if property_id is None:
            return False
        return can_access_property(db, user, property_id, "business") and user.role in (
            UserRole.owner,
            UserRole.property_manager,
        )

    return False


def can_access_property(db: Session, user: User, property_id: int, mode: str = "business") -> bool:
    """True if user can access this property in the given mode."""
    if user.role == UserRole.owner:
        profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == user.id).first()
        if not profile:
            return False
        prop = db.query(Property).filter(
            Property.id == property_id,
            Property.owner_profile_id == profile.id,
            Property.deleted_at.is_(None),
        ).first()
        return prop is not None
    if user.role == UserRole.property_manager:
        if mode == "business":
            return db.query(PropertyManagerAssignment).filter(
                PropertyManagerAssignment.property_id == property_id,
                PropertyManagerAssignment.user_id == user.id,
            ).first() is not None
        if mode == "personal":
            # Manager personal mode: must have ResidentMode for a unit in this property
            unit = db.query(Unit).filter(Unit.property_id == property_id).first()
            if not unit:
                return False
            return db.query(ResidentMode).filter(
                ResidentMode.unit_id == unit.id,
                ResidentMode.user_id == user.id,
                ResidentMode.mode == ResidentModeType.manager_personal,
            ).first() is not None
    if user.role == UserRole.tenant:
        # Tenant can only access property via their assigned unit
        ta = db.query(TenantAssignment).join(Unit).filter(
            TenantAssignment.user_id == user.id,
            Unit.property_id == property_id,
        ).first()
        return ta is not None
    return False


def can_access_unit(db: Session, user: User, unit_id: int, mode: str = "business") -> bool:
    """True if user can access this unit in the given mode."""
    unit = db.query(Unit).filter(Unit.id == unit_id).first()
    if not unit:
        return False
    if user.role == UserRole.owner:
        profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == user.id).first()
        if not profile:
            return False
        prop = db.query(Property).filter(
            Property.id == unit.property_id,
            Property.owner_profile_id == profile.id,
        ).first()
        if prop:
            return True
        # Owner in personal mode: must have ResidentMode for this unit
        if mode == "personal":
            return db.query(ResidentMode).filter(
                ResidentMode.unit_id == unit_id,
                ResidentMode.user_id == user.id,
                ResidentMode.mode == ResidentModeType.owner_personal,
            ).first() is not None
        return False
    if user.role == UserRole.property_manager:
        if mode == "business":
            return db.query(PropertyManagerAssignment).filter(
                PropertyManagerAssignment.property_id == unit.property_id,
                PropertyManagerAssignment.user_id == user.id,
            ).first() is not None
        if mode == "personal":
            return db.query(ResidentMode).filter(
                ResidentMode.unit_id == unit_id,
                ResidentMode.user_id == user.id,
                ResidentMode.mode == ResidentModeType.manager_personal,
            ).first() is not None
    if user.role == UserRole.tenant:
        return db.query(TenantAssignment).filter(
            TenantAssignment.unit_id == unit_id,
            TenantAssignment.user_id == user.id,
        ).first() is not None
    return False


def can_invite_guest(db: Session, user: User, unit_id: int, mode: str = "business") -> bool:
    """True if user can invite guests for this unit (owner, manager in personal mode, or tenant)."""
    return can_access_unit(db, user, unit_id, mode)


def can_modify_billing(db: Session, user: User, owner_profile_id: int) -> bool:
    """True only for owners who own this profile. Property managers cannot modify billing."""
    if user.role != UserRole.owner:
        return False
    profile = db.query(OwnerProfile).filter(
        OwnerProfile.id == owner_profile_id,
        OwnerProfile.user_id == user.id,
    ).first()
    return profile is not None


def can_assign_property_manager(db: Session, user: User, property_id: int) -> bool:
    """True only for owners who own this property."""
    return can_access_property(db, user, property_id, "business") and user.role == UserRole.owner


def can_confirm_occupancy(db: Session, user: User, stay) -> bool:
    """True if user can confirm occupancy for this stay (owner or assigned manager)."""
    if user.role == UserRole.owner:
        return stay.owner_id == user.id
    if user.role == UserRole.property_manager:
        return db.query(PropertyManagerAssignment).filter(
            PropertyManagerAssignment.property_id == stay.property_id,
            PropertyManagerAssignment.user_id == user.id,
        ).first() is not None
    return False


def can_view_audit_logs(db: Session, user: User, property_id: int) -> bool:
    """True for owners and assigned property managers."""
    if user.role == UserRole.owner:
        return can_access_property(db, user, property_id, "business")
    if user.role == UserRole.property_manager:
        return db.query(PropertyManagerAssignment).filter(
            PropertyManagerAssignment.property_id == property_id,
            PropertyManagerAssignment.user_id == user.id,
        ).first() is not None
    return False


def get_owner_personal_mode_units(db: Session, user_id: int) -> list[int]:
    """Return unit IDs where this owner can set presence (here/away) in Personal Mode.
    Includes units from ALL properties the owner owns. Owners can mark stay/away for any property."""
    unit_ids: list[int] = []
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == user_id).first()
    if not profile:
        return []

    # From explicit ResidentMode (in case any exist)
    resident_rows = db.query(ResidentMode.unit_id).filter(
        ResidentMode.user_id == user_id,
        ResidentMode.mode == ResidentModeType.owner_personal,
    ).all()
    for (u_id,) in resident_rows:
        unit_ids.append(u_id)

    # From ALL owned properties (owner can set presence for any property)
    owned_props = (
        db.query(Property)
        .filter(
            Property.owner_profile_id == profile.id,
            Property.deleted_at.is_(None),
        )
        .all()
    )
    for prop in owned_props:
        units = db.query(Unit.id).filter(Unit.property_id == prop.id).all()
        if units:
            for (u_id,) in units:
                unit_ids.append(u_id)
        elif not prop.is_multi_unit:
            # Single-unit: no Unit row exists; create one for Personal Mode
            u = Unit(
                property_id=prop.id,
                unit_label="1",
                occupancy_status=prop.occupancy_status or OccupancyStatus.unknown.value,
            )
            db.add(u)
            db.flush()
            unit_ids.append(u.id)

    return list(dict.fromkeys(unit_ids))  # preserve order, dedupe


def get_manager_personal_mode_units(db: Session, user_id: int) -> list[int]:
    """Return unit IDs where this property manager has Personal Mode (lives on-site)."""
    rows = db.query(ResidentMode.unit_id).filter(
        ResidentMode.user_id == user_id,
        ResidentMode.mode == ResidentModeType.manager_personal,
    ).all()
    return [r[0] for r in rows]
