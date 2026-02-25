"""
Delete all utility provider and authority letter records for property 25.
Run from project root: python scripts/delete_utility_property_25.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env")))

PROPERTY_ID = 25


def main():
    from app.database import SessionLocal
    from app.models import PropertyAuthorityLetter, PropertyUtilityProvider

    db = SessionLocal()
    try:
        letters_deleted = db.query(PropertyAuthorityLetter).filter(
            PropertyAuthorityLetter.property_id == PROPERTY_ID
        ).delete(synchronize_session=False)
        providers_deleted = db.query(PropertyUtilityProvider).filter(
            PropertyUtilityProvider.property_id == PROPERTY_ID
        ).delete(synchronize_session=False)
        db.commit()
        print(f"Property {PROPERTY_ID}: deleted {letters_deleted} authority letter(s), {providers_deleted} utility provider(s).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
