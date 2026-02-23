# DocuStay Test Flows for Client Demo

This document describes the test flows to demonstrate all property occupancy state changes and email notifications in the application.

---

## Overview: Property Occupancy States

| State | Description |
|-------|-------------|
| **UNKNOWN** | Initial state when property is created (never had a guest) |
| **OCCUPIED** | Guest has accepted invitation and stay is active |
| **VACANT** | Guest has checked out or owner confirmed unit vacated |
| **UNCONFIRMED** | Dead Man's Switch triggered, no owner response by deadline |

---

## Test Flow 1: Property Creation → UNKNOWN

**Objective:** Demonstrate that new properties start with UNKNOWN status.

### Steps:
1. Login as **Owner** (e.g., `johnDoe@gmail.com`)
2. Navigate to **Dashboard** → **Properties**
3. Click **Add Property**
4. Fill in property details:
   - Property Name: "Demo Property"
   - Street: "123 Demo Street"
   - City: "Miami"
   - State: "FL"
   - Zip: "33101"
5. Click **Save**

### Expected Results:
- Property created with status **UNKNOWN**
- Audit log entry: "Property registered" with `occupancy_status_new: "unknown"`

### Emails Sent:
- None (property creation doesn't trigger emails)

---

## Test Flow 2: Guest Accepts Invitation → OCCUPIED

**Objective:** Demonstrate status change from UNKNOWN/VACANT to OCCUPIED when guest accepts invitation.

### Steps:
1. **As Owner:**
   - Go to **Dashboard** → **Invitations**
   - Click **Create Invitation**
   - Select property, enter guest details:
     - Guest Name: "Test Guest"
     - Guest Email: `testguest@example.com`
     - Check-in Date: Today
     - Check-out Date: 7 days from today
   - Click **Send Invitation**

2. **As Guest:**
   - Check email for invitation link
   - Click the invitation link
   - Register/Login if needed
   - Review and sign the Guest Agreement
   - Accept the invitation

### Expected Results:
- Property status changes to **OCCUPIED**
- Stay is created with guest details
- Audit log entry: "Invitation accepted" with `occupancy_status_previous` → `occupancy_status_new: "occupied"`

### Emails Sent:
- **To Guest:** Welcome email with property details and stay dates
- **To Owner:** Notification that invitation was accepted

---

## Test Flow 3: Guest Checkout → VACANT

**Objective:** Demonstrate status change from OCCUPIED to VACANT when guest checks out.

### Steps:
1. Login as **Guest** (with an active stay)
2. Navigate to **Dashboard**
3. Find the active stay
4. Click **Check Out** / **End Stay**
5. Confirm checkout

### Expected Results:
- Property status changes to **VACANT**
- Stay marked with `checked_out_at` timestamp
- USAT token revoked (if no other active stays)
- Audit log entry: "Guest checked out" with `occupancy_status_previous: "occupied"` → `occupancy_status_new: "vacant"`

### Emails Sent:
- **To Guest:** Checkout confirmation email
- **To Owner:** Guest checkout notification email

---

## Test Flow 4: Guest Cancels Future Stay → VACANT

**Objective:** Demonstrate status change when guest cancels a future (not yet started) stay.

### Steps:
1. Create an invitation for a **future date** (start date > today)
2. Have guest accept the invitation
3. Login as **Guest**
4. Navigate to **Dashboard**
5. Find the upcoming stay
6. Click **Cancel Stay**
7. Confirm cancellation

### Expected Results:
- Property status changes to **VACANT** (if no other active stays)
- Stay marked with `cancelled_at` timestamp
- Audit log entry: "Stay cancelled by guest" with occupancy status changes

### Emails Sent:
- **To Owner:** Guest cancelled stay notification

---

## Test Flow 5: Owner Revokes Stay (Kill Switch)

**Objective:** Demonstrate the Kill Switch functionality for immediate revocation.

### Steps:
1. Login as **Owner**
2. Navigate to **Dashboard** → **Guests**
3. Find an active stay
4. Click **Kill Switch** / **Revoke**
5. Confirm revocation

### Expected Results:
- Stay marked with `revoked_at` timestamp
- Guest has 12 hours to vacate
- Audit log entry: "Stay revoked"

### Emails Sent:
- **To Guest:** Urgent 12-hour vacate notice

---

## Test Flow 6: Overstay Detection

**Objective:** Demonstrate automatic overstay detection and notifications.

### Prerequisites:
- Have a stay where `stay_end_date` is in the past
- Guest has NOT checked out

### Trigger:
Run the notification job (automatically runs daily, or manually):
```bash
cd c:\Users\arfam\Documents\Docustay\Docustay
.\.venv\Scripts\python.exe -c "from app.services.stay_timer import run_stay_notification_job; run_stay_notification_job()"
```

### Expected Results:
- Overstay detected and logged
- Audit log entry: "Overstay occurred"

### Emails Sent:
- **To Owner:** Overstay alert with guest details
- **To Guest:** Overstay warning notice

---

## Test Flow 7: Dead Man's Switch → UNCONFIRMED

**Objective:** Demonstrate the automatic transition to UNCONFIRMED when owner doesn't respond to DMS prompts.

### How Dead Man's Switch Works:
The Dead Man's Switch is a system-level protection that triggers automatically based on stay conditions:
- **48h before lease end:** First alert email to owner
- **On lease end day:** Urgent reminder email to owner
- **48h after lease end:** If no owner response, status flips to UNCONFIRMED

### Prerequisites:
- Have an active stay with Dead Man's Switch enabled (set via test script or API)
- Stay end date is more than 48 hours in the past
- Owner has NOT confirmed status (no vacated/renewed/holdover selection)

### Quick Test Setup:
```bash
cd c:\Users\arfam\Documents\Docustay\Docustay
.\.venv\Scripts\python.exe scripts/test_dms_unconfirmed.py
```

### Expected Results:
- Property status changes to **UNCONFIRMED**
- `dead_mans_switch_triggered_at` set on stay
- Shield Mode activated on property
- USAT token revoked
- Audit log entry: "Dead Man's Switch: auto-executed" with `occupancy_status_previous` → `occupancy_status_new: "unconfirmed"`

### Emails Sent:
- **To Owner:** DMS auto-executed notification
- **To Owner:** Shield Mode activated notification

---

## Test Flow 8: Owner Confirms Status (Exit UNCONFIRMED)

**Objective:** Demonstrate the three ways an owner can confirm status and exit UNCONFIRMED state.

### Prerequisites:
- Property is in UNCONFIRMED status (from Flow 7)
- OR property has a stay in the confirmation window (48h before → 48h after lease end)

### Steps:
1. Login as **Owner**
2. Navigate to **Dashboard** → **Properties** → Select property
3. See the "Confirm occupancy status" panel
4. Choose one of three options:

#### Option A: Unit Vacated
- Click **Unit Vacated**
- Property status → **VACANT**
- Stay marked as checked out
- Audit log: "Owner confirmed: Unit Vacated"

#### Option B: Lease Renewed
- Click **Lease Renewed**
- Enter new lease end date
- Click **Confirm renewal**
- Property status → **OCCUPIED**
- Stay end date updated
- Audit log: "Owner confirmed: Lease Renewed"

#### Option C: Holdover
- Click **Holdover**
- Property status → **OCCUPIED**
- Indicates guest still present without formal renewal
- Audit log: "Owner confirmed: Holdover"

### Emails Sent:
- None (confirmation is logged but no email notification)

---

## Test Flow 9: Initiate Removal (Eviction)

**Objective:** Demonstrate formal removal initiation for overstayed guests.

### Prerequisites:
- Have an overstayed guest (stay_end_date < today, guest not checked out)

### Steps:
1. Login as **Owner**
2. Navigate to **Dashboard**
3. See the "Overstay Detected" alert OR find overstayed guest in list
4. Click **Initiate Removal** / **Remove**
5. Review the confirmation modal:
   - Actions to be taken listed
   - Property and jurisdiction shown
6. Click **Confirm Removal**

### Expected Results:
- USAT token revoked (utility access disabled)
- Stay marked as revoked (if not already)
- Audit log entry: "Removal initiated" with full details

### Emails Sent:
- **To Guest:** Urgent removal notice (must vacate immediately)
- **To Owner:** Removal confirmation with actions taken

---

## Email Notification Summary

| Event | To Owner | To Guest |
|-------|----------|----------|
| Property Created | - | - |
| Invitation Sent | - | Invitation email |
| Invitation Accepted | Acceptance notification | Welcome email |
| Guest Checkout | Checkout notification | Checkout confirmation |
| Guest Cancels Stay | Cancellation notification | - |
| Stay Revoked (Kill Switch) | - | 12-hour vacate notice |
| Overstay Detected | Overstay alert | Overstay warning |
| DMS 48h Before | Reminder email | - |
| DMS Lease End Day | Urgent reminder | - |
| DMS Auto-Executed | Auto-execute + Shield Mode emails | - |
| Removal Initiated | Removal confirmation | Removal notice |

---

## Audit Log Categories

All state changes are logged with these categories:
- `status_change` - Property/stay status changes
- `dead_mans_switch` - DMS-related events
- `failed_attempt` - Failed actions (overlapping stays, etc.)
- `shield_mode` - Shield mode activation/deactivation
- `guest_signature` - Agreement signing events

---

## Quick Test Commands

### View Audit Logs for a Property
```bash
cd c:\Users\arfam\Documents\Docustay\Docustay
.\.venv\Scripts\python.exe -c "
from app.database import SessionLocal
from app.models.audit_log import AuditLog

db = SessionLocal()
logs = db.query(AuditLog).filter(AuditLog.property_id == 2).order_by(AuditLog.created_at.desc()).limit(10).all()
for log in reversed(logs):
    print(f'[{log.created_at}] {log.category}: {log.title}')
    print(f'  {log.message[:100]}...' if len(log.message or '') > 100 else f'  {log.message}')
db.close()
"
```

### Manually Trigger DMS Job
```bash
cd c:\Users\arfam\Documents\Docustay\Docustay
.\.venv\Scripts\python.exe -c "
from app.database import SessionLocal
from app.services.stay_timer import run_dead_mans_switch_job

db = SessionLocal()
run_dead_mans_switch_job(db)
db.close()
print('DMS job completed.')
"
```

### Reset Property to UNCONFIRMED for Testing
```bash
cd c:\Users\arfam\Documents\Docustay\Docustay
.\.venv\Scripts\python.exe -c "
from app.database import SessionLocal
from app.models.owner import Property

db = SessionLocal()
prop = db.query(Property).filter(Property.id == 2).first()
if prop:
    prop.occupancy_status = 'unconfirmed'
    db.commit()
    print(f'Property {prop.id} set to UNCONFIRMED')
db.close()
"
```

---

## Demo Checklist

Before the demo, ensure:
- [ ] At least one property exists
- [ ] At least one guest account exists
- [ ] Test email addresses are configured to receive emails
- [ ] Database has sample data for different states
- [ ] Backend server is running
- [ ] Frontend is accessible

During the demo, show:
- [ ] Property creation (UNKNOWN state)
- [ ] Invitation flow (OCCUPIED state)
- [ ] Guest checkout (VACANT state)
- [ ] Overstay detection (emails to both parties)
- [ ] DMS UNCONFIRMED transition
- [ ] Owner confirmation UI (exit UNCONFIRMED)
- [ ] Initiate Removal flow (eviction)
- [ ] Audit log entries for all actions
