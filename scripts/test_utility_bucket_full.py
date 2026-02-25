"""
Run the full Utility Bucket pipeline (same order as app: Census → Electric+gas → Water → FCC CSV → fallback).

Test data: 1 Infinite Loop, Cupertino, CA 95014 (matches test property 25).

Flow (see docs/UTILITY_BUCKET.md):
  1. Census Geocoder: lat/lng → state, county
  2. Electric + gas: Rewiring America (ZIP), NREL (lat/lon) if needed
  3. Water: state + county + city → EPA SDWIS CSV
  4. Internet: FCC BDC provider summary CSV (national)
  5. Full bucket: lookup_utility_providers() → all providers + authority letters

Run from project root: python scripts/test_utility_bucket_full.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env")))

# Test data: 1 Infinite Loop, Cupertino, CA 95014
TEST_LAT = 37.3331
TEST_LON = -122.02889
TEST_ZIP = "95014"
TEST_CITY = "Cupertino"
TEST_STATE = "CA"
TEST_ADDRESS = "1 Infinite Loop, Cupertino, CA 95014"


def main():
    print("=" * 60)
    print("UTILITY BUCKET – FULL PIPELINE TEST")
    print("Test location:", TEST_ADDRESS)
    print("lat=%s, lon=%s, zip=%s, city=%s, state=%s" % (TEST_LAT, TEST_LON, TEST_ZIP, TEST_CITY, TEST_STATE))
    print("=" * 60)

    state_abbrev: str | None = None
    county_name: str | None = None

    # --- Step 1: Census Geocoder (lat/lng → state, county) ---
    print("\n[STEP 1] Census Geocoder: lat/lng → state, county")
    print("-" * 40)
    from app.services.census_geocoder import lat_lng_to_geography
    geo = lat_lng_to_geography(TEST_LAT, TEST_LON)
    if geo:
        state_abbrev = geo.state_abbreviation
        county_name = geo.county_name
        print("  State (from geocoder):", state_abbrev)
        print("  County (from geocoder):", county_name)
    else:
        state_abbrev = TEST_STATE
        county_name = None
        print("  (Census failed; using test state=%s)" % TEST_STATE)

    # --- Step 2: Electric + gas (Rewiring America, then NREL if needed) ---
    print("\n[STEP 2] Electric + gas: Rewiring America (ZIP) then NREL (lat/lon)")
    print("-" * 40)
    from app.services.utility_lookup import _fetch_rewiring_america, _fetch_nrel_electric
    ra = _fetch_rewiring_america(TEST_ZIP, TEST_ADDRESS)
    print("  Rewiring America (electric/gas):", len(ra))
    for r in ra[:5]:
        print("   -", r.get("name"), "(%s)" % r.get("type"))
    if not any((x.get("type") or "").lower() == "electric" for x in ra):
        nrel = _fetch_nrel_electric(TEST_LAT, TEST_LON)
        print("  NREL (electric):", len(nrel))
        for n in nrel[:5]:
            print("   -", n.get("name"))

    # --- Step 3: Water (state + county + city from geocoder → EPA CSV) ---
    print("\n[STEP 3] Water: state + county + city → EPA SDWIS CSV")
    print("-" * 40)
    from app.services.water_lookup import lookup_water_providers
    from pathlib import Path
    csv_path = Path(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "CSV.csv")))
    water = lookup_water_providers(state_abbrev or TEST_STATE, city=TEST_CITY, county_name=county_name, csv_path=csv_path)
    print("  Water providers found:", len(water))
    for w in water[:5]:
        print("   -", w.get("name"), w.get("contact_phone") or "")

    # --- Step 4: Internet (FCC BDC CSV, national) ---
    print("\n[STEP 4] Internet: FCC BDC provider summary CSV (national)")
    print("-" * 40)
    from app.services.fcc_broadband import fetch_fcc_providers
    fcc = fetch_fcc_providers(0.0, 0.0)  # lat/lon ignored; CSV is national
    print("  Internet providers found:", len(fcc))
    for p in fcc[:5]:
        print("   -", p.get("name"))

    # --- Step 5: Full bucket (same as app: lookup_utility_providers) ---
    print("\n[STEP 5] Full Utility Bucket: lookup_utility_providers()")
    print("-" * 40)
    from app.services.utility_lookup import lookup_utility_providers, generate_authority_letters
    providers = lookup_utility_providers(
        zip_code=TEST_ZIP,
        lat=TEST_LAT,
        lon=TEST_LON,
        address=TEST_ADDRESS,
        city=TEST_CITY,
        state_abbreviation=state_abbrev or TEST_STATE,
    )
    print("  Total providers in bucket:", len(providers))
    by_type: dict[str, list] = {}
    for p in providers:
        by_type.setdefault(p.provider_type, []).append(p.name)
    for ptype, names in sorted(by_type.items()):
        print("   %s: %s" % (ptype, ", ".join(names[:5]) + (" ..." if len(names) > 5 else "")))

    letters = generate_authority_letters(providers, TEST_ADDRESS, "Test Property")
    print("  Authority letters generated:", len(letters))
    if letters:
        print("\n  Sample authority letter (first 400 chars):")
        print("  " + "-" * 36)
        print("  " + letters[0][1][:400].replace("\n", "\n  ") + ("..." if len(letters[0][1]) > 400 else ""))
        print("  " + "-" * 36)

    print("\n" + "=" * 60)
    print("DONE. Pipeline matches app: Census → Electric+gas → Water → FCC CSV → fallback.")
    print("=" * 60)


if __name__ == "__main__":
    main()
