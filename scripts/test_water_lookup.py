"""
Test water lookup from CSV.csv (EPA SDWIS) for California / Cupertino.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from pathlib import Path
from app.services.water_lookup import load_water_systems_csv, lookup_water_providers, reset_water_cache

def main():
    csv_path = Path(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "CSV.csv")))
    print(f"CSV path: {csv_path}, exists: {csv_path.exists()}\n")
    reset_water_cache()
    rows = load_water_systems_csv(csv_path)
    print(f"Loaded {len(rows)} active rows\n")

    print("Lookup: state=CA, city=Cupertino")
    providers = lookup_water_providers("CA", city="Cupertino", csv_path=csv_path)
    for p in providers[:5]:
        print(f"  - {p.get('name')} (phone: {p.get('contact_phone')})")

    if not providers:
        print("  (no match; trying state-only)")
        providers = lookup_water_providers("CA", csv_path=csv_path)
        print(f"  State-only: {len(providers)} results; first 3: {[p.get('name') for p in providers[:3]]}")

if __name__ == "__main__":
    main()
