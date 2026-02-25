"""
Run the Utility Bucket for test property 25 and save providers + authority letters to the DB.

Uses the same code path as the app: _run_utility_bucket_for_property(prop, db).
Property 25 should have Smarty data (e.g. 1 Infinite Loop, Cupertino, CA 95014) for best results.

Run from project root: python scripts/seed_utility_property_25.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env")))

PROPERTY_ID = 25


def main():
    from app.database import SessionLocal
    from app.models import Property
    from app.routers.owners import _run_utility_bucket_for_property

    db = SessionLocal()
    try:
        prop = db.query(Property).filter(Property.id == PROPERTY_ID).first()
        if not prop:
            print(f"Property {PROPERTY_ID} not found.")
            sys.exit(1)
        print(f"Running Utility Bucket for property {PROPERTY_ID}: {prop.street}, {prop.city}, {prop.state}")
        _run_utility_bucket_for_property(prop, db)
        db.commit()
        from app.models import PropertyUtilityProvider
        count = db.query(PropertyUtilityProvider).filter(PropertyUtilityProvider.property_id == prop.id).count()
        print(f"Done. Property {PROPERTY_ID} now has {count} utility provider(s) and authority letters in the DB.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
