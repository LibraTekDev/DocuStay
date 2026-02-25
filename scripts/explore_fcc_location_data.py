"""
Explore FCC BDC location- or geography-level availability data (Option B).

Goals:
  - List files for Location Coverage, Raw Coverage, and geography summaries (state/county level).
  - Download a sample file (e.g. one state) and print schema + sample rows to see if we have
    block/county/coordinates + provider for precise or county-level lookup.
  - No cache for now; raw API exploration.

Requires FCC_BROADBAND_API_USERNAME and FCC_PUBLIC_MAP_DATA_APIS in .env.

Usage:
  python scripts/explore_fcc_location_data.py                    # list all geography/location file types
  python scripts/explore_fcc_location_data.py --download State "Location Coverage" --state "California"
  python scripts/explore_fcc_location_data.py --download State "Provider Summary by Geography Type" --state "California"
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
DOWNLOAD_TIMEOUT = 300  # large files
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
    if not dates:
        raise SystemExit("No availability as_of_dates")
    return max(dates)


def _list_availability_files(settings, as_of_date: str, category: str = "", subcategory: str = "", state_name: str = "") -> list[dict]:
    import httpx
    params = {"technology_type": "Fixed Broadband"}
    if category:
        params["category"] = category
    if subcategory:
        params["subcategory"] = subcategory
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


def _download_file(settings, file_id: str, data_type: str = DATA_TYPE_AVAILABILITY) -> bytes:
    import httpx
    r = httpx.get(
        f"{FCC_BASE}/map/downloads/downloadFile/{data_type}/{file_id}",
        headers=_auth_headers(settings),
        timeout=DOWNLOAD_TIMEOUT,
    )
    r.raise_for_status()
    return r.content


def _extract_first_csv(raw: bytes) -> tuple[str | None, list[dict], list[str] | None]:
    """Extract first CSV from ZIP or parse as CSV. Returns (filename, rows, column_list)."""
    rows: list[dict] = []
    columns: list[str] | None = None
    name: str | None = None
    if raw[:4] == b"PK\x03\x04" or raw[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(raw), "r") as zf:
            for info in sorted(zf.namelist()):
                if info.lower().endswith(".csv"):
                    name = info
                    with zf.open(info) as f:
                        text = f.read().decode("utf-8", errors="replace")
                    reader = csv.DictReader(io.StringIO(text))
                    columns = reader.fieldnames or []
                    rows = list(reader)
                    break
        return (name, rows, columns)
    text = raw.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    columns = reader.fieldnames or []
    rows = list(reader)
    return (None, rows, columns)


def main():
    parser = argparse.ArgumentParser(description="Explore FCC location/geography-level availability data")
    parser.add_argument("--download", nargs=2, metavar=("CATEGORY", "SUBCATEGORY"),
                        help="Download one file: category (e.g. State, Summary) and subcategory (e.g. 'Location Coverage')")
    parser.add_argument("--state", default="", help="Filter list/download to this state name (e.g. California)")
    parser.add_argument("--max-rows", type=int, default=5, help="Max sample rows to print (default 5)")
    parser.add_argument("--max-files", type=int, default=15, help="Max file list rows when listing (default 15)")
    args = parser.parse_args()

    from app.config import get_settings
    settings = get_settings()

    as_of_date = _latest_availability_date(settings)
    print(f"Latest availability as_of_date: {as_of_date}")
    print()

    if args.download:
        category, subcategory = args.download
        print(f"Listing files: category={category!r}, subcategory={subcategory!r}, state={args.state or '(any)'}")
        files = _list_availability_files(settings, as_of_date, category, subcategory, args.state.strip() or None)
        if not files:
            print("No files found. Try without --state or different category/subcategory.")
            return
        # Prefer single file or first when filtered by state
        chosen = files[0]
        file_id = str(chosen.get("file_id"))
        print(f"Downloading file_id={file_id} ({chosen.get('file_name')}, state={chosen.get('state_name')})...")
        raw = _download_file(settings, file_id)
        print(f"Downloaded {len(raw)} bytes")
        name, rows, columns = _extract_first_csv(raw)
        if name:
            print(f"Extracted CSV from ZIP: {name}")
        if not rows:
            print("No CSV rows found.")
            return
        print(f"Columns ({len(columns or [])}): {columns}")
        print(f"Total rows: {len(rows)}")
        print("Sample rows:")
        for i, row in enumerate(rows[: args.max_rows]):
            # Show first 8-10 keys to fit
            keys = list(row.keys())[:10]
            sample = {k: (str(row.get(k))[:40] if row.get(k) else "") for k in keys}
            print(f"  {i+1}. {sample}")
        return

    # List only: show what's available for location/geography
    combos = [
        ("State", "Location Coverage"),
        ("State", "Raw Coverage"),
        ("State", "Provider Summary by Geography Type"),
        ("State", "Summary by Geography Type - Other Geographies"),
        ("State", "Summary by Geography Type - Census Place"),
        ("Summary", "Provider Summary by Geography Type"),
        ("Summary", "Summary by Geography Type - Other Geographies"),
    ]
    print("Listing geography/location-related file types (Fixed Broadband):")
    print("-" * 60)
    for category, subcategory in combos:
        files = _list_availability_files(settings, as_of_date, category, subcategory)
        print(f"\n  category={category!r}, subcategory={subcategory!r} -> {len(files)} file(s)")
        for f in files[: args.max_files]:
            state_name = (f.get("state_name") or "").strip() or "(national)"
            print(f"    file_id={f.get('file_id')} state={state_name} file_name={f.get('file_name')}")
        if len(files) > args.max_files:
            print(f"    ... and {len(files) - args.max_files} more")
    print()
    print("To download and inspect a file, run:")
    print('  python scripts/explore_fcc_location_data.py --download State "Location Coverage" --state California')
    print('  python scripts/explore_fcc_location_data.py --download State "Provider Summary by Geography Type" --state California')


if __name__ == "__main__":
    main()
