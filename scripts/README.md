# Scripts (deployment set)

For deployment, only these scripts are kept:

## List users in DB

- **`list_user_emails.py`** — List all user emails (and roles) from the database.  
  Run from project root: `python scripts/list_user_emails.py`

## Background jobs

- **`run_utility_provider_jobs.py`** — Run utility provider cache/population jobs.  
  Run: `python -m scripts.run_utility_provider_jobs [all|water|internet_bdc|fcc_internet|sdwa_water|pending_verify]`  
  Options: `--from-state FIPS` (fcc_internet), `--retry-files FILE_ID ...` (fcc_internet).

- **`run_sdwa_water_job.py`** — Run SDWA water merge job (EPA bulk → water_provider_cache).  
  Run: `python -m scripts.run_sdwa_water_job`

---

## Database schema (no migration scripts)

The schema source of truth is **`app.models`**. On startup, `Base.metadata.create_all(bind=engine)` creates all tables and columns. For a **new (empty) database**, no migration scripts are needed—just set `DATABASE_URL` and start the app. See `docs/DEPLOYMENT_DATASETS_AND_SCRIPTS.md` and `docs/BACKGROUND_JOBS.md` for datasets and job documentation.
