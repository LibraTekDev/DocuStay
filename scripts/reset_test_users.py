"""
Delete specified users and all their associated data from the database.
Run from project root: python scripts/reset_test_users.py

WARNING: This permanently deletes data. No undo.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env")))

# (email, role) - must match exactly
USERS_TO_DELETE = [
    ("owner@test.docustay.demo", "owner"),
    ("guest@test.docustay.demo", "guest"),
    ("owner_1770148108@test.docustay.demo", "owner"),
    ("guest_1770148108@test.docustay.demo", "guest"),
    ("owner_1770148177@test.docustay.demo", "owner"),
    ("guest_1770148177@test.docustay.demo", "guest"),
    ("owner@curl.demo", "owner"),
    ("guest@curl.demo", "guest"),
    ("owner_1770148337@curl.demo", "owner"),
    ("guest_1770148337@curl.demo", "guest"),
    ("johnDoe@gmail.com", "owner"),
    ("usamaahmed302@gmail.com", "owner"),
    ("work49825@gmail.com", "guest"),
    ("usamaaiobc123@gmail.com", "owner"),
    ("usamaahmed3082000@gmail.com", "owner"),
    ("aiobcwork@gmail.com", "guest"),
    ("developmentaiobc@gmail.com", "owner"),
    ("mtdeveloper33@gmail.com", "guest"),
    ("arfamujahid333@gmail.com", "guest"),
    ("arfamujahid12@gmail.com", "guest"),
    ("arfamujahid333@gmail.com", "owner"),
    ("l215758@lhr.nu.edu.pk", "guest"),
    ("arfamujahid12@gmail.com", "owner"),
    ("diwey41312@iaciu.com", "owner"),
    ("kabigov830@fentaoba.com", "guest"),
    ("rovofi7402@iaciu.com", "owner"),
    ("raxosak359@iaciu.com", "guest"),
    ("jobavaj994@alibto.com", "owner"),
    ("jobavaj994@alibto.com", "guest"),
    ("tatej37629@bitonc.com", "owner"),
    ("usamaahmed302@gmail.com", "guest"),
]


def main():
    from sqlalchemy import delete
    from app.database import SessionLocal
    from app.models import (
        User,
        OwnerProfile,
        Property,
        GuestProfile,
        Stay,
        Invitation,
        GuestPendingInvite,
        AgreementSignature,
        AuditLog,
        OwnerPOASignature,
        PendingRegistration,
    )
    from app.models.user import UserRole

    db = SessionLocal()
    try:
        # 1. Find users by (email, role)
        user_ids = set()
        for email, role_str in USERS_TO_DELETE:
            role = UserRole(role_str)
            u = db.query(User).filter(User.email == email, User.role == role).first()
            if u:
                user_ids.add(u.id)

        if not user_ids:
            print("No matching users found.")
            return

        user_ids = list(user_ids)
        print(f"Found {len(user_ids)} users to delete.")

        # 2. Collect related IDs
        owner_profiles = db.query(OwnerProfile).filter(OwnerProfile.user_id.in_(user_ids)).all()
        owner_profile_ids = [p.id for p in owner_profiles]
        property_ids = [r[0] for r in db.query(Property.id).filter(Property.owner_profile_id.in_(owner_profile_ids)).all()] if owner_profile_ids else []
        stay_ids = [r[0] for r in db.query(Stay.id).filter(
            (Stay.guest_id.in_(user_ids)) | (Stay.owner_id.in_(user_ids))
        ).all()]
        invitation_ids = [r[0] for r in db.query(Invitation.id).filter(Invitation.owner_id.in_(user_ids)).all()]

        # 3. Delete in dependency order
        from sqlalchemy import or_
        audit_cond = AuditLog.actor_user_id.in_(user_ids)
        if property_ids:
            audit_cond = or_(audit_cond, AuditLog.property_id.in_(property_ids))
        if stay_ids:
            audit_cond = or_(audit_cond, AuditLog.stay_id.in_(stay_ids))
        if invitation_ids:
            audit_cond = or_(audit_cond, AuditLog.invitation_id.in_(invitation_ids))
        n_audit = db.execute(delete(AuditLog).where(audit_cond)).rowcount

        gpi_cond = GuestPendingInvite.user_id.in_(user_ids)
        if invitation_ids:
            gpi_cond = or_(gpi_cond, GuestPendingInvite.invitation_id.in_(invitation_ids))
        n_gpi = db.execute(delete(GuestPendingInvite).where(gpi_cond)).rowcount

        n_stays = db.execute(delete(Stay).where(Stay.id.in_(stay_ids))).rowcount if stay_ids else 0
        n_inv = db.execute(delete(Invitation).where(Invitation.id.in_(invitation_ids))).rowcount if invitation_ids else 0
        n_agree = db.execute(delete(AgreementSignature).where(AgreementSignature.used_by_user_id.in_(user_ids))).rowcount
        n_poa = db.execute(delete(OwnerPOASignature).where(OwnerPOASignature.used_by_user_id.in_(user_ids))).rowcount
        n_guest = db.execute(delete(GuestProfile).where(GuestProfile.user_id.in_(user_ids))).rowcount
        n_props = db.execute(delete(Property).where(Property.owner_profile_id.in_(owner_profile_ids))).rowcount if owner_profile_ids else 0
        n_owner = db.execute(delete(OwnerProfile).where(OwnerProfile.user_id.in_(user_ids))).rowcount
        n_users = db.execute(delete(User).where(User.id.in_(user_ids))).rowcount

        # Clear any remaining orphaned audit logs (full reset)
        n_audit_extra = db.execute(delete(AuditLog)).rowcount

        emails = list({e for e, _ in USERS_TO_DELETE})
        n_pending = db.execute(delete(PendingRegistration).where(PendingRegistration.email.in_(emails))).rowcount

        db.commit()

        print("Deleted:")
        print(f"  audit_logs:         {n_audit} (+ {n_audit_extra} orphaned)")
        print(f"  guest_pending_inv:  {n_gpi}")
        print(f"  stays:              {n_stays}")
        print(f"  invitations:        {n_inv}")
        print(f"  agreement_signatures: {n_agree}")
        print(f"  owner_poa_signatures: {n_poa}")
        print(f"  guest_profiles:     {n_guest}")
        print(f"  properties:         {n_props}")
        print(f"  owner_profiles:     {n_owner}")
        print(f"  users:              {n_users}")
        print(f"  pending_registrations: {n_pending}")
        print("Done.")
    except Exception as e:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
