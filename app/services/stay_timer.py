"""Module G: Stay Timer & Legal Notification Engine + Dead Man's Switch."""
from datetime import date, timedelta, datetime, timezone
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.stay import Stay
from app.models.user import User
from app.models.region_rule import RegionRule
from app.models.audit_log import AuditLog
from app.models.owner import Property, USAT_TOKEN_STAGED, USAT_TOKEN_RELEASED, OccupancyStatus
from app.services.notifications import (
    send_stay_legal_warning,
    send_overstay_alert,
    send_dead_mans_switch_48h_before,
    send_dead_mans_switch_urgent_today,
    send_dead_mans_switch_auto_executed,
    send_shield_mode_activated_email,
)
from app.services.audit_log import create_log, CATEGORY_STATUS_CHANGE, CATEGORY_SHIELD_MODE, CATEGORY_DEAD_MANS_SWITCH
from app.config import get_settings

settings = get_settings()

# Dead Man's Switch audit titles (for idempotency)
DMS_TITLE_48H_BEFORE = "Dead Man's Switch: 48h before lease end"
DMS_TITLE_URGENT_TODAY = "Dead Man's Switch: urgent – lease ends today"
DMS_TITLE_AUTO_EXECUTED = "Dead Man's Switch: auto-executed"
SHIELD_ACTIVATED_LAST_DAY = "Shield Mode activated (last day of stay)"


def get_overstays(db: Session) -> list[Stay]:
    """Stays whose end date has passed and guest has not checked out or cancelled (overstay)."""
    today = date.today()
    return db.query(Stay).filter(
        Stay.stay_end_date < today,
        Stay.checked_out_at.is_(None),
        Stay.cancelled_at.is_(None),
    ).all()


def send_overstay_alerts_and_log(db: Session) -> None:
    """For each overstay not yet logged: email owner and guest, then append audit log."""
    from app.models.guest import GuestProfile

    overstays = get_overstays(db)
    for stay in overstays:
        # Only act once per stay: skip if we already logged this overstay
        existing = (
            db.query(AuditLog)
            .filter(
                AuditLog.stay_id == stay.id,
                AuditLog.title == "Overstay occurred",
            )
            .first()
        )
        if existing:
            continue

        owner = db.query(User).filter(User.id == stay.owner_id).first()
        guest = db.query(User).filter(User.id == stay.guest_id).first()
        prop = db.query(Property).filter(Property.id == stay.property_id).first()
        if not owner or not guest:
            continue

        guest_profile = db.query(GuestProfile).filter(GuestProfile.user_id == stay.guest_id).first()
        guest_name = (guest_profile.full_legal_name if guest_profile else None) or guest.full_name or guest.email
        property_name = "Property"
        if prop:
            property_name = (prop.name or "").strip() or (f"{prop.city}, {prop.state}".strip(", ") if (prop.city or prop.state) else "Property")
        end_str = stay.stay_end_date.isoformat()

        try:
            send_overstay_alert(
                owner.email,
                guest_name=guest_name,
                stay_end_date=end_str,
                region_code=stay.region_code or "",
                is_owner=True,
                property_name=property_name,
            )
            send_overstay_alert(
                guest.email,
                guest_name=guest_name,
                stay_end_date=end_str,
                region_code=stay.region_code or "",
                is_owner=False,
                property_name=property_name,
            )
        except Exception:
            pass

        create_log(
            db,
            CATEGORY_STATUS_CHANGE,
            "Overstay occurred",
            f"Overstay detected: stay {stay.id}, property {stay.property_id}, guest {guest_name}, end date was {end_str}. Emails sent to owner and guest.",
            property_id=stay.property_id,
            stay_id=stay.id,
            actor_email=None,
            meta={"guest_id": stay.guest_id, "owner_id": stay.owner_id, "stay_end_date": end_str},
        )
        db.commit()


def get_stays_approaching_limit(db: Session, days_before: int | None = None) -> list[Stay]:
    """Stays whose end date is within days_before (default from config) or on final day."""
    days = days_before if days_before is not None else settings.notification_days_before_limit
    threshold = date.today() + timedelta(days=days)
    return db.query(Stay).filter(
        Stay.stay_end_date >= date.today(),
        Stay.stay_end_date <= threshold,
    ).all()


def send_legal_warnings_for_stay(stay: Stay, db: Session, statute_ref: str) -> None:
    """Send email to owner and guest with legal warning (Module G)."""
    from app.models.guest import GuestProfile

    owner = db.query(User).filter(User.id == stay.owner_id).first()
    guest = db.query(User).filter(User.id == stay.guest_id).first()
    if not owner or not guest:
        return
    gp = db.query(GuestProfile).filter(GuestProfile.user_id == stay.guest_id).first()
    guest_name = gp.full_legal_name if gp else guest.email

    end_str = stay.stay_end_date.isoformat()
    send_stay_legal_warning(
        owner.email,
        guest_name=guest_name,
        stay_end_date=end_str,
        region_code=stay.region_code,
        statute_ref=statute_ref,
        is_owner=True,
    )
    send_stay_legal_warning(
        guest.email,
        guest_name=guest_name,
        stay_end_date=end_str,
        region_code=stay.region_code,
        statute_ref=statute_ref,
        is_owner=False,
    )


def _dms_already_logged(
    db: Session,
    title: str,
    stay_id: int | None = None,
    property_id: int | None = None,
    since_date: date | None = None,
) -> bool:
    """Return True if we already logged this event (for this stay or this property, optionally since date)."""
    q = db.query(AuditLog).filter(AuditLog.title == title)
    if stay_id is not None:
        q = q.filter(AuditLog.stay_id == stay_id)
    if property_id is not None:
        q = q.filter(AuditLog.property_id == property_id)
    if since_date is not None:
        from datetime import time as dt_time
        start_of_day = datetime.combine(since_date, dt_time.min).replace(tzinfo=timezone.utc)
        q = q.filter(AuditLog.created_at >= start_of_day)
    return q.first() is not None


def _get_guest_name(db: Session, stay: Stay) -> str:
    from app.models.guest import GuestProfile
    owner = db.query(User).filter(User.id == stay.owner_id).first()
    guest = db.query(User).filter(User.id == stay.guest_id).first()
    if not guest:
        return "Guest"
    gp = db.query(GuestProfile).filter(GuestProfile.user_id == stay.guest_id).first()
    return (gp.full_legal_name if gp else None) or (guest.full_name or "") or guest.email or "Guest"


def _get_property_name(db: Session, prop: Property | None) -> str:
    if not prop:
        return "Property"
    return (prop.name or "").strip() or (f"{prop.city}, {prop.state}".strip(", ") if (prop.city or prop.state) else "Property")


def run_dead_mans_switch_job(db: Session) -> None:
    """Dead Man's Switch: 48h before alert, today alert, 48h after auto-execute."""
    today = date.today()
    two_days_later = today + timedelta(days=2)
    two_days_ago = today - timedelta(days=2)

    # Stays with DMS enabled (integer 1)
    def dms_enabled(s: Stay) -> bool:
        return getattr(s, "dead_mans_switch_enabled", 0) == 1

    def alert_email(s: Stay) -> bool:
        return getattr(s, "dead_mans_switch_alert_email", 1) == 1

    # 1) 48 hours before lease end
    for stay in (
        db.query(Stay)
        .filter(
            Stay.stay_end_date == two_days_later,
            Stay.checked_out_at.is_(None),
            Stay.cancelled_at.is_(None),
        )
        .all()
    ):
        if not dms_enabled(stay) or _dms_already_logged(db, DMS_TITLE_48H_BEFORE, stay_id=stay.id):
            continue
        owner = db.query(User).filter(User.id == stay.owner_id).first()
        prop = db.query(Property).filter(Property.id == stay.property_id).first()
        if not owner or not alert_email(stay):
            continue
        try:
            send_dead_mans_switch_48h_before(
                owner.email,
                _get_guest_name(db, stay),
                _get_property_name(db, prop),
                stay.stay_end_date.isoformat(),
            )
        except Exception:
            pass
        create_log(
            db,
            CATEGORY_DEAD_MANS_SWITCH,
            DMS_TITLE_48H_BEFORE,
            f"Stay {stay.id}: 48h before lease end alert sent to owner.",
            property_id=stay.property_id,
            stay_id=stay.id,
            meta={"guest_id": stay.guest_id, "owner_id": stay.owner_id},
        )
        db.commit()

    # 1.5) Last day of guest's stay: activate Shield Mode for the property (any stay ending today)
    stays_ending_today = (
        db.query(Stay)
        .filter(
            Stay.stay_end_date == today,
            Stay.checked_out_at.is_(None),
            Stay.cancelled_at.is_(None),
        )
        .all()
    )
    property_ids_ending_today = {s.property_id for s in stays_ending_today}
    for prop_id in property_ids_ending_today:
        prop = db.query(Property).filter(Property.id == prop_id).first()
        if not prop or getattr(prop, "shield_mode_enabled", 0) == 1:
            continue
        if _dms_already_logged(db, SHIELD_ACTIVATED_LAST_DAY, property_id=prop_id, since_date=today):
            continue
        stay_for_prop = next((s for s in stays_ending_today if s.property_id == prop_id), None)
        if not stay_for_prop:
            continue
        owner = db.query(User).filter(User.id == stay_for_prop.owner_id).first()
        prop.shield_mode_enabled = 1
        db.add(prop)
        create_log(
            db,
            CATEGORY_SHIELD_MODE,
            SHIELD_ACTIVATED_LAST_DAY,
            f"Shield Mode activated for property {prop_id} (last day of stay {stay_for_prop.id}).",
            property_id=prop_id,
            stay_id=stay_for_prop.id,
            meta={"owner_id": stay_for_prop.owner_id},
        )
        db.commit()
        if owner:
            try:
                send_shield_mode_activated_email(
                    owner.email,
                    _get_property_name(db, prop),
                    last_day_of_stay=True,
                    guest_name=_get_guest_name(db, stay_for_prop),
                )
            except Exception:
                pass

    # 2) Lease end date = today (urgent)
    for stay in (
        db.query(Stay)
        .filter(
            Stay.stay_end_date == today,
            Stay.checked_out_at.is_(None),
            Stay.cancelled_at.is_(None),
        )
        .all()
    ):
        if not dms_enabled(stay) or _dms_already_logged(db, DMS_TITLE_URGENT_TODAY, stay_id=stay.id):
            continue
        owner = db.query(User).filter(User.id == stay.owner_id).first()
        prop = db.query(Property).filter(Property.id == stay.property_id).first()
        if not owner or not alert_email(stay):
            continue
        try:
            send_dead_mans_switch_urgent_today(
                owner.email,
                _get_guest_name(db, stay),
                _get_property_name(db, prop),
                stay.stay_end_date.isoformat(),
            )
        except Exception:
            pass
        create_log(
            db,
            CATEGORY_DEAD_MANS_SWITCH,
            DMS_TITLE_URGENT_TODAY,
            f"Stay {stay.id}: urgent lease-ends-today alert sent to owner.",
            property_id=stay.property_id,
            stay_id=stay.id,
            meta={"guest_id": stay.guest_id, "owner_id": stay.owner_id},
        )
        db.commit()

    # 3) 48 hours after lease end – flip to UNCONFIRMED (no auto-checkout; silence is forensic evidence)
    for stay in (
        db.query(Stay)
        .filter(
            Stay.stay_end_date <= two_days_ago,
            Stay.checked_out_at.is_(None),
            Stay.cancelled_at.is_(None),
        )
        .all()
    ):
        if not dms_enabled(stay):
            continue
        # Skip if owner already confirmed (vacated, renewed, holdover)
        if getattr(stay, "occupancy_confirmation_response", None) is not None:
            continue
        if getattr(stay, "dead_mans_switch_triggered_at", None) is not None:
            continue
        if _dms_already_logged(db, DMS_TITLE_AUTO_EXECUTED, stay_id=stay.id):
            continue

        owner = db.query(User).filter(User.id == stay.owner_id).first()
        prop = db.query(Property).filter(Property.id == stay.property_id).first()
        guest_name = _get_guest_name(db, stay)
        property_name = _get_property_name(db, prop)
        now = datetime.now(timezone.utc)

        # Mark DMS as triggered (no owner response) – do NOT set checked_out_at
        stay.dead_mans_switch_triggered_at = now
        db.add(stay)

        # Flip property to UNCONFIRMED (recorded silence = forensic evidence)
        prev_status = "unknown"
        if prop:
            prev_status = getattr(prop, "occupancy_status", None) or "unknown"
            prop.occupancy_status = OccupancyStatus.unconfirmed.value
            if prop.usat_token_state == USAT_TOKEN_RELEASED:
                prop.usat_token_state = USAT_TOKEN_STAGED
                prop.usat_token_released_at = None
            prop.shield_mode_enabled = 1
            db.add(prop)

        create_log(
            db,
            CATEGORY_DEAD_MANS_SWITCH,
            DMS_TITLE_AUTO_EXECUTED,
            f"Stay {stay.id}: No owner response by deadline. Occupancy status flipped {prev_status} -> unconfirmed (recorded silence). Utility lock activated; Shield Mode on.",
            property_id=stay.property_id,
            stay_id=stay.id,
            meta={
                "guest_id": stay.guest_id,
                "owner_id": stay.owner_id,
                "stay_end_date": stay.stay_end_date.isoformat(),
                "occupancy_status_previous": prev_status,
                "occupancy_status_new": OccupancyStatus.unconfirmed.value,
                "utility_lock_activated": True,
            },
        )
        db.commit()

        if owner and alert_email(stay):
            try:
                send_dead_mans_switch_auto_executed(
                    owner.email,
                    guest_name,
                    property_name,
                    stay.stay_end_date.isoformat(),
                )
                send_shield_mode_activated_email(
                    owner.email,
                    property_name,
                    triggered_by_dead_mans_switch=True,
                )
            except Exception:
                pass


def run_stay_notification_job() -> None:
    """Run once per day (or on demand): find stays approaching limit, send emails; then detect overstays, email owner+guest and log; then Dead Man's Switch."""
    if not settings.notification_cron_enabled:
        return
    db = SessionLocal()
    try:
        stays = get_stays_approaching_limit(db)
        for stay in stays:
            rule = db.query(RegionRule).filter(RegionRule.region_code == stay.region_code).first()
            statute_ref = rule.statute_reference if rule else stay.region_code
            send_legal_warnings_for_stay(stay, db, statute_ref or stay.region_code)
        send_overstay_alerts_and_log(db)
        run_dead_mans_switch_job(db)
    finally:
        db.close()
