"""Module B1: Owner onboarding."""
import csv
import io
import secrets
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User
from app.models.owner import OwnerProfile, Property, PropertyType, USAT_TOKEN_STAGED, USAT_TOKEN_RELEASED
from app.models.invitation import Invitation
from app.models.guest import PurposeOfStay, RelationshipToOwner
from app.schemas.owner import BulkUploadResult, PropertyCreate, PropertyResponse, PropertyUpdate, ReleaseUsatTokenRequest
from app.dependencies import get_current_user, require_owner, require_owner_onboarding_complete
from app.models.stay import Stay
from app.models.guest import GuestProfile
from app.services.audit_log import create_log, CATEGORY_STATUS_CHANGE, CATEGORY_SHIELD_MODE

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


@router.post("/properties", response_model=PropertyResponse)
def add_property(
    request: Request,
    data: PropertyCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_onboarding_complete),
):
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
    return PropertyResponse.model_validate(prop)


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
