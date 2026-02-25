"""
One-off: run the same utility lookup as the API for 1 Infinite Loop Cupertino.
Usage: from project root, python scripts/check_utility_cupertino.py
"""
from pathlib import Path
import sys

# Load .env and allow app imports
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from dotenv import load_dotenv
load_dotenv(root / ".env")

from app.services.smarty import verify_address
from app.services.utility_lookup import lookup_utility_providers

def main():
    street = "1 Infinite Loop"
    city = "Cupertino"
    state = "CA"
    zip_code = "95014"

    print("=== Address verification (Smarty) ===")
    result = verify_address(street=street, city=city, state=state, zipcode=zip_code)
    if not result:
        print("Smarty returned no result; using raw address for lookup.")
        address = f"{street}, {city}, {state} {zip_code}"
        lat, lon = None, None
        zip5 = zip_code
        res_city, res_state = city, state
    else:
        address = f"{result.delivery_line_1}, {result.city_name}, {result.state_abbreviation} {result.zipcode}"
        lat, lon = result.latitude, result.longitude
        zip5 = result.zipcode or zip_code
        res_city = result.city_name
        res_state = result.state_abbreviation
        print(f"Standardized: {address}")
        print(f"Lat/Lon: {lat}, {lon}")

    print("\n=== Utility lookup (same as API: Rewiring America for electric/gas, water, internet) ===")
    providers = lookup_utility_providers(
        zip_code=zip5,
        lat=lat,
        lon=lon,
        address=address,
        city=res_city,
        state_abbreviation=res_state,
    )

    by_type: dict[str, list[str]] = {}
    for p in providers:
        by_type.setdefault(p.provider_type, []).append(p.name)

    for utype in ("electric", "gas", "water", "internet"):
        names = by_type.get(utype) or []
        print(f"\n{utype.upper()}: {len(names)} provider(s)")
        for n in names:
            print(f"  - {n}")

    print("\n--- Raw list (name, type) ---")
    for p in providers:
        print(f"  {p.provider_type}: {p.name}")

if __name__ == "__main__":
    main()
