"""
Hard-delete a property by address (street, city, state, zip).
Deletes related: invitations, stays (after clearing audit_log.stay_id), property_utility_providers,
property_authority_letters, then the property. Audit logs for this property keep property_id=NULL.
Run from project root: python scripts/delete_property_by_address.py "1 Infinite Loop" "Cupertino" "CA" "95014"
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env")))


def main():
    from app.database import SessionLocal
    from app.models.owner import Property
    from app.models.invitation import Invitation
    from app.models.stay import Stay
    from app.models.property_utility import PropertyUtilityProvider, PropertyAuthorityLetter
    from app.models.audit_log import AuditLog

    # Parse args: street city state zip (all optional parts can be in one string or separate)
    if len(sys.argv) < 4:
        print("Usage: python scripts/delete_property_by_address.py <street> <city> <state> [zip]")
        print('Example: python scripts/delete_property_by_address.py "1 Infinite Loop" Cupertino CA 95014')
        sys.exit(1)

    street = (sys.argv[1] or "").strip()
    city = (sys.argv[2] or "").strip()
    state = (sys.argv[3] or "").strip()
    zip_code = (sys.argv[4] or "").strip() if len(sys.argv) > 4 else None

    if not street or not city or not state:
        print("street, city, and state are required.")
        sys.exit(1)

    db = SessionLocal()
    try:
        # Match on street (or smarty), city, state, zip (flexible). Include soft-deleted so we can hard-delete.
        q = db.query(Property).filter(
            (Property.street.ilike(f"%{street}%")) |
            (Property.smarty_delivery_line_1.isnot(None) & Property.smarty_delivery_line_1.ilike(f"%{street}%"))
        )
        q = q.filter(
            (Property.city.ilike(city)) | (Property.smarty_city_name.ilike(city))
        )
        q = q.filter(
            (Property.state.ilike(state)) | (Property.smarty_state_abbreviation.ilike(state))
        )
        if zip_code:
            zip5 = zip_code.split("-")[0].strip()[:5]
            q = q.filter(
                (Property.zip_code == zip5) | (Property.zip_code == zip_code) |
                (Property.smarty_zipcode == zip5) | (Property.smarty_zipcode == zip_code)
            )
        props = q.all()

        if not props:
            print(f"No property found for: {street}, {city}, {state} {zip_code or ''}")
            return

        for prop in props:
            pid = prop.id
            # Clear audit_log references so we can delete stays and then property
            db.query(AuditLog).filter(AuditLog.property_id == pid).update({AuditLog.property_id: None})
            stay_ids = [s.id for s in db.query(Stay).filter(Stay.property_id == pid).all()]
            if stay_ids:
                db.query(AuditLog).filter(AuditLog.stay_id.in_(stay_ids)).update({AuditLog.stay_id: None})
            db.query(Invitation).filter(Invitation.property_id == pid).delete()
            db.query(Stay).filter(Stay.property_id == pid).delete()
            db.query(PropertyAuthorityLetter).filter(PropertyAuthorityLetter.property_id == pid).delete()
            db.query(PropertyUtilityProvider).filter(PropertyUtilityProvider.property_id == pid).delete()
            db.delete(prop)
            print(f"Hard-deleted property id={pid}: {prop.street}, {prop.city}, {prop.state} {prop.zip_code or ''}")
        db.commit()
        print(f"Done. {len(props)} property(ies) permanently removed.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
