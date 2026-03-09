"""Shared occupancy logic for owner and manager views.

Units are considered effectively "occupied" when:
- the unit's stored occupancy_status is "occupied", or
- the unit has an on-site resident (ResidentMode with manager_personal).

This ensures both owner and manager see the same status for units where
a property manager is assigned as on-site resident.
"""
from datetime import date
from sqlalchemy.orm import Session

from app.models.owner import OccupancyStatus
from app.models.resident_mode import ResidentMode, ResidentModeType
from app.models.unit import Unit
from app.models.stay import Stay
from app.models.invitation import Invitation
from app.models.user import User
from app.models.tenant_assignment import TenantAssignment


def is_unit_effectively_occupied(db: Session, unit: Unit) -> bool:
    """True if the unit is occupied (stored status) or has an on-site resident (ResidentMode)."""
    if (unit.occupancy_status or "").lower() == OccupancyStatus.occupied.value:
        return True
    return (
        db.query(ResidentMode)
        .filter(
            ResidentMode.unit_id == unit.id,
            ResidentMode.mode == ResidentModeType.manager_personal,
        )
        .first()
        is not None
    )


def get_unit_display_occupancy_status(db: Session, unit: Unit) -> str:
    """Return the occupancy status to display for a unit (owner or manager view)."""
    if (unit.occupancy_status or "").lower() == OccupancyStatus.occupied.value:
        return OccupancyStatus.occupied.value
    if (
        db.query(ResidentMode)
        .filter(
            ResidentMode.unit_id == unit.id,
            ResidentMode.mode == ResidentModeType.manager_personal,
        )
        .first()
        is not None
    ):
        return OccupancyStatus.occupied.value
    return unit.occupancy_status or OccupancyStatus.unknown.value


def count_effectively_occupied_units(db: Session, units: list[Unit]) -> int:
    """Count how many units are effectively occupied (stored or on-site resident)."""
    return sum(1 for u in units if is_unit_effectively_occupied(db, u))


def get_property_display_occupancy_status(
    db: Session, prop, units: list[Unit]
) -> str:
    """Return property-level occupancy status for display (occupied if any unit is effectively occupied)."""
    if not units:
        return prop.occupancy_status or OccupancyStatus.unknown.value
    occupied_count = count_effectively_occupied_units(db, units)
    if occupied_count > 0:
        return OccupancyStatus.occupied.value
    return prop.occupancy_status or OccupancyStatus.unknown.value


def get_units_occupancy_display(
    db: Session, unit_ids: list[int]
) -> dict[int, dict]:
    """
    For each unit_id, return { "occupied_by": str | None, "invite_id": str | None }.
    Priority: active guest stay (with invite_id) > pending invitation > property manager resident > tenant.
    """
    if not unit_ids:
        return {}
    today = date.today()
    out = {uid: {"occupied_by": None, "invite_id": None} for uid in unit_ids}

    # Active stays (guest checked in, not out, not cancelled)
    stays = (
        db.query(Stay)
        .filter(
            Stay.unit_id.in_(unit_ids),
            Stay.checked_in_at.isnot(None),
            Stay.checked_out_at.is_(None),
            Stay.cancelled_at.is_(None),
        )
        .all()
    )
    inv_ids = [s.invitation_id for s in stays if s.invitation_id]
    invitations_by_id = {}
    if inv_ids:
        invs = db.query(Invitation).filter(Invitation.id.in_(inv_ids)).all()
        invitations_by_id = {i.id: i for i in invs}
    guest_user_ids = list({s.guest_id for s in stays})
    users_by_id = {}
    if guest_user_ids:
        users = db.query(User).filter(User.id.in_(guest_user_ids)).all()
        users_by_id = {u.id: u for u in users}
    for s in stays:
        if s.unit_id not in out:
            continue
        inv = invitations_by_id.get(s.invitation_id) if s.invitation_id else None
        guest_user = users_by_id.get(s.guest_id)
        name = None
        if inv:
            name = (inv.guest_name or "").strip()
        if not name and guest_user:
            name = (guest_user.full_name or "").strip() or guest_user.email
        if not name:
            name = "Guest"
        out[s.unit_id] = {
            "occupied_by": name,
            "invite_id": inv.invitation_code if inv else None,
        }

    # Pending invitations (STAGED) for units not yet filled by a stay
    still_empty = [uid for uid in unit_ids if out[uid]["occupied_by"] is None]
    if still_empty:
        invs = (
            db.query(Invitation)
            .filter(
                Invitation.unit_id.in_(still_empty),
                Invitation.token_state == "STAGED",
            )
            .all()
        )
        for inv in invs:
            if inv.unit_id not in out or out[inv.unit_id]["occupied_by"] is not None:
                continue
            name = (inv.guest_name or "").strip() or "Guest (pending)"
            out[inv.unit_id] = {"occupied_by": name, "invite_id": inv.invitation_code}

    # Property manager on-site resident
    still_empty = [uid for uid in unit_ids if out[uid]["occupied_by"] is None]
    if still_empty:
        modes = (
            db.query(ResidentMode)
            .filter(
                ResidentMode.unit_id.in_(still_empty),
                ResidentMode.mode == ResidentModeType.manager_personal,
            )
            .all()
        )
        manager_ids = list({m.user_id for m in modes})
        users_by_id = {}
        if manager_ids:
            users = db.query(User).filter(User.id.in_(manager_ids)).all()
            users_by_id = {u.id: u for u in users}
        for m in modes:
            if m.unit_id not in out or out[m.unit_id]["occupied_by"] is not None:
                continue
            u = users_by_id.get(m.user_id)
            base = (u.full_name or "").strip() or (u.email if u else "") or "Property manager"
            name = f"{base} (Property manager)" if "(Property manager)" not in base else base
            out[m.unit_id] = {"occupied_by": name, "invite_id": None}

    # Tenant assignment (current: end_date null or >= today)
    still_empty = [uid for uid in unit_ids if out[uid]["occupied_by"] is None]
    if still_empty:
        from sqlalchemy import or_

        assignments = (
            db.query(TenantAssignment)
            .filter(
                TenantAssignment.unit_id.in_(still_empty),
                or_(
                    TenantAssignment.end_date.is_(None),
                    TenantAssignment.end_date >= today,
                ),
            )
            .all()
        )
        tenant_ids = list({a.user_id for a in assignments})
        users_by_id = {}
        if tenant_ids:
            users = db.query(User).filter(User.id.in_(tenant_ids)).all()
            users_by_id = {u.id: u for u in users}
        for a in assignments:
            if a.unit_id not in out or out[a.unit_id]["occupied_by"] is not None:
                continue
            u = users_by_id.get(a.user_id)
            name = (u.full_name or "").strip() or (u.email if u else "Tenant")
            out[a.unit_id] = {"occupied_by": name, "invite_id": None}

    return out
