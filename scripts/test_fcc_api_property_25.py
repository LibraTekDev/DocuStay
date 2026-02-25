"""
Test FCC National Broadband Map Public Data API for property 25.

Property 25: 1 Infinite Loop, Cupertino, CA 95014
  lat=37.3331, lon=-122.02889, state=CA

Uses FCC_BROADBAND_API_USERNAME and FCC_PUBLIC_MAP_DATA_APIS from .env.

API from official Swagger (BDC Public Data API):
  host: broadbandmap.fcc.gov
  basePath: /api/public
  Auth: GET headers "username" (FCC User Reg email) and "hash_value" (API token).
  Paths: GET /map/listAsOfDates, GET /map/downloads/listAvailabilityData/{as_of_date}, etc.

Run: python scripts/test_fcc_api_property_25.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env")))

# Property 25 (1 Infinite Loop, Cupertino, CA 95014)
PROP25_LAT = 37.3331
PROP25_LON = -122.02889
PROP25_STATE = "CA"
PROP25_ZIP = "95014"

# From Swagger: host + basePath (no /map here; paths are /map/listAsOfDates etc.)
FCC_BASE = "https://broadbandmap.fcc.gov/api/public"
TIMEOUT = 30


def main():
    from app.config import get_settings
    settings = get_settings()
    username = (settings.fcc_broadband_api_username or "").strip()
    token = (settings.fcc_public_map_data_apis or "").strip()

    if not username or not token:
        print("Missing FCC API credentials. Set in .env:")
        print("  FCC_BROADBAND_API_USERNAME=your-fcc-login@email.com")
        print("  FCC_PUBLIC_MAP_DATA_APIS=your-api-token")
        sys.exit(1)

    # Strip in case .env has trailing newline or spaces
    username = username.strip()
    token = token.strip()
    print(f"Using username: {username[:3]}...{username[-10:] if len(username) > 13 else '(short)'}")
    print(f"Token length: {len(token)} chars")
    print()

    # Swagger: header params "username" and "hash_value" (exact names)
    headers = {
        "username": username,
        "hash_value": token,
        "user-agent": "play/0.0.0",  # some environments need non-browser UA
    }

    print("FCC National Broadband Map API test (property 25)")
    print("-" * 50)
    print(f"Property 25: lat={PROP25_LAT}, lon={PROP25_LON}, state={PROP25_STATE}")
    print(f"Base URL (from Swagger): {FCC_BASE}")
    print()

    try:
        import httpx
    except ImportError:
        import urllib.request
        req = urllib.request.Request(
            f"{FCC_BASE}/map/listAsOfDates",
            headers=headers,
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                body = r.read().decode()
                print("listAsOfDates response:", body[:500])
        except Exception as e:
            print("listAsOfDates failed:", e)
            sys.exit(1)
        sys.exit(0)

    client = httpx.Client(timeout=TIMEOUT)

    # 0) Status (no auth) - Swagger path GET /
    print("0) GET / (status, no auth)...")
    try:
        r = client.get(f"{FCC_BASE}/")
        print(f"   Status: {r.status_code}")
        if r.status_code == 200:
            print(f"   Response: {r.json()}")
        else:
            print(f"   Body: {r.text[:200]}")
    except Exception as e:
        print(f"   Error: {e}")
    print()

    # 1) List as-of dates - Swagger path GET /map/listAsOfDates (auth required)
    print("1) GET /map/listAsOfDates (auth: username + hash_value)...")
    try:
        r = client.get(f"{FCC_BASE}/map/listAsOfDates", headers=headers)
        print(f"   Status: {r.status_code}")
        if r.status_code == 200:
            data = r.json()
            print(f"   Response: {data}")
            list_ok = True
        else:
            print(f"   Body: {r.text[:400]}")
            list_ok = False
    except Exception as e:
        print(f"   Error: {e}")
        list_ok = False
    print()

    if not list_ok:
        print("   Auth failed. Check: token from broadbandmap.fcc.gov -> Manage API Access, username = FCC login email. Regenerate token if needed.")
    else:
        # 2) List availability data (Swagger: GET /map/downloads/listAvailabilityData/{as_of_date})
        # Use first as_of_date from step 1; optional query: category=Provider, technology_type=Fixed Broadband
        as_of_date = None
        if isinstance(data, dict) and data.get("data"):
            for item in data["data"]:
                if isinstance(item, dict) and item.get("as_of_date"):
                    as_of_date = item["as_of_date"]
                    break
        if as_of_date:
            print("2) GET /map/downloads/listAvailabilityData/{as_of_date} (Provider, Fixed Broadband)...")
            url = f"{FCC_BASE}/map/downloads/listAvailabilityData/{as_of_date}"
            try:
                r = client.get(url, headers=headers, params={"category": "Provider", "technology_type": "Fixed Broadband"})
                print(f"   Status: {r.status_code}")
                if r.status_code == 200:
                    avail = r.json()
                    print(f"   Keys: {list(avail.keys()) if isinstance(avail, dict) else 'n/a'}")
                    if isinstance(avail, dict) and avail.get("data"):
                        print(f"   Files count: {len(avail['data'])}")
                        for row in avail["data"][:3]:
                            if isinstance(row, dict):
                                print(f"   - provider_name={row.get('provider_name')} state={row.get('state_name')} file_id={row.get('file_id')}")
                else:
                    print(f"   Body: {r.text[:250]}")
            except Exception as e:
                print(f"   Error: {e}")
        else:
            print("2) No as_of_date from step 1; skipping listAvailabilityData.")

    client.close()
    print()
    print("Done. API spec: BDC Public Data API Swagger (host=broadbandmap.fcc.gov, basePath=/api/public).")


if __name__ == "__main__":
    main()
