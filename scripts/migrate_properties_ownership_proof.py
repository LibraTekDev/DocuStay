"""Add ownership proof columns to properties table.
Run once on existing DBs."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.database import engine


def run():
    with engine.connect() as conn:
        for col, defn in [
            ("ownership_proof_type", "VARCHAR(50)"),
            ("ownership_proof_filename", "VARCHAR(255)"),
            ("ownership_proof_content_type", "VARCHAR(100)"),
            ("ownership_proof_bytes", "BYTEA"),
            ("ownership_proof_uploaded_at", "TIMESTAMP WITH TIME ZONE"),
        ]:
            try:
                conn.execute(text(f"ALTER TABLE properties ADD COLUMN IF NOT EXISTS {col} {defn}"))
                conn.commit()
            except Exception as e:
                if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                    conn.rollback()
                    print(f"Column {col} already exists, skipping.")
                else:
                    raise
    print("Done. properties table has ownership proof columns.")


if __name__ == "__main__":
    run()
