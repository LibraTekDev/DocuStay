"""Backfill identity_verified_at and poa_waived_at for owner users created before Stripe Identity/POA were required.

1. Owners without identity_verified_at -> set identity_verified_at and poa_waived_at (skip Stripe + POA)
2. Owners with identity_verified_at but no POA linked -> set poa_waived_at (skip POA sign step)

Usage: python scripts/backfill_owner_identity_verified.py [--dry-run]
  With --dry-run: only print what would be updated; no DB changes.
  Run scripts/migrate_user_identity_and_owner_type.py first if poa_waived_at column is missing.
"""
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models.user import User, UserRole
from app.models.owner_poa_signature import OwnerPOASignature


def run(dry_run: bool = False):
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        updates = []

        # 1. Owners without identity_verified_at
        owners_without_identity = (
            db.query(User)
            .filter(User.role == UserRole.owner, User.identity_verified_at.is_(None))
            .all()
        )
        for u in owners_without_identity:
            u.identity_verified_at = now
            u.poa_waived_at = now
            updates.append((u, "identity+poa_waived"))

        # 2. Owners with identity but no POA (e.g. already ran identity backfill)
        owners_with_identity = (
            db.query(User)
            .filter(User.role == UserRole.owner, User.identity_verified_at.isnot(None))
            .all()
        )
        for u in owners_with_identity:
            if getattr(u, "poa_waived_at", None):
                continue
            has_poa = db.query(OwnerPOASignature).filter(OwnerPOASignature.used_by_user_id == u.id).first() is not None
            if not has_poa:
                u.poa_waived_at = now
                updates.append((u, "poa_waived"))

        if not updates:
            print("No owner users need backfill.")
            return
        print(f"Would update {len(updates)} owner(s):")
        for u, kind in updates:
            print(f"  id={u.id} email={u.email} -> {kind}")
        if dry_run:
            print("Dry run: no changes made. Run without --dry-run to apply.")
            return
        db.commit()
        print(f"Updated {len(updates)} owner(s).")
    finally:
        db.close()


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    run(dry_run=dry_run)
