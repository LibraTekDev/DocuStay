"""
Add sign-token and signature columns to property_authority_letters.
For a NEW database: not needed; app.models.property_utility.PropertyAuthorityLetter already defines these (create_all creates them).
Run once on an EXISTING DB: python scripts/migrate_authority_letter_sign.py (from project root)
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import text, inspect
from app.database import engine

COLUMNS = [
    ("sign_token", "VARCHAR(64) UNIQUE"),
    ("email_sent_at", "TIMESTAMP WITH TIME ZONE"),
    ("dropbox_sign_request_id", "VARCHAR(64)"),
    ("signed_at", "TIMESTAMP WITH TIME ZONE"),
    ("signed_pdf_bytes", "BYTEA"),
    ("signer_email", "VARCHAR(255)"),
]


def main():
    insp = inspect(engine)
    if "property_authority_letters" not in insp.get_table_names():
        print("  Table property_authority_letters does not exist (fresh DB). Nothing to do.")
        return
    existing = {c["name"] for c in insp.get_columns("property_authority_letters")}
    with engine.begin() as conn:
        for name, sql_type in COLUMNS:
            if name in existing:
                print(f"  skip (exists): property_authority_letters.{name}")
                continue
            stmt = f'ALTER TABLE property_authority_letters ADD COLUMN "{name}" {sql_type}'
            conn.execute(text(stmt))
            print(f"  added: property_authority_letters.{name}")
    print("Done. property_authority_letters has sign/signature columns.")


if __name__ == "__main__":
    main()
