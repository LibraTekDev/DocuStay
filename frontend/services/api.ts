/**
 * DocuStay backend API client.
 * Replaces Gemini service for auth, properties, and invitations.
 * All URLs from .env; no hardcoded localhost (set VITE_API_URL and VITE_APP_ORIGIN in .env for deployment).
 */
export const API_URL = (import.meta as any).env?.VITE_API_URL ?? (typeof window !== "undefined" ? "/api" : "");
/** Frontend app origin for Stripe return_url, invite links, etc. From .env VITE_APP_ORIGIN, or window.location.origin in browser. */
export const APP_ORIGIN =
  (import.meta as any).env?.VITE_APP_ORIGIN ?? (typeof window !== "undefined" ? window.location.origin : "");

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("docustay_token");
}

export function setToken(token: string | null) {
  if (typeof window === "undefined") return;
  if (token) localStorage.setItem("docustay_token", token);
  else localStorage.removeItem("docustay_token");
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: HeadersInit = {
    "Content-Type": "application/json",
    Accept: "application/json",
    ...(options.headers as Record<string, string>),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { ...options, headers });
  } catch (e) {
    const msg = (e as Error)?.message ?? "";
    if (msg === "Failed to fetch" || msg.includes("fetch") || msg.includes("NetworkError")) {
      throw new Error("The server is unavailable. Please try again later.");
    }
    throw e;
  }
  if (res.status === 401) {
    const text = await res.text();
    let detail = "";
    try {
      const j = JSON.parse(text);
      detail = (Array.isArray(j.detail) ? j.detail.map((d: any) => d.msg || d).join(", ") : (j.detail ?? "")) || "";
    } catch {
      detail = text || "";
    }
    const isLoginRequest = path === "/auth/login";
    const isOnboardingPage =
      typeof window !== "undefined" &&
      (window.location.hash.includes("onboarding/identity") ||
        window.location.hash.includes("onboarding/poa") ||
        window.location.pathname.includes("onboarding/identity") ||
        window.location.pathname.includes("onboarding/poa"));
    if (!isLoginRequest && typeof window !== "undefined" && !isOnboardingPage) {
      setToken(null);
      window.location.hash = "login";
      window.location.reload();
    }
    if (isLoginRequest) {
      throw new Error(detail || "Invalid email or password.");
    }
    // 401 on pending-owner: "try logging in" only for complete-signup (account may exist); otherwise "start over"
    if (path.includes("/auth/pending-owner/")) {
      const d = (detail || "").toLowerCase();
      const isCompleteSignup = path.includes("complete-signup");
      if ((d.includes("signup session not found") || d.includes("session not found")) && isCompleteSignup) {
        throw new Error("Your account may already be created. Try logging in with your email and password.");
      }
      if (d.includes("signup session not found") || d.includes("session not found")) {
        throw new Error("Your signup session was lost. Please start over from registration.");
      }
      if (d.includes("expired") || d.includes("invalid or expired")) {
        throw new Error("Your signup session expired. Please start over from registration or try logging in if you already completed signup.");
      }
      if (d.includes("not authenticated")) {
        throw new Error("Your session was lost. Please start over from registration.");
      }
      throw new Error(detail || "Something went wrong. Please start over from registration.");
    }
    throw new Error(detail || "Session expired. Please log in again.");
  }
  if (!res.ok) {
    const text = await res.text();
    let detail: string | object = text;
    try {
      const j = JSON.parse(text);
      detail = Array.isArray(j.detail) ? j.detail.map((d: any) => d.msg || d).join(", ") : (j.detail ?? text);
    } catch {
      // use text as-is
    }
    const detailStr = typeof detail === "object" && detail !== null && "detail" in (detail as object)
      ? String((detail as { detail?: string }).detail ?? text)
      : String(detail);
    if (res.status === 403 && typeof window !== "undefined") {
      const d = detailStr.toLowerCase();
      if (d.includes("identity verification")) window.location.hash = "onboarding/identity";
      else if (d.includes("master poa") || d.includes("poa")) window.location.hash = "onboarding/poa";
    }
    const err = new Error(detailStr) as Error & { errorCode?: string; sessionId?: string };
    if (typeof detail === "object" && detail !== null && "error_code" in (detail as object)) {
      err.errorCode = (detail as { error_code?: string }).error_code;
    }
    if (typeof detail === "object" && detail !== null && "session_id" in (detail as object)) {
      err.sessionId = (detail as { session_id?: string }).session_id;
    }
    throw err;
  }
  if (res.status === 204 || res.headers.get("content-length") === "0") return undefined as T;
  return res.json() as Promise<T>;
}

// --- Auth (match reference app expected shapes) ---
export type UserType = "PROPERTY_OWNER" | "GUEST";
export type AccountStatus = "PENDING_VERIFICATION" | "ACTIVE" | "FULLY_VERIFIED";

export interface UserSession {
  user_id: string;
  user_type: UserType;
  user_name: string;
  email: string;
  account_status: AccountStatus;
  token: string;
  identity_verified?: boolean;
  poa_linked?: boolean;
}

interface BackendUser {
  id: number;
  email: string;
  role: "owner" | "guest";
  full_name?: string | null;
  phone?: string | null;
  state?: string | null;
  city?: string | null;
  identity_verified?: boolean;
  poa_linked?: boolean;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user: BackendUser;
}

export function toUserSession(t: TokenResponse): UserSession {
  const u = t.user;
  return {
    user_id: String(u.id),
    user_type: u.role === "owner" ? "PROPERTY_OWNER" : "GUEST",
    user_name: u.full_name || u.email,
    email: u.email,
    account_status: "ACTIVE",
    token: t.access_token,
    identity_verified: u.identity_verified ?? false,
    poa_linked: u.poa_linked ?? false,
  };
}

export const authApi = {
  async login(
    email: string,
    password: string,
    role?: "owner" | "guest",
  ): Promise<{ status: string; data: UserSession; message?: string }> {
    const body = await request<TokenResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password, role: role ?? null }),
    });
    setToken(body.access_token);
    return { status: "success", data: toUserSession(body) };
  },
  async register(data: {
    full_name: string;
    email: string;
    phone: string;
    password: string;
    confirm_password: string;
    country: string;
    state: string;
    city: string;
    terms_agreed: boolean;
    privacy_agreed: boolean;
    poa_signature_id?: number | null;
  }): Promise<{
    status: string;
    data?: { user_id: string } | UserSession;
    skipVerification?: boolean;
    message?: string;
    validation?: Record<string, { error?: string }>;
  }> {
    try {
      const body = await request<{ user_id?: number; message?: string } & Partial<TokenResponse>>("/auth/register", {
        method: "POST",
        body: JSON.stringify({
          full_name: data.full_name,
          email: data.email,
          phone: data.phone,
          password: data.password,
          confirm_password: data.confirm_password,
          country: data.country,
          state: data.state,
          city: data.city,
          terms_agreed: data.terms_agreed,
          privacy_agreed: data.privacy_agreed,
          role: "owner",
          poa_signature_id: data.poa_signature_id ?? undefined,
        }),
      });
      if (body.access_token && body.user) {
        setToken(body.access_token);
        return {
          status: "success",
          data: toUserSession(body as TokenResponse),
          skipVerification: true,
        };
      }
      return {
        status: "success",
        data: { user_id: String(body.user_id!) },
      };
    } catch (e: any) {
      const msg = e?.message || "Registration failed";
      const validation: Record<string, { error: string }> = {};
      if (msg.includes("Passwords")) validation.password_match = { error: "Passwords do not match" };
      if (msg.includes("agree")) {
        validation.terms = { error: "You must agree to the Terms of Service" };
        validation.privacy = { error: "You must agree to the Privacy Policy" };
      }
      if (msg.includes("property owner")) validation.email = { error: "This email is already registered as a property owner. Please log in on the Owner Login page." };
      else if (msg.includes("already registered")) validation.email = { error: "Email already registered" };
      if (msg.toLowerCase().includes("phone") || msg.includes("digits")) validation.phone = { error: msg };
      return { status: "error", message: msg, validation };
    }
  },
  logout() {
    setToken(null);
  },
  getToken,
  /** Request password reset email. Role identifies owner vs guest when same email has both accounts. */
  async forgotPassword(email: string, role: "owner" | "guest"): Promise<{ status: string; message?: string }> {
    const res = await request<{ status?: string; message?: string }>("/auth/forgot-password", {
      method: "POST",
      body: JSON.stringify({ email: email.trim().toLowerCase(), role }),
    });
    return { status: (res as any)?.status || "ok", message: (res as any)?.message };
  },
  /** Set new password using token from reset email. */
  async resetPassword(token: string, new_password: string, confirm_password: string): Promise<{ status: string; message?: string }> {
    const res = await request<{ status?: string; message?: string }>("/auth/reset-password", {
      method: "POST",
      body: JSON.stringify({ token, new_password, confirm_password }),
    });
    return { status: (res as any)?.status || "ok", message: (res as any)?.message };
  },
  /** Accept an invitation as an existing guest (requires guest token). */
  async acceptInvite(invitationCode: string, agreementSignatureId: number): Promise<{ status: string; message?: string }> {
    const res = await request<{ status?: string; message?: string }>("/auth/accept-invite", {
      method: "POST",
      body: JSON.stringify({
        invitation_code: invitationCode.trim().toUpperCase(),
        agreement_signature_id: agreementSignatureId,
      }),
    });
    return { status: (res as any)?.status || "success", message: (res as any)?.message };
  },
  /** Verify email with code sent after registration. Returns token and sets it. */
  async verifyEmail(userId: string, code: string): Promise<{ status: string; data?: UserSession; message?: string }> {
    try {
      const body = await request<TokenResponse>("/auth/verify-email", {
        method: "POST",
        body: JSON.stringify({ user_id: Number(userId), code: code.trim() }),
      });
      setToken(body.access_token);
      return { status: "success", data: toUserSession(body) };
    } catch (e: any) {
      return { status: "error", message: e?.message ?? "Verification failed" };
    }
  },

  /** Resend verification code to the user's email. */
  async resendVerification(userId: string): Promise<{ status: string; message?: string }> {
    try {
      await request<{ status?: string; message?: string }>("/auth/resend-verification", {
        method: "POST",
        body: JSON.stringify({ user_id: Number(userId) }),
      });
      return { status: "success", message: "Verification code sent. Check your email." };
    } catch (e: any) {
      return { status: "error", message: e?.message ?? "Failed to resend" };
    }
  },

  /** Get current user (requires token). Used after verify step. */
  async me(): Promise<UserSession | null> {
    try {
      const body = await request<BackendUser>("/auth/me");
      const token = getToken();
      if (!token) return null;
      return {
        user_id: String(body.id),
        user_type: body.role === "owner" ? "PROPERTY_OWNER" : "GUEST",
        user_name: body.full_name || body.email,
        email: body.email,
        account_status: "ACTIVE",
        token,
        identity_verified: body.identity_verified ?? false,
        poa_linked: body.poa_linked ?? false,
      };
    } catch {
      return null;
    }
  },

  /** Link Master POA signature to current owner (after identity verification). Set authorizedAgentCertified true when user is Authorized Agent. */
  async linkOwnerPoa(poaSignatureId: number, authorizedAgentCertified = false): Promise<{ status: string; message?: string }> {
    const res = await request<{ status?: string; message?: string }>("/auth/owner/link-poa", {
      method: "POST",
      body: JSON.stringify({ poa_signature_id: poaSignatureId, authorized_agent_certified: authorizedAgentCertified }),
    });
    return { status: (res as any)?.status ?? "ok", message: (res as any)?.message };
  },
};

// --- Identity verification (Stripe Identity for owner onboarding) ---
export const identityApi = {
  /** Create a verification session (for existing owner user); returns URL to redirect to Stripe Identity. */
  async createVerificationSession(): Promise<{ client_secret: string; url?: string | null }> {
    return request<{ client_secret: string; url?: string | null }>("/auth/identity/verification-session", {
      method: "POST",
    });
  },
  /** Confirm identity after return from Stripe (for existing owner user). */
  async confirmIdentity(verificationSessionId: string): Promise<{ status: string; message?: string }> {
    return request<{ status?: string; message?: string }>("/auth/identity/confirm", {
      method: "POST",
      body: JSON.stringify({ verification_session_id: verificationSessionId }),
    });
  },
};

// --- Pending owner signup flow (after email verify, before user exists in DB) ---
export const pendingOwnerApi = {
  /** Create Stripe Identity session for pending owner. Return URL includes pending_id. */
  async createIdentitySession(): Promise<{ client_secret: string; url?: string | null }> {
    return request<{ client_secret: string; url?: string | null }>("/auth/pending-owner/identity-session", {
      method: "POST",
    });
  },
  /** Confirm identity after Stripe redirect (updates pending record). */
  async confirmIdentity(verificationSessionId: string): Promise<{ status: string; message?: string }> {
    return request<{ status?: string; message?: string }>("/auth/pending-owner/confirm-identity", {
      method: "POST",
      body: JSON.stringify({ verification_session_id: verificationSessionId }),
    });
  },
  /** Get the verification_session_id we stored when creating the session. Use when Stripe redirect omits session_id in URL. */
  async getLatestIdentitySession(): Promise<{ verification_session_id: string }> {
    return request<{ verification_session_id: string }>("/auth/pending-owner/latest-identity-session");
  },
  /** Get a fresh Stripe Identity URL to retry verification (same session). Returns url for requires_input; already_verified if done. */
  async getIdentityRetryUrl(verificationSessionId: string): Promise<{ url?: string | null; already_verified?: boolean; message?: string }> {
    return request<{ url?: string | null; already_verified?: boolean; message?: string }>("/auth/pending-owner/identity-retry", {
      method: "POST",
      body: JSON.stringify({ verification_session_id: verificationSessionId }),
    });
  },
  /** Get email/full_name for POA modal. */
  async me(): Promise<{ email: string; full_name: string | null }> {
    return request<{ email: string; full_name: string | null }>("/auth/pending-owner/me");
  },
  /** Create user, link POA, delete pending; returns token + user. */
  async completeSignup(poaSignatureId: number): Promise<{ access_token: string; token_type: string; user: BackendUser }> {
    return request<{ access_token: string; token_type: string; user: BackendUser }>("/auth/pending-owner/complete-signup", {
      method: "POST",
      body: JSON.stringify({ poa_signature_id: poaSignatureId }),
    });
  },
};

// --- Dashboard (owner stays: real data from DB) ---
export type RiskLevel = "low" | "medium" | "high";
export type StayClassification = "guest" | "lodger" | "tenant_risk";

export interface OwnerStayView {
  stay_id: number;
  property_id: number;
  guest_name: string;
  property_name: string;
  stay_start_date: string;
  stay_end_date: string;
  region_code: string;
  legal_classification: StayClassification;
  max_stay_allowed_days: number;
  risk_indicator: RiskLevel;
  applicable_laws: string[];
  revoked_at?: string | null;
  checked_out_at?: string | null;
  cancelled_at?: string | null;
  usat_token_released_at?: string | null;
  dead_mans_switch_enabled?: boolean;
  needs_occupancy_confirmation?: boolean;
  show_occupancy_confirmation_ui?: boolean;
  confirmation_deadline_at?: string | null;
  occupancy_confirmation_response?: string | null;
}

export interface OwnerInvitationView {
  id: number;
  invitation_code: string;
  property_id: number;
  property_name: string;
  guest_name?: string | null;
  guest_email: string | null;
  stay_start_date: string;
  stay_end_date: string;
  region_code: string;
  status: string;
  created_at: string | null;
  is_expired?: boolean;
}

export interface GuestStayView {
  stay_id: number;
  property_name: string;
  approved_stay_start_date: string;
  approved_stay_end_date: string;
  region_code: string;
  region_classification: string;
  legal_notice: string;
  statute_reference?: string | null;
  plain_english_explanation?: string | null;
  applicable_laws: string[];
  usat_token?: string | null;
  revoked_at?: string | null;
  vacate_by?: string | null;
  checked_out_at?: string | null;
  cancelled_at?: string | null;
}

export interface GuestPendingInviteView {
  invitation_code: string;
  property_name: string;
  stay_start_date: string;
  stay_end_date: string;
  host_name: string | null;
  region_code: string;
}

export interface OwnerAuditLogEntry {
  id: number;
  property_id: number | null;
  stay_id: number | null;
  invitation_id: number | null;
  category: string;
  title: string;
  message: string;
  actor_user_id: number | null;
  actor_email: string | null;
  ip_address: string | null;
  created_at: string;
  property_name: string | null;
}

export interface BillingInvoiceView {
  id: string;
  number: string | null;
  description: string | null;
  amount_due_cents: number;
  amount_paid_cents: number;
  currency: string;
  status: string;
  created: string;
  hosted_invoice_url: string | null;
}

export interface BillingPaymentView {
  invoice_id: string;
  amount_cents: number;
  currency: string;
  paid_at: string;
  description: string | null;
}

export interface BillingResponse {
  invoices: BillingInvoiceView[];
  payments: BillingPaymentView[];
  /** False until onboarding invoice is paid; owner cannot invite guests until then. */
  can_invite: boolean;
  /** Active property count (subscription is based on this). */
  current_unit_count?: number | null;
  /** Properties with Shield on. */
  current_shield_count?: number | null;
}

export const dashboardApi = {
  ownerStays: () => request<OwnerStayView[]>("/dashboard/owner/stays"),
  ownerInvitations: () => request<OwnerInvitationView[]>("/dashboard/owner/invitations"),
  /** Invoices and payments for owner billing section. */
  billing: () => request<BillingResponse>("/dashboard/owner/billing"),
  /** Create Stripe Billing Portal session; redirect user to returned URL to pay. After payment (e.g. Klarna) they return to our app. */
  billingPortalSession: () =>
    request<{ url: string }>("/dashboard/owner/billing/portal-session", { method: "POST" }),
  /** Cancel a pending invitation (owner only). */
  cancelInvitation: (invitationId: number) =>
    request<{ status: string; message?: string }>(`/dashboard/owner/invitations/${invitationId}/cancel`, { method: "POST" }),
  /** Append-only audit logs for owner's properties. Filter by time (ISO UTC), category, search. */
  ownerLogs: (params?: { from_ts?: string; to_ts?: string; category?: string; search?: string }) => {
    const sp = new URLSearchParams();
    if (params?.from_ts) sp.set("from_ts", params.from_ts);
    if (params?.to_ts) sp.set("to_ts", params.to_ts);
    if (params?.category) sp.set("category", params.category);
    if (params?.search) sp.set("search", params.search);
    const q = sp.toString();
    return request<OwnerAuditLogEntry[]>(`/dashboard/owner/logs${q ? `?${q}` : ""}`);
  },
  guestStays: () => request<GuestStayView[]>("/dashboard/guest/stays"),
  guestPendingInvites: () => request<GuestPendingInviteView[]>("/dashboard/guest/pending-invites"),
  guestAddPendingInvite: (invitationCode: string) =>
    request<GuestPendingInviteView>("/dashboard/guest/pending-invites", {
      method: "POST",
      body: JSON.stringify({ invitation_code: invitationCode.trim().toUpperCase() }),
    }),
  /** Get signed guest agreement PDF for a stay. Guest only. Returns blob. */
  guestStaySignedAgreementBlob: async (stayId: number): Promise<Blob> => {
    const res = await fetch(`${API_URL}/dashboard/guest/stays/${stayId}/signed-agreement-pdf`, {
      headers: { Authorization: `Bearer ${getToken()}` },
    });
    if (res.status === 404) throw new Error("No signed agreement found for this stay.");
    if (!res.ok) throw new Error(await res.text().catch(() => "Failed to load signed agreement."));
    return res.blob();
  },
  /** End an ongoing stay (sets end date to today). Guest only. */
  guestEndStay: (stayId: number) =>
    request<{ status: string; message?: string }>(`/dashboard/guest/stays/${stayId}/end`, { method: "POST" }),
  /** Cancel a future stay. Guest only. */
  guestCancelStay: (stayId: number) =>
    request<{ status: string; message?: string }>(`/dashboard/guest/stays/${stayId}/cancel`, { method: "POST" }),
  /** Revoke stay (Kill Switch). Owner only. Guest must vacate in 12 hours; email sent to guest. */
  revokeStay: (stayId: number) =>
    request<{ status: string; message?: string }>(`/dashboard/owner/stays/${stayId}/revoke`, { method: "POST" }),
  /** Initiate formal removal for overstayed guest. Revokes USAT token, sends emails to guest and owner. */
  initiateRemoval: (stayId: number) =>
    request<{ status: string; message?: string; usat_revoked?: boolean }>(`/dashboard/owner/stays/${stayId}/initiate-removal`, { method: "POST" }),
  /** Owner confirms occupancy: Unit Vacated, Lease Renewed, or Holdover. */
  confirmOccupancyStatus: (stayId: number, action: "vacated" | "renewed" | "holdover", newLeaseEndDate?: string) =>
    request<{ status: string; message?: string; occupancy_status?: string; new_lease_end_date?: string }>(
      `/dashboard/owner/stays/${stayId}/confirm-occupancy`,
      {
        method: "POST",
        body: JSON.stringify(
          action === "renewed" ? { action, new_lease_end_date: newLeaseEndDate } : { action }
        ),
      }
    ),
};

// --- Properties ---
export interface Property {
  id: number;
  name: string | null;
  street: string;
  city: string;
  state: string;
  zip_code: string | null;
  region_code: string;
  owner_occupied: boolean;
  property_type: string | null;
  property_type_label: string | null;
  bedrooms: string | null;
  usat_token?: string | null;
  usat_token_state?: string;
  usat_token_released_at?: string | null;
  deleted_at?: string | null;
  /** Shield Mode: software monitoring. ON = PASSIVE GUARD (occupied) or ACTIVE MONITORING (vacant). Owner can turn OFF. */
  shield_mode_enabled?: boolean;
  occupancy_status?: string;  // vacant | occupied | unknown | unconfirmed
  ownership_proof_filename?: string | null;
  ownership_proof_type?: string | null;
  ownership_proof_uploaded_at?: string | null;
}

export interface BulkUploadResult {
  created: number;
  updated: number;
  failed_from_row: number | null;
  failure_reason: string | null;
}

/** Utility Bucket: providers and authority letters for a property. */
export interface PropertyUtilityProviderItem {
  id: number;
  provider_name: string;
  provider_type: string;
  utilityapi_id: string | null;
  contact_phone: string | null;
  contact_email: string | null;
}

export interface PropertyAuthorityLetterItem {
  id: number;
  provider_name: string;
  provider_type?: string;
  letter_content: string;
  email_sent_at?: string | null;
  signed_at?: string | null;
  has_signed_pdf?: boolean;
}

/** User-added provider not in list; verification from background job. */
export interface PendingProviderItem {
  id: number;
  provider_name: string;
  provider_type: string;
  verification_status: string; // pending | in_progress | approved | rejected
}

export interface PropertyUtilitiesResponse {
  providers: PropertyUtilityProviderItem[];
  authority_letters: PropertyAuthorityLetterItem[];
  pending_providers?: PendingProviderItem[];
}

/** Verify address + get utility options (for add-property flow). */
export interface VerifyAddressAndUtilitiesResponse {
  standardized_address: {
    delivery_line_1?: string | null;
    city_name?: string | null;
    state_abbreviation?: string | null;
    zipcode?: string | null;
    latitude?: number | null;
    longitude?: number | null;
  } | null;
  providers_by_type: Record<string, { name: string; phone: string | null }[]>;
}

export const propertiesApi = {
  /** Active properties only (dashboard main list and invite dropdown). */
  list: () => request<Property[]>("/owners/properties"),
  /** Inactive (soft-deleted) properties only. */
  listInactive: () => request<Property[]>("/owners/properties?inactive=1"),
  add: (data: {
    property_name?: string;
    street_address: string;
    city: string;
    state: string;
    zip_code?: string;
    country?: string;
    property_type?: string;
    bedrooms?: string;
    is_primary_residence: boolean;
  }) =>
    request<Property>("/owners/properties", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  get: (id: number) => request<Property>(`/owners/properties/${id}`),
  /** Utility Bucket: providers and authority letters for this property. */
  getUtilities: (id: number) => request<PropertyUtilitiesResponse>(`/owners/properties/${id}/utilities`),
  /** Verify address (Smarty) and fetch utility options by type. For add-property utilities step. */
  verifyAddressAndUtilities: (data: { street_address: string; city: string; state: string; zip_code?: string }) =>
    request<VerifyAddressAndUtilitiesResponse>("/owners/verify-address-and-utilities", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  /** Save owner-selected utility providers and generate authority letters. */
  setPropertyUtilities: (propertyId: number, data: { selected: { provider_type: string; provider_name: string }[]; pending: { provider_type: string; provider_name: string }[] }) =>
    request<PropertyUtilitiesResponse>(`/owners/properties/${propertyId}/utilities`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  /** Start background lookup for provider contact emails (electric/gas/internet with null email). Returns 202 Accepted. */
  lookupProviderContacts: (propertyId: number, providerIds?: number[]) =>
    request<{ message: string }>(`/owners/properties/${propertyId}/provider-contacts/lookup`, {
      method: "POST",
      body: JSON.stringify(providerIds != null ? { provider_ids: providerIds } : {}),
    }),
  /** Owner config (e.g. test provider email for development). */
  getOwnerConfig: () => request<{ test_provider_email: string | null }>("/owners/config"),
  /** Send authority letters to providers by email (in dev: to TEST_PROVIDER_EMAIL). */
  emailAuthorityLettersToProviders: (propertyId: number) =>
    request<{ message: string; sent_count: number }>(`/owners/properties/${propertyId}/email-providers`, {
      method: "POST",
    }),
  /** Get signed PDF for an authority letter (owner auth). Returns blob URL for opening in new tab. */
  getAuthorityLetterSignedPdfUrl: async (propertyId: number, letterId: number): Promise<string> => {
    const token = getToken();
    const res = await fetch(`${API_URL}/owners/properties/${propertyId}/authority-letters/${letterId}/signed-pdf`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) throw new Error(await res.text().then((t) => t || res.statusText));
    const blob = await res.blob();
    return URL.createObjectURL(blob);
  },
  update: (id: number, data: {
    property_name?: string;
    street_address?: string;
    city?: string;
    state?: string;
    zip_code?: string;
    region_code?: string;
    property_type?: string;
    bedrooms?: string;
    is_primary_residence?: boolean;
    owner_occupied?: boolean;
    shield_mode_enabled?: boolean;
  }) =>
    request<Property>(`/owners/properties/${id}`, {
      method: "PUT",
      body: JSON.stringify(data),
    }),
  delete: (id: number) =>
    request<{ status: string; message: string }>(`/owners/properties/${id}`, {
      method: "DELETE",
    }),
  /** Reactivate an inactive (soft-deleted) property. */
  reactivate: (id: number) =>
    request<Property>(`/owners/properties/${id}/reactivate`, { method: "POST" }),
  /** Get ownership proof URL for viewing (opens in new tab). Returns blob URL; caller should revoke when done. */
  getOwnershipProofBlob: async (propertyId: number): Promise<Blob> => {
    const token = getToken();
    const headers: HeadersInit = {};
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const res = await fetch(`${API_URL}/owners/properties/${propertyId}/ownership-proof`, { headers });
    if (res.status === 404) throw new Error("No ownership proof uploaded for this property.");
    if (!res.ok) throw new Error(await res.text().catch(() => "Failed to load proof."));
    return res.blob();
  },
  /** Upload ownership proof (deed, tax bill, etc.) for a property. */
  uploadOwnershipProof: async (propertyId: number, proofType: string, file: File): Promise<Property> => {
    const token = getToken();
    const headers: HeadersInit = {};
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const form = new FormData();
    form.append("proof_type", proofType);
    form.append("proof_file", file);
    const res = await fetch(`${API_URL}/owners/properties/${propertyId}/ownership-proof`, {
      method: "POST",
      headers,
      body: form,
    });
    if (!res.ok) {
      const text = await res.text();
      let detail = text;
      try {
        const j = JSON.parse(text);
        detail = Array.isArray(j.detail) ? j.detail.map((d: any) => d.msg || d).join(", ") : (j.detail || text);
      } catch {
        // use text
      }
      throw new Error(detail);
    }
    return res.json() as Promise<Property>;
  },
  /** Bulk upload properties from CSV. Returns created/updated counts and first failure row if any. */
  bulkUpload: async (file: File): Promise<BulkUploadResult> => {
    const token = getToken();
    const headers: HeadersInit = {};
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${API_URL}/owners/properties/bulk-upload`, {
      method: "POST",
      headers,
      body: form,
    });
    if (res.status === 401) {
      setToken(null);
      if (typeof window !== "undefined") {
        window.location.hash = "login";
        window.location.reload();
      }
      throw new Error("Session expired. Please log in again.");
    }
    const text = await res.text();
    if (!res.ok) {
      let detail = text;
      try {
        const j = JSON.parse(text);
        detail = Array.isArray(j.detail) ? j.detail.map((d: any) => d.msg || d).join(", ") : (j.detail || text);
      } catch {
        // use text
      }
      throw new Error(detail);
    }
    return text ? JSON.parse(text) : { created: 0, updated: 0, failed_from_row: null, failure_reason: null };
  },
  /** Release USAT token to the selected guest stay(s). Only those guests will see the token. */
  releaseUsatToken: (propertyId: number, stayIds: number[]) =>
    request<Property>(`/owners/properties/${propertyId}/release-usat-token`, {
      method: "POST",
      body: JSON.stringify({ stay_ids: stayIds }),
      headers: { "Content-Type": "application/json" },
    }),
};

// --- Invitations ---
export interface InvitationDetails {
  valid: boolean;
  property_name?: string | null;
  property_address?: string | null;
  stay_start_date?: string;
  stay_end_date?: string;
  region_code?: string;
  host_name?: string;
  guest_name?: string | null;
}

export const invitationsApi = {
  getDetails: (code: string) =>
    request<InvitationDetails>(`/owners/invitation-details?code=${encodeURIComponent(code)}`),
  async create(data: {
    owner_id: string;
    property_id?: number;
    guest_name: string;
    checkin_date: string;
    checkout_date: string;
    dead_mans_switch_enabled?: boolean;
    dead_mans_switch_alert_email?: boolean;
    dead_mans_switch_alert_sms?: boolean;
    dead_mans_switch_alert_dashboard?: boolean;
    dead_mans_switch_alert_phone?: boolean;
  }): Promise<{ status: string; data?: { invitation_code: string }; message?: string }> {
    try {
      const res = await request<{ invitation_code?: string }>("/owners/invitations", {
        method: "POST",
        body: JSON.stringify(data),
      });
      const code = (res as any)?.invitation_code || "INV-" + Math.random().toString(36).slice(2, 8).toUpperCase();
      return { status: "success", data: { invitation_code: code } };
    } catch (e: any) {
      return { status: "error", message: e?.message || "Invitation failed" };
    }
  },
};

// --- Agreements (invite signing) ---
export interface AgreementDocResponse {
  document_id: string;
  region_code: string;
  title: string;
  content: string;
  document_hash: string;
  property_address?: string | null;
  stay_start_date?: string | null;
  stay_end_date?: string | null;
  host_name?: string | null;
  already_signed?: boolean;
  signed_at?: string | null;
  signed_by?: string | null;
  signature_id?: number | null;
  has_dropbox_signed_pdf?: boolean;
}

export const agreementsApi = {
  getInvitationAgreement: (invitationCode: string, guestEmail?: string | null) => {
    const code = invitationCode.trim().toUpperCase();
    const params = guestEmail ? `?guest_email=${encodeURIComponent(guestEmail.trim())}` : "";
    return request<AgreementDocResponse>(`/agreements/invitation/${encodeURIComponent(code)}${params}`);
  },
  signInvitationAgreement: (data: {
    invitation_code: string;
    guest_email: string;
    guest_full_name: string;
    typed_signature: string;
    acks: { read: boolean; temporary: boolean; vacate: boolean; electronic: boolean };
    document_hash: string;
  }) =>
    request<{ signature_id: number }>("/agreements/sign", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  signInvitationAgreementWithDropbox: (data: {
    invitation_code: string;
    guest_email: string;
    guest_full_name: string;
    typed_signature: string;
    acks: { read: boolean; temporary: boolean; vacate: boolean; electronic: boolean };
    document_hash: string;
  }) =>
    request<{ signature_id: number }>("/agreements/sign-with-dropbox", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  /** Authority letter (provider sign flow, public link by token). */
  getAuthorityLetterByToken: (token: string) =>
    request<AuthorityLetterDocResponse>(`/agreements/authority-letter/${encodeURIComponent(token)}`),
  signAuthorityLetterWithDropbox: (token: string, data: {
    signer_email: string;
    signer_name: string;
    acks: { read: boolean; temporary: boolean; vacate: boolean; electronic: boolean };
  }) =>
    request<{ signature_id: number }>(`/agreements/authority-letter/${encodeURIComponent(token)}/sign-with-dropbox`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
};

export interface AuthorityLetterDocResponse {
  letter_id: number;
  provider_name: string;
  provider_type: string;
  content: string;
  property_address?: string | null;
  property_name?: string | null;
  already_signed?: boolean;
  signed_at?: string | null;
  has_dropbox_signed_pdf?: boolean;
}

// --- Owner Master POA (signup) ---
export interface OwnerPOADocResponse {
  document_id: string;
  title: string;
  content: string;
  document_hash: string;
  already_signed?: boolean;
  signed_at?: string | null;
  signed_by?: string | null;
  signature_id?: number | null;
  has_dropbox_signed_pdf?: boolean;
}

export interface OwnerPOASignatureResponse {
  signature_id: number;
  signed_at: string;
  signed_by: string;
  document_title: string;
  document_id: string;
  has_dropbox_signed_pdf?: boolean;
}

export const ownerPoaApi = {
  getDocument: (ownerEmail?: string | null) => {
    const params = ownerEmail?.trim() ? `?owner_email=${encodeURIComponent(ownerEmail.trim())}` : "";
    return request<OwnerPOADocResponse>(`/agreements/owner-poa${params}`);
  },
  signWithDropbox: (data: {
    owner_email: string;
    owner_full_name: string;
    typed_signature: string;
    acks: { read: boolean; temporary: boolean; vacate: boolean; electronic: boolean };
    document_hash: string;
  }) =>
    request<{ signature_id: number }>("/agreements/owner-poa/sign-with-dropbox", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  getMySignature: () =>
    request<OwnerPOASignatureResponse | null>("/agreements/owner-poa/my-signature"),
};

// --- Guest registration (from invite link) ---
export const authApiGuest = {
  async register(data: {
    invitation_id: string;
    invitation_code: string;
    full_name: string;
    email: string;
    phone: string;
    password: string;
    confirm_password: string;
    permanent_address: string;
    permanent_city: string;
    permanent_state: string;
    permanent_zip: string;
    terms_agreed: boolean;
    privacy_agreed: boolean;
    guest_status_acknowledged: boolean;
    no_tenancy_acknowledged: boolean;
    vacate_acknowledged: boolean;
    agreement_signature_id?: number | null;
  }): Promise<{ status: string; data?: UserSession; message?: string; validation?: Record<string, { error?: string }> }> {
    try {
      const body = await request<TokenResponse & { user_id?: number; message?: string }>("/auth/register/guest", {
        method: "POST",
        body: JSON.stringify(data),
      });
      if (body.user_id != null && !body.access_token) {
        return {
          status: "success",
          data: { user_id: String(body.user_id), verificationRequired: true as const },
          message: body.message || "Check your email for the verification code.",
        };
      }
      setToken(body.access_token);
      return {
        status: "success",
        data: toUserSession(body as TokenResponse),
      };
    } catch (e: any) {
      const msg = e?.message || "Registration failed";
      const validation: Record<string, { error: string }> = {};
      if (msg.includes("Passwords")) validation.password_match = { error: "Passwords do not match" };
      if (msg.includes("agree")) {
        validation.terms = { error: "You must agree to the Terms of Service and Privacy Policy" };
        validation.privacy = { error: "You must agree to the Terms of Service and Privacy Policy" };
      }
      if (msg.includes("acknowledge")) validation.acknowledgments = { error: "You must acknowledge all guest and vacate terms" };
      if (msg.includes("already registered")) validation.email = { error: "Email already registered" };
      if (msg.includes("Invalid or expired") || msg.includes("Invitation code")) validation.invitation = { error: "Invalid or expired invitation code." };
      return { status: "error", message: msg, validation };
    }
  },
};
