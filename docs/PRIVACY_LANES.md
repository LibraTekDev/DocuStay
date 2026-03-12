# Privacy Lanes: Lane-Based Data Access

**Ownership does not override privacy scope.** The system uses three distinct lanes. Permissions follow the lane, not ownership status.

## Business Mode vs Personal Mode

- **Business mode** (default): Owners and property managers act in management scope. They see property-level data only; no tenant guest activity.
- **Personal mode**: Owners/managers who live on-site see their own guest invites and stays (property-lane only; never tenant-invited guest data).

---

## 1. Property / Management Lane (Business Mode)

What owners and property managers see when acting in business mode (`X-Context-Mode: business`).

**They can see:**
- Properties
- Unit status (occupied / vacant / unknown)
- Shield Mode status
- Property billing
- Property-level audits (logs filtered to exclude tenant guest events)
- Property assignments
- Tenant invitation status at the property level
- Management activity on the property

**They cannot see:** Tenant guest activity (who a tenant invited, guest names, tenant guest stays, overstays, agreements, audit logs).

**Implementation:** Owner/manager invitations and stays return `[]` in business mode. Logs exclude tenant-lane events. Units show `occupancy_status` only (no `occupied_by` or `invite_id`).

---

## 2. Tenant Lane (Personal Mode for Tenants)

Belongs to the tenant or resident.

**Tenants can see:**
- Their own guest invites
- Guest stays, guest overstays
- Guest agreements, guest authorization history

This information stays private to the tenant. Even if the property owner manages the building, that does not expose tenant guest data.

**Implementation:** `GET /dashboard/tenant/invitations` and `GET /dashboard/tenant/guest-history` filter by `invited_by_user_id == current_user.id`. Tenant logs include only events for their invitations.

---

## 3. Guest Lane

Guests have the most limited scope.

**Guests can only see:**
- Their own authorization record
- The agreement they signed
- Their own stay status

**They cannot see:** Anything about the property or other users.

**Implementation:** `GET /dashboard/guest/pending-invites`, `GET /dashboard/guest/stays`, `GET /dashboard/guest/logs` filter by `current_user.id`. No property browse or other-user data.

---

## Personal Mode vs Business Mode

Users can switch between personal mode and business mode, but the privacy rules still apply.

- **In business mode:** Owners and property managers manage properties and units. They see property-level data only.
- **In personal mode:** A user might manage their own residence or personal property. They see their own guest invites and stays (property-lane only).

**Even if someone owns the property, switching modes does not unlock tenant-private information.**

---

## Key Rule

Instead of asking **"Who owns the property?"**, the system asks **"What lane does this data belong to?"**

Every record belongs to one of these lanes:

- **property / management**
- **tenant**
- **guest**

Permissions follow the lane — not the ownership status of the user.

---

## Why This Simplifies Everything

Once records are separated into lanes:

- **UI decisions become obvious** — which tabs to show, what data to display
- **Permissions become predictable** — lane determines access, not role alone
- **Privacy rules stay correct** — tenant data never leaks to owner/manager
- **Development becomes much easier** — one place to check (lane) instead of ownership + role + mode

---

## Implementation Reference

- **Tenant lane** = invitation/stay where `invited_by_user_id` is a user with `role == tenant`
- **Property lane** = invitation/stay where inviter is owner or property manager
- Use `app/services/privacy_lanes.py` for lane detection and filtering
- Owners and managers must NEVER see tenant-invited guest data (invitations, stays, logs, names)
