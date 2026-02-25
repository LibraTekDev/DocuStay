"""Module B1: Owner onboarding."""
import csv
import io
import secrets
from datetime import datetime, timezone
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.models.owner import OwnerProfile, Property, PropertyType, USAT_TOKEN_STAGED, USAT_TOKEN_RELEASED
from app.models.invitation import Invitation
from app.models.guest import PurposeOfStay, RelationshipToOwner
from app.schemas.owner import (
    AuthorityLetterResponse,
    BulkUploadResult,
    EmailProvidersResponse,
    OwnerConfigResponse,
    PendingProviderResponse,
    PropertyCreate,
    PropertyResponse,
    PropertyUpdate,
    PropertyUtilityProvidersResponse,
    ReleaseUsatTokenRequest,
    SetPropertyUtilitiesRequest,
    StandardizedAddressResponse,
    UtilityOptionItem,
    UtilityProviderResponse,
    VerifyAddressAndUtilitiesResponse,
    VerifyAddressRequest,
)
from app.dependencies import get_current_user, require_owner, require_owner_onboarding_complete
from app.models.stay import Stay
from app.models.guest import GuestProfile
from app.services.audit_log import create_log, CATEGORY_STATUS_CHANGE, CATEGORY_SHIELD_MODE
from app.services.smarty import verify_address
from app.services.utility_lookup import lookup_utility_providers, generate_authority_letters, _provider_to_raw
from app.services.utility_lookup import UtilityProvider
from app.models.property_utility import PropertyUtilityProvider, PropertyAuthorityLetter
from app.background_jobs import submit_utility_job
from app.services.provider_contact_search import run_provider_contact_lookup_job
from app.services.census_geocoder import geocode_coordinates
from app.utility_providers.pending_provider_verification_job import run_pending_provider_verification_job
from app.utility_providers.sqlite_cache import add_pending_provider, get_pending_providers_for_property
from app.config import get_settings
from app.services.authority_letter_email import send_authority_letter_to_provider
from app.services.dropbox_sign import get_signed_pdf

router = APIRouter(prefix="/owners", tags=["owners"])

_PURPOSE_MAP = {"visit": PurposeOfStay.travel, "vacation": PurposeOfStay.travel, "caregiving": PurposeOfStay.personal, "house_sitting": PurposeOfStay.personal}
_REL_MAP = {"friend": RelationshipToOwner.friend, "family": RelationshipToOwner.family, "acquaintance": RelationshipToOwner.other, "tenant_applicant": RelationshipToOwner.other}


class InvitationCreate(BaseModel):
    owner_id: str | None = None
    property_id: int | None = None
    guest_name: str = ""
    guest_email: str = ""
    guest_phone: str = ""
    relationship: str = "friend"
    purpose: str = "visit"
    checkin_date: str = ""
    checkout_date: str = ""
    personal_message: str = ""
    # Dead Man's Switch: auto-protect when lease ends without owner response (default: OFF, owner can enable)
    dead_mans_switch_enabled: bool = False
    dead_mans_switch_alert_email: bool = True
    dead_mans_switch_alert_sms: bool = False
    dead_mans_switch_alert_dashboard: bool = True
    dead_mans_switch_alert_phone: bool = False
    # When only guest_name + property_id are sent, checkin/checkout default to today + 14 days


def _ensure_property_usat_token(prop: Property, db: Session) -> None:
    """Backfill USAT token for properties created before staged tokens were added."""
    if prop.usat_token:
        return
    token = "USAT-" + secrets.token_hex(12).upper()
    for _ in range(10):
        if db.query(Property).filter(Property.usat_token == token).first() is None:
            break
        token = "USAT-" + secrets.token_hex(12).upper()
    else:
        token = f"USAT-{secrets.token_hex(8).upper()}-{prop.id}"
    prop.usat_token = token
    prop.usat_token_state = USAT_TOKEN_STAGED
    db.add(prop)


@router.get("/config", response_model=OwnerConfigResponse)
def get_owner_config(
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Return owner-facing config (e.g. test provider email for development)."""
    settings = get_settings()
    email = (settings.test_provider_email or "").strip() or None
    return OwnerConfigResponse(test_provider_email=email)


@router.get("/properties", response_model=list[PropertyResponse])
def list_my_properties(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
    inactive: bool = False,
):
    """List properties. Default: active only (for dashboard main list and invite dropdown). inactive=1: inactive only (soft-deleted)."""
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile:
        return []
    if inactive:
        props = db.query(Property).filter(
            Property.owner_profile_id == profile.id,
            Property.deleted_at.isnot(None),
        ).all()
    else:
        props = db.query(Property).filter(
            Property.owner_profile_id == profile.id,
            Property.deleted_at.is_(None),
        ).all()
    for p in props:
        if not p.usat_token:
            _ensure_property_usat_token(p, db)
    db.commit()
    return [PropertyResponse.model_validate(p) for p in props]


@router.post("/verify-address-and-utilities", response_model=VerifyAddressAndUtilitiesResponse)
def verify_address_and_utilities(
    data: VerifyAddressRequest,
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Run Smarty address verification and utility lookup; return standardized address and providers by type (for add-property utilities step)."""
    street = (data.street_address or "").strip()
    city = (data.city or "").strip()
    state = (data.state or "").strip()
    zip_code = (data.zip_code or "").strip() or None
    print(f"[PropertyFlow] verify_address_and_utilities: street={street!r}, city={city!r}, state={state!r}, zip={zip_code!r}")
    if not street or not city or not state:
        raise HTTPException(status_code=400, detail="street_address, city, and state are required")
    print(f"[PropertyFlow] Calling Smarty verify_address(...)")
    result = verify_address(street=street, city=city, state=state, zipcode=zip_code)
    standardized_address = None
    lat = None
    lon = None
    zip5 = zip_code
    if result:
        standardized_address = StandardizedAddressResponse(
            delivery_line_1=result.delivery_line_1,
            city_name=result.city_name,
            state_abbreviation=result.state_abbreviation,
            zipcode=result.zipcode,
            latitude=result.latitude,
            longitude=result.longitude,
        )
        lat = result.latitude
        lon = result.longitude
        zip5 = result.zipcode or zip_code
    address = ", ".join(filter(None, [
        result.delivery_line_1 if result else street,
        f"{result.city_name if result else city}, {result.state_abbreviation if result else state} {zip5 or ''}".strip(),
    ])) if result else f"{street}, {city}, {state} {zip_code or ''}".strip()
    print(f"[PropertyFlow] Smarty result: standardized={result is not None}; calling lookup_utility_providers(zip={zip5!r}, ...)")
    providers = lookup_utility_providers(
        zip_code=zip5,
        lat=lat,
        lon=lon,
        address=address,
        city=result.city_name if result else city,
        state_abbreviation=result.state_abbreviation if result else state,
    )
    print(f"[PropertyFlow] lookup_utility_providers returned {len(providers)} provider(s)")
    # Only show providers in the user's area; cap each type so we don't overwhelm the UI
    _MAX_PROVIDERS_PER_TYPE = 50
    by_type: dict[str, list[UtilityOptionItem]] = {}
    for p in providers:
        t = p.provider_type
        if t not in by_type:
            by_type[t] = []
        if len(by_type[t]) < _MAX_PROVIDERS_PER_TYPE:
            by_type[t].append(UtilityOptionItem(name=p.name, phone=p.phone))
    return VerifyAddressAndUtilitiesResponse(
        standardized_address=standardized_address,
        providers_by_type=by_type,
    )


@router.post("/properties", response_model=PropertyResponse)
def add_property(
    request: Request,
    data: PropertyCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    print(f"[PropertyFlow] add_property: street={getattr(data, 'street_address', None) or getattr(data, 'street', None)!r}, ...")
    street = data.street_address or data.street
    if not street:
        raise HTTPException(status_code=400, detail="street or street_address required")
    region = (data.region_code or data.state or "US").upper()[:20]
    owner_occ = data.owner_occupied if data.owner_occupied is not None else data.is_primary_residence
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile:
        profile = OwnerProfile(user_id=current_user.id)
        db.add(profile)
        db.commit()
        db.refresh(profile)
    def _generate_usat_token() -> str:
        return "USAT-" + secrets.token_hex(12).upper()

    prop = Property(
        owner_profile_id=profile.id,
        name=data.property_name,
        street=street,
        city=data.city,
        state=data.state,
        zip_code=data.zip_code,
        region_code=region,
        owner_occupied=owner_occ,
        property_type=data.property_type_enum,
        property_type_label=data.property_type,
        bedrooms=data.bedrooms,
    )
    db.add(prop)
    db.flush()
    for _ in range(10):
        token = _generate_usat_token()
        if db.query(Property).filter(Property.usat_token == token).first() is None:
            prop.usat_token = token
            prop.usat_token_state = USAT_TOKEN_STAGED
            break
    else:
        prop.usat_token = _generate_usat_token() + "-" + str(prop.id)
        prop.usat_token_state = USAT_TOKEN_STAGED

    _apply_smarty_address(prop, street, data.city, data.state, data.zip_code)
    # Utility providers are set by the frontend via POST /properties/{id}/utilities after owner selects from dropdowns

    property_display = (data.property_name or "").strip() or f"{street}, {data.city}, {data.state}".strip(", ")
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "Property registered",
        f"Owner registered property: {property_display} (id={prop.id}). Occupancy status: unknown (initial).",
        property_id=prop.id,
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=request.client.host if request.client else None,
        user_agent=(request.headers.get("user-agent") or "").strip() or None,
        meta={"property_id": prop.id, "street": street, "city": data.city, "state": data.state, "region_code": region, "occupancy_status_new": "unknown"},
    )
    db.commit()
    db.refresh(prop)
    print(f"[PropertyFlow] add_property: created property_id={prop.id}")
    return PropertyResponse.model_validate(prop)


def _apply_smarty_address(prop: Property, street: str, city: str, state: str, zip_code: str | None) -> None:
    """Call Smarty US Street API and populate standardized address fields on the property."""
    print(f"[PropertyFlow] _apply_smarty_address: calling Smarty verify_address for property_id={prop.id}")
    result = verify_address(street=street, city=city, state=state, zipcode=zip_code)
    if result:
        prop.smarty_delivery_line_1 = result.delivery_line_1
        prop.smarty_city_name = result.city_name
        prop.smarty_state_abbreviation = result.state_abbreviation
        prop.smarty_zipcode = result.zipcode
        prop.smarty_plus4_code = result.plus4_code
        prop.smarty_latitude = result.latitude
        prop.smarty_longitude = result.longitude


def _run_utility_bucket_for_property(prop: Property, db: Session) -> None:
    """Run Utility Bucket: Census → Rewiring America → Water CSV → FCC BDC CSV; save providers + authority letters."""
    zip_code = prop.smarty_zipcode or prop.zip_code
    lat = prop.smarty_latitude
    lon = prop.smarty_longitude
    city = prop.smarty_city_name or prop.city
    state_abbrev = prop.smarty_state_abbreviation or prop.state
    address = ", ".join(
        filter(
            None,
            [
                prop.smarty_delivery_line_1 or prop.street,
                (prop.smarty_city_name or prop.city) + ", " + (prop.smarty_state_abbreviation or prop.state or "") + " " + (prop.smarty_zipcode or prop.zip_code or ""),
            ],
        )
    )
    if not address.strip():
        address = (prop.street or "") + ", " + (prop.city or "") + ", " + (prop.state or "")
    providers = lookup_utility_providers(
        zip_code=zip_code,
        lat=lat,
        lon=lon,
        address=address,
        city=city,
        state_abbreviation=state_abbrev,
    )
    if not providers:
        return
    letters = generate_authority_letters(providers, address, prop.name)
    for p, content in letters:
        prv = PropertyUtilityProvider(
            property_id=prop.id,
            provider_name=p.name,
            provider_type=p.provider_type,
            utilityapi_id=p.utilityapi_id,
            contact_phone=p.phone,
            contact_email=getattr(p, "email", None),
            raw_data=_provider_to_raw(p),
        )
        db.add(prv)
        db.flush()
        letter = PropertyAuthorityLetter(
            property_id=prop.id,
            property_utility_provider_id=prv.id,
            provider_name=p.name,
            provider_type=p.provider_type,
            letter_content=content,
        )
        db.add(letter)


def _normalize_addr(s: str | None) -> str:
    """Normalize for address matching: strip, collapse spaces, upper."""
    if not s or not isinstance(s, str):
        return ""
    return " ".join(s.strip().split()).upper()


def _parse_bool_cell(val: str | None) -> bool:
    if val is None or (isinstance(val, str) and not val.strip()):
        return False
    v = (val.strip().lower() if isinstance(val, str) else str(val)).lower()
    return v in ("1", "true", "yes", "y")


@router.post("/properties/bulk-upload", response_model=BulkUploadResult)
def bulk_upload_properties(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Upload properties via CSV. Required columns: street_address (or street), city, state. Optional: property_name, zip_code, region_code, property_type, bedrooms, is_primary_residence. Existing properties matched by (street, city, state) are updated only when values change; empty optional cells keep existing values."""
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="No owner profile")

    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Please upload a CSV file.")

    content = b""
    try:
        content = file.file.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not read file: {e!s}")
    if not content:
        raise HTTPException(status_code=400, detail="File is empty.")

    try:
        text = content.decode("utf-8-sig").strip()
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be UTF-8 encoded.")

    reader = csv.DictReader(io.StringIO(text))
    orig_headers = list(reader.fieldnames or [])
    norm_to_orig = {h.strip().lower().replace(" ", "_"): h for h in orig_headers}
    rows = list(reader)
    if not rows:
        raise HTTPException(status_code=400, detail="CSV has no data rows.")

    created = 0
    updated = 0
    failed_from_row = None
    failure_reason = None
    existing_props: list[Property] = (
        db.query(Property)
        .filter(
            Property.owner_profile_id == profile.id,
            Property.deleted_at.is_(None),
        )
        .all()
    )

    def _get_cell(row: dict, *keys: str) -> str | None:
        for k in keys:
            orig = norm_to_orig.get(k) or norm_to_orig.get(k.replace("_", ""))
            if orig and row.get(orig) is not None:
                v = str(row[orig]).strip()
                if v:
                    return v
        return None

    for idx, row in enumerate(rows, start=1):
        row_num = idx
        street = _get_cell(row, "street_address", "street")
        city = _get_cell(row, "city")
        state = _get_cell(row, "state")

        if not street:
            failed_from_row = row_num
            failure_reason = "Missing required column: street_address or street."
            break
        if not city:
            failed_from_row = row_num
            failure_reason = "Missing required column: city."
            break
        if not state:
            failed_from_row = row_num
            failure_reason = "Missing required column: state."
            break

        state_upper = state.upper()[:50]
        city_norm = _normalize_addr(city)
        street_norm = _normalize_addr(street)
        if not city_norm or not street_norm:
            failed_from_row = row_num
            failure_reason = "street, city, and state cannot be blank after trimming."
            break

        zip_code = _get_cell(row, "zip_code")
        region_raw = _get_cell(row, "region_code")
        region_code = (region_raw or state_upper).upper()[:20]
        property_type_label = _get_cell(row, "property_type")
        bedrooms = _get_cell(row, "bedrooms")
        if bedrooms is not None:
            bedrooms = bedrooms[:10]
        is_primary = _parse_bool_cell(_get_cell(row, "is_primary_residence"))
        property_name = _get_cell(row, "property_name")

        property_type_enum = None
        if property_type_label:
            pl = property_type_label.lower().strip()
            if pl in ("entire_home", "entire home"):
                property_type_enum = PropertyType.entire_home
            elif pl in ("private_room", "private room"):
                property_type_enum = PropertyType.private_room

        state_norm = _normalize_addr(state)
        existing_match = None
        for p in existing_props:
            if _normalize_addr(p.street) == street_norm and _normalize_addr(p.city) == city_norm and _normalize_addr(p.state) == state_norm:
                existing_match = p
                break

        if existing_match is None:
            prop = Property(
                owner_profile_id=profile.id,
                name=property_name,
                street=street.strip(),
                city=city.strip(),
                state=state_upper,
                zip_code=zip_code,
                region_code=region_code,
                owner_occupied=is_primary,
                property_type=property_type_enum,
                property_type_label=property_type_label,
                bedrooms=bedrooms,
            )
            db.add(prop)
            db.flush()
            for _ in range(10):
                token = "USAT-" + secrets.token_hex(12).upper()
                if db.query(Property).filter(Property.usat_token == token).first() is None:
                    prop.usat_token = token
                    prop.usat_token_state = USAT_TOKEN_STAGED
                    break
            else:
                prop.usat_token = "USAT-" + secrets.token_hex(8).upper() + "-" + str(prop.id)
                prop.usat_token_state = USAT_TOKEN_STAGED
            _apply_smarty_address(prop, street.strip(), city.strip(), state_upper, zip_code)
            try:
                _run_utility_bucket_for_property(prop, db)
            except Exception as e:
                print(f"[Owners] Utility bucket failed for property {prop.id} (row {row_num}): {e}")
            created += 1
            property_display = (property_name or "").strip() or f"{street.strip()}, {city.strip()}, {state_upper}".strip(", ")
            create_log(
                db,
                CATEGORY_STATUS_CHANGE,
                "Property registered",
                f"Owner registered property via bulk upload: {property_display} (id={prop.id}, row {row_num}).",
                property_id=prop.id,
                actor_user_id=current_user.id,
                actor_email=current_user.email,
                ip_address=request.client.host if request.client else None,
                user_agent=(request.headers.get("user-agent") or "").strip() or None,
                meta={"property_id": prop.id, "bulk_upload_row": row_num, "street": street.strip(), "city": city.strip(), "state": state_upper},
            )
            db.commit()
            db.refresh(prop)
            existing_props.append(prop)
        else:
            updates = {}
            if property_name is not None and (existing_match.name or "").strip() != property_name:
                updates["name"] = property_name
            if street.strip() != (existing_match.street or "").strip():
                updates["street"] = street.strip()
            if city.strip() != (existing_match.city or "").strip():
                updates["city"] = city.strip()
            if state_upper != (existing_match.state or "").strip():
                updates["state"] = state_upper
            if zip_code is not None and (existing_match.zip_code or "").strip() != (zip_code or "").strip():
                updates["zip_code"] = zip_code or None
            if region_raw is not None and (existing_match.region_code or "").strip() != (region_code or "").strip():
                updates["region_code"] = region_code
            if is_primary != existing_match.owner_occupied:
                updates["owner_occupied"] = is_primary
            if property_type_enum is not None and existing_match.property_type != property_type_enum:
                updates["property_type"] = property_type_enum
            if property_type_label is not None and (existing_match.property_type_label or "").strip() != (property_type_label or "").strip():
                updates["property_type_label"] = property_type_label or None
            if bedrooms is not None and (existing_match.bedrooms or "").strip() != (bedrooms or "").strip():
                updates["bedrooms"] = bedrooms

            for key, val in updates.items():
                if key == "name":
                    existing_match.name = val
                elif key == "street":
                    existing_match.street = val
                elif key == "city":
                    existing_match.city = val
                elif key == "state":
                    existing_match.state = val
                elif key == "zip_code":
                    existing_match.zip_code = val
                elif key == "region_code":
                    existing_match.region_code = val.upper()[:20]
                elif key == "owner_occupied":
                    existing_match.owner_occupied = val
                elif key == "property_type":
                    existing_match.property_type = val
                elif key == "property_type_label":
                    existing_match.property_type_label = val
                elif key == "bedrooms":
                    existing_match.bedrooms = val
            if updates:
                updated += 1
            db.commit()

    return BulkUploadResult(created=created, updated=updated, failed_from_row=failed_from_row, failure_reason=failure_reason)


@router.get("/properties/{property_id}", response_model=PropertyResponse)
def get_property(
    property_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    print(f"[PropertyFlow] get_property: property_id={property_id}")
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="No owner profile")
    prop = db.query(Property).filter(
        Property.id == property_id,
        Property.owner_profile_id == profile.id,
    ).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    return PropertyResponse.model_validate(prop)


@router.get("/properties/{property_id}/utilities", response_model=PropertyUtilityProvidersResponse)
def get_property_utilities(
    property_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Return utility providers and authority letters for the property (Utility Bucket)."""
    print(f"[PropertyFlow] get_property_utilities: property_id={property_id}")
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="No owner profile")
    prop = db.query(Property).filter(
        Property.id == property_id,
        Property.owner_profile_id == profile.id,
    ).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    providers = db.query(PropertyUtilityProvider).filter(PropertyUtilityProvider.property_id == prop.id).all()
    letters = db.query(PropertyAuthorityLetter).filter(PropertyAuthorityLetter.property_id == prop.id).all()
    pending_list = get_pending_providers_for_property(prop.id)
    test_email_override = (get_settings().test_provider_email or "").strip() or None
    # Known wrong email from SerpApi when searching "Test provider" - never show this for Test provider
    _wrong_test_provider_email = "contact@switchhealth.ca"
    def _is_test_provider(p) -> bool:
        return (p.provider_name or "").strip().lower() == "test provider"
    # For "Test provider", fix DB and always use TEST_PROVIDER_EMAIL from config
    if test_email_override:
        test_lower = test_email_override.lower()
        for p in providers:
            if _is_test_provider(p):
                current = (p.contact_email or "").strip().lower()
                if current != test_lower:
                    p.contact_email = test_email_override
        db.commit()
    def _contact_email(p) -> str | None:
        if _is_test_provider(p):
            # Never return wrong SerpApi email; use config or nothing
            if test_email_override:
                return test_email_override
            stored = (p.contact_email or "").strip().lower()
            if stored == _wrong_test_provider_email:
                return None
            return p.contact_email or None
        return p.contact_email
    with_email = sum(1 for p in providers if _contact_email(p))
    print(f"[PropertyFlow] get_property_utilities: returning {len(providers)} providers ({with_email} with contact_email), {len(letters)} letters, {len(pending_list)} pending")
    return PropertyUtilityProvidersResponse(
        providers=[
            UtilityProviderResponse(
                id=p.id,
                provider_name=p.provider_name,
                provider_type=p.provider_type,
                utilityapi_id=p.utilityapi_id,
                contact_phone=p.contact_phone,
                contact_email=_contact_email(p),
            )
            for p in providers
        ],
        authority_letters=[
            AuthorityLetterResponse(
                id=l.id,
                provider_name=l.provider_name,
                provider_type=l.provider_type or "",
                letter_content=l.letter_content,
                email_sent_at=getattr(l, "email_sent_at", None),
                signed_at=getattr(l, "signed_at", None),
                has_signed_pdf=bool(getattr(l, "signed_pdf_bytes", None)),
            )
            for l in letters
        ],
        pending_providers=[
            PendingProviderResponse(id=pp["id"], provider_name=pp["provider_name"], provider_type=pp["provider_type"], verification_status=pp["verification_status"])
            for pp in pending_list
        ],
    )


@router.post("/properties/{property_id}/utilities", response_model=PropertyUtilityProvidersResponse)
def set_property_utilities(
    property_id: int,
    body: SetPropertyUtilitiesRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Save owner-selected utility providers and generate authority letters. Pending (custom) providers are stored for later detail fetch."""
    print(f"[PropertyFlow] set_property_utilities: property_id={property_id}, selected={len(body.selected or [])}, pending={len(body.pending or [])}")
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="No owner profile")
    prop = db.query(Property).filter(
        Property.id == property_id,
        Property.owner_profile_id == profile.id,
    ).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    # Replace existing providers and letters for this property
    db.query(PropertyAuthorityLetter).filter(PropertyAuthorityLetter.property_id == prop.id).delete()
    db.query(PropertyUtilityProvider).filter(PropertyUtilityProvider.property_id == prop.id).delete()
    db.flush()
    print(f"[PropertyFlow] Cleared existing providers and letters for property_id={property_id}")
    address = ", ".join(filter(
        None,
        [
            prop.smarty_delivery_line_1 or prop.street,
            f"{prop.smarty_city_name or prop.city}, {prop.smarty_state_abbreviation or prop.state} {prop.smarty_zipcode or prop.zip_code or ''}".strip(),
        ],
    ))
    if not address.strip():
        address = f"{prop.street or ''}, {prop.city or ''}, {prop.state or ''}".strip(", ")
    # County for pending providers (from Census if we have lat/lon)
    county_name: str | None = None
    lat, lon = prop.smarty_latitude, prop.smarty_longitude
    if lat is not None and lon is not None:
        geo = geocode_coordinates(lon, lat)
        if geo:
            county_name = geo.county_name or None
    state_abbrev_for_pending = (prop.smarty_state_abbreviation or prop.state or "").strip().upper() or None
    # Add pending (user-added custom) providers to SQLite with property_id, state, county for verification job
    pending_count = 0
    for item in body.pending or []:
        pt = (item.provider_type or "").strip().lower()
        pn = (item.provider_name or "").strip()
        if pt and pn:
            add_pending_provider(pt, pn, property_id=prop.id, state=state_abbrev_for_pending, county=county_name)
            pending_count += 1
            print(f"[PropertyFlow] Added pending provider to SQLite: type={pt}, name={pn}, state={state_abbrev_for_pending!r}, county={county_name!r}")
    # Save selected providers and generate authority letters; look up contact for water
    state_abbrev = (prop.smarty_state_abbreviation or prop.state or "").strip().upper()
    city = (prop.smarty_city_name or prop.city or "").strip() or None
    test_email_for_save = (get_settings().test_provider_email or "").strip() or None
    print(f"[PropertyFlow] Property state={state_abbrev}, city={city or '(any)'}; saving selected providers")
    for item in body.selected or []:
        pn = (item.provider_name or "").strip()
        pt = (item.provider_type or "").strip().lower()
        if not pn or not pt:
            continue
        contact_phone: str | None = None
        contact_email: str | None = None
        if pn == "Test provider" and test_email_for_save:
            contact_email = test_email_for_save
            print(f"[PropertyFlow] Test provider selected for {pt}; using test_provider_email for authority letter")
        elif pt == "water" and state_abbrev:
            print(f"[PropertyFlow] Water provider: calling get_water_provider_contact(name={pn!r}, state={state_abbrev}, city={city!r})")
            from app.services.water_lookup import get_water_provider_contact
            contact = get_water_provider_contact(pn, state_abbrev, city=city or None)
            contact_phone = contact.get("contact_phone")
            contact_email = contact.get("contact_email")
            print(f"[PropertyFlow] Water contact result: email={contact_email!r}, phone={contact_phone!r}")
        u = UtilityProvider(name=pn, provider_type=pt, utilityapi_id=None, phone=contact_phone, email=contact_email, raw={})
        prv = PropertyUtilityProvider(
            property_id=prop.id,
            provider_name=u.name,
            provider_type=u.provider_type,
            utilityapi_id=u.utilityapi_id,
            contact_phone=u.phone,
            contact_email=u.email,
            raw_data=_provider_to_raw(u),
        )
        db.add(prv)
        db.flush()
        content = next(
            (c for _p, c in generate_authority_letters([u], address, prop.name or "")),
            "",
        )
        letter = PropertyAuthorityLetter(
            property_id=prop.id,
            property_utility_provider_id=prv.id,
            provider_name=u.name,
            provider_type=u.provider_type,
            letter_content=content,
        )
        db.add(letter)
        print(f"[PropertyFlow] Saved provider: name={pn}, type={pt}, contact_email={contact_email!r}")
    db.commit()
    print(f"[PropertyFlow] Committed {len(body.selected or [])} providers and authority letters")
    # Send authority letter email only when the provider has contact_email. In testing (TEST_PROVIDER_EMAIL set), send only to that address—never to real authorities.
    letters_for_email = db.query(PropertyAuthorityLetter).filter(PropertyAuthorityLetter.property_id == prop.id).all()
    test_email_send = (get_settings().test_provider_email or "").strip().lower() or None
    for letter in letters_for_email:
        to_email = None
        if (letter.provider_name or "").strip() == "Test provider" and test_email_send:
            to_email = test_email_send
        elif letter.property_utility_provider_id:
            prv = db.query(PropertyUtilityProvider).filter(PropertyUtilityProvider.id == letter.property_utility_provider_id).first()
            if prv and (prv.contact_email or "").strip():
                to_email = (prv.contact_email or "").strip().lower()
        if to_email:
            if test_email_send and to_email != test_email_send:
                print(f"[PropertyFlow] Testing env: skipping send to real authority {to_email} for {letter.provider_name}")
                continue
            try:
                if send_authority_letter_to_provider(db, letter, to_email, letter.provider_name, prop.name):
                    print(f"[PropertyFlow] Authority letter email sent to {to_email} for {letter.provider_name}")
            except Exception as e:
                print(f"[PropertyFlow] Failed to send authority letter email for {letter.provider_name}: {e}")
    # Start background lookup for providers missing contact_email (electric/gas/internet)
    serp_key = (get_settings().serpapi_key or "").strip()
    if serp_key:
        need_lookup = db.query(PropertyUtilityProvider).filter(
            PropertyUtilityProvider.property_id == prop.id,
            PropertyUtilityProvider.contact_email.is_(None),
            PropertyUtilityProvider.provider_type.in_(("electric", "gas", "internet")),
        ).all()
        if need_lookup:
            print(f"[PropertyFlow] BACKGROUND JOB ENQUEUED: provider_contact_lookup property_id={prop.id} ({len(need_lookup)} providers to lookup)")
            background_tasks.add_task(submit_utility_job, run_provider_contact_lookup_job, prop.id)
        else:
            print(f"[PropertyFlow] SERPAPI_KEY set but no providers need lookup (all have contact_email or water-only)")
    else:
        print(f"[PropertyFlow] SERPAPI_KEY not set; skipping background provider-contact lookup")
    if pending_count and serp_key:
        print(f"[PropertyFlow] BACKGROUND JOB ENQUEUED: pending_provider_verification ({pending_count} new pending)")
        background_tasks.add_task(submit_utility_job, run_pending_provider_verification_job)
    providers = db.query(PropertyUtilityProvider).filter(PropertyUtilityProvider.property_id == prop.id).all()
    letters = db.query(PropertyAuthorityLetter).filter(PropertyAuthorityLetter.property_id == prop.id).all()
    pending_list = get_pending_providers_for_property(prop.id)
    print(f"[PropertyFlow] set_property_utilities: returning 200 with {len(providers)} providers, {len(letters)} letters, {len(pending_list)} pending")
    return PropertyUtilityProvidersResponse(
        providers=[
            UtilityProviderResponse(
                id=p.id,
                provider_name=p.provider_name,
                provider_type=p.provider_type,
                utilityapi_id=p.utilityapi_id,
                contact_phone=p.contact_phone,
                contact_email=p.contact_email,
            )
            for p in providers
        ],
        authority_letters=[
            AuthorityLetterResponse(
                id=l.id,
                provider_name=l.provider_name,
                provider_type=l.provider_type or "",
                letter_content=l.letter_content,
                email_sent_at=getattr(l, "email_sent_at", None),
                signed_at=getattr(l, "signed_at", None),
                has_signed_pdf=bool(getattr(l, "signed_pdf_bytes", None)),
            )
            for l in letters
        ],
        pending_providers=[
            PendingProviderResponse(id=pp["id"], provider_name=pp["provider_name"], provider_type=pp["provider_type"], verification_status=pp["verification_status"])
            for pp in pending_list
        ],
    )


class ProviderContactsLookupRequest(BaseModel):
    """Optional: limit lookup to these provider row ids. If omitted, all providers for the property with null contact_email (electric/gas/internet) are looked up."""
    provider_ids: list[int] | None = None


class ProviderContactsLookupResponse(BaseModel):
    message: str


@router.post(
    "/properties/{property_id}/provider-contacts/lookup",
    response_model=ProviderContactsLookupResponse,
    status_code=202,
)
def lookup_provider_contacts(
    property_id: int,
    background_tasks: BackgroundTasks,
    body: ProviderContactsLookupRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """
    Start a background job to find contact emails for this property's providers (electric/gas/internet)
    that have no contact_email set. Uses SerpApi when SERPAPI_KEY is configured.
    Returns 202 Accepted; when the user loads the property later, provider emails may be filled.
    """
    print(f"[PropertyFlow] lookup_provider_contacts: property_id={property_id}, body.provider_ids={getattr(body, 'provider_ids', None) if body else None}")
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="No owner profile")
    prop = db.query(Property).filter(
        Property.id == property_id,
        Property.owner_profile_id == profile.id,
    ).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    if not (get_settings().serpapi_key or "").strip():
        print(f"[PropertyFlow] lookup_provider_contacts: SERPAPI_KEY not set -> 202 with message (not configured)")
        return ProviderContactsLookupResponse(message="Provider contact lookup not configured (SERPAPI_KEY).")
    provider_ids = body.provider_ids if body else None
    print(f"[PropertyFlow] BACKGROUND JOB ENQUEUED: provider_contact_lookup property_id={property_id} provider_ids={provider_ids}")
    background_tasks.add_task(submit_utility_job, run_provider_contact_lookup_job, property_id, provider_ids)
    return ProviderContactsLookupResponse(message="Provider contact lookup started.")


@router.post("/properties/{property_id}/email-providers", response_model=EmailProvidersResponse)
def email_authority_letters_to_providers(
    property_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """
    Send authority letter email to each provider that has contact_email (one email per letter with sign link).
    When TEST_PROVIDER_EMAIL is set, only send to that address (i.e. only for providers the user chose as "Test provider"); never send to real authorities in testing.
    """
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="No owner profile")
    prop = db.query(Property).filter(
        Property.id == property_id,
        Property.owner_profile_id == profile.id,
    ).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    letters = db.query(PropertyAuthorityLetter).filter(PropertyAuthorityLetter.property_id == prop.id).all()
    if not letters:
        return EmailProvidersResponse(message="No authority letters for this property.", sent_count=0)
    test_email_send = (get_settings().test_provider_email or "").strip().lower() or None
    sent_count = 0
    for letter in letters:
        to_email = None
        if (letter.provider_name or "").strip() == "Test provider" and test_email_send:
            to_email = test_email_send
        elif letter.property_utility_provider_id:
            prv = db.query(PropertyUtilityProvider).filter(PropertyUtilityProvider.id == letter.property_utility_provider_id).first()
            if prv and (prv.contact_email or "").strip():
                to_email = (prv.contact_email or "").strip().lower()
        if to_email:
            if test_email_send and to_email != test_email_send:
                continue  # Testing: do not send to real authorities
            try:
                if send_authority_letter_to_provider(db, letter, to_email, letter.provider_name, prop.name, resend=True):
                    sent_count += 1
                    print(f"[PropertyFlow] email-providers: authority letter sent to {to_email} for {letter.provider_name}")
            except Exception as e:
                print(f"[PropertyFlow] email-providers: failed for {letter.provider_name}: {e}")
    return EmailProvidersResponse(
        message=f"Authority letter emails sent to {sent_count} provider(s)." if sent_count else "No emails sent (no provider with contact email, or in testing only Test provider receives emails).",
        sent_count=sent_count,
    )


@router.get("/properties/{property_id}/authority-letters/{letter_id}/signed-pdf")
def get_authority_letter_signed_pdf_owner(
    property_id: int,
    letter_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Return the signed PDF for an authority letter (owner only). Fetches from Dropbox if not yet in DB."""
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="No owner profile")
    prop = db.query(Property).filter(
        Property.id == property_id,
        Property.owner_profile_id == profile.id,
    ).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    letter = db.query(PropertyAuthorityLetter).filter(
        PropertyAuthorityLetter.id == letter_id,
        PropertyAuthorityLetter.property_id == prop.id,
    ).first()
    if not letter:
        raise HTTPException(status_code=404, detail="Authority letter not found")
    if letter.signed_pdf_bytes:
        return Response(
            content=letter.signed_pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="DocuStay-Authority-Letter-{letter.provider_name or "signed"}.pdf"'},
        )
    if letter.dropbox_sign_request_id:
        pdf_bytes = get_signed_pdf(letter.dropbox_sign_request_id)
        if pdf_bytes:
            from datetime import datetime, timezone
            letter.signed_pdf_bytes = pdf_bytes
            letter.signed_at = letter.signed_at or datetime.now(timezone.utc)
            db.commit()
            return Response(
                content=pdf_bytes,
                media_type="application/pdf",
                headers={"Content-Disposition": f'inline; filename="DocuStay-Authority-Letter-{letter.provider_name or "signed"}.pdf"'},
            )
    raise HTTPException(status_code=404, detail="Signed PDF not yet available. The provider may not have signed yet.")


_ALLOWED_PROOF_TYPES = frozenset({"deed", "tax_bill", "utility_bill", "mortgage_statement"})
_MAX_PROOF_SIZE = 10 * 1024 * 1024  # 10MB
_ALLOWED_CONTENT_TYPES = frozenset({"application/pdf", "image/jpeg", "image/jpg", "image/png"})


@router.post("/properties/{property_id}/ownership-proof", response_model=PropertyResponse)
def upload_ownership_proof(
    request: Request,
    property_id: int,
    proof_type: str = Form("deed"),
    proof_file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Store ownership verification document (deed, tax bill, etc.) for the property."""
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="No owner profile")
    prop = db.query(Property).filter(
        Property.id == property_id,
        Property.owner_profile_id == profile.id,
    ).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    proof_type = (proof_type or "deed").strip().lower()
    if proof_type not in _ALLOWED_PROOF_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid proof_type. Use one of: {sorted(_ALLOWED_PROOF_TYPES)}")
    content_type = (proof_file.content_type or "").split(";")[0].strip().lower()
    if content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"File must be PDF or image (JPEG/PNG). Got: {content_type or 'unknown'}",
        )
    contents = proof_file.file.read()
    if len(contents) > _MAX_PROOF_SIZE:
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 10MB.")
    filename = (proof_file.filename or "proof").strip() or "proof"
    if len(filename) > 255:
        filename = filename[:251] + filename[filename.rfind("."):] if "." in filename else filename[:255]
    now = datetime.now(timezone.utc)
    prop.ownership_proof_type = proof_type
    prop.ownership_proof_filename = filename
    prop.ownership_proof_content_type = content_type
    prop.ownership_proof_bytes = contents
    prop.ownership_proof_uploaded_at = now
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "Ownership proof uploaded",
        f"Owner uploaded {proof_type} proof ({filename}) for property {prop.name or prop.street}.",
        property_id=prop.id,
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=request.client.host if request.client else None,
        meta={"proof_type": proof_type, "filename": filename},
    )
    db.commit()
    db.refresh(prop)
    return PropertyResponse.model_validate(prop)


@router.get("/properties/{property_id}/ownership-proof")
def get_ownership_proof(
    property_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Return the ownership proof file for viewing/download. For properties without proof, returns 404 (no exception—frontend shows friendly message)."""
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="No owner profile")
    prop = db.query(Property).filter(
        Property.id == property_id,
        Property.owner_profile_id == profile.id,
    ).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    if not prop.ownership_proof_bytes:
        raise HTTPException(status_code=404, detail="No ownership proof uploaded for this property.")
    content_type = prop.ownership_proof_content_type or "application/octet-stream"
    filename = prop.ownership_proof_filename or "proof"
    return Response(
        content=bytes(prop.ownership_proof_bytes),
        media_type=content_type,
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.post("/properties/{property_id}/release-usat-token", response_model=PropertyResponse)
def release_usat_token(
    request: Request,
    property_id: int,
    data: ReleaseUsatTokenRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Release the property's USAT token to the selected guest stay(s). Only those guests will see the token. Owner must choose at least one active stay for this property."""
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="No owner profile")
    prop = _get_owner_property(property_id, profile, db)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    if not prop.usat_token:
        raise HTTPException(status_code=400, detail="This property has no USAT token.")
    if not data.stay_ids:
        raise HTTPException(status_code=400, detail="Select at least one guest to release the token to.")
    now = datetime.now(timezone.utc)
    released_to_stays = []
    for stay_id in data.stay_ids:
        stay = db.query(Stay).filter(
            Stay.id == stay_id,
            Stay.property_id == property_id,
            Stay.owner_id == current_user.id,
            Stay.checked_out_at.is_(None),
            Stay.cancelled_at.is_(None),
        ).first()
        if not stay:
            raise HTTPException(
                status_code=400,
                detail=f"Stay {stay_id} is not an active stay for this property. Only current guests can receive the token.",
            )
        stay.usat_token_released_at = now
        db.add(stay)
        released_to_stays.append(stay)
    # Clear token from active stays at this property that were not selected (so Manage can revoke)
    other_active = (
        db.query(Stay)
        .filter(
            Stay.property_id == property_id,
            Stay.owner_id == current_user.id,
            Stay.checked_out_at.is_(None),
            Stay.cancelled_at.is_(None),
            Stay.id.notin_(data.stay_ids),
        )
        .all()
    )
    for stay in other_active:
        stay.usat_token_released_at = None
        db.add(stay)
    prop.usat_token_state = USAT_TOKEN_RELEASED
    prop.usat_token_released_at = now

    property_name = (prop.name or f"{prop.city}, {prop.state}" if prop else None) or "Property"
    guest_names = []
    for s in released_to_stays:
        guest = db.query(User).filter(User.id == s.guest_id).first()
        gp = db.query(GuestProfile).filter(GuestProfile.user_id == s.guest_id).first()
        name = (gp.full_legal_name if gp else None) or (guest.full_name if guest else None) or (guest.email if guest else "Unknown")
        guest_names.append(name)
    guest_list = ", ".join(guest_names)
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "USAT token released",
        f"USAT token released for property {property_name} to guest(s): {guest_list}. Stay IDs: {data.stay_ids}.",
        property_id=property_id,
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=request.client.host if request.client else None,
        user_agent=(request.headers.get("user-agent") or "").strip() or None,
        meta={"stay_ids": data.stay_ids, "guest_names": guest_names, "property_name": property_name},
    )
    db.commit()
    db.refresh(prop)
    return PropertyResponse.model_validate(prop)


def _get_owner_property(property_id: int, profile: OwnerProfile, db: Session) -> Property | None:
    return db.query(Property).filter(
        Property.id == property_id,
        Property.owner_profile_id == profile.id,
    ).first()


def _snapshot_property(prop: Property) -> dict:
    """Current property fields that can be updated (for change detection)."""
    return {
        "name": prop.name,
        "street": prop.street,
        "city": prop.city,
        "state": prop.state,
        "zip_code": prop.zip_code,
        "region_code": prop.region_code,
        "owner_occupied": prop.owner_occupied,
        "property_type": prop.property_type.value if prop.property_type else None,
        "property_type_label": prop.property_type_label,
        "bedrooms": prop.bedrooms,
        "shield_mode_enabled": getattr(prop, "shield_mode_enabled", 0),
    }


@router.put("/properties/{property_id}", response_model=PropertyResponse)
def update_property(
    request: Request,
    property_id: int,
    data: PropertyUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="No owner profile")
    prop = _get_owner_property(property_id, profile, db)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    old = _snapshot_property(prop)

    if data.property_name is not None:
        prop.name = data.property_name
    if data.street_address is not None or data.street is not None:
        prop.street = (data.street_address or data.street or prop.street)
    if data.city is not None:
        prop.city = data.city
    if data.state is not None:
        prop.state = data.state
    if data.zip_code is not None:
        prop.zip_code = data.zip_code
    if data.region_code is not None:
        prop.region_code = data.region_code.upper()[:20]
    if data.owner_occupied is not None:
        prop.owner_occupied = data.owner_occupied
    if data.is_primary_residence is not None and data.owner_occupied is None:
        prop.owner_occupied = data.is_primary_residence
    if data.property_type_enum is not None:
        prop.property_type = data.property_type_enum
    if data.property_type is not None:
        prop.property_type_label = data.property_type
    if data.bedrooms is not None:
        prop.bedrooms = data.bedrooms
    # Owner can only turn Shield Mode OFF; it turns on automatically on the last day of a guest's stay
    if data.shield_mode_enabled is not None and data.shield_mode_enabled is False:
        prop.shield_mode_enabled = 0

    new = _snapshot_property(prop)
    changes = []
    changes_meta = {}
    for key in old:
        ov, nv = old[key], new[key]
        if nv is not None and getattr(nv, "value", None) is not None:
            nv = getattr(nv, "value", nv)
        if ov is not None and getattr(ov, "value", None) is not None:
            ov = getattr(ov, "value", ov)
        if ov != nv:
            changes.append(f"{key}: {ov!r} → {nv!r}")
            changes_meta[key] = {"old": ov, "new": nv}

    if changes:
        db.flush()
        ip = request.client.host if request.client else None
        ua = (request.headers.get("user-agent") or "").strip() or None
        property_name = (prop.name or "").strip() or f"{prop.city}, {prop.state}".strip(", ") or f"Property {property_id}"
        create_log(
            db,
            CATEGORY_STATUS_CHANGE,
            "Property updated",
            f"Owner updated property: {property_name} (id={property_id}). Changes: " + "; ".join(changes),
            property_id=prop.id,
            actor_user_id=current_user.id,
            actor_email=current_user.email,
            ip_address=ip,
            user_agent=ua,
            meta={"property_id": property_id, "property_name": property_name, "changes": changes_meta},
        )
        if "shield_mode_enabled" in changes_meta and changes_meta["shield_mode_enabled"].get("new") == 0:
            create_log(
                db,
                CATEGORY_SHIELD_MODE,
                "Shield Mode turned off",
                f"Owner turned off Shield Mode for {property_name}.",
                property_id=prop.id,
                actor_user_id=current_user.id,
                actor_email=current_user.email,
                ip_address=ip,
                user_agent=ua,
                meta={"property_id": property_id, "property_name": property_name},
            )
    db.commit()
    db.refresh(prop)
    return PropertyResponse.model_validate(prop)


def _has_active_stay(db: Session, property_id: int) -> bool:
    """True if there is any stay at this property that is not checked out and not cancelled."""
    return (
        db.query(Stay)
        .filter(
            Stay.property_id == property_id,
            Stay.checked_out_at.is_(None),
            Stay.cancelled_at.is_(None),
        )
        .first()
        is not None
    )


@router.delete("/properties/{property_id}")
def delete_property(
    request: Request,
    property_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Soft-delete property: set deleted_at so it is hidden from dashboard and invite list; can be reactivated. Only allowed when there is no active stay (past stays are OK). Data is kept for logs."""
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="No owner profile")
    prop = _get_owner_property(property_id, profile, db)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    if prop.deleted_at is not None:
        return {"status": "success", "message": "Property is already inactive."}
    if _has_active_stay(db, property_id):
        raise HTTPException(
            status_code=400,
            detail="Cannot remove property: it has an active guest stay. Wait for the stay to end or be cancelled first.",
        )
    property_name = (prop.name or "").strip() or f"{prop.city}, {prop.state}".strip(", ") or f"Property {property_id}"
    ip = request.client.host if request.client else None
    ua = (request.headers.get("user-agent") or "").strip() or None
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "Property deleted",
        f"Owner removed property from dashboard (inactive): {property_name} (id={property_id}, {prop.city}, {prop.state}). Data retained for logs.",
        property_id=property_id,
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=ip,
        user_agent=ua,
        meta={"property_id": property_id, "property_name": property_name},
    )
    db.commit()
    prop.deleted_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "success", "message": "Property removed from dashboard. It has been moved to Inactive properties and can be reactivated."}


@router.post("/properties/{property_id}/reactivate", response_model=PropertyResponse)
def reactivate_property(
    request: Request,
    property_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Reactivate an inactive (soft-deleted) property so it appears in dashboard and invite list again."""
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="No owner profile")
    prop = _get_owner_property(property_id, profile, db)
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    if prop.deleted_at is None:
        db.refresh(prop)
        return PropertyResponse.model_validate(prop)
    property_name = (prop.name or "").strip() or f"{prop.city}, {prop.state}".strip(", ") or f"Property {property_id}"
    prop.deleted_at = None
    db.commit()
    ip = request.client.host if request.client else None
    ua = (request.headers.get("user-agent") or "").strip() or None
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "Property reactivated",
        f"Owner reactivated property: {property_name} (id={property_id}). Property now visible in dashboard.",
        property_id=property_id,
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=ip,
        user_agent=ua,
        meta={"property_id": property_id, "property_name": property_name},
    )
    db.commit()
    db.refresh(prop)
    return PropertyResponse.model_validate(prop)


@router.post("/invitations")
def create_invitation(
    request: Request,
    data: InvitationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
    """Create a guest invitation; store it and return code for the link."""
    prop_id = data.property_id
    if not prop_id:
        raise HTTPException(status_code=400, detail="property_id required")
    profile = db.query(OwnerProfile).filter(OwnerProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Owner profile not found")
    prop = db.query(Property).filter(Property.id == prop_id, Property.owner_profile_id == profile.id).first()
    if not prop:
        raise HTTPException(status_code=404, detail="Property not found")
    if prop.deleted_at is not None:
        raise HTTPException(status_code=400, detail="Cannot create invitation for an inactive property. Reactivate the property first.")
    if not (data.guest_name or "").strip():
        raise HTTPException(status_code=400, detail="guest_name is required")
    if not data.checkin_date or not data.checkout_date:
        raise HTTPException(status_code=400, detail="checkin_date and checkout_date are required")
    start = datetime.strptime(data.checkin_date, "%Y-%m-%d").date()
    end = datetime.strptime(data.checkout_date, "%Y-%m-%d").date()
    if end <= start:
        raise HTTPException(status_code=400, detail="checkout_date must be after checkin_date")
    code = "INV-" + secrets.token_hex(4).upper()
    purpose = _PURPOSE_MAP.get((data.purpose or "visit").lower(), PurposeOfStay.travel)
    rel = _REL_MAP.get((data.relationship or "friend").lower(), RelationshipToOwner.friend)
    # Dead Man's Switch is always on: triggered automatically; alerts by Email and Dashboard notification
    dms = 1
    dms_email = 1
    dms_sms = 0
    dms_dash = 1
    dms_phone = 0
    inv = Invitation(
        invitation_code=code,
        owner_id=current_user.id,
        property_id=prop.id,
        guest_name=(data.guest_name or "").strip() or None,
        guest_email=(data.guest_email or "").strip() or None,
        stay_start_date=start,
        stay_end_date=end,
        purpose_of_stay=purpose,
        relationship_to_owner=rel,
        region_code=prop.region_code,
        status="pending",
        dead_mans_switch_enabled=dms,
        dead_mans_switch_alert_email=dms_email,
        dead_mans_switch_alert_sms=dms_sms,
        dead_mans_switch_alert_dashboard=dms_dash,
        dead_mans_switch_alert_phone=dms_phone,
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)
    ip = request.client.host if request.client else None
    ua = (request.headers.get("user-agent") or "").strip() or None
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "Invitation created",
        f"Owner created invitation {code} for property {prop.id}, guest {data.guest_name or data.guest_email or '—'}, {start}–{end}.",
        property_id=prop.id,
        invitation_id=inv.id,
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=ip,
        user_agent=ua,
        meta={"invitation_code": code, "guest_name": (data.guest_name or "").strip(), "guest_email": (data.guest_email or "").strip()},
    )
    db.commit()
    return {"invitation_code": code}


@router.get("/invitation-details")
def get_invitation_details(
    code: str,
    db: Session = Depends(get_db),
):
    """Public: get invitation details by code for the invite signup page (pending only)."""
    code = code.strip().upper()
    inv = db.query(Invitation).filter(Invitation.invitation_code == code, Invitation.status == "pending").first()
    if not inv:
        return {"valid": False}
    prop = db.query(Property).filter(Property.id == inv.property_id).first()
    owner = db.query(User).filter(User.id == inv.owner_id).first()
    return {
        "valid": True,
        "property_name": prop.name if prop else None,
        "property_address": f"{prop.street}, {prop.city}, {prop.state}{(' ' + prop.zip_code) if (prop and prop.zip_code) else ''}" if prop else None,
        "stay_start_date": str(inv.stay_start_date),
        "stay_end_date": str(inv.stay_end_date),
        "region_code": inv.region_code,
        "host_name": (owner.full_name if owner else None) or (owner.email if owner else ""),
        "guest_name": inv.guest_name,
    }
