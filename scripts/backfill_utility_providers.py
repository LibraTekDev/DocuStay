"""
Backfill utility providers and authority letters for properties that have Smarty data but no utility providers.
Run: python scripts/backfill_utility_providers.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env")))


def main():
    from app.database import SessionLocal
    from app.models import Property, PropertyUtilityProvider, PropertyAuthorityLetter
    from app.services.utility_lookup import lookup_utility_providers, generate_authority_letters, _provider_to_raw

    db = SessionLocal()
    try:
        # Find properties with smarty_zipcode but no utility providers
        props = db.query(Property).filter(
            Property.deleted_at.is_(None),
            Property.smarty_zipcode.isnot(None),
        ).all()

        backfilled = 0
        for prop in props:
            existing = db.query(PropertyUtilityProvider).filter(PropertyUtilityProvider.property_id == prop.id).first()
            if existing:
                continue
            zip_code = prop.smarty_zipcode or prop.zip_code
            address = ", ".join(filter(None, [
                prop.smarty_delivery_line_1 or prop.street,
                (prop.smarty_city_name or prop.city or "") + ", " + (prop.smarty_state_abbreviation or prop.state or "") + " " + (prop.smarty_zipcode or prop.zip_code or ""),
            ]))
            if not address.strip():
                address = (prop.street or "") + ", " + (prop.city or "") + ", " + (prop.state or "")
            providers = lookup_utility_providers(
                zip_code=zip_code,
                lat=prop.smarty_latitude,
                lon=prop.smarty_longitude,
                address=address,
                city=prop.smarty_city_name or prop.city,
                state_abbreviation=prop.smarty_state_abbreviation or prop.state,
            )
            if not providers:
                continue
            letters = generate_authority_letters(providers, address, prop.name)
            for p, content in letters:
                prv = PropertyUtilityProvider(
                    property_id=prop.id,
                    provider_name=p.name,
                    provider_type=p.provider_type,
                    utilityapi_id=p.utilityapi_id,
                    contact_phone=p.phone,
                    raw_data=_provider_to_raw(p),
                )
                db.add(prv)
                db.flush()
                letter = PropertyAuthorityLetter(
                    property_id=prop.id,
                    property_utility_provider_id=prv.id,
                    provider_name=p.name,
                    provider_type=p.provider_type,
                    letter_content=content,
                )
                db.add(letter)
            backfilled += 1
            print(f"  Backfilled property {prop.id}: {prop.street}, {prop.city}, {prop.state} -> {len(providers)} providers")

        db.commit()
        print(f"\nBackfilled {backfilled} property(ies).")
    finally:
        db.close()


if __name__ == "__main__":
    main()
