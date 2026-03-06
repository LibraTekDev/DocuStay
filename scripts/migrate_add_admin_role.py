"""
Add 'admin' value to the UserRole enum and optionally create an admin user.

1. Adds enum value: ALTER TYPE userrole ADD VALUE 'admin';
2. If ADMIN_EMAIL and ADMIN_PASSWORD are set in .env (or environment), creates a new
   admin user with that email and password (password is hashed with bcrypt).

Run from project root:
  python scripts/migrate_add_admin_role.py

Default admin (when env not set): admin@docustay.com / DreamsOfDreams89.
Override with .env: ADMIN_EMAIL, ADMIN_PASSWORD. All verification flags are set true for the admin user.
If a user with that email and role=admin already exists, the script updates their password and verification flags.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env")))


def main():
    from sqlalchemy import text
    try:
        from app.database import engine
    except Exception as e:
        print(f"Cannot get engine: {e}")
        sys.exit(1)

    # Step 1: Add 'admin' to the userrole enum
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TYPE userrole ADD VALUE 'admin'"))
            conn.commit()
            print("userrole enum: 'admin' value added")
        except Exception as e:
            err = str(e).lower()
            if "already exists" in err or "duplicate" in err:
                print("userrole enum: 'admin' already exists")
            else:
                print(f"Error: {e}")
                sys.exit(1)

    # Step 2: Create or update admin user (default: admin@docustay.com / DreamsOfDreams89)
    admin_email = (os.environ.get("ADMIN_EMAIL") or "admin@docustay.com").strip().lower()
    admin_password = os.environ.get("ADMIN_PASSWORD") or "DreamsOfDreams89"

    if admin_email and admin_password:
        from datetime import datetime, timezone
        from app.database import SessionLocal
        from app.models.user import User, UserRole
        from app.services.auth import get_password_hash

        now = datetime.now(timezone.utc)
        db = SessionLocal()
        try:
            existing = db.query(User).filter(User.email == admin_email, User.role == UserRole.admin).first()
            hashed = get_password_hash(admin_password)
            if existing:
                existing.hashed_password = hashed
                existing.email_verified = True
                existing.identity_verified_at = now
                existing.poa_waived_at = now
                db.commit()
                print(f"Admin user updated: {admin_email} (password and verifications set)")
            else:
                user = User(
                    email=admin_email,
                    hashed_password=hashed,
                    role=UserRole.admin,
                    full_name=os.environ.get("ADMIN_FULL_NAME", "Admin").strip() or "Admin",
                    email_verified=True,
                    identity_verified_at=now,
                    poa_waived_at=now,
                )
                db.add(user)
                db.commit()
                print(f"Admin user created: {admin_email}")
        except Exception as e:
            db.rollback()
            print(f"Failed to create/update admin user: {e}")
            sys.exit(1)
        finally:
            db.close()
    else:
        print("To create an admin user, set ADMIN_EMAIL and ADMIN_PASSWORD in .env and run again.")

    print("Done.")


# -----------------------------------------------------------------------------
# Optional: raw SQL for admin admin@docustay.com (password must be bcrypt-hashed).
# Get hash: python -c "from app.services.auth import get_password_hash; print(get_password_hash('DreamsOfDreams89'))"
#
#   ALTER TYPE userrole ADD VALUE 'admin';
#
#   INSERT INTO users (email, hashed_password, role, full_name, email_verified, identity_verified_at, poa_waived_at)
#   VALUES (
#     'admin@docustay.com',
#     'THE_BCRYPT_HASH',
#     'admin',
#     'Admin',
#     true,
#     NOW() AT TIME ZONE 'UTC',
#     NOW() AT TIME ZONE 'UTC'
#   )
#   ON CONFLICT (email, role) DO UPDATE SET
#     hashed_password = EXCLUDED.hashed_password,
#     email_verified = true,
#     identity_verified_at = EXCLUDED.identity_verified_at,
#     poa_waived_at = EXCLUDED.poa_waived_at;
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    main()
