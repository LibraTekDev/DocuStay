"""Query all tables in the utility provider SQLite DB and show row counts + sample row."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.utility_providers.sqlite_cache import get_db_path, get_connection, ensure_tables

def main():
    path = get_db_path()
    print("DB path:", path)
    print()

    conn = get_connection()
    ensure_tables(conn)

    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    print("Tables:", [t[0] for t in tables])
    print()

    for (tname,) in tables:
        n = conn.execute(f"SELECT COUNT(*) FROM [{tname}]").fetchone()[0]
        print(f"{tname}: {n} rows")
        if n > 0:
            cols = [c[1] for c in conn.execute(f"PRAGMA table_info([{tname}])").fetchall()]
            row = conn.execute(f"SELECT * FROM [{tname}] LIMIT 1").fetchone()
            print("  sample:", dict(zip(cols, row)))
        print()

    conn.close()
    print("Done.")

if __name__ == "__main__":
    main()
