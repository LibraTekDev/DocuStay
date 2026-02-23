"""Add identity_verified_at, stripe_verification_session_id, owner_type, authorized_agent_certified_at to users table.
Run once on existing DBs. New DBs get these from create_all via app.models.user.User."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.database import engine

def run():
    with engine.connect() as conn:
        for col, defn in [
            ("identity_verified_at", "TIMESTAMP WITH TIME ZONE"),
            ("stripe_verification_session_id", "VARCHAR(255)"),
            ("owner_type", "VARCHAR(32)"),
            ("authorized_agent_certified_at", "TIMESTAMP WITH TIME ZONE"),
            ("poa_waived_at", "TIMESTAMP WITH TIME ZONE"),
        ]:
            try:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col} {defn}"))
                conn.commit()
            except Exception as e:
                if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                    conn.rollback()
                    print(f"Column {col} already exists, skipping.")
                else:
                    raise
    print("Done. users table has identity and owner_type columns.")


if __name__ == "__main__":
    run()
