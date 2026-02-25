"""
Refresh the FCC BDC provider summary CSV from the FCC Public Data API (Option 2).

Flow:
  1. GET /map/listAsOfDates -> pick latest availability as_of_date
  2. GET /map/downloads/listAvailabilityData/{as_of_date} with category=Summary,
     subcategory=Provider Summary, technology_type=Fixed Broadband
  3. Pick file_id(s) from response (prefer national/single file; else merge multiple)
  4. GET /map/downloads/downloadFile/availability/{file_id} -> save (ZIP or CSV)
  5. If ZIP, extract CSV(s); normalize to columns our app expects: holding_company,
     unit_count_res, unit_count_bus (and optional provider_id, technology_code, etc.)
  6. Write final CSV to --output path (default: data/fcc/bdc_provider_summary_{as_of_date}.csv)

Requires FCC_BROADBAND_API_USERNAME and FCC_PUBLIC_MAP_DATA_APIS in .env.
Run: python scripts/refresh_fcc_csv_from_api.py [--output path]
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
DATA_TYPE_AVAILABILITY = "availability"


def _auth_headers(settings) -> dict[str, str]:
    username = (settings.fcc_broadband_api_username or "").strip()
    token = (settings.fcc_public_map_data_apis or "").strip()
    if not username or not token:
        raise SystemExit("Set FCC_BROADBAND_API_USERNAME and FCC_PUBLIC_MAP_DATA_APIS in .env")
    return {
        "username": username,
        "hash_value": token,
        "user-agent": "play/0.0.0",
    }


def _latest_availability_date(settings) -> str:
    """Return latest as_of_date for data_type=availability."""
    import httpx
    headers = _auth_headers(settings)
    r = httpx.get(f"{FCC_BASE}/map/listAsOfDates", headers=headers, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    if data.get("status") != "successful" or not data.get("data"):
        raise SystemExit("listAsOfDates failed or empty")
    dates = [item["as_of_date"] for item in data["data"] if item.get("data_type") == "availability"]
    if not dates:
        raise SystemExit("No availability as_of_dates in response")
    return max(dates)


def _list_availability_files(settings, as_of_date: str, category: str, subcategory: str) -> list[dict]:
    """List availability data files for given as_of_date and filters."""
    import httpx
    headers = _auth_headers(settings)
    params = {
        "category": category,
        "subcategory": subcategory,
        "technology_type": "Fixed Broadband",
    }
    r = httpx.get(
        f"{FCC_BASE}/map/downloads/listAvailabilityData/{as_of_date}",
        headers=headers,
        params=params,
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("status") != "successful":
        raise SystemExit(f"listAvailabilityData failed: {data.get('message', data)}")
    return data.get("data") or []


def _download_file(settings, file_id: str, data_type: str = DATA_TYPE_AVAILABILITY) -> bytes:
    """Download file by id; returns raw bytes (ZIP or CSV)."""
    import httpx
    headers = _auth_headers(settings)
    r = httpx.get(
        f"{FCC_BASE}/map/downloads/downloadFile/{data_type}/{file_id}",
        headers=headers,
        timeout=120,
    )
    r.raise_for_status()
    return r.content


def _extract_csv_from_bytes(raw: bytes) -> tuple[str | None, list[dict]]:
    """
    If raw is ZIP, extract first CSV and return (filename, rows).
    If raw looks like CSV, parse and return (None, rows).
    Returns rows as list of dicts (from csv.DictReader).
    """
    rows: list[dict] = []
    name: str | None = None
    if raw[:4] == b"PK\x03\x04" or raw[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(raw), "r") as zf:
            for info in zf.namelist():
                if info.lower().endswith(".csv"):
                    name = info
                    with zf.open(info) as f:
                        text = f.read().decode("utf-8", errors="replace")
                    reader = csv.DictReader(io.StringIO(text))
                    rows = list(reader)
                    break
        return (name, rows)
    # Assume CSV
    text = raw.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    rows = list(reader)
    return (None, rows)


def _normalize_to_app_format(rows: list[dict]) -> list[dict]:
    """
    Map FCC columns to the format our fcc_broadband.py expects:
    holding_company, unit_count_res, unit_count_bus (and optional provider_id, technology_code, etc.)
    """
    out: list[dict] = []
    for row in rows:
        # Common FCC column names (vary by file)
        name = (
            (row.get("holding_company") or row.get("provider_name") or row.get("Holding Company") or "").strip()
        )
        if not name:
            continue
        try:
            res = int(row.get("unit_count_res") or row.get("Unit_Count_Res") or row.get("Unit Count Res") or 0)
        except (TypeError, ValueError):
            res = 0
        try:
            bus = int(row.get("unit_count_bus") or row.get("Unit_Count_Bus") or row.get("Unit Count Bus") or 0)
        except (TypeError, ValueError):
            bus = 0
        out.append({
            "provider_id": row.get("provider_id") or row.get("Provider_ID") or "",
            "holding_company": name,
            "technology_code": row.get("technology_code") or row.get("Technology_Code") or "",
            "technology_code_desc": row.get("technology_code_desc") or row.get("Technology_Code_Desc") or "",
            "unit_count_res": res,
            "unit_count_bus": bus,
        })
    return out


def _write_csv(path: str, rows: list[dict], columns: list[str]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} rows to {path}")


def main():
    parser = argparse.ArgumentParser(description="Refresh FCC BDC provider summary CSV from API")
    parser.add_argument(
        "--output",
        default=None,
        help="Output CSV path (default: data/fcc/bdc_provider_summary_{as_of_date}.csv)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Only list files, do not download")
    args = parser.parse_args()

    from app.config import get_settings
    settings = get_settings()

    print("FCC BDC: refresh CSV from API")
    print("-" * 50)

    # 1) Latest availability date
    as_of_date = _latest_availability_date(settings)
    print(f"Latest availability as_of_date: {as_of_date}")

    # 2) List files: try Provider Summary first (national or per-state summary)
    for category, subcategory in [
        ("Summary", "Provider Summary"),
        ("Summary", "Provider List"),
        ("Provider", "Provider Summary"),
    ]:
        files = _list_availability_files(settings, as_of_date, category, subcategory)
        if files:
            print(f"  category={category}, subcategory={subcategory} -> {len(files)} file(s)")
            break
    else:
        # No filter: get all and pick Summary-like
        files = _list_availability_files(settings, as_of_date, "Summary", "Provider Summary")
        if not files:
            files = _list_availability_files(settings, as_of_date, "", "")  # no filter
            if files:
                # Filter to rows that look like provider summary (have provider_name or holding_company)
                files = [f for f in files if f.get("provider_name") or f.get("category") == "Summary"][:50]
        if not files:
            raise SystemExit("No availability files found for Provider Summary / Provider List.")

    # Prefer single national file (no state or first)
    if len(files) == 1:
        chosen = files
    else:
        national = [f for f in files if not (f.get("state_name") or "").strip() or (f.get("state_name") or "").strip().lower() == "national"]
        chosen = national[:1] if national else files[:1]
    file_id = str(chosen[0].get("file_id"))
    file_name = chosen[0].get("file_name") or f"file_{file_id}"
    print(f"Selected file_id={file_id} file_name={file_name}")

    if args.dry_run:
        print("Dry run: not downloading. Remove --dry-run to download and write CSV.")
        return

    # 3) Download
    print("Downloading...")
    raw = _download_file(settings, file_id)
    print(f"Downloaded {len(raw)} bytes")

    # 4) Extract CSV from ZIP or raw CSV
    name_inside, rows = _extract_csv_from_bytes(raw)
    if name_inside:
        print(f"Extracted CSV from ZIP: {name_inside}")
    if not rows:
        raise SystemExit("No CSV rows extracted. File may be empty or different format.")

    print(f"Parsed {len(rows)} rows. Sample columns: {list(rows[0].keys())[:10]}")

    # 5) Normalize to app format and aggregate by holding_company for output
    normalized = _normalize_to_app_format(rows)
    if not normalized:
        raise SystemExit("No rows with holding_company/provider name. Check column mapping.")

    # Aggregate by holding_company (sum units) so we have one row per provider with total units
    totals: dict[str, dict] = {}
    for r in normalized:
        h = r["holding_company"]
        if h not in totals:
            totals[h] = {**r, "unit_count_res": 0, "unit_count_bus": 0}
        totals[h]["unit_count_res"] += r["unit_count_res"]
        totals[h]["unit_count_bus"] += r["unit_count_bus"]
    aggregated = list(totals.values())

    # 6) Write
    out_path = args.output
    if not out_path:
        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        out_path = os.path.join(root, "data", "fcc", f"bdc_provider_summary_{as_of_date}.csv")
    columns = ["provider_id", "holding_company", "technology_code", "technology_code_desc", "unit_count_res", "unit_count_bus"]
    _write_csv(out_path, aggregated, columns)

    print("Done. To use this file, set in .env: FCC_BROADBAND_CSV_PATH=" + os.path.abspath(out_path))
    print("Or replace your existing BDC CSV file with this path.")


if __name__ == "__main__":
    main()
