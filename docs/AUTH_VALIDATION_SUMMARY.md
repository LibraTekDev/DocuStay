# Auth Pages – Validation Summary

This document summarizes client-side validations on login and signup pages, and what was added in the latest pass.

---

## 1. `#login` (Owner / PM / Tenant / Guest Login)

| Check | Already there? | Added? |
|-------|----------------|--------|
| Email & password required (non-empty) | ✅ Yes | — |
| Email format valid | — | ✅ Yes |
| Invite link valid when role=tenant and link provided (DB: `invitationsApi.getDetails`) | ✅ Yes | — |

---

## 2. `#register` (Create Owner Account)

| Check | Already there? | Added? |
|-------|----------------|--------|
| Required: first name, last name, email, state, city | ✅ Yes | — |
| Email format valid | — | ✅ Yes |
| Phone required & valid format (E.164, 10–15 digits via `validatePhone`) | ✅ Yes | — |
| Password required | ✅ Yes | — |
| Password length ≥ 8 | ✅ Yes | — |
| Password & confirm match | ✅ Yes | — |
| Terms & Privacy agreed | ✅ Yes | — |

---

## 3. `#register/manager` (Register Manager Landing – paste invite)

| Check | Already there? | Added? |
|-------|----------------|--------|
| Invite link/code non-empty and extractable | ✅ Yes | — |
| Invite token valid in DB before continuing (`authApi.getManagerInvite`) | — | ✅ Yes |

---

## 4. `#register/manager/:token` (Property Manager Signup)

| Check | Already there? | Added? |
|-------|----------------|--------|
| Invite token validated on load (DB); invalid/expired shows error | ✅ Yes | — |
| Full name, email required | ✅ Yes | — |
| Email format valid | — | ✅ Yes |
| Phone optional; if provided, validated with `validatePhone` | ✅ Yes | — |
| Password required | ✅ Yes | — |
| Password length ≥ 8 | ✅ Yes | — |
| Password & confirm match | ✅ Yes | — |

---

## 5. `#guest-signup` and `#guest-signup/tenant` (Tenant / Guest Signup)

| Check | Already there? | Added? |
|-------|----------------|--------|
| All required fields non-empty (name, email, phone, password, confirm, address, city, state, zip) | ✅ Yes | — |
| All acknowledgments checked (terms, privacy, guest status, no tenancy, vacate) | ✅ Yes | — |
| Email format valid | — | ✅ Yes |
| Password length ≥ 8 | — | ✅ Yes |
| Password & confirm match | — | ✅ Yes |
| Phone valid (`validatePhone`) | ✅ Yes | — |
| When invitation link present (code length ≥ 5): invite valid in DB (`invitationsApi.getDetails`), not expired, not used | — | ✅ Yes |

---

## 6. Register from invite (e.g. `#register-from-invite/:code`)

| Check | Already there? | Added? |
|-------|----------------|--------|
| Invite valid on load (DB); invalid/expired/used blocks or notifies | ✅ Yes | — |
| Required fields + full address for guest | ✅ Yes | — |
| All acknowledgments checked | ✅ Yes | — |
| Agreement must be signed (`agreementSignatureId`) | ✅ Yes | — |
| Email format valid | — | ✅ Yes |
| Password length ≥ 8 | — | ✅ Yes |
| Password & confirm match | — | ✅ Yes |
| Phone valid (`validatePhone`) | ✅ Yes | — |

---

## Shared validation rules

- **Required fields**: Cannot be empty (trimmed); specific messages per page/field where applicable.
- **Password**: Minimum 8 characters; password and confirm must match (on all pages that have both).
- **Phone**: `validatePhone()` – required where phone is required; optional fields validated only when non-empty (E.164-style, 10–15 digits).
- **Email**: Regex `^[^\s@]+@[^\s@]+\.[^\s@]+$` used on all pages that collect email.
- **Invite link**:
  - **Login (tenant)**: If invite code present, `invitationsApi.getDetails` used; submit blocked if invalid or no longer valid/used.
  - **Register Manager Landing**: Before navigating to `register/manager/:token`, `authApi.getManagerInvite(token)` used; invalid/expired shows error.
  - **Guest Signup**: If invite code length ≥ 5, `invitationsApi.getDetails` used before submit; invalid/expired/used blocks submit.
- **Acknowledgments**: All required checkboxes (terms, privacy, guest status, no tenancy, vacate) must be checked before submit where applicable.

---

## Files changed (this pass)

- `frontend/pages/Auth/Login.tsx` – email format
- `frontend/pages/Auth/RegisterOwner.tsx` – email format
- `frontend/pages/Auth/RegisterManager.tsx` – email format
- `frontend/pages/Auth/RegisterManagerLanding.tsx` – invite token validated via API before navigate
- `frontend/pages/Guest/GuestLogin.tsx` – email format
- `frontend/pages/Guest/GuestSignup.tsx` – email format, password length & match, invite validity (DB) when code present
- `frontend/pages/Guest/RegisterFromInvite.tsx` – email format, password length & match
