"""
Test EPA ECHO Drinking Water REST API – get_systems + get_qid.

No API key required. ECHO returns water systems by state/county; we need PWS name and phone
for the utility bucket. Run: python scripts/test_epa_echo_water.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import httpx

_ECHO_BASE = "https://echodata.epa.gov/echo"


def get_systems(state: str, county: str | None = None, city: str | None = None) -> dict | None:
    """Call get_systems; returns JSON with QueryID and row counts."""
    params: dict = {"p_st": state.strip().upper()[:2], "output": "JSON"}
    if county and str(county).strip():
        params["p_cty"] = str(county).strip()
    if city and str(city).strip():
        params["p_city"] = str(city).strip()
    url = f"{_ECHO_BASE}/sdw_rest_services.get_systems"
    try:
        with httpx.Client(timeout=30.0) as client:
            r = client.get(url, params=params)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"get_systems failed: {e}")
        return None


def get_qid(qid: str, pageno: int = 1, timeout: float = 60.0) -> dict | None:
    """Fetch one page of water system results by QID."""
    url = f"{_ECHO_BASE}/sdw_rest_services.get_qid"
    try:
        with httpx.Client(timeout=timeout) as client:
            r = client.get(url, params={"qid": qid, "pageno": pageno, "output": "JSON"})
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"get_qid failed: {e}")
        return None


def main():
    print("EPA ECHO Drinking Water API test")
    print("-" * 50)
    # Use county filter to get fewer rows so get_qid is more likely to succeed
    print("State: CA, County: San Diego (smaller result set)")
    data = get_systems("CA", county="San Diego")
    if not data:
        print("No response from get_systems. Exiting.")
        sys.exit(1)

    res = data.get("Results") or {}
    msg = res.get("Message", "")
    qid = res.get("QueryID")
    query_rows = res.get("QueryRows", "0")
    print(f"Message: {msg}, QueryID: {qid}, QueryRows: {query_rows}")

    if not qid:
        print("No QueryID; cannot fetch results.")
        sys.exit(0)

    print("\nFetching first page of results (get_qid, 60s timeout)...")
    page = get_qid(str(qid), pageno=1, timeout=60.0)
    if not page:
        print("get_qid failed or timed out. ECHO may still be used with get_download for CSV.")
        sys.exit(1)

    # Response structure: Results.WaterSystems = list of system dicts
    results = page.get("Results") or page
    if isinstance(results, dict):
        for key, val in results.items():
            if isinstance(val, list) and val and isinstance(val[0], dict):
                cols = list(val[0].keys())
                print(f"\nFound {len(val)} system(s) in key '{key}'. All columns ({len(cols)}): {cols}")
                # Show a few rows; look for any with non-empty name
                for i, row in enumerate(val[:5]):
                    name = (row.get("PWSName") or row.get("pwsname") or "").strip() or "(no name)"
                    cities = (row.get("CitiesServed") or "") or ""
                    counties = (row.get("CountiesServed") or "") or ""
                    if name and name != "(no name)" and len(name) > 2:
                        print(f"  Sample row {i+1}: PWSName={name[:50]!r}  CitiesServed={str(cities)[:40]!r}  CountiesServed={str(counties)[:40]!r}")
                # Print one full row (first with a name) so user can see exact keys/values
                for row in val:
                    if (row.get("PWSName") or "").strip():
                        print("\n--- One full record (first 12 fields) ---")
                        keys = list(row.keys())[:12]
                        for k in keys:
                            print(f"  {k}: {row.get(k)}")
                        break
                break
        else:
            print("Raw Results keys:", list(results.keys()))
    else:
        print("Unexpected response structure:", type(results))

    print("\nDone. If you see water system names above, ECHO API is usable for the flow.")


if __name__ == "__main__":
    main()
