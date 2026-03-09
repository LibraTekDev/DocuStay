"""Schemas for public live property page and portfolio (no auth)."""
from datetime import date, datetime

from pydantic import BaseModel


# --- Portfolio (owner public page) ---


class PortfolioPropertyItem(BaseModel):
    """Single property for portfolio listing (public info only)."""
    id: int
    name: str | None
    city: str
    state: str
    region_code: str
    property_type_label: str | None = None
    bedrooms: str | None = None
    is_multi_unit: bool = False
    unit_count: int | None = None  # when is_multi_unit, number of units


class PortfolioOwnerInfo(BaseModel):
    """Owner basic info for portfolio page."""
    full_name: str | None = None
    email: str = ""
    phone: str | None = None
    state: str | None = None


class PortfolioPagePayload(BaseModel):
    """Payload for GET /public/portfolio/{slug}."""
    owner: PortfolioOwnerInfo
    properties: list[PortfolioPropertyItem] = []


class LivePropertyInfo(BaseModel):
    """Property summary for live page."""
    name: str | None
    street: str
    city: str
    state: str
    zip_code: str | None
    region_code: str
    occupancy_status: str  # vacant | occupied | unknown | unconfirmed
    shield_mode_enabled: bool  # Independent of occupancy. When True, display as PASSIVE GUARD (occupied) or ACTIVE MONITORING (vacant).
    token_state: str = "staged"  # staged | released – for Quick Decision layer
    tax_id: str | None = None
    apn: str | None = None


class LiveOwnerInfo(BaseModel):
    """Owner contact for live page."""
    full_name: str | None
    email: str
    phone: str | None


class LiveCurrentGuestInfo(BaseModel):
    """Current guest and stay for live page."""
    guest_name: str
    stay_start_date: date
    stay_end_date: date
    checked_out_at: datetime | None  # when set, guest has checked out
    dead_mans_switch_enabled: bool


class LiveStaySummary(BaseModel):
    """Past or upcoming stay summary."""
    guest_name: str
    stay_start_date: date
    stay_end_date: date
    checked_out_at: datetime | None = None


class LiveInvitationSummary(BaseModel):
    """Invitation summary for live page – invite states indicate stay status."""
    invitation_code: str
    guest_label: str | None  # guest_name or guest_email (no PII beyond what owner entered)
    stay_start_date: date
    stay_end_date: date
    status: str  # pending, ongoing, accepted, cancelled
    token_state: str  # STAGED, BURNED, EXPIRED, REVOKED


class LiveLogEntry(BaseModel):
    """Single audit log entry for property (public view)."""
    category: str
    title: str
    message: str
    created_at: datetime


class JurisdictionStatuteView(BaseModel):
    """Single statute citation for authority wrap."""
    citation: str
    plain_english: str | None = None


class JurisdictionWrap(BaseModel):
    """Jurisdictional POA wrap: applicable law for this property (by zip/region)."""
    state_name: str
    applicable_statutes: list[JurisdictionStatuteView] = []
    removal_guest_text: str | None = None
    removal_tenant_text: str | None = None
    agreement_type: str | None = None


class LivePropertyPagePayload(BaseModel):
    """Full payload for GET /api/public/live/{slug} – evidence view."""
    has_current_guest: bool
    property: LivePropertyInfo
    owner: LiveOwnerInfo
    current_guest: LiveCurrentGuestInfo | None = None
    last_stay: LiveStaySummary | None = None
    upcoming_stays: list[LiveStaySummary] = []
    invitations: list[LiveInvitationSummary] = []  # invite states → stay status
    logs: list[LiveLogEntry] = []
    # Quick Decision / evidence layer
    authorization_state: str  # ACTIVE | NONE | EXPIRED | REVOKED
    record_id: str  # live_slug for re-verification
    generated_at: datetime
    # Authority layer (Master POA)
    poa_signed_at: datetime | None = None
    poa_signature_id: int | None = None  # for View POA link
    # Jurisdictional wrap: applicable law for this property (by zip)
    jurisdiction_wrap: JurisdictionWrap | None = None


# --- Verify portal (token = Invitation ID, no auth) ---


class VerifyRequest(BaseModel):
    """Request for POST /public/verify. Token ID = invitation code (Invite ID)."""
    token_id: str  # Invitation code (e.g. INV-XXXX)
    property_address: str | None = None  # Optional; when provided, must match property for this token
    name: str | None = None  # Optional; logged only
    phone: str | None = None  # Optional; logged only


class VerifyResponse(BaseModel):
    """Response for POST /public/verify. Read-only, live state."""
    valid: bool
    reason: str | None = None  # Short reason when invalid
    property_name: str | None = None
    property_address: str | None = None
    occupancy_status: str | None = None
    token_state: str | None = None
    stay_end_date: date | None = None
    guest_name: str | None = None
    poa_signed_at: datetime | None = None
    live_slug: str | None = None
    generated_at: datetime | None = None
    audit_entries: list[LiveLogEntry] = []
