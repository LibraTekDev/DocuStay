"""Create property_utility_providers and property_authority_letters tables.
For NEW DB: not needed; models define these.
Run on EXISTING DB: python scripts/migrate_property_utilities.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import text, inspect
from app.database import engine


def main():
    insp = inspect(engine)
    tables = insp.get_table_names()

    with engine.begin() as conn:
        if "property_utility_providers" not in tables:
            conn.execute(text("""
                CREATE TABLE property_utility_providers (
                    id SERIAL PRIMARY KEY,
                    property_id INTEGER NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
                    provider_name VARCHAR(255) NOT NULL,
                    provider_type VARCHAR(32) NOT NULL,
                    utilityapi_id VARCHAR(64),
                    contact_phone VARCHAR(50),
                    contact_email VARCHAR(255),
                    raw_data TEXT,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """))
            conn.execute(text("CREATE INDEX ix_property_utility_providers_property_id ON property_utility_providers(property_id)"))
            print("  created: property_utility_providers")
        else:
            cols = [c["name"] for c in insp.get_columns("property_utility_providers")]
            for col_name, col_def in [("contact_phone", "VARCHAR(50)"), ("contact_email", "VARCHAR(255)")]:
                if col_name not in cols:
                    conn.execute(text(f"ALTER TABLE property_utility_providers ADD COLUMN {col_name} {col_def}"))
                    print(f"  added column: property_utility_providers.{col_name}")
            print("  skip (exists): property_utility_providers")

        if "property_authority_letters" not in tables:
            conn.execute(text("""
                CREATE TABLE property_authority_letters (
                    id SERIAL PRIMARY KEY,
                    property_id INTEGER NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
                    property_utility_provider_id INTEGER REFERENCES property_utility_providers(id) ON DELETE CASCADE,
                    provider_name VARCHAR(255) NOT NULL,
                    letter_content TEXT NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
                )
            """))
            conn.execute(text("CREATE INDEX ix_property_authority_letters_property_id ON property_authority_letters(property_id)"))
            print("  created: property_authority_letters")
        else:
            cols = [c["name"] for c in insp.get_columns("property_authority_letters")]
            if "property_utility_provider_id" not in cols:
                conn.execute(text("ALTER TABLE property_authority_letters ADD COLUMN property_utility_provider_id INTEGER REFERENCES property_utility_providers(id) ON DELETE CASCADE"))
                print("  added column: property_authority_letters.property_utility_provider_id")
            print("  skip (exists): property_authority_letters")

    print("Done.")


if __name__ == "__main__":
    main()
