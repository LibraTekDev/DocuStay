"""
Test FCC BDC provider summary CSV: load internet providers (national top-N).

Uses bdc_us_fixed_broadband_provider_summary_J25_17feb2026.csv from project root or data/fcc/.
BDC releases twice per year (January + June); e.g. J25 = June 2025.
Optional parquet build: python scripts/update_fcc.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".env")))

from app.services.fcc_broadband import fetch_fcc_providers, get_internet_provider_names

def main():
    lat = 37.3331
    lon = -122.02889
    print(f"Test: lat={lat}, lon={lon} (Cupertino, CA)\n")
    providers = fetch_fcc_providers(lat, lon)
    print(f"\nProviders: {len(providers)}")
    for p in providers[:10]:
        print(f"  - {p.get('name')}")
    names = get_internet_provider_names(lat, lon)
    print(f"\nNames list: {names[:10]}")

if __name__ == "__main__":
    main()
