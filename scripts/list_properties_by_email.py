"""
Display all property data for an owner by email.
Run from project root: python scripts/list_properties_by_email.py
        or: python scripts/list_properties_by_email.py rovofi7402@iaciu.com
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env")))

EMAIL = "rovofi7402@iaciu.com"  # default; override with argv[1]


def _serialize(v):
    if v is None:
        return None
    if hasattr(v, "value"):  # Enum
        return v.value
    if hasattr(v, "isoformat"):  # datetime
        return v.isoformat()
    if isinstance(v, bytes):
        return f"<{len(v)} bytes>"
    return v


def main():
    email = (sys.argv[1] if len(sys.argv) > 1 else EMAIL).strip()
    if not email:
        print("Usage: python scripts/list_properties_by_email.py <email>")
        sys.exit(1)

    from app.database import SessionLocal
    from app.models.user import User, UserRole
    from app.models.owner import OwnerProfile, Property

    db = SessionLocal()
    try:
        users = db.query(User).filter(User.email == email, User.role == UserRole.owner).all()
        if not users:
            print(f"No owner found with email: {email}")
            return

        for user in users:
            profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == user.id).first()
            if not profile:
                print(f"Owner {email} (id={user.id}) has no owner profile. No properties.")
                continue

            props = db.query(Property).filter(Property.owner_profile_id == profile.id).order_by(Property.id).all()
            print(f"\nProperties for {email} (user_id={user.id}, owner_profile_id={profile.id})")
            print(f"Total: {len(props)} property(ies)\n")
            print("-" * 60)

            for i, p in enumerate(props, 1):
                data = {
                    "id": p.id,
                    "name": p.name,
                    "street": p.street,
                    "city": p.city,
                    "state": p.state,
                    "zip_code": p.zip_code,
                    "region_code": p.region_code,
                    "smarty_delivery_line_1": p.smarty_delivery_line_1,
                    "smarty_city_name": p.smarty_city_name,
                    "smarty_state_abbreviation": p.smarty_state_abbreviation,
                    "smarty_zipcode": p.smarty_zipcode,
                    "smarty_plus4_code": p.smarty_plus4_code,
                    "smarty_latitude": p.smarty_latitude,
                    "smarty_longitude": p.smarty_longitude,
                    "owner_occupied": p.owner_occupied,
                    "property_type": _serialize(p.property_type),
                    "property_type_label": p.property_type_label,
                    "bedrooms": p.bedrooms,
                    "usat_token": p.usat_token,
                    "usat_token_state": p.usat_token_state,
                    "usat_token_released_at": _serialize(p.usat_token_released_at),
                    "occupancy_status": p.occupancy_status,
                    "shield_mode_enabled": p.shield_mode_enabled,
                    "deleted_at": _serialize(p.deleted_at),
                    "ownership_proof_type": p.ownership_proof_type,
                    "ownership_proof_filename": p.ownership_proof_filename,
                    "created_at": _serialize(p.created_at),
                }
                print(f"\n--- Property {i} (id={p.id}) ---")
                for k, v in data.items():
                    if v is not None:
                        print(f"  {k}: {v}")
            print()
    finally:
        db.close()


if __name__ == "__main__":
    main()
