"""
Test database connectivity. Run from project root: python scripts/check_db_connection.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env")))


def main():
    from sqlalchemy import text
    from app.database import SessionLocal, engine
    from app.config import get_settings

    settings = get_settings()
    url = settings.database_url
    # Hide password in print
    safe_url = url.split("@")[-1] if "@" in url else url[:50]
    print(f"Connecting to ...@{safe_url}")

    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        print("DB connection OK")
        return 0
    except Exception as e:
        print(f"DB connection failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
