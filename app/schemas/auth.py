"""Module A: Auth schemas."""
import re
from pydantic import BaseModel, EmailStr, model_validator, field_validator
from app.models.user import UserRole, OwnerType

PHONE_MIN_DIGITS = 10
PHONE_MAX_DIGITS = 15


def _normalize_phone(value: str | None) -> str:
    if value is None:
        return ""
    s = value.strip()
    digits = re.sub(r"\D", "", s)
    return digits


def _validate_phone_digits(phone: str) -> None:
    digits = _normalize_phone(phone)
    if not digits:
        raise ValueError("Phone number is required.")
    if len(digits) < PHONE_MIN_DIGITS:
        raise ValueError(f"Phone number must have at least {PHONE_MIN_DIGITS} digits (e.g. 5551234567 or +1 555 123 4567).")
    if len(digits) > PHONE_MAX_DIGITS:
        raise ValueError(f"Phone number cannot exceed {PHONE_MAX_DIGITS} digits.")


class UserCreate(BaseModel):
    full_name: str
    email: EmailStr
    phone: str = ""
    password: str
    confirm_password: str = ""
    country: str = "USA"
    state: str
    city: str
    terms_agreed: bool = False
    privacy_agreed: bool = False
    role: UserRole = UserRole.owner
    poa_signature_id: int | None = None  # optional; owner signs POA after identity verification
    owner_type: OwnerType | None = None  # Owner of Record vs Authorized Agent (property manager)

    @field_validator("phone")
    @classmethod
    def phone_valid(cls, v: str) -> str:
        _validate_phone_digits(v or "")
        return (v or "").strip()

    @model_validator(mode="after")
    def passwords_match_and_agreed(self):
        if self.confirm_password != self.password:
            raise ValueError("Passwords do not match")
        if not self.terms_agreed or not self.privacy_agreed:
            raise ValueError("You must agree to Terms and Privacy Policy")
        return self


class UserLogin(BaseModel):
    email: EmailStr
    password: str
    role: UserRole | None = None  # Required to distinguish owner vs guest when same email has both


class UserResponse(BaseModel):
    id: int
    email: str
    role: UserRole
    full_name: str | None = None
    phone: str | None = None
    state: str | None = None
    city: str | None = None
    identity_verified: bool = False
    poa_linked: bool = False  # owner has linked Master POA signature

    class Config:
        from_attributes = True


class TokenPayload(BaseModel):
    sub: int
    email: str
    role: UserRole


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class GuestRegister(BaseModel):
    """Guest registration; invitation_code optional. With code but no agreement_signature_id, account is created and invite is added as pending."""
    invitation_id: str = ""
    invitation_code: str = ""
    full_name: str
    email: EmailStr
    phone: str = ""
    password: str
    confirm_password: str = ""
    permanent_address: str
    permanent_city: str
    permanent_state: str
    permanent_zip: str
    terms_agreed: bool = False
    privacy_agreed: bool = False
    guest_status_acknowledged: bool = False
    no_tenancy_acknowledged: bool = False
    vacate_acknowledged: bool = False
    agreement_signature_id: int | None = None  # optional; when set with valid invite, creates stay; otherwise invite is pending on dashboard

    @model_validator(mode="after")
    def passwords_match_and_agreed(self):
        if self.confirm_password != self.password:
            raise ValueError("Passwords do not match")
        if not self.terms_agreed or not self.privacy_agreed:
            raise ValueError("You must agree to Terms and Privacy Policy")
        if not self.guest_status_acknowledged or not self.no_tenancy_acknowledged or not self.vacate_acknowledged:
            raise ValueError("You must acknowledge all guest and vacate terms")
        return self


class AcceptInvite(BaseModel):
    """Accept an invitation as an existing guest (creates Stay, marks invitation accepted)."""
    invitation_code: str
    agreement_signature_id: int


class VerifyEmailRequest(BaseModel):
    """Verify email with code sent after registration."""
    user_id: int
    code: str


class ResendVerificationRequest(BaseModel):
    """Request a new verification code for pending signup."""
    user_id: int


class RegisterPendingResponse(BaseModel):
    """Response from register when email verification is required (no token yet)."""
    user_id: int
    message: str = "Check your email for the verification code."


class LinkPOARequest(BaseModel):
    """Link an existing Master POA signature to the current owner (after identity verification)."""
    poa_signature_id: int
    authorized_agent_certified: bool = False  # required True when owner_type is authorized_agent


class PendingOwnerIdentitySessionRequest(BaseModel):
    """Optional: frontend sends return_url so Stripe redirects to same origin (preserves localStorage token)."""
    return_url: str | None = None


class PendingOwnerIdentitySessionResponse(BaseModel):
    client_secret: str
    url: str | None = None


class PendingOwnerConfirmIdentityRequest(BaseModel):
    verification_session_id: str


class PendingOwnerMeResponse(BaseModel):
    email: str
    full_name: str | None


class PendingOwnerLatestIdentitySessionResponse(BaseModel):
    """Session id we stored when creating the identity session; use when Stripe redirect omits session_id in URL."""
    verification_session_id: str


class CompleteOwnerSignupRequest(BaseModel):
    poa_signature_id: int
