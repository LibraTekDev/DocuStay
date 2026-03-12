# QA Handoff Document

This document covers all features to test. For each section: **what to test**, **how to trigger the flow**, **where to find it in the UI**, and **what to look out for**.

---

## 1. Revocation Emails & Record Access

### What to test
- Revocation emails include full authorization record details (property address, guest name, dates, status, revocation date)
- Emails include a link to view the record and signed agreement
- Verify page shows full record, status, dates, and signed agreement

### How to trigger

| Flow | Steps |
|------|-------|
| **Vacate 12h notice (Revoke)** | 1. Owner creates guest invite → Guest accepts and signs → Guest checks in. 2. Owner goes to Personal mode → Guests tab → Find active stay → Click **Revoke**. 3. Guest receives email. |
| **Removal notice (overstay)** | 1. Have a guest stay past end date (overstay). 2. Owner goes to Personal mode → Guests tab → Find overstayed stay → Click **Initiate removal**. 3. Guest receives removal notice; owner receives confirmation. |

### Where to find in UI
- **Revoke button:** Owner Dashboard (Personal mode) → Guests tab → Active stay card → Revoke
- **Initiate removal:** Same location, on overstayed stays
- **Verify page:** `/#check` or `/#check?token=INV-XXXX` (e.g. `https://yourapp.com/#check?token=INV-ABC123`)
- **Verify link in email:** Click "View record" or similar in revocation/removal emails

### What to look out for
- [ ] Revocation email contains: property address, guest name, stay dates, status, revocation date
- [ ] Email has working link to verify page
- [ ] Verify page shows: property address, guest name, dates, status (ACTIVE / REVOKED / EXPIRED / etc.)
- [ ] Verify page has link to view signed agreement PDF when available

---

## 2. Stay End Reminders (formerly Dead Man's Switch)

### What to test
- Stay end reminder email is sent when a guest invitation is created (owner or tenant)
- Email uses new terminology: "Stay end reminders" (not "Dead Man's Switch")

### How to trigger
- **Owner:** Personal mode → Invitations tab → Create new guest invitation (with Stay end reminders enabled)
- **Tenant:** Tenant Dashboard → Create guest invitation
- Email is sent to owner/manager when invitation is created with Stay end reminders enabled

### Where to find in UI
- **Create invitation:** Owner: Property Detail → Invite Guest; Tenant: Tenant Dashboard → Invitations → Create
- **Stay end reminders toggle:** In invitation creation flow (enable when creating invite)

### What to look out for
- [ ] Email received when guest invite is created with Stay end reminders on
- [ ] Wording says "Stay end reminders" not "Dead Man's Switch"

---

## 3. Tenant Scope Clarification

### What to test
- DocuStay does not revoke or expire tenants
- UI and docs do not mention tenant revocation/expiration
- Token states: REVOKED = guest authorization revoked; CANCELLED = tenant self-cancel
- Invitation expiry applies only to guest invitations (tenant invitations excluded)

### How to trigger
- **Tenant self-cancel:** Tenant Dashboard → Cancel future assignment (for future-dated tenant assignment)
- **Guest revoke:** Owner revokes guest stay (see section 1)

### Where to find in UI
- **Tenant cancel:** Tenant Dashboard → Unit/assignment card → Cancel future assignment
- **Token states:** Event ledger, Verify page, stay/invitation cards (look for Active, Pending, Revoked, Cancelled)

### What to look out for
- [ ] No "Revoke tenant" or "Expire tenant" options anywhere
- [ ] REVOKED = guest authorization revoked (owner action)
- [ ] CANCELLED = tenant self-cancelled their assignment
- [ ] Guest invitations can expire (e.g. pending 12h); tenant invitations do not expire the same way

---

## 4. User-Facing Terminology

### Terminology mapping

| Old term | New term |
|----------|----------|
| Dead Man's Switch | Stay end reminders |
| Kill Switch | Revoke |
| BURNED | Active (authorization active) |
| STAGED | Pending |
| Token burn/expire/revoke | Status changes (active / expired / revoked) |

### Where to verify
- Dashboard labels, buttons, emails, Help Center, Verify page, Event ledger

### What to look out for
- [ ] No "Kill Switch" or "Dead Man's Switch" in user-facing UI
- [ ] Status shows "Active" / "Pending" / "Revoked" instead of BURNED/STAGED/REVOKED
- [ ] Event ledger uses "Status changes (active / expired / revoked)" type wording

---

## 5. Where Revocation Emails Are Sent

| Email | When sent | Recipient |
|-------|-----------|-----------|
| **Vacate 12h notice** | Owner clicks Revoke on a stay | Guest |
| **Removal notice** | Owner initiates formal removal for overstayed guest | Guest |
| **Removal confirmation** | Same as above | Owner |

### What to look out for
- [ ] Revoke → Guest gets vacate email
- [ ] Initiate removal → Guest gets removal notice, Owner gets confirmation

---

## 6. Dummy Email Testing Scripts

### What to test
- Scripts send preview emails to test address without real user actions

### How to trigger

```bash
# From project root
python scripts/send_dummy_revocation_emails.py
```
Sends 3 emails: Vacate 12h notice, Removal notice (guest), Removal confirmation (owner).

```bash
python scripts/send_dummy_dms_enabled_email.py
```
Sends Stay end reminders enabled email.

### Prerequisites
- `MAILGUN_API_KEY` + `MAILGUN_DOMAIN` (or `SENDGRID_API_KEY`) in `.env`
- Update `TEST_EMAIL` in script if needed (default: arfamujahid333@gmail.com)

### What to look out for
- [ ] Emails arrive at test address (check spam)
- [ ] Content matches expected templates

---

## 7. Landing Page, Terms of Service, Privacy Policy

### What to test
- Landing page has updated wording
- Terms of Service and Privacy Policy are accessible and linked correctly

### Where to find in UI
- **Landing:** `/#` or root URL
- **Terms of Service:** `/#terms` or footer link "Terms of Service"
- **Privacy Policy:** `/#privacy` or footer link "Privacy Policy"

### What to look out for
- [ ] Landing page copy is correct
- [ ] Footer links: Terms of Service, Privacy Policy
- [ ] Links open in new tab or navigate correctly
- [ ] Terms and Privacy Policy pages render fully

---

## 8. Personal vs. Business Mode (with Privacy Lanes)

### What to test
- **Personal mode:** Full property management (add/edit, primary residence, statuses), guests, invitations
- **Business mode:** Properties only, no guest/stay data; management features (event ledger, billing)
- **Privacy lanes:** Owner/manager never see tenant-invited guest data, even in Personal mode

### How to trigger

| Flow | Steps |
|------|-------|
| **Switch to Personal** | Owner/Manager Dashboard → Mode switcher (Business/Personal) → Select Personal |
| **Switch to Business** | Same → Select Business |
| **Create tenant, then tenant invites guest** | 1. Owner creates tenant invite → Tenant signs up. 2. Tenant creates guest invite → Guest accepts. 3. Owner switches to Personal → Should NOT see that guest's name or stay |

### Where to find in UI
- **Mode switcher:** Owner Dashboard, Manager Dashboard, Property Detail (top/settings area)
- **Business mode tabs:** Properties, Billing, Event ledger. No Guests or Invitations.
- **Personal mode tabs:** Guests, Invitations appear in addition to Properties

### What to look out for
- [ ] Business mode: No Guests or Invitations tabs (or hidden)
- [ ] Personal mode: Guests and Invitations tabs visible
- [ ] Business mode: Units show only status (Occupied/Vacant) — no guest names
- [ ] Personal mode: Owner sees only invites/stays they created; never tenant-invited guest data
- [ ] Event ledger: No tenant guest events (e.g. "Guest checked in" for tenant-invited guests) in owner/manager view
- [ ] Public live page: Tenant-invited guest names show as "Guest" not real name

### Reference
See `docs/PRIVACY_LANES_CLIENT_SUMMARY.md` for full product summary.

---

## 9. Quick Test Checklist

| # | Area | Pass/Fail |
|---|------|-----------|
| 1 | Revocation emails include full record + verify link | |
| 2 | Verify page (#check?token=...) shows record + signed agreement | |
| 3 | Stay end reminder email on guest invite creation | |
| 4 | No tenant revocation/expiration in UI | |
| 5 | Terminology: Stay end reminders, Revoke, Active, Pending | |
| 6 | Vacate 12h notice (Revoke) → Guest | |
| 7 | Removal notice → Guest, Removal confirmation → Owner | |
| 8 | Dummy email scripts run successfully | |
| 9 | Landing page, Terms, Privacy Policy accessible | |
| 10 | Business mode: no guest data | |
| 11 | Personal mode: owner/manager guest data only (never tenant-invited) | |
| 12 | Tenant-invited guest names anonymized on public live page | |

---

## Environment Notes

- Ensure backend and frontend are running
- Email: Configure Mailgun or SendGrid in `.env` for real emails
- For scripts: Run from project root with `python scripts/...`
