# Scripts

## Database schema: built from models (no migrations for new DBs)

**The schema source of truth is `app.models`.** When the app starts, `Base.metadata.create_all(bind=engine)` runs and creates all tables with the **full current schema**. So:

- **New database:** Create the DB (e.g. empty PostgreSQL database), set `DATABASE_URL`, and start the app. All tables and columns are created automatically. **You do not need to run any `migrate_*.py` scripts.**

- **Existing database:** If the database was created from an older version of the code (before some columns or tables were added to the models), run the relevant `migrate_*.py` script once to add missing columns/constraints, or run `migrate_all_tables.py` to sync missing columns from the current models.

### Migration scripts (for existing DBs only)

| Script | What it adds / does |
|--------|----------------------|
| `migrate_stays_revoked_at.py` | `stays.revoked_at` |
| `migrate_stays_checked_out_cancelled.py` | `stays.checked_out_at`, `stays.cancelled_at` |
| `migrate_properties_usat_token.py` | `properties.usat_token`, `usat_token_state`, `usat_token_released_at` |
| `migrate_users_columns.py` | User columns: `full_name`, `phone`, `state`, `city`, `country`, `created_at`, `updated_at`, `email_verified`, `email_verification_code`, `email_verification_expires_at` |
| `migrate_email_role_unique.py` | Drops unique on `users.email` only; adds `UNIQUE (email, role)` |
| `migrate_agreement_signature_dropbox.py` | `agreement_signatures.dropbox_sign_request_id` |
| `migrate_audit_logs.py` | Creates `audit_logs` table |
| `migrate_occupancy_status.py` | `properties.occupancy_status`; `stays.occupancy_confirmation_response`, `occupancy_confirmation_responded_at` |
| `migrate_all_tables.py` | `create_all()` then adds any columns present in models but missing in existing tables |

All of the above are already reflected in the current models; the scripts exist only to update databases that were created before those changes were added to the code.
