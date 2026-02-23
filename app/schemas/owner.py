"""Module B1: Owner onboarding schemas."""
from datetime import datetime
from pydantic import BaseModel, field_validator
from app.models.owner import PropertyType


class PropertyCreate(BaseModel):
    """Accepts reference app field names: property_name, street_address, etc."""
    property_name: str | None = None
    street_address: str | None = None
    street: str | None = None
    city: str
    state: str
    zip_code: str | None = None
    country: str = "USA"
    region_code: str | None = None
    property_type: str | None = None  # house, apartment, condo, townhouse
    bedrooms: str | None = None
    is_primary_residence: bool = False
    owner_occupied: bool | None = None
    property_type_enum: PropertyType | None = None


class PropertyUpdate(BaseModel):
    """All optional; only provided fields are updated."""
    property_name: str | None = None
    street_address: str | None = None
    street: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    region_code: str | None = None
    property_type: str | None = None
    bedrooms: str | None = None
    is_primary_residence: bool | None = None
    owner_occupied: bool | None = None
    property_type_enum: PropertyType | None = None
    shield_mode_enabled: bool | None = None


class ReleaseUsatTokenRequest(BaseModel):
    """Which stay(s) to release the USAT token to (active guests at this property)."""
    stay_ids: list[int] = []  # at least one required; validated in endpoint


class BulkUploadResult(BaseModel):
    """Result of CSV bulk upload: counts and first failure info."""
    created: int = 0
    updated: int = 0
    failed_from_row: int | None = None  # 1-based; None if all succeeded
    failure_reason: str | None = None


class PropertyResponse(BaseModel):
    id: int
    name: str | None
    street: str
    city: str
    state: str
    zip_code: str | None
    region_code: str
    owner_occupied: bool
    property_type: PropertyType | None
    property_type_label: str | None
    bedrooms: str | None
    usat_token: str | None = None
    usat_token_state: str = "staged"
    usat_token_released_at: datetime | None = None
    deleted_at: datetime | None = None
    shield_mode_enabled: bool = False
    occupancy_status: str = "unknown"  # vacant | occupied | unknown | unconfirmed
    ownership_proof_filename: str | None = None
    ownership_proof_type: str | None = None
    ownership_proof_uploaded_at: datetime | None = None

    @field_validator("shield_mode_enabled", mode="before")
    @classmethod
    def coerce_shield_mode(cls, v: bool | int | None) -> bool:
        if v is None:
            return False
        return bool(v)

    class Config:
        from_attributes = True


class OwnerProfileCreate(BaseModel):
    pass
