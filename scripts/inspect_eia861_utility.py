"""Inspect EIA-861 Utility_Data and other files for column names (contact, email, phone, etc.)."""
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))

def main():
    try:
        import pandas as pd
    except ImportError:
        print("pip install pandas openpyxl")
        return
    base = root / "f8612024"
    if not base.exists():
        print("f8612024 folder not found")
        return
    # Focus on Utility_Data first (utility identification)
    utility_path = base / "Utility_Data_2024.xlsx"
    if not utility_path.exists():
        print("Utility_Data_2024.xlsx not found")
        return
    xl = pd.ExcelFile(utility_path)
    print("=== Utility_Data_2024.xlsx ===")
    print("Sheets:", xl.sheet_names)
    contact_keywords = ["contact", "email", "phone", "addr", "mail", "fax", "e-mail", "telephone"]
    for name in xl.sheet_names:
        df = pd.read_excel(utility_path, sheet_name=name, header=None)
        print(f"\n--- Sheet: {name} (first 5 rows, first 12 cols) ---")
        print(df.iloc[:5, :12].to_string())
        # also get all unique cell values that might be field names (row 0)
        row0 = df.iloc[0].astype(str).tolist()
        matching = [v for v in row0 if v and str(v) != "nan" and any(k in str(v).lower() for k in contact_keywords)]
        if matching:
            print("  >> Contact-related in row0:", matching)
    # Full column list from Utility_Data (header in row 1)
    df_states = pd.read_excel(utility_path, sheet_name="States", header=1)
    print("\n--- Utility_Data 'States' all columns ---")
    print(list(df_states.columns))
    contact_in_states = [c for c in df_states.columns if any(k in str(c).lower() for k in contact_keywords)]
    print("  >> Contact-related columns:", contact_in_states or "NONE")
    # EIA-861 Form (what they collect) - sheet names / labels
    form_path = base / "2024 EIA-861 Form.xlsx"
    if form_path.exists():
        try:
            xl_form = pd.ExcelFile(form_path)
            print("\n=== 2024 EIA-861 Form.xlsx (form structure) ===")
            print("Sheets:", xl_form.sheet_names)
            for name in xl_form.sheet_names[:3]:  # first 3 sheets
                df = pd.read_excel(form_path, sheet_name=name, header=None)
                # look for contact/email/phone in any cell
                s = df.astype(str).stack()
                contact_cells = s[s.str.lower().str.contains("contact|email|e-mail|phone|fax|address", na=False)].tolist()
                if contact_cells:
                    print(f"  Sheet '{name}' cells mentioning contact/email/phone/address:", contact_cells[:15])
        except Exception as e:
            print("Form file:", e)
    # Also quick check other likely files
    for fname in ["Distribution_Systems_2024.xlsx", "Delivery_Companies_2024.xlsx", "Frame_2024.xlsx"]:
        path = base / fname
        if not path.exists():
            continue
        try:
            df = pd.read_excel(path, nrows=0)
            cols = list(df.columns)
            matching = [c for c in cols if any(k in str(c).lower() for k in contact_keywords)]
            print(f"\n=== {fname} ===")
            print("Columns:", cols[:30], "..." if len(cols) > 30 else "")
            if matching:
                print("  >> Contact-related:", matching)
        except Exception as e:
            print(f"\n{fname}: {e}")

if __name__ == "__main__":
    main()
