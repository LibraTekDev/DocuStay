# Property Registration, Utilities & Provider Contact

Single reference for: property registration flow, utility providers and background jobs, how provider contact email reaches the UI, and contact policy. For **paid vs free and API keys**, see **docs/UTILITY_PROVIDERS_AND_KEYS.md**. For **API/dataset technical detail** (request/response, modules), see **docs/UTILITY_PROVIDERS_CURRENT.md**.

---

## 1. Registration steps (frontend)

| Step | Name     | What the user does |
|------|----------|--------------------|
| 1    | Location | Enter address (street, city, state, ZIP) and property name |
| 2    | Details  | Property type, bedrooms, primary residence |
| 3    | Proof    | Choose proof type (deed, tax bill, etc.) and upload file (PDF/image) |
| 4    | Utilities| See utility options for the address; select one provider per type (or add custom); submit |

User must upload proof in step 3 before continuing. On step 4 they submit to complete registration.

---

## 2. APIs and flow

### Step 4 – Loading utility options

**`POST /owners/verify-address-and-utilities`**  
Body: `{ street_address, city, state, zip_code? }`

Backend: **Smarty** (address + lat/lon) → **Census Geocoder** (state, county) → **utility lookup**: Rewiring America (electric/gas by ZIP), water (`water_provider_cache` → EPA ECHO → EPA SDWIS CSV fallback), internet (`internet_provider_cache` → `internet_bdc_fallback`). Response: `standardized_address`, `providers_by_type` (each list of `{ name, phone? }`; email is not in this response).

### Submit – Completing registration

1. **`POST /owners/properties`** – Create property (Smarty applied again).
2. **`POST /owners/properties/{id}/ownership-proof`** – Upload proof file.
3. **`POST /owners/properties/{id}/utilities`** – Save selected and pending (custom) providers.
   - **Selected** providers are written to PostgreSQL (property_utility_providers, authority_letters). For **water**: `get_water_provider_contact(name, state, city)` sets contact. For **electric, gas, internet**: `contact_email` null; if **SERPAPI_KEY** is set, a **background task** runs SerpApi to find and save contact email (headless browser on 403). Emails appear when the owner loads the property later.
   - **Pending** (user-added custom) providers are written to SQLite `pending_providers` with **property_id**, **state**, **county** (state/county from property Smarty address and Census geocoder). If **SERPAPI_KEY** is set, a **pending_verify** background job is enqueued to verify each via SerpApi and set **verification_status** (approved/rejected). Status is shown on the Utilities tab (Pending → In progress → Approved / Rejected).

### Provider contact lookup (automatic and manual)

- **Automatic:** After `POST .../utilities`, when `SERPAPI_KEY` is set and there are electric/gas/internet providers with no email, the backend enqueues `run_provider_contact_lookup_job(property_id)`.
- **Manual:** **`POST /owners/properties/{id}/provider-contacts/lookup`** (body optional: `{ provider_ids?: number[] }`). Returns **202 Accepted** and starts the same job. The Utilities tab shows a **"Look up contacts"** button when any electric/gas/internet provider has no email; clicking it calls this endpoint and the UI can refresh after a few seconds.

### Viewing utilities later

**`GET /owners/properties/{id}/utilities`** returns `providers` (with `contact_email`, `contact_phone`) and `authority_letters`. The UI shows a mailto link when `contact_email` is set, otherwise **"No email on file"**. Email is only what the backend stored; the frontend does not perform lookup.

---

## 3. Flow diagram

```
Step 1–3: Location, Details, Proof (user fills form, uploads proof)
                    ↓
Step 4:  POST /owners/verify-address-and-utilities
         → Smarty → Census → Rewiring America, Water, Internet (cache/API/CSV)
         → UI shows providers_by_type; user selects (or adds custom)
                    ↓
Submit:  POST /owners/properties → create property
         POST /owners/properties/{id}/ownership-proof → upload proof
         POST /owners/properties/{id}/utilities → save selected + pending
         → Water: get_water_provider_contact() → contact_email/phone set
         → Electric/gas/internet: contact_email null; if SERPAPI_KEY set
           → background task: run_provider_contact_lookup_job (SerpApi ± headless)
                    ↓
Later:   Owner opens property → Utilities tab
         GET /owners/properties/{id}/utilities
         → UI: mailto or "No email on file"
         Optional: "Look up contacts" → POST .../provider-contacts/lookup (202)
```

---

## 4. Utility providers by type and background jobs

| Type | Source(s) we use | Background job(s) |
|------|------------------|-------------------|
| Address / geography | Smarty, Census Geocoder | — |
| Electric | Rewiring America API | — |
| Gas | Rewiring America API | — |
| Water | `water_provider_cache`, EPA ECHO, EPA SDWIS CSV | **water_csv_job**, **sdwa_water_job** |
| Internet | `internet_provider_cache`, `internet_bdc_fallback` | **fcc_internet_job**, **internet_bdc_csv_job** |
| Provider contact email | Water cache (water); SerpApi (electric/gas/internet) | — (SerpApi runs as task after set utilities) |
| **Custom (user-added) providers** | SQLite `pending_providers` (name, state, county, verification_status) | **pending_verify** (SerpApi → approved/rejected); also enqueued when user adds custom providers at registration |

None of these jobs run at app startup; run them manually or via a scheduler.

**Logging:** When jobs are **scheduled** from the API, the router logs `[PropertyFlow] BACKGROUND JOB ENQUEUED: <job_name> ...`. When a job **runs**, it logs `[ProviderContact]` or `[PendingProviderVerify]` **BACKGROUND JOB START** and **BACKGROUND JOB COMPLETE** (with summary: updated count, approved/rejected, or skip reason). Grep for `BACKGROUND JOB` or `[ProviderContact]` / `[PendingProviderVerify]` to trace runs.

---

## 5. Provider contact policy and UI

- **Model:** `contact_email` and `contact_phone` are nullable on `property_utility_providers` and in the water cache. The API returns `contact_email: string | null`; the frontend shows a mailto link or **"No email on file"**.
- **When email is missing:** Treat as **"mail only"** (owner can send the authority letter by post or use the provider’s phone/address). We do not require email to save a provider.
- **Contact sources today:** **Water** – SQLite `water_provider_cache` (and water lookup), populated by `water_csv_job` and `sdwa_water_job` (SDWIS/SDWA CSV). **Electric / gas / internet** – SerpApi (search + snippets/pages; 403 → Playwright headless). Optional manual trigger: **"Look up contacts"** on the Utilities tab or `POST .../provider-contacts/lookup`.
- **Policy:** Avoid UtilityAPI for cost; use free/curated/SerpApi first. Use UtilityAPI only as a fallback when contact cannot be found otherwise.

---

## 6. Background jobs (detail)

Jobs populate SQLite caches or verify user-added providers. **Run:** `python -m scripts.run_utility_provider_jobs [all | water | sdwa_water | internet_bdc | fcc_internet | pending_verify]`. **`all`** runs water, internet_bdc, and fcc_internet (not sdwa_water or pending_verify).

### Summary

| Job | What it does | Target table | When to run | In `all`? |
|-----|--------------|--------------|-------------|-----------|
| **water** | Load EPA SDWIS-style CSV → water cache (full replace) | `water_provider_cache` | When you update the water CSV | Yes |
| **sdwa_water** | Merge EPA SDWA bulk CSV → water cache (contact email/phone) | `water_provider_cache` | Quarterly or when adding contact data | No |
| **internet_bdc** | Load FCC BDC provider summary CSV → national fallback | `internet_bdc_fallback` | When you update the BDC CSV | Yes |
| **fcc_internet** | Fetch FCC Location Coverage API → county-level providers | `internet_provider_cache` | Monthly or after FCC data refresh | Yes |
| **pending_verify** | Verify user-added providers via SerpApi → set verification_status (approved/rejected) | `pending_providers` | Enqueued when user adds custom providers; or run manually to catch up | No |

### 6.1 Water CSV job (`water`)

- **Purpose:** Full replace of `water_provider_cache` from a local EPA SDWIS-style CSV (e.g. `CSV.csv`). Saves contact email/phone if the CSV has `contactemail` / `EMAIL_ADDR` (and phone columns).
- **Config:** `WATER_CSV_PATH` (optional; default project root `CSV.csv`).

```bash
python -m scripts.run_utility_provider_jobs water
# Or: python -m app.utility_providers.water_csv_job
```

### 6.2 SDWA water job (`sdwa_water`)

- **Purpose:** Merge EPA SDWA bulk data into the water cache by PWSID; adds/updates contact email and phone from `SDWA_PUB_WATER_SYSTEMS.csv`. Does not remove existing rows missing from the CSV.
- **Config:** `WATER_SDWA_CSV_PATH` (optional; default `SDWA_latest_downloads/SDWA_PUB_WATER_SYSTEMS.csv` or project-root file).

```bash
python -m scripts.run_utility_provider_jobs sdwa_water
# Or: python -m scripts.run_sdwa_water_job [--csv path] [--download]
```

### 6.3 Internet BDC CSV job (`internet_bdc`)

- **Purpose:** Populate national fallback list from FCC BDC provider summary CSV.
- **Config:** `FCC_BROADBAND_CSV_PATH` (optional; auto-detected in project root or `data/fcc/`).

```bash
python -m scripts.run_utility_provider_jobs internet_bdc
# Or: python -m app.utility_providers.internet_bdc_csv_job
```

### 6.4 FCC internet job (`fcc_internet`)

- **Purpose:** Download FCC Location Coverage (Fixed Broadband) by state, aggregate by county, upsert into `internet_provider_cache`. Target states: Florida, California, Texas, New York (configurable).
- **Config:** **Required** – `FCC_BROADBAND_API_USERNAME`, `FCC_PUBLIC_MAP_DATA_APIS`.

```bash
python -m scripts.run_utility_provider_jobs fcc_internet
# Options: --from-state 06 (resume), --retry-files <ids>
# Or: python -m app.utility_providers.fcc_internet_job
```

### 6.5 Pending provider verification job (`pending_verify`)

- **Purpose:** For user-added (custom) providers not in our list, we store them in SQLite `pending_providers` with name, state, county (from property address/Smarty/Census). This job calls SerpApi to search for the provider; if organic results match the name and look like an official/utility source, we set `verification_status = approved`, else `rejected`. Status is shown on the property Utilities tab (Pending → In progress → Approved / Rejected).
- **Trigger:** Automatically enqueued when the user adds custom providers at registration (`POST .../utilities` with `pending`). Can also be run manually to process any remaining pending rows.
- **Config:** `SERPAPI_KEY` (required for this job).

```bash
python -m scripts.run_utility_provider_jobs pending_verify
# Or: run_pending_provider_verification_job() in app (enqueued via BackgroundTasks when pending providers are added)
```

### Environment variables (jobs)

| Variable | Used by | Purpose |
|----------|---------|---------|
| `WATER_CSV_PATH` | water | SDWIS-style water CSV (default: project root `CSV.csv`) |
| `WATER_SDWA_CSV_PATH` | sdwa_water | Path to `SDWA_PUB_WATER_SYSTEMS.csv` or folder |
| `FCC_BROADBAND_CSV_PATH` | internet_bdc | BDC provider summary CSV path |
| `FCC_INTERNET_CACHE_PATH` | All jobs | SQLite DB path (default: `data/utility_providers/internet_cache.db`) |
| `FCC_BROADBAND_API_USERNAME`, `FCC_PUBLIC_MAP_DATA_APIS` | fcc_internet | FCC API credentials (required for this job) |
| `SERPAPI_KEY` | pending_verify | SerpApi key for provider verification (required for this job) |

---

## 7. Related docs

- **UTILITY_PROVIDERS_AND_KEYS.md** – Paid vs free, API keys, env vars for every source.
- **UTILITY_PROVIDERS_CURRENT.md** – Technical reference: request/response, modules, config for each API and dataset.
