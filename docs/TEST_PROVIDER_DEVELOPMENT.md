# Test provider (development only — remove in production)

A **test provider** lets you test the full authority letter flow (email + sign link + Dropbox signature) without sending emails to real utility providers. For development only; do not use in production.

## Behavior when `TEST_PROVIDER_EMAIL` is set (testing env)

- **Send rule**: Authority letter emails are sent **only when the provider has a contact email**. In testing, we **never send to real authorities**—only to the test provider address.
  - When the user selects **"Test provider"** for a utility, we store that provider with `contact_email = TEST_PROVIDER_EMAIL`, so the authority letter email is sent to that address.
  - For any other provider (real or custom), if they have a `contact_email`, we **do not** send in testing (we skip so no real provider receives email).
  - If a provider has no email, no email is sent (no fallback to test address for unknown providers).
- **Provider contact lookup**: The background job that looks up real provider emails (e.g. SerpApi) still runs and may fill `contact_email` for electric/gas/internet. In testing, we **do not send** those emails to the found addresses; we only send to the test provider when the user explicitly chose "Test provider".

## Frontend

- **Add Property (step 4 – Utilities)**: When `test_provider_email` is present in owner config, each utility dropdown gets an extra option **"Test provider (your-test@example.com)"**. A banner explains: *"Testing: Authority letter emails are sent only to the test provider address. No emails are sent to real utility providers."*
- **Property Detail – Utilities tab**: When `test_provider_email` is present, a **"Test provider (development only)"** section shows one row per utility type with that email (for reference).

## Email and signature flow for test provider

1. User adds a property and selects **Test provider** for one or more utilities.
2. Backend saves providers with `contact_email = TEST_PROVIDER_EMAIL` for those selections and sends one authority letter email per letter to that address (with sign link).
3. Test inbox receives email(s); each link is `{frontend}#/provider/authority/{token}`.
4. Opening the link loads the public authority letter page; backend `GET /agreements/authority-letter/{token}` returns the letter content (no auth).
5. User signs via Dropbox; frontend calls `POST /agreements/authority-letter/{token}/sign-with-dropbox`. Signature is recorded and PDF is stored.
6. Owner can see signed status and signed PDF on the property Utilities tab.

The flow is the same for test provider as for a real provider; only the recipient address is the test inbox.

## How to enable in development

1. In `.env` set: `TEST_PROVIDER_EMAIL=your-test@example.com`
2. Restart the backend.
3. Add a property and on step 4 choose **Test provider** for at least one utility. Submit; check the test inbox for the authority letter email and complete the sign flow.

## Production

- **Do not set `TEST_PROVIDER_EMAIL` in production.** Leave it unset or empty. Then:
  - `GET /owners/config` returns `test_provider_email: null`.
  - Frontend does not show the test provider option or banner.
  - Authority letter emails are sent only to providers that have a `contact_email` (no test redirect, no sending to test address).
