"""
Display property and utility data for property 25 from the DB.
Shows: properties row, property_utility_providers, property_authority_letters.

Run from project root: python scripts/show_utility_records_property_25.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env")))

PROPERTY_ID = 25


def _val(v):
    if v is None:
        return "None"
    if hasattr(v, "value"):  # enum
        return v.value
    if isinstance(v, bytes):
        return f"<{len(v)} bytes>"
    return v


def main():
    from app.database import SessionLocal
    from app.models import Property, PropertyUtilityProvider, PropertyAuthorityLetter

    db = SessionLocal()
    try:
        prop = db.query(Property).filter(Property.id == PROPERTY_ID).first()
        if not prop:
            print(f"Property {PROPERTY_ID} not found.")
            sys.exit(1)

        print("=" * 70)
        print(f"PROPERTY (id={prop.id})")
        print("=" * 70)
        print(f"  owner_profile_id     = {prop.owner_profile_id}")
        print(f"  name                 = {prop.name!r}")
        print(f"  street               = {prop.street!r}")
        print(f"  city                 = {prop.city!r}")
        print(f"  state                = {prop.state!r}")
        print(f"  zip_code             = {prop.zip_code!r}")
        print(f"  region_code          = {prop.region_code!r}")
        print(f"  smarty_delivery_line_1   = {prop.smarty_delivery_line_1!r}")
        print(f"  smarty_city_name      = {prop.smarty_city_name!r}")
        print(f"  smarty_state_abbreviation = {prop.smarty_state_abbreviation!r}")
        print(f"  smarty_zipcode        = {prop.smarty_zipcode!r}")
        print(f"  smarty_plus4_code     = {prop.smarty_plus4_code!r}")
        print(f"  smarty_latitude       = {prop.smarty_latitude}")
        print(f"  smarty_longitude      = {prop.smarty_longitude}")
        print(f"  owner_occupied       = {prop.owner_occupied}")
        print(f"  property_type        = {_val(prop.property_type)}")
        print(f"  property_type_label   = {prop.property_type_label!r}")
        print(f"  bedrooms             = {prop.bedrooms!r}")
        print(f"  usat_token           = {prop.usat_token!r}")
        print(f"  usat_token_state     = {prop.usat_token_state!r}")
        print(f"  usat_token_released_at = {prop.usat_token_released_at}")
        print(f"  created_at           = {prop.created_at}")
        print(f"  updated_at           = {prop.updated_at}")
        print(f"  deleted_at           = {prop.deleted_at}")
        print(f"  shield_mode_enabled  = {prop.shield_mode_enabled}")
        print(f"  occupancy_status     = {prop.occupancy_status!r}")
        print(f"  ownership_proof_type = {prop.ownership_proof_type!r}")
        print(f"  ownership_proof_filename = {prop.ownership_proof_filename!r}")
        print(f"  ownership_proof_content_type = {prop.ownership_proof_content_type!r}")
        print(f"  ownership_proof_bytes = {_val(prop.ownership_proof_bytes)}")
        print(f"  ownership_proof_uploaded_at = {prop.ownership_proof_uploaded_at}")
        print()

        providers = db.query(PropertyUtilityProvider).filter(
            PropertyUtilityProvider.property_id == PROPERTY_ID
        ).order_by(PropertyUtilityProvider.provider_type, PropertyUtilityProvider.id).all()

        print("=" * 70)
        print(f"PROPERTY_UTILITY_PROVIDERS ({len(providers)} rows)")
        print("=" * 70)
        if not providers:
            print("  (none)\n")
        else:
            show_all = len(providers) <= 25
            for i, p in enumerate(providers, 1):
                if not show_all and i > 20:
                    print(f"  ... and {len(providers) - 20} more.")
                    break
                print(f"  [{i}] id={p.id}  type={p.provider_type!r}  name={p.provider_name!r}")
                print(f"      utilityapi_id={p.utilityapi_id!r}  contact_phone={p.contact_phone!r}")
                raw_str = p.raw_data if isinstance(p.raw_data, str) else str(p.raw_data) if p.raw_data else ""
                preview = raw_str[:120] + ("..." if len(raw_str) > 120 else "")
                print(f"      raw_data={preview!r}")
                print(f"      created_at={p.created_at}")
                print()
        print()

        letters = db.query(PropertyAuthorityLetter).filter(
            PropertyAuthorityLetter.property_id == PROPERTY_ID
        ).order_by(PropertyAuthorityLetter.id).all()

        print("=" * 70)
        print(f"PROPERTY_AUTHORITY_LETTERS ({len(letters)} rows)")
        print("=" * 70)
        if not letters:
            print("  (none)\n")
        else:
            show_all = len(letters) <= 25
            for i, l in enumerate(letters, 1):
                if not show_all and i > 20:
                    print(f"  ... and {len(letters) - 20} more.")
                    break
                content_str = l.letter_content if isinstance(l.letter_content, str) else str(l.letter_content or "")
                preview = content_str[:200].replace("\n", " ") + ("..." if len(content_str) > 200 else "")
                print(f"  [{i}] id={l.id}  provider={l.provider_name!r}  type={l.provider_type!r}")
                print(f"      property_utility_provider_id={l.property_utility_provider_id}")
                print(f"      letter_content={preview!r}")
                print(f"      created_at={l.created_at}")
                print()
    finally:
        db.close()


if __name__ == "__main__":
    main()
