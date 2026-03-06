---
name: USAT QR and Verify Portal
overview: Plan for the public /verify portal (token + address verification with full attempt logging). Guest-side QR (invite_id) already exists; this plan does not add it.
todos: []
isProject: false
---

# USAT QR Code and /verify Portal – Implementation Plan

## How this fits the existing app

- **USAT today:** Each property has a unique `usat_token` (e.g. `USAT-HEX`) and `usat_token_state` (STAGED / RELEASED). Only the **owner** sees it ([dashboard.py](app/routers/dashboard.py) line 808). That property-level token remains **owner-only** in this plan.
- **Released USAT token = Invitation ID (invite code):** The token that proves **guest** temporary utility authorization is the **Invitation ID** (`invitation_code`), i.e. the invite code (e.g. `INV-XXXX`) that was BURNED when the guest signed the agreement and the stay was created. The guest already receives `invite_id` in [GuestStayView](app/schemas/dashboard.py) for each stay. No need to expose the property's `usat_token` to the guest.
- **Agreement flow:** Guest signs in Dropbox → stay is created, invitation token_state → BURNED. The **invite code** is then the "released" token the guest can show as proof of authorization.
- **Verify:** There is no `/verify` page or API yet. The public API is [public.py](app/routers/public.py) (e.g. `GET /public/live/{slug}`).

The plan below:

1. Uses the **Invitation ID** (invite code) as the verification token: /verify accepts Token ID = invitation code and Property Address. (Guest-side QR already exists.)
2. Adds a **standalone /verify** page: anyone submits Token ID + Property Address (optional name/phone); every attempt is logged; response is read-only, live, with validity and audit context.

---

## Part A: Released USAT token = Invitation ID (no backend release step)

**Decision:** The "released USAT token" for the guest is the **Invitation ID** (`invitation_code`). It is already "released" when the guest signs and the stay is created (invitation token_state → BURNED). The guest already gets `invite_id` in `GuestStayView` for each stay.

**Backend (no changes required for release):**

- **No change** to guest check-in or to `stay.usat_token_released_at` / property `usat_token` for this feature. Property USAT stays owner-only.
- **Guest stay list API** already returns `invite_id` (invitation code) in [GuestStayView](app/schemas/dashboard.py). Use that as the token for /verify. Guest-side QR (View QR Code) already exists; this plan does not add it.

---

## Part B: /verify portal (public, high priority)

**Purpose:** Single page where anyone (law enforcement, owner, guest, third party) can answer: *Is there an active authorization record for this address and token right now?* Every attempt is logged; failed or mismatched attempts are recorded as "Identity Conflict" for timeline integrity. No owner notification or escalation.

**Route:** Add a **standalone** verify experience. Options:

- **SPA:** `#verify` (e.g. `docustay.online/#verify`) with a dedicated [VerifyPage.tsx](frontend/pages/Verify/VerifyPage.tsx) or similar, or
- **Separate page:** `docustay.online/verify` as its own route (may require router/config so `/verify` serves the SPA).

Recommendation: Implement as **SPA view** `#verify` so the same app and auth model apply; document the canonical URL as `docustay.online/verify` (or with hash) in [PRODUCT_SYSTEM_OVERVIEW.md](docs/PRODUCT_SYSTEM_OVERVIEW.md).

**Form (required vs optional):**

- **Required:** Token ID, Property Address (second-factor to avoid token guessing).
- **Optional:** Name, Phone (submitted and logged but not used for validity).

**Backend – new public endpoint:**

- **POST** (or GET with query params) `**/api/public/verify`** (no auth).
- Request body (or query): `token_id` (required), `property_address` (required), optional `name`, `phone`.
- Logic:
  1. **Look up token:** Treat `token_id` as **Invitation ID** (invitation_code). Find Invitation where `invitation_code == token_id` (trimmed, case-insensitive). If none, log and return invalid.
  2. **Resolve property:** From the invitation, get `property_id`; load Property. If property is deleted or missing, log and return invalid. Match **property address** to the submitted `property_address` (normalize or compare street/city/state/zip). If address does not match the property, log as "Identity Conflict" / "address_mismatch" and return invalid.
  3. **Validity rules (per requirement):**
    - Invitation token_state is **BURNED** (accepted stay).
    - Stay exists for this invitation, not revoked, not checked out, not cancelled; stay end date not passed (or within grace if any).
    - "Valid" = invitation exists, token_state BURNED, linked stay active, address matches, not expired/revoked.
  4. **Log every attempt** via [audit_log](app/services/audit_log.py): e.g. category `verify_attempt` or `failed_attempt`; include token_id, address (normalized), optional name/phone, result (valid / invalid), and reason (e.g. "no_property_match", "token_not_found", "token_revoked", "stay_ended", "valid"). For invalid/mismatch, use a title like "Identity Conflict" or "Verify attempt – no match" so it’s clear in the audit timeline.
  5. **Response (read-only, live):**
    - `valid: boolean`
    - **Verified authority summary:** e.g. property name, address, occupancy status.
    - **Master POA summary reference:** e.g. that the property is under a DocuStay Master POA (link or reference to live POA info if desired; today live page has POA summary).
    - **Current property status:** occupancy, Shield (property-level USAT state remains owner-only; not exposed on verify).
    - **Relevant token states:** invitation token_state (BURNED = accepted), stay revoked/checked out/cancelled.
    - **Live timestamp** (server time).
    - **Expandable detailed audit timeline:** recent audit log entries for this property (and optionally stay) so the verifier can see a timeline. Paginated or last N entries.

**Frontend – /verify page:**

- Form: Token ID (required), Property Address (required), Name (optional), Phone (optional). Submit to `POST /api/public/verify`.
- Result panel:
  - If **valid:** Show verified authority summary (property name, address, occupancy), Master POA reference, property status, token states, visible Record ID, timestamp, and live link for re-verification. Page must be read-only, live, and printable. Optionally link to the existing live property page (`#live/{slug}`) for full evidence view.
  - If **invalid:** Show "No active authorization found" (or similar), timestamp, and optionally a short reason (e.g. "Token not found" / "Address does not match" / "Authorization ended"). Do not expose internal details beyond what’s needed for clarity.
- All attempts are logged on the server; no client-side-only logging. Logging does **not** trigger owner notification or escalation.

**Security / abuse:** Address + token together limit guessing. Rate limiting on `/api/public/verify` (e.g. by IP or by token+address) is recommended to avoid brute-force; exact limits can be tuned later.

---

## Part C: Token format and "cryptographically signed" (optional later)

- **Current:** The verification token is the **Invitation ID** (invitation_code, e.g. `INV-XXXX`). Validity is determined entirely by DB state on /verify (invitation exists, token_state BURNED, stay active, address matches).
- **Requirement:** "Cryptographically signed digital token." For **Phase 1**, the plan uses the invite code as the token; "valid" = invitation exists, token_state BURNED, linked stay active, not revoked/expired, address matches. That satisfies "proves temporary utility authorization" and "valid = exists, not expired, not revoked, linked to identity."
- **Later (optional):** Add a signed payload (e.g. JWT) that encodes invite_id, property_id, stay_id, expiry; /verify could validate signature in addition to DB state. Not required for the first version.

---

## Part D: What not to do (elements that don’t apply or are out of scope)

- **Do not** use the mock [SignAgreement.tsx](frontend/pages/Guest/SignAgreement.tsx) flow or client-only `generateUSATToken` for the real post-agreement flow; the real flow is: sign in Dropbox → stay created → invite code is the token. Guest-side QR already exists.
- **Do not** expose property `usat_token` to the guest; the verification token is the Invitation ID (invite code) only.
- **Do not** notify or escalate to the owner on verify attempts; logging only.
- **Do not** require login on /verify; it’s user-agnostic and public.
- **Do not** change the meaning of "token_state" (STAGED/BURNED/EXPIRED/REVOKED) for invitations; /verify uses invitation token_state and stay state.

---

## Implementation order

1. **Backend: POST /api/public/verify** – Token ID = invitation code; look up Invitation, property, stay; validate address and active stay; log every attempt; return summary + audit timeline.
2. **Frontend: /verify page** – Form (token, address, optional name/phone), call verify API; when valid, show result (summary, Record ID, timestamp, live link; optionally link to live property page).
3. **Docs** – Update [PRODUCT_SYSTEM_OVERVIEW.md](docs/PRODUCT_SYSTEM_OVERVIEW.md) with "Verify portal".

---

## Summary diagram

```mermaid
flowchart LR
  subgraph today [Current state]
    Sign[Guest signs agreement]
    Stay[Stay created]
    CheckIn[Guest check-in]
    Stay --> CheckIn
    Sign --> Stay
    CheckIn --> Occ[Occupancy OCCUPIED]
    OwnerSees[Owner sees USAT]
  end

  subgraph new [New behavior]
    Scan[Verifier scans existing QR or types token]
    Scan --> Verify[/verify page]
    Verify --> API[POST /public/verify]
    API --> Log[Log attempt]
    API --> Result[Return valid + summary or invalid]
  end
```



This keeps the existing registration and document-signing flow unchanged and adds a clear place for USAT/QR and /verify in the app and in the product doc.