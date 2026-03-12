# Testing Guide: Roles + Personal Mode & Feature Impact Changes

## Personal vs. Business Mode – Scope Isolation

**Personal mode** (owners and on-site managers):
- Manage own properties and statuses, including multiple properties
- Mark one as primary residence, indicate statuses (vacant, away, inactive)
- Use resident features: presence (here/away), guest invites, guest/stay activity
- Guests and Invitations tabs visible; presence card for personal-mode units

**Business mode** (management scope only):
- Property status, occupancy, Shield Mode, billing, event ledger
- **No personal guest or stay activity is shown**
- Stays and invitations APIs return `[]` when `X-Context-Mode: business`
- Manager units: `occupied_by` and `invite_id` are omitted for privacy
- Guests and Invitations tabs hidden; presence features unavailable

The system enforces this isolation: once in business mode, the dashboard and APIs stay within management scope and do not expose personal guest/stay data.

---

## How to Test

### Prerequisites
- Backend running (e.g. `uvicorn app.main:app`) – schema created via `Base.metadata.create_all()` on startup
- Frontend running (e.g. `npm run dev`)
- Test users: Owner, Property Manager, Tenant, Guest
- Owner with at least one property
- Property Manager assigned to a property
- Tenant assigned to a unit
- Owner/Manager with `ResidentMode` for Personal Mode

---

## How to onboard a property manager in the app

**Yes, Personal Mode for property managers is implemented.** A manager gets Personal Mode only when the owner adds them as an **on-site resident** for a specific unit (see step 4 below).

### 1. Owner invites a manager

1. Log in as **Owner**.
2. Go to **My Properties** → open a property (Property Detail).
3. Click **Invite Manager** (near the top).
4. Enter the manager’s **email** → **Send invitation**.
5. The backend creates a `ManagerInvitation` and sends an email with a signup link:  
   `https://<your-app>/#register/manager/<token>`  
   (If email is not configured, the link is still created; you can copy it from logs or use the same token in the URL.)

### 2. Manager signs up (or logs in)

**New manager (first time):**

1. Open the link from the email (e.g. `/#register/manager/TOKEN`).
2. The app loads **RegisterManager**: form is pre-filled with the invited email and property name (from `GET /auth/manager-invite/{token}`).
3. Enter **full name**, **password** (and optional phone).
4. Submit → backend creates a **User** with role `property_manager`, creates a **PropertyManagerAssignment** (manager ↔ property), marks the invitation accepted, sends a welcome email.
5. Manager is logged in and redirected (typically to Manager Dashboard).

**Existing manager (already has a property_manager account):**

1. Open the same invite link.
2. If the email matches an existing property_manager user, they enter their **password** and submit.
3. Backend adds a **PropertyManagerAssignment** for this property to that user (no new user created).
4. Manager is logged in and can see the new property in their dashboard.

### 3. Manager uses the dashboard

- Manager goes to **Manager Dashboard** (e.g. `/#dashboard` when logged in as property_manager).
- Tabs: **Properties**, **Stays**, **Logs**, **Billing** (read-only).
- They see only **properties they are assigned to**; for each property they can view units, occupancy, invite tenants, and see logs/billing.

### 4. Optional: Give the manager Personal Mode (on-site resident)

If the manager **lives on-site** in one of the units:

1. As **Owner**, stay on **Property Detail** for that property.
2. In the **Assigned managers** card, find the manager.
3. For multi-unit properties: choose a **unit** from the dropdown (e.g. “Unit 101”) and click **Add as on-site**.
4. Backend creates a **ResidentMode** (mode = manager_personal) for that manager + unit.
5. When the manager next loads their dashboard, they see the **Business / Personal** mode switcher. In **Personal** mode they can set **Presence** (Here/Away) and invite guests for that unit like a resident.

### Test by Role

1. **Owner** – Business mode, Personal mode (if ResidentMode exists), Presence in Personal mode, Add multi-unit property, Revoke/initiate removal (no USAT wording)
2. **Property Manager** – Assigned properties, stays, logs, billing (read-only), invite tenant, Presence in Personal mode (if ResidentMode)
3. **Tenant** – Invite guest, guest history, invitations, Presence (with timestamps and guest authorization during away)
4. **Guest** – Existing flows unchanged (SignAgreement success says "stay confirmed", no USAT)

---

## Tenant and Guest Logic (Summary)

**Tenant logic**
- Tenants occupy a **specific unit** (assigned via TenantAssignment).
- Tenants can: **view their assigned unit**, **invite guests** (same UI and API as owners/managers: shared `InviteGuestModal` and `POST /owners/invitations` with `unit_id`), **manage guest authorizations** (presence/away and “guests authorized during away”), **view guest history**, and **set presence (here/away)**.
- Tenants **cannot** invite other tenants, manage other units, or manage properties. Invite-tenant endpoints require owner or property manager only; the tenant dashboard exposes only “Invite guest.”

**Guest logic**
- Guests are invited by tenants, owners, or property managers.
- Guests can: **view their authorized stay**, **see stay status**, **access QR verification**, and **view their audit trail**.
- Guests **cannot** access tenant or property management; access is limited to their authorized stay.

---

## How to onboard a tenant and test tenant flows

Tenants are invited by **Property Manager** (or owner) to a **specific unit**. The tenant receives a link, signs up (email verification + agreement), and gets a **TenantAssignment** to that unit. They then use the **Tenant Dashboard** (invite guests via the same Invite Guest modal as owners/managers, presence, guest history).

### Prerequisites for tenant testing

- Backend and frontend running.
- At least one **property** with a **vacant unit**.
- A **Property Manager** assigned to that property (see “How to onboard a property manager” above).

---

### 1. Create a tenant invitation (as Manager)

1. Log in as **Property Manager**.
2. Go to **Manager Dashboard** → **Properties** → open the property that has a vacant unit.
3. In the **Units** section, find a unit with status **Vacant**.
4. Click **Invite tenant** (or “Invite tenant” next to that unit).
5. In the modal, enter:
   - **Tenant name** (e.g. “Jane Tenant”).
   - **Tenant email** (e.g. `tenant@example.com`) – the tenant will register with this email.
   - **Lease start date** and **Lease end date** (YYYY-MM-DD).
6. Submit → the app creates an invitation and shows an **invite link**, e.g.  
   `https://<your-app>/#invite/INV-XXXXXXXX`  
   Copy this link (or use `#register-from-invite/INV-XXXXXXXX`).

**Backend:** Creates an `Invitation` with `token_state=BURNED`, `unit_id` set, and `guest_email` = tenant email. No Stay is created until the tenant completes signup.

---

### 2. Tenant signup (first time)

1. **Open the invite link** in a new/incognito window (or different browser):  
   `#invite/INV-XXXXXXXX` or `#register-from-invite/INV-XXXXXXXX`.
2. You should see the **invitation page** with “Tenant Invitation” and “You’re invited as a tenant.” The **email** field should be **pre-filled** with the address the manager entered.
3. Fill in:
   - **Full name**
   - **Email** (must match the invite email if the manager set it)
   - **Phone**
   - **Password** and **Confirm password**
   - Check all **acknowledgments** (guest status, no tenancy, vacate, terms, privacy).
4. Click **Review & Sign Agreement** → complete the **Dropbox Sign** flow (same agreement content as guest).
5. Click **Create Account & Accept Tenant Invitation**.
6. **If email verification is enabled (e.g. Mailgun):**
   - You get “Check your email for the verification code.”
   - Enter the **6-digit code** on the verify page → Submit.
   - You are logged in and redirected to **Tenant Dashboard** (`#tenant-dashboard`).
7. **If email verification is disabled:** You are logged in immediately and redirected to **Tenant Dashboard**.

**Backend:** User is created with `role=tenant`; **TenantAssignment** is created for the invitation’s unit and lease dates; invitation status is set to `accepted`.

---

### 3. Tenant login (existing tenant)

1. Go to `#login/tenant` (or use the app’s Tenant / Guest login entry point with “Sign in” for tenants).
2. Enter the **email** and **password** used when the tenant signed up.
3. Submit → you are logged in and redirected to **Tenant Dashboard** (`#tenant-dashboard`).

**Direct URLs:**

- Tenant login: `#login/tenant`
- After login, app redirects to: `#tenant-dashboard`

---

### 4. Tenant dashboard – what to test

Once on **Tenant Dashboard** (`#tenant-dashboard`):

| Area | What to do | Expected |
|------|------------|----------|
| **Assigned unit** | Load dashboard | Card shows property name, unit label (e.g. “Unit 1”), and address. If no unit assigned, message: “No unit assigned yet.” |
| **Invite a guest** | Click **Invite guest** | InviteGuestModal opens with **no property selector** (unit is fixed). Enter guest name, check-in/check-out dates → submit. Invitation link is generated; same agreement flow as owner/manager. |
| **Your invitations** | After inviting a guest | List of invitations you created; status (pending/ongoing/cancelled). **Cancel** button for pending/ongoing. |
| **Guest history** | After a guest accepts and has a stay | Section “Guest history” lists stays (guest name, property, dates, “checked out” if applicable). |
| **Presence** | Toggle **Set to Away** | Confirmation with “Guests authorized during this period” checkbox. After confirming, status shows “Away” and “Away since &lt;date&gt;”. Toggle back to **Set to Present** to clear away. |
| **Presence load** | Refresh the page | Presence state (present/away, timestamps, guests authorized) loads from API. |

**Permissions:** Tenant can only see and act on their **assigned unit** (one unit). They cannot see other units or properties.

---

### 5. Tenant flow – quick checklist

| Test | Steps | Expected |
|------|--------|----------|
| **Manager creates tenant invite** | Manager → Property → Vacant unit → Invite tenant (name, email, lease dates) | Invitation created; link shown (e.g. `#invite/INV-…`) |
| **Tenant signup from link** | Open invite link → Register from invite (tenant UI: email prefilled, no permanent address) → Sign agreement → Submit | Account created; if verification on, verify then → tenant-dashboard |
| **Tenant signup (no verification)** | Same as above with verification off | Redirect to tenant-dashboard immediately |
| **Tenant login** | `#login/tenant` → email + password | Redirect to tenant-dashboard |
| **Tenant sees unit** | Tenant dashboard load | Assigned unit and property shown |
| **Tenant invite guest** | Tenant → Invite guest → dates → submit | Invitation created for tenant’s unit only |
| **Tenant cancel invite** | Tenant → Your invitations → Cancel | Invitation cancelled |
| **Tenant guest history** | Tenant has invited guest who has stay | Guest history list shows that stay |
| **Tenant presence** | Tenant → Set to Away (optional: guests authorized) → Confirm | Presence updated; “Away since” and optional guest auth shown |
| **Tenant presence load** | Refresh tenant dashboard | Presence state from API (present/away, timestamps) |

---

### 6. Tenant – negative / edge checks

| Check | How | Expected |
|-------|-----|----------|
| Wrong email at signup | Use invite link but register with a **different** email (when manager set guest_email) | Backend returns 400: “Please use the email address this invitation was sent to.” |
| Used invite | Use same invite link after tenant already accepted | Invitation details show invalid or no longer valid/used; cannot complete signup again. |
| Tenant cannot see other units | Log in as tenant; try to open another property or unit (e.g. owner URL) | No access; tenant only has tenant-dashboard and their single unit. |
| Cancel invite (tenant) | Tenant cancels one of their own invitations | Only the user who created the invite (or owner) can cancel; cancel succeeds and invitation status → cancelled. |

---

## Change List & Expected Behavior

### Backend: Dependencies (`app/dependencies.py`)
- **Added** `get_context_mode()` – Reads `X-Context-Mode: business|personal` from request headers.
- **Added** `require_owner_or_manager` – Allows Owner OR Property Manager.
- **Expected:** Requests with `X-Context-Mode: personal` are treated as Personal mode; `require_owner_or_manager` accepts both Owner and Property Manager.

### Backend: Permissions (`app/services/permissions.py`)
- **Added** `can_confirm_occupancy(db, user, stay)` – True for owner or assigned manager.
- **Added** `Action` enum – `VIEW_BILLING`, `MODIFY_BILLING`, `INVITE_GUEST`, `SET_PRESENCE`, `VIEW_LOGS`, etc.
- **Added** `can_perform_action(db, user, action, property_id?, unit_id?, mode)` – User + Property/Unit + Role + Mode + Action.
- **Expected:** Permissions are evaluated via `can_perform_action`; SET_PRESENCE only allowed in personal mode; INVITE_GUEST uses mode.

### Backend: Invitation Create (`app/routers/owners.py` – `POST /owners/invitations`)
- **Changed** Dependency from `require_owner_onboarding_complete` to `get_current_user`.
- **Added** Support for `unit_id` and `invited_by_user_id` in request body.
- **Added** Tenant path: requires `unit_id`, checks `can_invite_guest`.
- **Added** Property Manager path: requires `unit_id`, checks `can_invite_guest` in personal mode.
- **Expected:** Owner (business/personal), Tenant, and Property Manager (personal) can create invitations; Tenant and Manager must send `unit_id`.

### Backend: Cancel Invitation (`app/routers/dashboard.py` – `POST /dashboard/owner/invitations/{id}/cancel`)
- **Changed** Dependency from `require_owner_onboarding_complete` to `get_current_user`.
- **Changed** Authorization to allow owner **or** `invited_by_user_id`.
- **Expected:** Owner and the user who created the invite can cancel it.

### Backend: Tenant Invitations (`app/routers/dashboard.py` – `GET /dashboard/tenant/invitations`)
- **Added** Endpoint for invitations created by the tenant.
- **Expected:** Returns invitations where `invited_by_user_id == current_user.id`.

### Backend: Tenant Guest History (`app/routers/dashboard.py` – `GET /dashboard/tenant/guest-history`)
- **Added** Endpoint for stays of guests invited by the tenant.
- **Expected:** Returns stays where the invitation's `invited_by_user_id` is the tenant.

### Backend: Manager Property Detail (`app/routers/managers.py` – `GET /managers/properties/{id}`)
- **Added** Read-only property summary for assigned properties.
- **Expected:** Manager gets property summary only for properties they are assigned to.

### Backend: Manager Invite Tenant (`app/routers/managers.py` – `POST /managers/units/{id}/invite-tenant`)
- **Added** Endpoint to create tenant invitations for vacant units.
- **Expected:** Manager can invite tenants for vacant units on assigned properties; creates invitation with `token_state=BURNED`.

### Backend: Manager Stays (`app/routers/dashboard.py` – `GET /dashboard/manager/stays`)
- **Added** Stays for properties assigned to the manager.
- **Expected:** Returns stays for assigned properties only.

### Backend: Manager Logs (`app/routers/dashboard.py` – `GET /dashboard/manager/logs`)
- **Added** Audit logs for assigned properties.
- **Changed** (Central Event Ledger) – Now reads from `event_ledger` instead of `audit_logs`. Same response shape (`OwnerAuditLogEntry`); category/title/message derived from `action_type` + metadata.
- **Expected:** Returns logs for assigned properties only; data source is the event ledger.

### Backend: Manager Billing (`app/routers/dashboard.py` – `GET /dashboard/manager/billing`)
- **Added** Read-only billing for the owner of assigned properties.
- **Expected:** Returns invoices/payments; no billing portal or payment changes.

### Backend: Confirm Vacant (`app/routers/dashboard.py` – `POST /dashboard/owner/properties/{id}/confirm-vacant`)
- **Changed** Dependency from `require_owner_onboarding_complete` to `require_owner_or_manager`.
- **Added** `can_access_property` check.
- **Expected:** Owner and assigned Manager can confirm vacant for their properties.

### Backend: Confirm Occupancy (`app/routers/dashboard.py` – `POST /dashboard/owner/stays/{id}/confirm-occupancy`)
- **Changed** Dependency from `require_owner_onboarding_complete` to `require_owner_or_manager`.
- **Added** `can_confirm_occupancy` check.
- **Expected:** Owner and assigned Manager can confirm vacated/renewed/holdover.

### Backend: Owner Personal Mode Units (`app/routers/dashboard.py` – `GET /dashboard/owner/personal-mode-units`)
- **Added** Endpoint returning unit IDs where owner has Personal Mode.
- **Expected:** Returns `{ unit_ids: number[] }` for owner's ResidentMode units.

### Backend: Manager Personal Mode Units (`app/routers/dashboard.py` – `GET /dashboard/manager/personal-mode-units`)
- **Added** Endpoint returning unit IDs where manager has Personal Mode.
- **Expected:** Returns `{ unit_ids: number[] }` for manager's ResidentMode units.

### Backend: Owner grants manager Personal Mode (`app/routers/owners.py`)
- **Added** `GET /owners/properties/{id}/assigned-managers` – List managers assigned to the property, including `has_resident_mode` and `resident_unit_label`.
- **Added** `POST /owners/properties/{id}/managers/add-resident-mode` – Body: `{ manager_user_id, unit_id }`. Owner can grant a manager Personal Mode for a unit (manager lives on-site).
- **Expected:** When manager lives on-site, owner adds them as resident for a unit; manager then gets Personal Mode for that unit.

### Backend: Away/Presence – Model (`app/models/resident_presence.py`)
- **Added** `away_started_at`, `away_ended_at`, `guests_authorized_during_away` to `ResidentPresence`.
- **Schema:** `resident_presences.away_started_at`, `away_ended_at`, `guests_authorized_during_away` (in models; created on startup).
- **Expected:** Presence records store timestamps and guest authorization flag.

### Backend: Away/Presence – Endpoints (`app/routers/dashboard.py`)
- **Added** `GET /dashboard/presence?unit_id={id}` – Returns current presence for unit; requires `can_perform_action(SET_PRESENCE)`.
- **Changed** `POST /dashboard/presence` – Restrict to personal mode only (`can_perform_action(SET_PRESENCE)`); add `guests_authorized_during_away`; set timestamps; log with `CATEGORY_PRESENCE`.
- **Expected:** Only Tenant or Owner/Manager in Personal Mode can set presence; Business Mode blocked; timestamps and guest auth stored; presence changes logged.

### Backend: Property Creation – Multi-Unit (`app/routers/owners.py`, `app/schemas/owner.py`)
- **Added** `unit_count` to `PropertyCreate` schema.
- **Changed** `add_property` – When `unit_count` > 1: set `is_multi_unit=True`, create Unit rows ("1", "2", …).
- **Expected:** Multi-unit properties get Unit rows; single-unit unchanged.

### Backend: Activity Logs (`app/services/audit_log.py`)
- **Added** `CATEGORY_PRESENCE`, `CATEGORY_TENANT_ASSIGNMENT`.
- **Presence** changes logged in `POST /dashboard/presence`.
- **Expected:** Presence/away changes appear in logs; new categories available for filtering.

### Backend: Central Event Ledger
- **Added** `app/models/event_ledger.py` – Append-only `EventLedger` model (id, created_at, actor_user_id, action_type, target_object_type, target_object_id, property_id, unit_id, stay_id, invitation_id, previous_value, new_value, meta, ip_address, user_agent).
- **Added** `app/services/event_ledger.py` – `create_ledger_event()`, `ledger_event_to_display()`, `get_actor_email()`, action type constants, and category/title mapping for backward-compatible API responses.
- **Added** `event_ledger` table – in `EventLedger` model; created on startup via `Base.metadata.create_all()`.
- **Dual-write:** Every meaningful action (property create/update/delete, invitation create/cancel, stay revoke/check-in/check-out, presence, DMS, billing, agreement sign, verify, login, etc.) now also writes to the event ledger via `create_ledger_event()` alongside existing `create_log()`.
- **Readers switched to ledger:** `GET /dashboard/owner/logs`, `GET /dashboard/manager/logs`, `GET /public/live/{slug}` (audit timeline), and `GET /admin/audit-logs` now query `event_ledger` instead of `audit_logs`. Response shapes unchanged (category, title, message derived from action_type).
- **New events:** Successful login writes `UserLoggedIn`; action types `ManagerAssigned` and `UserRoleChanged` are defined for future use.
- **Expected:** Owner logs, Manager logs, Live property audit timeline, and Admin audit logs all read from the event ledger; filtering by time, category, and search works; API response format is unchanged so frontend needs no changes.

### Backend: Billing Hardening (`app/routers/dashboard.py` – `POST /dashboard/owner/billing/portal-session`)
- **Added** Explicit 403 for `property_manager` role (defense in depth).
- **Expected:** Property managers cannot create billing portal sessions even if somehow routed there.

### Frontend: API Client (`frontend/services/api.ts`)
- **Added** `getContextMode()`, `setContextMode()` – Read/write context mode from `localStorage`.
- **Added** `X-Context-Mode` header on requests.
- **Added** `invitationsApi.create` support for `unit_id`.
- **Added** `dashboardApi.tenantInvitations`, `tenantGuestHistory`.
- **Added** `dashboardApi.managerStays`, `managerLogs`, `managerBilling`.
- **Added** `dashboardApi.ownerPersonalModeUnits`, `managerPersonalModeUnits`.
- **Added** `dashboardApi.confirmVacant`.
- **Added** `dashboardApi.getPresence(unitId)`, `setPresence(unitId, status, guestsAuthorizedDuringAway?)`.
- **Added** `dashboardApi.managerProperties`, `managerUnits`, `managerInviteTenant`.
- **Added** `unit_count` to `propertiesApi.add` payload.
- **Expected:** All new endpoints are callable; context mode is sent with requests.

### Frontend: InviteGuestModal (`frontend/components/InviteGuestModal.tsx`)
- **Added** `unitId` prop.
- **Changed** When `unitId` is set, property selector is hidden and `unit_id` is sent.
- **Expected:** Tenant/Personal mode: no property picker; invitation is created for the given unit.

### Frontend: Owner Dashboard (`frontend/pages/Owner/OwnerDashboard.tsx`)
- **Added** Mode switcher (Business/Personal) when owner has Personal Mode units.
- **Added** Billing tab hidden in Personal mode.
- **Added** `ownerPersonalModeUnits` fetch and `contextMode` state.
- **Added** Presence card in Personal mode – toggle Away/Present, "Guests authorized during this period" checkbox, timestamps.
- **Changed** Revoke modal/success – "USAT token" replaced with neutral wording ("stay authorization", "access disabled").
- **Expected:** Mode switcher appears when owner has ResidentMode; Billing is hidden in Personal mode; Presence toggle in Personal mode; no USAT wording.

### Frontend: Manager Dashboard (`frontend/pages/Manager/ManagerDashboard.tsx`)
- **Added** Tabs: Properties, Stays, Logs, Billing.
- **Added** Stays tab – lists stays for assigned properties.
- **Added** Logs tab – lists audit logs for assigned properties.
- **Added** Billing tab – read-only invoices.
- **Added** "Invite tenant" for vacant units (when `u.id > 0`).
- **Added** Mode switcher when manager has Personal Mode units.
- **Added** Invite Tenant modal (name, email, lease dates).
- **Added** Presence card in Personal mode – toggle Away/Present, "Guests authorized during this period" checkbox, timestamps.
- **Expected:** Manager sees Properties, Stays, Logs, Billing; can invite tenants; Presence toggle in Personal mode.

### Frontend: Tenant Dashboard (`frontend/pages/Tenant/TenantDashboard.tsx`)
- **Added** Invite Guest button and InviteGuestModal with `unitId`.
- **Added** "Your invitations" list with cancel.
- **Added** "Guest history" section.
- **Changed** Presence – On load, calls `GET /dashboard/presence?unit_id={id}`; when setting Away, shows "Guests authorized during this period" checkbox; displays timestamps (e.g. "Away since 3/5/2025").
- **Expected:** Tenant can invite guests; Presence loads from API; Away shows confirm modal with guest auth checkbox and timestamps.

### Frontend: Add Property (`frontend/pages/Owner/AddProperty.tsx`)
- **Added** Property types: duplex, triplex, quadplex.
- **Added** Conditional Step 2 – For apartment, duplex, triplex, quadplex: "Number of units" (required); for house/condo: bedrooms, primary residence (unchanged).
- **Added** `unit_count` to payload when multi-unit.
- **Expected:** Multi-unit types show unit count field; duplex/triplex/quadplex prefilled 2/3/4; apartment requires input.

### Frontend: USAT Removal
- **OwnerDashboard** – Revoke modal and success: "USAT token" → "stay authorization", "access disabled".
- **HelpCenter** – FAQ "What is a USAT Token?" → "How does utility authorization work?"; "What if a guest stays past…" updated.
- **OwnerPOASignModal** – "utility authorization tokens (e.g. USAT)" → "utility authorization".
- **enforcementService** – "DocuStay USAT Protocol" → "DocuStay Authorization Protocol".
- **SignAgreement** – Removed `generateUSATToken`; success "USAT token issued" → "stay confirmed".
- **Deleted** `USATTokenDisplay.tsx` (unused).
- **API types** – `usat_token`, etc. retained for responses; not displayed in UI.
- **Expected:** No USAT wording anywhere in user-facing UI.

---

## Quick Test Checklist

| Test | Steps | Expected |
|------|-------|----------|
| Owner invite (business) | Owner → Invite Guest → create invite | Invitation created with `property_id` |
| Tenant invite | Tenant → Invite Guest → create invite | Invitation created with `unit_id` |
| Tenant cancel | Tenant → Your invitations → Cancel | Invitation cancelled |
| Manager stays | Manager → Stays tab | Stays for assigned properties |
| Manager logs | Manager → Logs tab | Logs for assigned properties |
| Manager billing | Manager → Billing tab | Read-only invoices |
| Manager invite tenant | Manager → Properties → vacant unit → Invite tenant | Invitation created |
| Owner mode switcher | Owner with ResidentMode → dashboard | Business/Personal switcher visible |
| Owner Personal mode | Owner → Personal → Billing tab | Billing tab hidden |
| Manager mode switcher | Manager with ResidentMode → dashboard | Business/Personal switcher visible |
| Owner grants manager Personal Mode | Property Detail → Assigned managers → Add as on-site (select unit) | Manager gets ResidentMode for that unit; mode switcher appears on their dashboard |
| Tenant guest history | Tenant with invited guests | Guest history list shown |
| Confirm vacant (manager) | Manager → confirm vacant for assigned property | Vacant confirmed |
| Confirm occupancy (manager) | Manager → confirm occupancy for stay | Occupancy confirmed |
| **Tenant presence** | Tenant → Set to Away → check "Guests authorized" → Confirm | Presence set; timestamps stored; "Away since…" shown |
| **Tenant presence load** | Tenant → refresh dashboard | Presence state loads from API |
| **Owner presence (Personal)** | Owner → Personal mode → Set to Away | Presence card visible; toggle works |
| **Manager presence (Personal)** | Manager → Personal mode → Set to Away | Presence card visible; toggle works |
| **Add multi-unit property** | Owner → Add Property → Apartment → Units: 8 | Property created with 8 Unit rows |
| **Add duplex** | Owner → Add Property → Duplex (prefilled 2) | Unit count 2; can override |
| **Presence in logs** | Set presence → Owner/Manager → Logs | Presence change entry with category "presence" |
| **No USAT in UI** | Owner → Revoke modal; Help Center; SignAgreement | No "USAT" or "USAT token" anywhere |
| **Billing portal (manager)** | Manager attempting portal session | 403 (defense in depth) |
| **Event ledger – Owner logs** | Owner → Logs tab | Entries from event_ledger; same columns (category, title, message, etc.) |
| **Event ledger – Manager logs** | Manager → Logs tab | Entries from event_ledger for assigned properties only |
| **Event ledger – Live page** | Public live property page → Audit timeline | Timeline entries from event_ledger for that property |
| **Event ledger – Admin logs** | Admin → Audit logs | Global event_ledger with filters (category, property_id, etc.) |
| **Tenant signup from invite** | Open `#invite/INV-…` or `#register-from-invite/INV-…` → fill form (email prefilled) → sign agreement → submit | Tenant account + TenantAssignment; redirect to tenant-dashboard (or verify first) |
| **Tenant login** | `#login/tenant` → email + password | Redirect to tenant-dashboard |
| **Tenant invite guest** | Tenant → Invite guest → create invite | Invitation for tenant’s unit only |
| **Tenant presence** | Tenant → Set to Away → Confirm (optional: guests authorized) | Presence saved; “Away since” and guest auth shown |

---

## 4. Property Manager Logic – Verification

Requirements (sections 4 & 5):

- **Assigned by owners** – Owners assign managers via Property Detail → Invite Property Manager; assignment stored in `property_manager_assignments`.
- **See properties assigned to them** – ✅ `GET /managers/properties` returns only properties where `PropertyManagerAssignment.user_id == current_user.id`.
- **View units within those properties** – ✅ `GET /managers/properties/{id}/units` lists units for an assigned property only (404 if not assigned).
- **See occupancy status of units** – ✅ Each unit in the list has `occupancy_status` (vacant / occupied / unknown / unconfirmed). Property summary shows `occupied_count` / `unit_count`.
- **Invite tenants to units** – ✅ `POST /managers/units/{id}/invite-tenant` creates a BURNED invitation for that unit; manager must be assigned to the unit’s property.
- **Manage tenant assignments** – Tenant assignments (tenant ↔ unit) exist in the model; manager “invites tenant” which creates an invitation. The tenant signs up and gets linked via the invitation/stay flow. There is no separate “tenant assignment” CRUD UI for managers; inviting a tenant is the way to assign (invitation → stay → tenant occupies unit).
- **View logs for those properties** – ✅ `GET /dashboard/manager/logs` returns event-ledger entries filtered by `_manager_property_ids` (assigned properties only).
- **View billing related to those properties** – ✅ `GET /dashboard/manager/billing` returns read-only billing for the **owner** of the assigned properties (invoices/payments from Stripe). Note: Stripe is customer-level, so the manager sees the full billing for that owner (all of the owner’s properties), not per-property breakdown.
- **Must not modify billing or payment methods** – ✅ `POST /dashboard/owner/billing/portal-session` returns 403 for `property_manager` role. Manager dashboard has no “Manage billing” or “Update payment method” actions.
- **Personal Mode for on-site managers** – ✅ Owner can add a manager as “on-site” for a unit via Property Detail → Assigned managers → Add as on-site (unit selector). This creates `ResidentMode` for that manager + unit. Manager then has Business/Personal mode switcher and can set presence for that unit.

**Unit status when tenant accepts:** Property- and unit-level occupancy are set to **occupied when the guest checks in** (not at invitation accept). On check-in, if the stay has a `unit_id`, that unit’s `occupancy_status` is set to occupied. On checkout (guest checkout or owner/manager “vacated” confirmation), the unit is set back to vacant. The manager’s unit list therefore shows Occupied/Vacant correctly after check-in and checkout.

---

## 5. Property Manager Example Scenario – How to Test (Quadplex)

**Setup**

1. **Owner** – Log in as owner. Create or select a property, set type to **Quadplex**, set **Units** to 4 (or use an existing quadplex).
2. **Assign manager** – On Property Detail → **Invite Property Manager** with the manager’s email. Manager receives invite; they sign up (or already have a `property_manager` account) and accept. They appear under **Assigned managers**.
3. **Optional: on-site manager** – In Property Detail → Assigned managers → **Add as on-site** and choose a unit (e.g. 101). Manager now has Personal Mode for that unit.

**Manager flow (quadplex example)**

1. **Log in as the property manager.** Go to Manager Dashboard.
2. **Properties tab** – You should see **Example Quadplex** (or the property name) with address, occupancy status, and “X/4 units occupied”. Expand **View units**.
3. **Units** – You should see units 101, 102, 103, 104 (or 1, 2, 3, 4 depending on labels) with **Occupied** or **Vacant** badges.
4. **Occupancy** – Confirm that occupied units show “Occupied” and vacant units show “Vacant”.
5. **Invite tenant (vacant unit)** – For a **Vacant** unit, click **Invite tenant**. Fill: Tenant name, Tenant email, Lease start, Lease end → **Create invitation**. Copy the invite link and open it in an incognito window (or another browser).
6. **Tenant accepts** – As “tenant” (new user), complete sign-up from the invite link and sign the agreement. A stay is created. After the tenant **checks in** (Guest dashboard → Check in), the property (and ideally the specific unit) should reflect occupied status; refresh the Manager dashboard and confirm the unit now shows **Occupied**.
7. **Logs** – Open the **Logs** tab. You should see entries only for the assigned property (e.g. “Invitation accepted”, “Guest checked in”, “Property registered”, etc.).
8. **Billing** – Open the **Billing** tab. You should see **read-only** invoices/payments for the owner (no “Manage billing” or “Update payment method”). Text should state that only the owner can change billing.
9. **Personal Mode (if on-site)** – If the manager was added as on-site for a unit, the **Business / Personal** switcher appears. Switch to **Personal** and set **Presence** (Here / Away, optional “Guests authorized during this period”). Confirm it saves and appears in logs.

**Negative checks**

- **Manager cannot open billing portal** – As manager, try to open the owner billing portal (e.g. a hidden or dev-only link that calls `POST /dashboard/owner/billing/portal-session`). Expect **403** and message that property managers cannot modify billing.
- **Manager sees only assigned properties** – Assign the manager to one property only. Confirm they do not see other properties in **Properties** tab, **Stays**, or **Logs**.

**Quick checklist (Quadplex scenario)**

| Step | Action | Expected |
|------|--------|----------|
| 1 | Owner creates quadplex, 4 units | Property has 4 units |
| 2 | Owner invites manager, manager accepts | Manager appears in Assigned managers |
| 3 | Manager → Properties | Sees quadplex; X/4 units occupied |
| 4 | Manager → View units | Sees 101–104 (or 1–4) with Occupied/Vacant |
| 5 | Manager → Invite tenant (vacant unit) | Invitation created; link to share |
| 6 | Tenant signs up from link, signs agreement | Stay created |
| 7 | Tenant checks in | Property/unit show occupied; manager refreshes and sees unit Occupied |
| 8 | Manager → Logs | Only this property’s events |
| 9 | Manager → Billing | Read-only list; no payment method change |
| 10 | Owner adds manager as on-site for unit 101 | Manager gets Business/Personal; can set presence in Personal |
