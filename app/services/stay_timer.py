"""Module G: Stay Timer & Legal Notification Engine + Dead Man's Switch."""
import logging
from datetime import date, timedelta, datetime, timezone
from sqlalchemy.orm import Session

logger = logging.getLogger("uvicorn.error")
from app.database import SessionLocal
from app.models.stay import Stay
from app.models.user import User
from app.models.region_rule import RegionRule
from app.models.audit_log import AuditLog
from app.models.owner import OwnerProfile, Property, USAT_TOKEN_STAGED, USAT_TOKEN_RELEASED, OccupancyStatus
from app.services.notifications import (
    send_stay_legal_warning,
    send_overstay_alert,
    send_dead_mans_switch_48h_before,
    send_dead_mans_switch_urgent_today,
    send_dead_mans_switch_auto_executed,
    send_shield_mode_activated_email,
    send_vacant_monitoring_prompt,
    send_vacant_monitoring_flipped,
)
from app.services.audit_log import create_log, CATEGORY_STATUS_CHANGE, CATEGORY_SHIELD_MODE, CATEGORY_DEAD_MANS_SWITCH
from app.services.event_ledger import create_ledger_event, ACTION_OVERSTAY_OCCURRED, ACTION_DMS_48H_ALERT, ACTION_DMS_AUTO_EXECUTED, ACTION_SHIELD_MODE_ON, ACTION_VACANT_MONITORING_NO_RESPONSE
from app.services.billing import sync_subscription_quantities
from app.config import get_settings

settings = get_settings()

# Dead Man's Switch audit titles (for idempotency)
DMS_TITLE_48H_BEFORE = "Dead Man's Switch: 48h before lease end"
DMS_TITLE_URGENT_TODAY = "Dead Man's Switch: urgent – lease ends today"
DMS_TITLE_AUTO_EXECUTED = "Dead Man's Switch: auto-executed"
SHIELD_ACTIVATED_LAST_DAY = "Shield Mode activated (last day of stay)"
# Test mode: effective "lease end" = stay created_at + this duration (invite acceptance = stay creation)
DMS_TEST_MODE_MINUTES_AFTER_CREATE = 2


def get_overstays(db: Session) -> list[Stay]:
    """Stays whose end date has passed and guest has not checked out or cancelled (overstay). Only includes stays that have been checked into."""
    today = date.today()
    return db.query(Stay).filter(
        Stay.checked_in_at.isnot(None),
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
        create_ledger_event(
            db,
            ACTION_OVERSTAY_OCCURRED,
            target_object_type="Stay",
            target_object_id=stay.id,
            property_id=stay.property_id,
            stay_id=stay.id,
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


def _ensure_utc(dt: datetime | None) -> datetime | None:
    """Return datetime with UTC tzinfo; if naive, assume UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _run_dead_mans_switch_job_test_mode(db: Session) -> None:
    """DMS test mode: effective lease end = checked_in_at + 2 min (if set), else created_at + 2 min. 48h before / urgent / auto-execute use that window."""
    now = datetime.now(timezone.utc)
    effective_end_delta = timedelta(minutes=DMS_TEST_MODE_MINUTES_AFTER_CREATE)
    urgent_window_before_end = timedelta(minutes=1)  # "urgent" = last 1 min before effective end

    def dms_enabled(s: Stay) -> bool:
        return getattr(s, "dead_mans_switch_enabled", 0) == 1

    def alert_email(s: Stay) -> bool:
        return getattr(s, "dead_mans_switch_alert_email", 1) == 1

    stays = (
        db.query(Stay)
        .filter(
            Stay.checked_out_at.is_(None),
            Stay.cancelled_at.is_(None),
        )
        .all()
    )
    dms_stays = [s for s in stays if dms_enabled(s)]
    logger.info("DMS job (test mode): started, %d total stays, %d with DMS on", len(stays), len(dms_stays))
    for stay in stays:
        if not dms_enabled(stay):
            continue
        # Prefer checked_in_at + 2 min (when testing via check-in flow); else created_at + 2 min (accept-invite flow)
        checked_in_at = getattr(stay, "checked_in_at", None)
        if checked_in_at:
            base_dt = _ensure_utc(checked_in_at)
        else:
            created_at = getattr(stay, "created_at", None)
            if not created_at:
                continue
            base_dt = _ensure_utc(created_at)
        effective_end_dt = base_dt + effective_end_delta
        effective_end_date_str = effective_end_dt.date().isoformat()

        # 1) 48h before (test: before effective end, send once)
        if now < effective_end_dt and not _dms_already_logged(db, DMS_TITLE_48H_BEFORE, stay_id=stay.id):
            owner = db.query(User).filter(User.id == stay.owner_id).first()
            prop = db.query(Property).filter(Property.id == stay.property_id).first()
            if owner and alert_email(stay):
                try:
                    send_dead_mans_switch_48h_before(
                        owner.email,
                        _get_guest_name(db, stay),
                        _get_property_name(db, prop),
                        effective_end_date_str,
                    )
                except Exception:
                    pass
                create_log(
                    db,
                    CATEGORY_DEAD_MANS_SWITCH,
                    DMS_TITLE_48H_BEFORE,
                    f"Stay {stay.id}: 48h before (test mode, effective end {effective_end_date_str}) alert sent to owner.",
                    property_id=stay.property_id,
                    stay_id=stay.id,
                    meta={"guest_id": stay.guest_id, "owner_id": stay.owner_id, "dms_test_mode": True},
                )
                db.commit()

        # 2) Urgent today (test: last minute before effective end)
        if (
            effective_end_dt - urgent_window_before_end <= now < effective_end_dt
            and not _dms_already_logged(db, DMS_TITLE_URGENT_TODAY, stay_id=stay.id)
        ):
            owner = db.query(User).filter(User.id == stay.owner_id).first()
            prop = db.query(Property).filter(Property.id == stay.property_id).first()
            if owner and alert_email(stay):
                try:
                    send_dead_mans_switch_urgent_today(
                        owner.email,
                        _get_guest_name(db, stay),
                        _get_property_name(db, prop),
                        effective_end_date_str,
                    )
                except Exception:
                    pass
                create_log(
                    db,
                    CATEGORY_DEAD_MANS_SWITCH,
                    DMS_TITLE_URGENT_TODAY,
                    f"Stay {stay.id}: urgent (test mode, effective end {effective_end_date_str}) alert sent to owner.",
                    property_id=stay.property_id,
                    stay_id=stay.id,
                    meta={"guest_id": stay.guest_id, "owner_id": stay.owner_id, "dms_test_mode": True},
                )
                db.commit()

        # 3) Auto-execute after effective end (test: 2 min after create)
        if now < effective_end_dt:
            continue
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

        stay.dead_mans_switch_triggered_at = now
        db.add(stay)

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
            f"Stay {stay.id}: No owner response by deadline (test mode, effective end {effective_end_date_str}). Occupancy status flipped {prev_status} -> unconfirmed.",
            property_id=stay.property_id,
            stay_id=stay.id,
            meta={
                "guest_id": stay.guest_id,
                "owner_id": stay.owner_id,
                "stay_end_date": effective_end_date_str,
                "occupancy_status_previous": prev_status,
                "occupancy_status_new": OccupancyStatus.unconfirmed.value,
                "utility_lock_activated": True,
                "dms_test_mode": True,
            },
        )
        db.commit()
        try:
            if prop:
                profile = db.query(OwnerProfile).filter(OwnerProfile.id == prop.owner_profile_id).first()
                if profile:
                    sync_subscription_quantities(db, profile)
        except Exception:
            pass
        if owner and alert_email(stay):
            try:
                send_dead_mans_switch_auto_executed(
                    owner.email,
                    guest_name,
                    property_name,
                    effective_end_date_str,
                )
                send_shield_mode_activated_email(
                    owner.email,
                    property_name,
                    triggered_by_dead_mans_switch=True,
                )
            except Exception:
                pass

    # Shield activation (test mode): skip last-day Shield activation tied to real stay_end_date to avoid side effects
    logger.info("DMS job (test mode): finished")
    return


def run_dms_test_mode_catchup_job() -> None:
    """DMS test mode only: find stays that checked in >2 min ago but still have DMS off, turn DMS on and run DMS job. Handles missed one-off job (e.g. server restart)."""
    if not getattr(settings, "dms_test_mode", False):
        logger.debug("DMS test-mode catchup job: skipped (dms_test_mode=False)")
        return
    logger.info("DMS test-mode catchup job: started")
    db = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=DMS_TEST_MODE_MINUTES_AFTER_CREATE)
        stays = (
            db.query(Stay)
            .filter(
                Stay.checked_in_at.isnot(None),
                Stay.checked_in_at < cutoff,
                Stay.checked_out_at.is_(None),
                Stay.cancelled_at.is_(None),
            )
            .all()
        )
        to_turn_on = [s for s in stays if getattr(s, "dead_mans_switch_enabled", 0) == 0]
        logger.info(
            "DMS test-mode catchup job: found %d stay(s) checked in >2min ago, %d with DMS off",
            len(stays),
            len(to_turn_on),
        )
        changed = False
        for stay in to_turn_on:
            stay.dead_mans_switch_enabled = 1
            db.add(stay)
            changed = True
        if changed:
            db.commit()
            logger.info("DMS test-mode catchup job: turned DMS on for %d stay(s), running run_dead_mans_switch_job", len(to_turn_on))
            run_dead_mans_switch_job(db)
        else:
            logger.info("DMS test-mode catchup job: no stays needed DMS on, done")
    except Exception as e:
        logger.exception("DMS test-mode catchup job: failed: %s", e)
    finally:
        db.close()
        logger.info("DMS test-mode catchup job: finished")


def run_dead_mans_switch_job(db: Session) -> None:
    """Dead Man's Switch: 48h before alert, today alert, 48h after auto-execute. When DMS_TEST_MODE=true, uses 2 min after stay creation."""
    if settings.dms_test_mode:
        logger.info("DMS job: running test-mode path (effective end = 2 min after check-in/create)")
        _run_dead_mans_switch_job_test_mode(db)
        return

    today = date.today()
    two_days_later = today + timedelta(days=2)
    two_days_ago = today - timedelta(days=2)

    # Stays with DMS enabled (integer 1)
    def dms_enabled(s: Stay) -> bool:
        return getattr(s, "dead_mans_switch_enabled", 0) == 1

    def alert_email(s: Stay) -> bool:
        return getattr(s, "dead_mans_switch_alert_email", 1) == 1

    # 1) 48 hours before lease end: turn DMS on for this stay (prod: DMS is not on from creation) and send alert
    for stay in (
        db.query(Stay)
        .filter(
            Stay.checked_in_at.isnot(None),
            Stay.stay_end_date == two_days_later,
            Stay.checked_out_at.is_(None),
            Stay.cancelled_at.is_(None),
        )
        .all()
    ):
        # In prod, DMS turns on here (48h before lease end), not at creation or check-in
        if not dms_enabled(stay):
            stay.dead_mans_switch_enabled = 1
            db.add(stay)
            db.commit()
        if _dms_already_logged(db, DMS_TITLE_48H_BEFORE, stay_id=stay.id):
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

    # 1.5) Last day of guest's stay: activate Shield Mode for the property (any checked-in stay ending today)
    stays_ending_today = (
        db.query(Stay)
        .filter(
            Stay.checked_in_at.isnot(None),
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
        try:
            profile = db.query(OwnerProfile).filter(OwnerProfile.id == prop.owner_profile_id).first()
            if profile:
                sync_subscription_quantities(db, profile)
        except Exception:
            pass
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

    # 2) Lease end date = today (urgent; only for checked-in stays)
    for stay in (
        db.query(Stay)
        .filter(
            Stay.checked_in_at.isnot(None),
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

    # 3) 48 hours after lease end – flip to UNCONFIRMED (only for checked-in stays; no auto-checkout)
    for stay in (
        db.query(Stay)
        .filter(
            Stay.checked_in_at.isnot(None),
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
        try:
            if prop:
                profile = db.query(OwnerProfile).filter(OwnerProfile.id == prop.owner_profile_id).first()
                if profile:
                    sync_subscription_quantities(db, profile)
        except Exception:
            pass

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


# Vacant monitoring audit title (idempotency)
VACANT_MONITORING_FLIPPED = "Vacant monitoring: no response – status UNCONFIRMED"


def run_vacant_monitoring_job(db: Session) -> None:
    """Vacant-unit monitoring: prompt at defined intervals; no response by deadline → flip to UNCONFIRMED, Shield on."""
    interval_days = getattr(settings, "vacant_monitoring_interval_days", 7) or 7
    response_days = getattr(settings, "vacant_monitoring_response_days", 7) or 7
    now = datetime.now(timezone.utc)
    today = now.date()

    vacant_with_monitoring = (
        db.query(Property)
        .filter(
            Property.occupancy_status == OccupancyStatus.vacant.value,
            Property.deleted_at.is_(None),
        )
        .all()
    )
    # Filter by vacant_monitoring_enabled (attribute may not exist on older DBs)
    monitored = [p for p in vacant_with_monitoring if getattr(p, "vacant_monitoring_enabled", 0) == 1]

    for prop in monitored:
        last_prompted = getattr(prop, "vacant_monitoring_last_prompted_at", None)
        response_due = getattr(prop, "vacant_monitoring_response_due_at", None)
        confirmed_at = getattr(prop, "vacant_monitoring_confirmed_at", None)

        # 1) Send prompt if due (never prompted, or interval has elapsed since last prompt)
        due_for_prompt = last_prompted is None or (
            (now - last_prompted).total_seconds() >= interval_days * 24 * 3600
        )
        if due_for_prompt:
            prop.vacant_monitoring_last_prompted_at = now
            prop.vacant_monitoring_response_due_at = now + timedelta(days=response_days)
            db.add(prop)
            db.commit()
            profile = db.query(OwnerProfile).filter(OwnerProfile.id == prop.owner_profile_id).first()
            owner = db.query(User).filter(User.id == profile.user_id).first() if profile else None
            if owner and owner.email:
                property_name = (prop.name or "").strip() or (f"{prop.city}, {prop.state}".strip(", ") if (prop.city or prop.state) else "Property")
                response_due_date = (now + timedelta(days=response_days)).strftime("%Y-%m-%d")
                try:
                    send_vacant_monitoring_prompt(owner.email, property_name, response_due_date)
                except Exception:
                    pass
            continue  # do not also flip in same run for this property

        # 2) Flip to UNCONFIRMED if response_due_at has passed and no confirmation since last prompt
        if response_due is None:
            continue
        if response_due.tzinfo is None:
            response_due = response_due.replace(tzinfo=timezone.utc)
        if response_due > now:
            continue
        if confirmed_at is not None and last_prompted is not None and confirmed_at >= last_prompted:
            continue
        if _dms_already_logged(db, VACANT_MONITORING_FLIPPED, property_id=prop.id):
            continue

        prev_status = getattr(prop, "occupancy_status", None) or "vacant"
        prop.occupancy_status = OccupancyStatus.unconfirmed.value
        prop.shield_mode_enabled = 1
        prop.vacant_monitoring_response_due_at = None
        db.add(prop)
        create_log(
            db,
            CATEGORY_STATUS_CHANGE,
            VACANT_MONITORING_FLIPPED,
            f"Vacant monitoring: no response by deadline. Property {prop.id} status {prev_status} -> unconfirmed; Shield Mode on.",
            property_id=prop.id,
            meta={"occupancy_status_previous": prev_status, "occupancy_status_new": OccupancyStatus.unconfirmed.value},
        )
        db.commit()
        profile = db.query(OwnerProfile).filter(OwnerProfile.id == prop.owner_profile_id).first()
        try:
            if profile:
                sync_subscription_quantities(db, profile)
        except Exception:
            pass
        owner = db.query(User).filter(User.id == profile.user_id).first() if profile else None
        if owner and owner.email:
            property_name = (prop.name or "").strip() or (f"{prop.city}, {prop.state}".strip(", ") if (prop.city or prop.state) else "Property")
            try:
                send_vacant_monitoring_flipped(owner.email, property_name)
                send_shield_mode_activated_email(owner.email, property_name, triggered_by_dead_mans_switch=False)
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
        run_vacant_monitoring_job(db)
    finally:
        db.close()
