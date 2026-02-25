"""
Print the first 5 rows of all utility provider SQLite tables.
Run from project root: python scripts/print_utility_tables_sample.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.utility_providers.sqlite_cache import get_db_path, get_connection, ensure_tables

SAMPLE_SIZE = 5


def main():
    path = get_db_path()
    print("DB path:", path)
    print()

    conn = get_connection()
    ensure_tables(conn)

    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()

    for (tname,) in tables:
        n = conn.execute(f"SELECT COUNT(*) FROM [{tname}]").fetchone()[0]
        print("=" * 60)
        print(f"  {tname}  (total rows: {n})")
        print("=" * 60)
        if n == 0:
            print("  (empty)")
            print()
            continue
        cols = [c[1] for c in conn.execute(f"PRAGMA table_info([{tname}])").fetchall()]
        rows = conn.execute(f"SELECT * FROM [{tname}] LIMIT {SAMPLE_SIZE}").fetchall()
        for i, row in enumerate(rows, 1):
            print(f"  --- row {i} ---")
            for col, val in zip(cols, row):
                print(f"    {col}: {val}")
        print()

    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
