"""
Test utility provider lookup using property 25 data (1 Infinite Loop, Cupertino, CA 95014).

Uses same flow as app: Census → Rewiring America + NREL → Water CSV → FCC BDC CSV → fallback.
DRY_RUN=True: no API/DB calls; DRY_RUN=False: calls lookup and prints results.

Run: python scripts/test_utility_lookup.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env")))

# Test data from property 25 (1 Infinite Loop, Cupertino, CA 95014)
TEST_PROPERTY = {
    "zip_code": "95014",
    "lat": 37.3331,
    "lon": -122.02889,
    "address": "1 Infinite Loop, Cupertino, CA 95014",
    "city": "Cupertino",
    "state": "CA",
    "name": "1 Infinite Loop Cupertino, CA 95014 USA",
}

DRY_RUN = True  # Set False to run actual lookup


def main():
    from app.services.utility_lookup import lookup_utility_providers, generate_authority_letters

    print("Utility Provider Lookup Test (property 25 data)")
    print("-" * 50)
    print(f"Address: {TEST_PROPERTY['address']}")
    print(f"ZIP: {TEST_PROPERTY['zip_code']}  Lat: {TEST_PROPERTY['lat']}  Lon: {TEST_PROPERTY['lon']}")
    print()

    if DRY_RUN:
        print("DRY_RUN=True – no actual lookup. Set DRY_RUN=False to run.")
        print("Expected: electric/gas (Rewiring America), water (EPA CSV), internet (FCC BDC CSV top-N).")
        return

    providers = lookup_utility_providers(
        zip_code=TEST_PROPERTY["zip_code"],
        lat=TEST_PROPERTY["lat"],
        lon=TEST_PROPERTY["lon"],
        address=TEST_PROPERTY["address"],
        city=TEST_PROPERTY["city"],
        state_abbreviation=TEST_PROPERTY["state"],
    )

    if not providers:
        print("No providers found for this ZIP.")
        sys.exit(1)

    print(f"Found {len(providers)} provider(s):\n")
    for i, p in enumerate(providers, 1):
        print(f"  {i}. {p.name} ({p.provider_type})")
        print(f"     UtilityAPI ID: {p.utilityapi_id or '(none)'}  Phone: {p.phone or '(none)'}")

    letters = generate_authority_letters(providers, TEST_PROPERTY["address"], TEST_PROPERTY["name"])
    print("\nAuthority Letters generated:")
    for p, content in letters:
        print(f"\n  --- {p.name} ({p.provider_type}) ---")
        print(f"  {content[:200]}...")
    print("\nDone.")


if __name__ == "__main__":
    main()
