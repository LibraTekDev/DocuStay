"""
Build a seed CSV of electric utilities from EIA-861 (f8612024) for filling contact emails.

EIA-861 does not publish contact info; this script outputs one row per (utility name, state)
so you can add contact_email and contact_phone from state PUC pages or utility websites.

Usage:
  python scripts/build_electric_contact_seed.py

Output:
  data/utility_providers/electric_contact_seed.csv
  Columns: provider_name, state, source_identifier, contact_email, contact_phone

Then fill contact_email and contact_phone (e.g. in Excel or a text editor) and load
into your provider contact store. See docs/ELECTRIC_PROVIDER_EMAILS.md.
"""

from pathlib import Path
import csv

def main() -> None:
    try:
        import pandas as pd
    except ImportError:
        print("pip install pandas openpyxl")
        return

    root = Path(__file__).resolve().parents[1]
    base = root / "f8612024"
    utility_path = base / "Utility_Data_2024.xlsx"
    if not utility_path.exists():
        print(f"Not found: {utility_path}")
        return

    # States + Territories; header is row 1
    dfs = []
    for sheet in ["States", "Territories"]:
        try:
            df = pd.read_excel(utility_path, sheet_name=sheet, header=1)
            if "Utility Name" in df.columns and "State" in df.columns:
                dfs.append(df[["Utility Number", "Utility Name", "State"]].dropna(subset=["Utility Name", "State"]))
        except Exception as e:
            print(f"Skip sheet {sheet}: {e}")
    if not dfs:
        print("No data read from Utility_Data_2024.xlsx")
        return

    combined = pd.concat(dfs, ignore_index=True)
    combined["State"] = combined["State"].astype(str).str.strip().str.upper()
    combined["Utility Name"] = combined["Utility Name"].astype(str).str.strip()
    # Dedupe by (name, state) — same utility can appear in multiple NERC columns
    combined = combined.drop_duplicates(subset=["Utility Name", "State"], keep="first")
    combined = combined.sort_values(["State", "Utility Name"]).reset_index(drop=True)

    out_dir = root / "data" / "utility_providers"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "electric_contact_seed.csv"

    rows = []
    for _, r in combined.iterrows():
        rows.append({
            "provider_name": (r["Utility Name"] or "").strip(),
            "state": (r["State"] or "").strip(),
            "source_identifier": str(int(r["Utility Number"])) if pd.notna(r["Utility Number"]) else "",
            "contact_email": "",
            "contact_phone": "",
        })

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["provider_name", "state", "source_identifier", "contact_email", "contact_phone"])
        w.writeheader()
        w.writerows(rows)

    print(f"Wrote {len(rows)} rows to {out_path}")
    print("Next: fill contact_email and contact_phone from utility websites or state PUC; then load into your contact store.")
    print("See docs/ELECTRIC_PROVIDER_EMAILS.md.")

if __name__ == "__main__":
    main()
