"""Delete a user by email. Removes or unlinks all related data (stays, invitations, properties, POA link, audit refs, pending, guest_pending_invites) then deletes the user.
Usage: python scripts/delete_owner_by_email.py [email]
  If email omitted, defaults to arfamujahid333@gmail.com
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models.user import User, UserRole
from app.models.owner import OwnerProfile, Property
from app.models.invitation import Invitation
from app.models.stay import Stay
from app.models.owner_poa_signature import OwnerPOASignature
from app.models.audit_log import AuditLog
from app.models.pending_registration import PendingRegistration

DEFAULT_EMAIL = "arfamujahid333@gmail.com"


def run():
    email = (sys.argv[1] if len(sys.argv) > 1 else DEFAULT_EMAIL).strip().lower()
    if not email:
        print("Usage: python scripts/delete_owner_by_email.py [email]")
        return

    db = SessionLocal()
    try:
        # Try to find user (any role)
        user = db.query(User).filter(User.email == email).first()
        if not user:
            # Also check pending registrations
            pending = db.query(PendingRegistration).filter(PendingRegistration.email == email).all()
            if pending:
                for p in pending:
                    db.delete(p)
                db.commit()
                print(f"Deleted {len(pending)} pending registration(s) for: {email}")
            else:
                print(f"No user or pending registration found with email: {email}")
            return

        uid = user.id
        role = user.role.value if user.role else "unknown"
        print(f"Found user id={uid}, email={user.email}, role={role}. Deleting related data then user...")

        # Import GuestPendingInvite model
        try:
            from app.models.guest_pending_invite import GuestPendingInvite
            has_guest_pending_invite = True
        except ImportError:
            has_guest_pending_invite = False

        # Delete guest_pending_invites where this user is the guest
        if has_guest_pending_invite:
            guest_pending = db.query(GuestPendingInvite).filter(GuestPendingInvite.user_id == uid).all()
            for gp in guest_pending:
                db.delete(gp)
            if guest_pending:
                print(f"  Deleted {len(guest_pending)} guest pending invite(s)")

        # If owner: Delete guest_pending_invites that reference their invitations
        if user.role == UserRole.owner:
            invs = db.query(Invitation).filter(Invitation.owner_id == uid).all()
            inv_ids = [inv.id for inv in invs]
            if inv_ids and has_guest_pending_invite:
                gp_for_invites = db.query(GuestPendingInvite).filter(GuestPendingInvite.invitation_id.in_(inv_ids)).all()
                for gp in gp_for_invites:
                    db.delete(gp)
                if gp_for_invites:
                    print(f"  Deleted {len(gp_for_invites)} guest pending invite(s) for owner's invitations")

        # Stays where this user is the owner OR guest
        stays_as_owner = db.query(Stay).filter(Stay.owner_id == uid).all()
        stays_as_guest = db.query(Stay).filter(Stay.guest_id == uid).all()
        for s in stays_as_owner:
            db.delete(s)
        for s in stays_as_guest:
            db.delete(s)
        if stays_as_owner:
            print(f"  Deleted {len(stays_as_owner)} stay(s) as owner")
        if stays_as_guest:
            print(f"  Deleted {len(stays_as_guest)} stay(s) as guest")

        # Invitations created by this owner
        if user.role == UserRole.owner:
            invs = db.query(Invitation).filter(Invitation.owner_id == uid).all()
            for inv in invs:
                db.delete(inv)
            if invs:
                print(f"  Deleted {len(invs)} invitation(s)")

        # Unlink POA signature (keep record, just unlink from user)
        db.query(OwnerPOASignature).filter(OwnerPOASignature.used_by_user_id == uid).update(
            {"used_by_user_id": None, "used_at": None}
        )
        print("  Unlinked Master POA signature(s)")

        # Audit log: keep entries but clear actor_user_id so we can delete user
        db.query(AuditLog).filter(AuditLog.actor_user_id == uid).update({"actor_user_id": None})
        print("  Cleared audit log actor_user_id references")

        # Properties via OwnerProfile (for owners)
        if user.role == UserRole.owner:
            profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == uid).first()
            if profile:
                props = db.query(Property).filter(Property.owner_profile_id == profile.id).all()
                for p in props:
                    db.delete(p)
                if props:
                    print(f"  Deleted {len(props)} property(ies)")
                db.delete(profile)
                print("  Deleted owner profile")

        # Guest profile (for guests)
        if user.role == UserRole.guest:
            try:
                from app.models.guest import GuestProfile
                guest_profile = db.query(GuestProfile).filter(GuestProfile.user_id == uid).first()
                if guest_profile:
                    db.delete(guest_profile)
                    print("  Deleted guest profile")
            except ImportError:
                pass

        # Pending registrations with this email
        pending = db.query(PendingRegistration).filter(PendingRegistration.email == email).all()
        for p in pending:
            db.delete(p)
        if pending:
            print(f"  Deleted {len(pending)} pending registration(s)")

        db.delete(user)
        db.commit()
        print(f"Deleted user: {email}")
    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run()
