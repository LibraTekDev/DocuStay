"""
Fetch FCC BDC location-level (or county-level) fixed broadband providers.

Uses State + "Location Coverage" files: each row has block_geoid, brand_name, provider_id.
- block_geoid = Census block GEOID (15 digits: state 2 + county 3 + tract 6 + block 4).
- First 5 digits = state FIPS + county FIPS -> county-level filter.
- Full block_geoid -> block-level (precise) filter.

No cache for now; fetches from API on each run. Cache can be added later.

Requires FCC_BROADBAND_API_USERNAME and FCC_PUBLIC_MAP_DATA_APIS in .env.

Usage:
  python scripts/fcc_location_providers.py --state California --county-fips 085   # Santa Clara
  python scripts/fcc_location_providers.py --state California --county-fips 085 --download-one   # use 1 tech file only (faster)
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import sys
import zipfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from dotenv import load_dotenv
load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env")))

FCC_BASE = "https://broadbandmap.fcc.gov/api/public"
TIMEOUT = 60
DOWNLOAD_TIMEOUT = 600  # 10 min for large state files
DATA_TYPE_AVAILABILITY = "availability"


def _auth_headers(settings) -> dict[str, str]:
    username = (settings.fcc_broadband_api_username or "").strip()
    token = (settings.fcc_public_map_data_apis or "").strip()
    if not username or not token:
        raise SystemExit("Set FCC_BROADBAND_API_USERNAME and FCC_PUBLIC_MAP_DATA_APIS in .env")
    return {"username": username, "hash_value": token, "user-agent": "play/0.0.0"}


def _latest_availability_date(settings) -> str:
    import httpx
    r = httpx.get(f"{FCC_BASE}/map/listAsOfDates", headers=_auth_headers(settings), timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    if data.get("status") != "successful" or not data.get("data"):
        raise SystemExit("listAsOfDates failed or empty")
    dates = [item["as_of_date"] for item in data["data"] if item.get("data_type") == "availability"]
    return max(dates)


def _list_availability_files(settings, as_of_date: str, category: str, subcategory: str, state_name: str = "") -> list[dict]:
    import httpx
    params = {"category": category, "subcategory": subcategory, "technology_type": "Fixed Broadband"}
    r = httpx.get(
        f"{FCC_BASE}/map/downloads/listAvailabilityData/{as_of_date}",
        headers=_auth_headers(settings),
        params=params,
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("status") != "successful":
        raise SystemExit(f"listAvailabilityData failed: {data.get('message', data)}")
    files = data.get("data") or []
    if state_name:
        state_lower = state_name.strip().lower()
        files = [f for f in files if (f.get("state_name") or "").strip().lower() == state_lower]
    return files


def _download_file(settings, file_id: str) -> bytes:
    import httpx
    r = httpx.get(
        f"{FCC_BASE}/map/downloads/downloadFile/{DATA_TYPE_AVAILABILITY}/{file_id}",
        headers=_auth_headers(settings),
        timeout=DOWNLOAD_TIMEOUT,
    )
    r.raise_for_status()
    return r.content


def _extract_csv_rows(raw: bytes) -> list[dict]:
    rows: list[dict] = []
    if raw[:4] == b"PK\x03\x04" or raw[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(raw), "r") as zf:
            for info in sorted(zf.namelist()):
                if info.lower().endswith(".csv"):
                    with zf.open(info) as f:
                        text = f.read().decode("utf-8", errors="replace")
                    reader = csv.DictReader(io.StringIO(text))
                    rows = list(reader)
                    break
    else:
        text = raw.decode("utf-8", errors="replace")
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
    return rows


def _state_fips_from_usps(state_usps: str) -> str:
    """Approximate state FIPS from 2-letter USPS (for Census). Not exhaustive."""
    from app.services.census_geocoder import lat_lng_to_geography
    # Use a known point in state to get FIPS, or a small map
    # For script we can require state_fips input or use a dict for common states
    _MAP = {
        "CA": "06", "TX": "48", "FL": "12", "NY": "36", "PA": "42", "IL": "17", "OH": "39",
        "GA": "13", "NC": "37", "MI": "26", "NJ": "34", "VA": "51", "WA": "53", "AZ": "04",
        "MA": "25", "CO": "08", "IN": "18", "TN": "47", "MO": "29", "MD": "24", "WI": "55",
    }
    return _MAP.get((state_usps or "").strip().upper(), "")


def get_providers_for_county_from_rows(rows: list[dict], state_fips: str, county_fips: str) -> set[str]:
    """
    From Location Coverage rows, return set of brand_name where block_geoid starts with state_fips + county_fips.
    state_fips = 2 digits, county_fips = 3 digits (e.g. CA=06, Santa Clara=085 -> 06085).
    """
    prefix = (state_fips + county_fips).strip()
    if len(prefix) != 5:
        return set()
    providers: set[str] = set()
    for row in rows:
        bg = (row.get("block_geoid") or "").strip()
        if bg.startswith(prefix):
            name = (row.get("brand_name") or "").strip()
            if name:
                providers.add(name)
    return providers


def main():
    parser = argparse.ArgumentParser(description="FCC location/county-level fixed broadband providers")
    parser.add_argument("--state", required=True, help="State name (e.g. California) or USPS (e.g. CA)")
    parser.add_argument("--county-fips", default="", help="3-digit county FIPS (e.g. 085 for Santa Clara). If omitted, show sample rows.")
    parser.add_argument("--state-fips", default="", help="2-digit state FIPS (e.g. 06 for CA). Auto-derived from state name if possible.")
    parser.add_argument("--download-one", action="store_true", help="Download only one tech file (Other) for speed; otherwise all tech files for state.")
    parser.add_argument("--max-rows", type=int, default=0, help="If set, only process this many rows (for quick test).")
    args = parser.parse_args()

    from app.config import get_settings
    settings = get_settings()

    state_name = args.state.strip()
    state_fips = (args.state_fips or "").strip()
    if not state_fips and len(state_name) == 2:
        state_fips = _state_fips_from_usps(state_name)
    if not state_fips and state_name.lower() == "california":
        state_fips = "06"

    as_of_date = _latest_availability_date(settings)
    print(f"Latest as_of_date: {as_of_date}")
    print(f"State: {state_name}, state_fips: {state_fips or '(unknown)'}, county_fips: {args.county_fips or '(all)'}")
    print()

    files = _list_availability_files(settings, as_of_date, "State", "Location Coverage", state_name)
    if not files:
        print("No Location Coverage files for this state.")
        return
    if args.download_one:
        other = [f for f in files if "Other" in (f.get("file_name") or "")]
        files = other[:1] if other else files[:1]
    print(f"Downloading {len(files)} file(s)...")
    all_rows: list[dict] = []
    for f in files:
        file_id = str(f.get("file_id"))
        print(f"  {f.get('file_name')} (id={file_id})...")
        raw = _download_file(settings, file_id)
        rows = _extract_csv_rows(raw)
        if args.max_rows and args.max_rows > 0:
            rows = rows[: args.max_rows]
        all_rows.extend(rows)
    print(f"Total rows: {len(all_rows)}")
    if not all_rows:
        print("No rows.")
        return
    cols = list(all_rows[0].keys())
    print(f"Columns: {cols}")
    print()

    if args.county_fips and state_fips:
        county_fips = args.county_fips.strip()
        if len(county_fips) == 2:
            county_fips = "0" + county_fips
        providers = get_providers_for_county_from_rows(all_rows, state_fips, county_fips)
        print(f"Providers in state_fips={state_fips} county_fips={county_fips} (block_geoid prefix {state_fips}{county_fips}): {len(providers)}")
        for p in sorted(providers):
            print(f"  - {p}")
    else:
        # Show sample block_geoid and unique brands in first 10k rows
        sample_bg = set()
        sample_brands = set()
        for r in all_rows[: 10000]:
            bg = (r.get("block_geoid") or "").strip()
            if bg:
                sample_bg.add(bg[:5])
            b = (r.get("brand_name") or "").strip()
            if b:
                sample_brands.add(b)
        print("Sample block_geoid prefixes (first 5 = state+county FIPS):", sorted(sample_bg)[:15])
        print("Sample brand_name (first 10k rows):", sorted(sample_brands)[:20])
        print()
        print("To get providers for a county, run with --county-fips (e.g. 085 for Santa Clara, CA).")


if __name__ == "__main__":
    main()
