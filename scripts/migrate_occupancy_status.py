"""Add occupancy_status to properties and occupancy_confirmation_* to stays.
For a NEW database: not needed; models define these.
Run once on an EXISTING DB: python scripts/migrate_occupancy_status.py (from project root)
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import text, inspect
from app.database import engine


def main():
    insp = inspect(engine)

    # properties.occupancy_status
    if "properties" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("properties")}
        if "occupancy_status" not in cols:
            with engine.begin() as conn:
                conn.execute(text(
                    "ALTER TABLE properties ADD COLUMN occupancy_status VARCHAR(32) DEFAULT 'unknown'"
                ))
            print("  added: properties.occupancy_status")
        else:
            print("  skip (exists): properties.occupancy_status")

    # stays.occupancy_confirmation_response, occupancy_confirmation_responded_at
    if "stays" in insp.get_table_names():
        cols = {c["name"] for c in insp.get_columns("stays")}
        with engine.begin() as conn:
            if "occupancy_confirmation_response" not in cols:
                conn.execute(text(
                    'ALTER TABLE stays ADD COLUMN occupancy_confirmation_response VARCHAR(32)'
                ))
                print("  added: stays.occupancy_confirmation_response")
            else:
                print("  skip (exists): stays.occupancy_confirmation_response")
            if "occupancy_confirmation_responded_at" not in cols:
                conn.execute(text(
                    'ALTER TABLE stays ADD COLUMN occupancy_confirmation_responded_at TIMESTAMP WITH TIME ZONE'
                ))
                print("  added: stays.occupancy_confirmation_responded_at")
            else:
                print("  skip (exists): stays.occupancy_confirmation_responded_at")

    print("Done.")


if __name__ == "__main__":
    main()
