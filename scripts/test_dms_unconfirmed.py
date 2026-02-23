"""Set up a stay to trigger UNCONFIRMED status for testing."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, timedelta
from app.database import SessionLocal
from app.models.user import User
from app.models.owner import OwnerProfile, Property
from app.models.stay import Stay
from app.models.audit_log import AuditLog
from app.services.stay_timer import run_dead_mans_switch_job

OWNER_EMAIL = "johnDoe@gmail.com"
DMS_TITLE_AUTO_EXECUTED = "Dead Man's Switch: auto-executed"

db = SessionLocal()

# Find owner
owner = db.query(User).filter(User.email == OWNER_EMAIL).first()
if not owner:
    print(f"Owner {OWNER_EMAIL} not found.")
    db.close()
    exit(1)
print(f"Found owner: {owner.email} (id={owner.id})")

# Find owner profile and properties
profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == owner.id).first()
if not profile:
    print("No owner profile found.")
    db.close()
    exit(1)

props = db.query(Property).filter(Property.owner_profile_id == profile.id, Property.deleted_at.is_(None)).all()
if not props:
    print("No active properties found for this owner.")
    db.close()
    exit(1)

print(f"Found {len(props)} property(ies):")
for p in props:
    print(f"  - id={p.id} name={p.name or p.street} status={p.occupancy_status}")

# Find a stay for this owner's property that hasn't had DMS auto-executed yet
stays = (
    db.query(Stay)
    .filter(
        Stay.owner_id == owner.id,
        Stay.checked_out_at.is_(None),
        Stay.cancelled_at.is_(None),
    )
    .all()
)

# Prefer a stay without an existing DMS auto-executed log
stay = None
for s in stays:
    existing_log = db.query(AuditLog).filter(
        AuditLog.stay_id == s.id,
        AuditLog.title == DMS_TITLE_AUTO_EXECUTED
    ).first()
    if not existing_log:
        stay = s
        break

# If all stays already have DMS logs, use the first one and show logs instead
already_triggered = False
if not stay and stays:
    stay = stays[0]
    already_triggered = True

if not stay:
    print("\nNo active stay found for this owner. Creating a test scenario is not possible without a stay.")
    print("Please create an invitation, have a guest accept it, then run this script again.")
    db.close()
    exit(1)

prop = db.query(Property).filter(Property.id == stay.property_id).first()
print(f"\nUsing stay {stay.id} at property '{prop.name or prop.street}' (id={prop.id})")
print(f"  Current stay_end_date: {stay.stay_end_date}")
print(f"  Current DMS enabled: {stay.dead_mans_switch_enabled}")
print(f"  Current property status: {prop.occupancy_status}")

if already_triggered:
    print("\n[NOTE] This stay already has a DMS auto-executed audit log.")
    print("  The DMS job won't re-trigger (idempotent by design).")
    print("  Showing existing logs instead...")
else:
    # Reset property status to 'unknown' so the transition is observable
    prop.occupancy_status = "unknown"
    db.add(prop)

    # Set stay to have ended 3 days ago, enable DMS, clear any confirmation
    stay.stay_end_date = date.today() - timedelta(days=3)
    stay.dead_mans_switch_enabled = 1
    stay.occupancy_confirmation_response = None
    stay.occupancy_confirmation_responded_at = None
    stay.dead_mans_switch_triggered_at = None
    db.commit()
    print(f"\nUpdated stay {stay.id}:")
    print(f"  stay_end_date = {stay.stay_end_date} (3 days ago)")
    print(f"  dead_mans_switch_enabled = 1")
    print(f"  occupancy_confirmation_response = None")

    # Run the DMS job
    print("\nRunning Dead Man's Switch job...")
    run_dead_mans_switch_job(db)

    # Refresh and check property status
    db.refresh(prop)
    db.refresh(stay)
    print(f"\nAfter DMS job:")
    print(f"  Property {prop.id} occupancy_status: {prop.occupancy_status}")
    print(f"  Stay dead_mans_switch_triggered_at: {stay.dead_mans_switch_triggered_at}")

    if prop.occupancy_status == "unconfirmed":
        print("\n[OK] SUCCESS: Property is now UNCONFIRMED.")
        print("  Open the owner dashboard to see the confirmation UI.")
    else:
        print(f"\n[!] Property status is '{prop.occupancy_status}' (expected 'unconfirmed').")

# Show recent audit logs for this property/stay
print("\n--- Recent Audit Logs (property={}, stay={}) ---".format(prop.id, stay.id))
logs = (
    db.query(AuditLog)
    .filter(
        (AuditLog.property_id == prop.id) | (AuditLog.stay_id == stay.id)
    )
    .order_by(AuditLog.created_at.desc())
    .limit(10)
    .all()
)
if logs:
    for log in reversed(logs):
        ts = log.created_at.strftime("%Y-%m-%d %H:%M:%S") if log.created_at else "?"
        meta_str = ""
        if log.meta:
            prev = log.meta.get("occupancy_status_previous")
            new = log.meta.get("occupancy_status_new")
            if prev or new:
                meta_str = f" [{prev} -> {new}]"
        # Sanitize message for Windows console
        msg = (log.message or "")[:120].encode('ascii', 'replace').decode('ascii')
        print(f"  [{ts}] {log.category}: {log.title}{meta_str}")
        print(f"      {msg}{'...' if len(log.message or '') > 120 else ''}")
else:
    print("  No audit logs found for this property/stay.")

db.close()
