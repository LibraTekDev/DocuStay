"""Quick check: look up a water provider by name in SQLite cache."""
import sys
from pathlib import Path
_path = Path(__file__).resolve().parent.parent
if str(_path) not in sys.path:
    sys.path.insert(0, str(_path))

from app.utility_providers.sqlite_cache import get_connection, ensure_tables

name = "BURKWOOD TREATMENT CENTER" if len(sys.argv) < 2 else " ".join(sys.argv[1:])
conn = get_connection(read_only=True)
ensure_tables(conn)
cur = conn.execute(
    "SELECT pwsid, pwsname, state, contactemail, contactphone FROM water_provider_cache WHERE UPPER(pwsname) LIKE ?",
    ("%" + name.upper() + "%",),
)
rows = cur.fetchall()
for r in rows:
    print(dict(r))
if not rows:
    print("No rows found.")
conn.close()
