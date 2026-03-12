# Privacy Lanes: Client Summary

## What Changed

DocuStay now enforces **lane-based privacy**: data belongs to one of three lanes (property/management, tenant, or guest), and access follows the lane — not who owns the property.

**Core rule:** Even if you own the property or run the property management company, you cannot see tenant-private activity. Tenant guest data stays with the tenant.

---

## 1. Business Mode vs Personal Mode

**Business mode** (default): You manage properties and units. You see property-level information only — no guest names, no tenant guest activity.

**Personal mode:** You manage your own residence or personal property. You see your own guest invites and stays (ones you created), but never tenant-invited guest data.

**Important:** Switching to personal mode does not unlock tenant-private information.

### Where to see this in the UI

| Location | What to look for |
|----------|------------------|
| **Owner Dashboard** | Mode switcher (Business / Personal). In Business mode: tabs show Properties, Billing, Event ledger. In Personal mode: additional Guests and Invitations tabs appear. |
| **Manager Dashboard** | Same mode switcher. In Business mode: Properties, Billing, Event ledger. In Personal mode: Guests and Invitations tabs. |
| **Property Detail** (Owner / Manager) | Same mode. In Business mode: Overview, Units, Event ledger. In Personal mode: Stay, Guests sections appear. |

---

## 2. What Owners & Property Managers See

### In Business Mode

| You can see | Where in the UI |
|-------------|-----------------|
| Properties | Properties tab, property list |
| Unit status (occupied / vacant / unknown) | Properties → Units list. Each unit shows status only — no names. |
| Shield Mode status | Property detail, Overview |
| Property billing | Billing tab |
| Property-level audits | Event ledger tab |

**You cannot see:** Tenant guest activity — who a tenant invited, guest names, tenant guest stays, overstays, agreements, or audit logs for tenant-invited guests.

### In Personal Mode

| You can see | Where in the UI |
|-------------|-----------------|
| Your own guest invites | Guests tab, Invitations tab |

**You cannot see:** Invites or stays created by tenants. Tenant guest data stays private.

---

## 3. What Tenants See

Tenants see only their own guest activity:

- Their guest invites
- Guest stays and overstays
- Guest agreements and authorization history

### Where to see this in the UI

| Location | What to look for |
|----------|------------------|
| **Tenant Dashboard** | Invitations tab (invites the tenant created), Guest History (stays for those guests). |

---

## 4. What Guests See

Guests see only their own data:

- Their authorization record
- The agreement they signed
- Their stay status

They do not see property details or other users.

### Where to see this in the UI

| Location | What to look for |
|----------|------------------|
| **Guest Dashboard** | Pending invites, Stays, signed agreement download. No property browse or other users. |

---

## 5. What to Look Out For (Verification)

### As Owner or Property Manager

1. **Business mode:** Switch to Business. Confirm you do not see Guests or Invitations tabs (or that they are hidden). Event ledger should show no tenant guest events (e.g. no “Guest checked in” for tenant-invited guests).
2. **Personal mode:** Switch to Personal. Confirm you only see invites and stays you created. If a tenant has invited a guest, you should not see that guest’s name or stay.
3. **Units list:** In Business mode, units show “Occupied” or “Vacant” only — no guest names. In Personal mode, for tenant-invited guests the unit should show “Occupied” (not the guest’s name).
4. **Public live page:** If you share the property’s live link, tenant-invited guest names should appear as “Guest,” not real names.

### As Tenant

1. **Invitations:** You see only invites you created. You can manage those guests (stays, agreements, history).
2. **Event ledger:** You see only events for your invites and your own actions — not other tenants’ guest activity.

### As Guest

1. **Dashboard:** You see only your own stays and agreements. No property list or other users.

---

## Summary

- **Ownership does not override privacy.** Tenant guest data stays with the tenant.
- **Mode switching** does not unlock tenant-private data.
- **Lanes:** Property/management, tenant, guest. Access follows the lane.
- **UI:** Mode switcher controls what tabs and data you see. Business = property-level only. Personal = your own guest data only (never tenant-invited).
