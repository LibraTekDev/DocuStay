"""Agreement document + signature schemas."""
from datetime import datetime
from pydantic import BaseModel, EmailStr, Field, model_validator


class AgreementDocResponse(BaseModel):
    document_id: str
    region_code: str
    title: str
    content: str
    document_hash: str

    property_address: str | None = None
    stay_start_date: str | None = None
    stay_end_date: str | None = None
    host_name: str | None = None

    already_signed: bool = False
    signed_at: datetime | None = None
    signed_by: str | None = None
    signature_id: int | None = None
    has_dropbox_signed_pdf: bool = False


class AgreementAcks(BaseModel):
    read: bool = False
    temporary: bool = False
    vacate: bool = False
    electronic: bool = False


class AgreementSignRequest(BaseModel):
    invitation_code: str = Field(..., min_length=3, max_length=64)
    guest_email: EmailStr
    guest_full_name: str = Field(..., min_length=1, max_length=255)
    typed_signature: str = Field(..., min_length=1, max_length=255)
    acks: AgreementAcks
    document_hash: str = Field(..., min_length=16, max_length=128)
    ip_address: str | None = Field(None, max_length=64)

    @model_validator(mode="after")
    def validate_acks(self):
        if not (self.acks.read and self.acks.temporary and self.acks.vacate and self.acks.electronic):
            raise ValueError("All acknowledgments must be accepted to sign")
        return self


class SignatureStatusResponse(BaseModel):
    """Whether the agreement has been fully signed in Dropbox (signed PDF available)."""
    completed: bool


class AgreementSignResponse(BaseModel):
    signature_id: int
    sign_url: str | None = None


# --- Owner Master POA ---


class OwnerPOADocResponse(BaseModel):
    """Master POA document for owner signup."""
    document_id: str
    title: str
    content: str
    document_hash: str
    already_signed: bool = False
    signed_at: datetime | None = None
    signed_by: str | None = None
    signature_id: int | None = None
    has_dropbox_signed_pdf: bool = False


class OwnerPOASignRequest(BaseModel):
    owner_email: EmailStr
    owner_full_name: str = Field(..., min_length=1, max_length=255)
    typed_signature: str = Field(..., min_length=1, max_length=255)
    acks: AgreementAcks
    document_hash: str = Field(..., min_length=16, max_length=128)

    @model_validator(mode="after")
    def validate_acks(self):
        if not (self.acks.read and self.acks.temporary and self.acks.vacate and self.acks.electronic):
            raise ValueError("All acknowledgments must be accepted to sign")
        return self


class OwnerPOASignatureResponse(BaseModel):
    """Signed POA info for Settings / view."""
    signature_id: int
    signed_at: datetime
    signed_by: str
    document_title: str
    document_id: str
    has_dropbox_signed_pdf: bool = False

    class Config:
        from_attributes = True


# --- Authority letter (utility provider sign flow) ---


class AuthorityLetterDocResponse(BaseModel):
    """Authority letter document for provider to view and sign (public link by token)."""
    letter_id: int
    provider_name: str
    provider_type: str
    content: str
    property_address: str | None = None
    property_name: str | None = None
    already_signed: bool = False
    signed_at: datetime | None = None
    has_dropbox_signed_pdf: bool = False


class AuthorityLetterSignRequest(BaseModel):
    """Provider signer info for Dropbox Sign."""
    signer_email: EmailStr
    signer_name: str = Field(..., min_length=1, max_length=255)
    acks: AgreementAcks

    @model_validator(mode="after")
    def validate_acks(self):
        if not (self.acks.read and self.acks.temporary and self.acks.vacate and self.acks.electronic):
            raise ValueError("All acknowledgments must be accepted to sign")
        return self

