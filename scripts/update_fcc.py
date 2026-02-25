"""
Import FCC BDC fixed broadband provider summary CSV into Parquet.

Supports:
- BDC file: bdc_us_fixed_broadband_provider_summary_J25_17feb2026.csv (column: holding_company)
- Legacy: provider_summary.csv in data/fcc/ (column: provider_name)

FCC BDC releases are twice per year (January + June). File naming: e.g. J25 = June 2025.
Run after downloading the latest BDC CSV. Parquet: ~10× faster lookup, smaller size.

Usage:
    python scripts/update_fcc.py

Looks for CSV in: project root, then data/fcc/
Writes: data/fcc/providers.parquet (normalized "provider" column)
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pandas as pd

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR = os.path.join(PROJECT_ROOT, "data", "fcc")
OUTPUT_PARQUET = os.path.join(DATA_DIR, "providers.parquet")

# Default BDC filename (project root or data/fcc/)
_DEFAULT_CSV_NAME = "bdc_us_fixed_broadband_provider_summary_J25_17feb2026.csv"
_LEGACY_CSV = os.path.join(DATA_DIR, "provider_summary.csv")


def _find_csv() -> str | None:
    for path in (
        os.path.join(PROJECT_ROOT, _DEFAULT_CSV_NAME),
        os.path.join(DATA_DIR, _DEFAULT_CSV_NAME),
        _LEGACY_CSV,
    ):
        if os.path.isfile(path):
            return path
    return None


def main():
    csv_path = _find_csv()
    if not csv_path:
        print("No BDC provider summary CSV found.")
        print(f"  Place {_DEFAULT_CSV_NAME} in project root or in data/fcc/")
        print(f"  Or place provider_summary.csv in data/fcc/")
        sys.exit(1)
    os.makedirs(DATA_DIR, exist_ok=True)
    df = pd.read_csv(csv_path)
    # Normalize to "provider" column (BDC uses holding_company; legacy uses provider_name)
    if "holding_company" in df.columns:
        df = df.rename(columns={"holding_company": "provider"})
    elif "provider_name" in df.columns:
        df = df.rename(columns={"provider_name": "provider"})
    else:
        print("CSV must have 'holding_company' or 'provider_name' column")
        sys.exit(1)
    df.to_parquet(OUTPUT_PARQUET, index=False)
    print(f"Wrote {OUTPUT_PARQUET} ({len(df)} rows) from {os.path.basename(csv_path)}")


if __name__ == "__main__":
    main()
