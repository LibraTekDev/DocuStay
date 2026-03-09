# Why "This invitation has expired or is invalid" can appear before expiry

The message **"This invitation has expired or is invalid. You can't use this link to sign."** is shown when the **GET /agreements/invitation/{code}** request fails with a 404 and the error text contains "expired", "not found", or "not pending". So the user sees it whenever the agreement endpoint cannot return an agreement for that code — not only when the invite has actually expired.

## When does the backend return 404?

`build_invitation_agreement()` returns `None` (and the route returns 404 "Invitation not found or not pending") when:

1. **No invitation with that code**  
   The `invitation_code` in the URL does not match any row in the DB (wrong code, typo, or link from another env).

2. **Status not allowed**  
   Only `status in ["pending", "ongoing"]` is allowed. If the invite is `expired`, `cancelled`, or `accepted` in a way that excludes it, the lookup returns nothing.

3. **Token state filter (guest vs tenant)**  
   - **Guest invites**: must have `token_state != "BURNED"` (only STAGED invites can load the agreement to sign).  
   - **Tenant invites**: are created with `token_state="BURNED"`; the codebase allows them by treating tenant kind separately (`invitation_kind == "tenant"` OR `token_state != "BURNED"`). If that logic were missing, tenant links would always 404.

4. **Actual expiry (cleanup job)**  
   Pending guest invites are marked expired by a background job after:
   - **test_mode**: 5 minutes  
   - **production**: 12 hours  

   So if the link is correct and the invite is guest/STAGED, "just created" should not be expired unless the job has already run (e.g. >5 min in test_mode).

## Causes that make it seem "before expiring"

- **Wrong code in the link**  
  If the UI or copy-paste uses a code that was never saved (e.g. frontend fallback to a random code when the create API didn’t return `invitation_code`), the backend will 404 immediately. The frontend was updated to never use a random code and to treat a missing `invitation_code` in the create response as an error.

- **Tenant invite link**  
  Tenant invites are created with `token_state="BURNED"`. Previously, the agreement endpoint required `token_state != "BURNED"`, so tenant links always 404’d. The agreement builder was updated to allow tenant invites (by invitation kind) so they can load and sign.

- **Paste/link parsing**  
  When pasting a link (e.g. on the tenant dashboard), the extracted code must match the DB exactly (after trim/uppercase). If the pasted URL or path is wrong, the extracted code won’t match and the user gets the same error.

- **Expiry in test_mode**  
  In test_mode, pending invites expire after 5 minutes. If the user created the invite, left the tab, and came back after 5+ minutes, the invite may already be expired.

## What was changed

- **Backend**: Allow tenant invites in `build_invitation_agreement` (so BURNED tenant invites can load the agreement).  
- **Backend**: Log a warning when the agreement lookup returns 404 (with the requested `invitation_code`) to help debug code mismatches.  
- **Frontend**: Do not use a random fallback when the create-invitation API does not return `invitation_code`; return an error so the user never gets a link that can’t be used.  
- **Expiry**: Guest invitation expiry remains **test_mode 5 min**, **production 12 hours**.

## How to debug next time

1. Check server logs for: `Agreement lookup 404: invitation_code='INV-...'`.  
2. In the DB, confirm there is an invitation with that exact `invitation_code`, and check its `status`, `token_state`, and `invitation_kind`.  
3. Confirm the link the user is using (or the code parsed from paste) is exactly that code (no extra characters, correct path/hash segment).
