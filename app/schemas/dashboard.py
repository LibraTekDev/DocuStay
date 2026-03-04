"""Module F: Legal restrictions & law display (Owner / Guest views)."""
from datetime import date, datetime
from pydantic import BaseModel
from app.models.region_rule import StayClassification, RiskLevel


class OwnerInvitationView(BaseModel):
    """Owner view: invitation for dashboard guests list (pending and accepted)."""
    id: int
    invitation_code: str  # Invite ID (used as Stay ID for display)
    property_id: int
    property_name: str
    guest_name: str | None = None
    guest_email: str | None
    stay_start_date: date
    stay_end_date: date
    region_code: str
    status: str  # pending, ongoing (e.g. CSV occupied), accepted, cancelled, expired
    token_state: str = "STAGED"  # STAGED | BURNED | EXPIRED | REVOKED
    created_at: datetime | None
    is_expired: bool = False  # True when pending and created_at older than 12 hours


class GuestPendingInviteView(BaseModel):
    """Guest view: one pending invitation to sign on dashboard."""
    invitation_code: str
    property_name: str
    stay_start_date: date
    stay_end_date: date
    host_name: str | None
    region_code: str


class OwnerStayView(BaseModel):
    """Owner view: guest name, dates, region, classification, max stay, risk, applicable laws."""
    stay_id: int
    property_id: int
    invite_id: str | None = None  # Invitation code (Invite ID) for this stay
    token_state: str | None = None  # STAGED | BURNED | EXPIRED | REVOKED (from linked invitation)
    guest_name: str
    property_name: str
    stay_start_date: date
    stay_end_date: date
    region_code: str
    legal_classification: StayClassification
    max_stay_allowed_days: int
    risk_indicator: RiskLevel
    applicable_laws: list[str]
    revoked_at: datetime | None = None
    checked_in_at: datetime | None = None  # when set, stay counts as "active" for occupancy and DMS
    checked_out_at: datetime | None = None
    cancelled_at: datetime | None = None
    usat_token_released_at: datetime | None = None  # when set, this guest can see the USAT token
    dead_mans_switch_enabled: bool = False  # DMS on for this stay (alerts + confirmation flow)
    # Status confirmation: owner must select Unit Vacated | Lease Renewed | Holdover before deadline (stay_end + 48h)
    needs_occupancy_confirmation: bool = False  # True when in confirmation window, no response yet
    show_occupancy_confirmation_ui: bool = False  # True when needs_conf OR property UNCONFIRMED and this stay triggered it
    confirmation_deadline_at: datetime | None = None  # stay_end_date + 48h
    occupancy_confirmation_response: str | None = None  # vacated | renewed | holdover


class GuestStayView(BaseModel):
    """Guest view: property, approved dates, region classification, legal notice and laws. usat_token when released; vacate_by when revoked."""
    stay_id: int
    invite_id: str | None = None  # Invite ID (invitation code) for this stay
    token_state: str | None = None  # STAGED | BURNED | EXPIRED | REVOKED
    property_live_slug: str | None = None  # for building live link URL (#live/<slug>)
    property_name: str
    approved_stay_start_date: date
    approved_stay_end_date: date
    region_code: str
    region_classification: str
    legal_notice: str = "This stay does not grant tenancy or homestead rights."
    statute_reference: str | None = None
    plain_english_explanation: str | None = None
    applicable_laws: list[str] = []
    usat_token: str | None = None
    revoked_at: datetime | None = None
    vacate_by: str | None = None  # ISO datetime: revoked_at + 12 hours
    checked_in_at: datetime | None = None  # when set, stay is "active" (occupancy/DMS); guest can Check in on or after start date
    checked_out_at: datetime | None = None  # when set, stay is view-only (no Checkout button)
    cancelled_at: datetime | None = None  # when set, stay is view-only (no Cancel stay button)


class OwnerAuditLogEntry(BaseModel):
    """Single append-only audit log entry for owner logs view."""
    id: int
    property_id: int | None
    stay_id: int | None
    invitation_id: int | None
    category: str
    title: str
    message: str
    actor_user_id: int | None
    actor_email: str | None
    ip_address: str | None
    created_at: datetime
    property_name: str | None = None  # resolved for display

    class Config:
        from_attributes = True


class BillingInvoiceView(BaseModel):
    """Single Stripe invoice for billing tab."""
    id: str
    number: str | None
    description: str | None
    amount_due_cents: int
    amount_paid_cents: int
    currency: str
    status: str  # draft, open, paid, uncollectible, void
    created: datetime
    hosted_invoice_url: str | None = None


class BillingPaymentView(BaseModel):
    """Single payment (paid invoice) for billing tab."""
    invoice_id: str
    amount_cents: int
    currency: str
    paid_at: datetime
    description: str | None = None


class BillingResponse(BaseModel):
    """Invoices and payments for owner billing section."""
    invoices: list[BillingInvoiceView] = []
    payments: list[BillingPaymentView] = []
    can_invite: bool = True  # False until onboarding invoice is paid (when onboarding was charged)
    current_unit_count: int | None = None  # Active properties (for subscription); shown so user sees subscription reflects current count
    current_shield_count: int | None = None  # Properties with Shield on


class BillingPortalSessionResponse(BaseModel):
    """URL for Stripe Customer Billing Portal; redirect here so after payment (e.g. Klarna) user returns to our app."""
    url: str


class PortfolioLinkResponse(BaseModel):
    """Owner portfolio public page: slug and hash path for building full URL."""
    portfolio_slug: str
    portfolio_url: str  # e.g. "portfolio/abc123" (hash part without #); frontend builds full URL