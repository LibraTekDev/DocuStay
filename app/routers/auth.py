"""Module A: Authentication & role selection."""
import random
import secrets
import string
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from sqlalchemy.sql import func
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.models.user import User, UserRole
from app.models.invitation import Invitation
from app.models.stay import Stay
from app.models.agreement_signature import AgreementSignature
from app.models.guest_pending_invite import GuestPendingInvite
from app.models.owner import OwnerProfile, Property, OccupancyStatus
from app.models.owner_poa_signature import OwnerPOASignature
from app.models.pending_registration import PendingRegistration
from app.services.audit_log import create_log, CATEGORY_STATUS_CHANGE, CATEGORY_GUEST_SIGNATURE, CATEGORY_FAILED_ATTEMPT
from app.services.billing import sync_subscription_quantities
from app.schemas.auth import (
    UserCreate,
    UserLogin,
    Token,
    UserResponse,
    GuestRegister,
    AcceptInvite,
    VerifyEmailRequest,
    ResendVerificationRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    RegisterPendingResponse,
    LinkPOARequest,
    PendingOwnerIdentitySessionRequest,
    PendingOwnerIdentitySessionResponse,
    PendingOwnerConfirmIdentityRequest,
    PendingOwnerMeResponse,
    PendingOwnerLatestIdentitySessionResponse,
    PendingOwnerIdentityRetryRequest,
    PendingOwnerIdentityRetryResponse,
    CompleteOwnerSignupRequest,
)
from app.services.auth import (
    get_password_hash,
    verify_password,
    create_access_token,
    create_pending_owner_token,
    create_password_reset_token,
    decode_token_with_error,
)
from app.services.dropbox_sign import get_signed_pdf
from app.services.notifications import (
    send_verification_email,
    send_password_reset_email,
    send_owner_welcome_email,
    send_guest_welcome_email,
    send_guest_signup_welcome_email,
    send_guest_stay_added_email,
)
from app.dependencies import get_current_user, require_owner, require_guest, get_pending_owner
from app.models.guest import GuestProfile
from app.config import get_settings


def _user_to_response(user: User, db: Session) -> UserResponse:
    """Build UserResponse with identity_verified and poa_linked."""
    identity_verified = bool(getattr(user, "identity_verified_at", None))
    poa_linked = False
    if user.role == UserRole.owner:
        has_poa = db.query(OwnerPOASignature).filter(OwnerPOASignature.used_by_user_id == user.id).first() is not None
        poa_waived = bool(getattr(user, "poa_waived_at", None))
        poa_linked = has_poa or poa_waived
    return UserResponse(
        id=user.id,
        email=user.email,
        role=user.role,
        full_name=user.full_name,
        phone=user.phone,
        state=user.state,
        city=user.city,
        identity_verified=identity_verified,
        poa_linked=poa_linked,
    )

router = APIRouter(prefix="/auth", tags=["auth"])

VERIFICATION_CODE_EXPIRE_MINUTES = 10


def _mailgun_configured() -> bool:
    s = get_settings()
    return bool(s.mailgun_api_key and s.mailgun_domain)


def _generate_verification_code() -> str:
    return "".join(random.choices(string.digits, k=6))


def _register_email_taken_message(existing_role: UserRole) -> str:
    if existing_role == UserRole.owner:
        return "This email is already registered as a property owner. Please log in on the Owner Login page."
    return "This email is already registered as a guest. Please log in on the Guest Login page."


def _validate_and_claim_owner_poa(
    db: Session,
    poa_signature_id: int,
    owner_email: str,
    *,
    dropbox_incomplete_message: str = "Please complete signing in Dropbox before continuing. Then try again.",
) -> None:
    """Validate POA signature exists, email matches, not already used, and (when sent to Dropbox) completed in Dropbox. Raises HTTPException on failure."""
    sig = db.query(OwnerPOASignature).filter(OwnerPOASignature.id == poa_signature_id).first()
    if not sig:
        raise HTTPException(status_code=400, detail="Invalid Master POA signature. Please sign the document again.")
    if sig.owner_email.strip().lower() != (owner_email or "").strip().lower():
        raise HTTPException(status_code=400, detail="Master POA signature email does not match registration email.")
    if sig.used_by_user_id is not None:
        raise HTTPException(status_code=400, detail="This Master POA signature was already used for another account.")
    if getattr(sig, "dropbox_sign_request_id", None) and not getattr(sig, "signed_pdf_bytes", None):
        pdf_bytes = get_signed_pdf(sig.dropbox_sign_request_id)
        if pdf_bytes:
            sig.signed_pdf_bytes = pdf_bytes
            db.commit()
        else:
            raise HTTPException(status_code=400, detail=dropbox_incomplete_message)


def _owner_onboarding_complete(db: Session, user: User) -> bool:
    """True if owner has completed identity verification and linked Master POA."""
    if user.role != UserRole.owner:
        return True
    if not getattr(user, "identity_verified_at", None):
        return False
    poa = db.query(OwnerPOASignature).filter(OwnerPOASignature.used_by_user_id == user.id).first()
    return poa is not None


@router.post("/register")
def register(data: UserCreate, db: Session = Depends(get_db)):
    # Same email can have both owner and guest accounts (unique on email+role).
    existing_same_role = db.query(User).filter(User.email == data.email, User.role == data.role).first()
    if existing_same_role:
        # Owner who hasn't finished onboarding can "continue" by submitting the form with correct password
        if existing_same_role.role == UserRole.owner and not _owner_onboarding_complete(db, existing_same_role):
            if not verify_password(data.password, existing_same_role.hashed_password):
                raise HTTPException(
                    status_code=400,
                    detail="An account with this email exists but onboarding wasn't completed. Please log in with your password on the Owner Login page to continue.",
                )
            print(f"[Auth] Existing owner (incomplete onboarding): returning token for {data.email} — no verification email sent.", flush=True)
            token = create_access_token(existing_same_role.id, existing_same_role.email, existing_same_role.role)
            return Token(access_token=token, user=_user_to_response(existing_same_role, db))
        raise HTTPException(
            status_code=400,
            detail=_register_email_taken_message(existing_same_role.role),
        )

    # Owner: POA is linked after identity verification (separate step); do not require or claim here
    if data.role == UserRole.owner and data.poa_signature_id:
        _validate_and_claim_owner_poa(
            db, data.poa_signature_id, data.email,
            dropbox_incomplete_message="Please complete signing in Dropbox before completing signup.",
        )

    # Owner signup always requires email verification via Mailgun (no bypass).
    if data.role == UserRole.owner:
        # Remove any existing pending owner for this email so they can start fresh (e.g. abandoned email verify or Stripe failed).
        existing_pending = db.query(PendingRegistration).filter(
            PendingRegistration.email == data.email,
            PendingRegistration.role == UserRole.owner,
        ).all()
        for p in existing_pending:
            db.delete(p)
        if existing_pending:
            db.commit()
            print(f"[Auth] Removed {len(existing_pending)} existing pending owner(s) for {data.email} so signup can start fresh", flush=True)

        # Reload config so UI flow uses same .env as script (avoid stale cache)
        from app.services.notifications import _get_fresh_settings
        _get_fresh_settings()
        if not _mailgun_configured():
            raise HTTPException(
                status_code=503,
                detail="Email verification is required for owner signup. Please configure MAILGUN_API_KEY and MAILGUN_DOMAIN in .env and restart the server.",
            )
        code = _generate_verification_code()
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=VERIFICATION_CODE_EXPIRE_MINUTES)
        extra = {"owner_type": (data.owner_type.value if data.owner_type else None)}
        pending = PendingRegistration(
            email=data.email,
            hashed_password=get_password_hash(data.password),
            role=UserRole.owner,
            full_name=data.full_name or None,
            phone=data.phone or None,
            state=data.state or None,
            city=data.city or None,
            country=data.country or None,
            verification_code=code,
            expires_at=expires_at,
            extra_data=extra,
        )
        db.add(pending)
        db.commit()
        db.refresh(pending)
        _log_mailgun_status = _mailgun_configured()
        print(f"[Auth] Owner signup: Mailgun configured={_log_mailgun_status} domain={get_settings().mailgun_domain or '(none)'}", flush=True)
        print(f"[Auth] Sending verification email to {data.email} (owner signup pending_id={pending.id})", flush=True)
        try:
            # send_verification_email clears config cache and calls send_email -> _send_email_mailgun
            sent = send_verification_email(data.email, code)
        except Exception as e:
            print(f"[Auth] Verification email exception: {type(e).__name__}: {e}", flush=True)
            db.delete(pending)
            db.commit()
            raise HTTPException(
                status_code=503,
                detail="We could not send the verification email. Please check MAILGUN_API_KEY, MAILGUN_DOMAIN, and MAILGUN_FROM_EMAIL in .env, then restart the server and try again.",
            ) from e
        print(f"[Auth] Verification email sent={sent} for {data.email}", flush=True)
        if not sent:
            db.delete(pending)
            db.commit()
            raise HTTPException(
                status_code=503,
                detail="We could not send the verification email. Please check MAILGUN_API_KEY, MAILGUN_DOMAIN, and MAILGUN_FROM_EMAIL in .env and restart the server, then try again.",
            )
        return RegisterPendingResponse(user_id=pending.id)

    bypass_verification = not _mailgun_configured()

    if bypass_verification and data.role != UserRole.owner:
        # Guest with no mailgun: create user immediately
        user = User(
            email=data.email,
            hashed_password=get_password_hash(data.password),
            role=data.role,
            full_name=data.full_name or None,
            phone=data.phone or None,
            state=data.state or None,
            city=data.city or None,
            country=data.country or None,
            email_verified=True,
            email_verification_code=None,
            email_verification_expires_at=None,
        )
        db.add(user)
        try:
            db.commit()
        except IntegrityError as e:
            db.rollback()
            msg = str(getattr(getattr(e, "orig", None), "args", [""])[0] if hasattr(e, "orig") and e.orig else str(e))
            if "email" in msg.lower() or "unique" in msg.lower():
                raise HTTPException(status_code=400, detail=_register_email_taken_message(data.role))
            raise
        db.refresh(user)
        token = create_access_token(user.id, user.email, user.role)
        return Token(access_token=token, user=_user_to_response(user, db))

    # Guest (or other roles): store pending and send verification email, or create user immediately if Mailgun not configured.
    if not bypass_verification:
        # Store pending registration; user is created only after email verification.
        code = _generate_verification_code()
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=VERIFICATION_CODE_EXPIRE_MINUTES)
        pending = PendingRegistration(
            email=data.email,
            hashed_password=get_password_hash(data.password),
            role=data.role,
            full_name=data.full_name or None,
            phone=data.phone or None,
            state=data.state or None,
            city=data.city or None,
            country=data.country or None,
            verification_code=code,
            expires_at=expires_at,
            extra_data=(
            {"poa_signature_id": data.poa_signature_id, "owner_type": (data.owner_type.value if data.owner_type else None)}
            if data.role == UserRole.owner else None
        ),
        )
        db.add(pending)
        db.commit()
        db.refresh(pending)
        sent = send_verification_email(data.email, code)
        if not sent:
            db.delete(pending)
            db.commit()
            print(f"Verification email not sent to {data.email}. Check MAILGUN_* settings (domain, from_email).", flush=True)
            raise HTTPException(
                status_code=503,
                detail="We could not send the verification email. Please check your email address and try again, or try again later. If the problem continues, check that Mailgun is configured with MAILGUN_DOMAIN and MAILGUN_FROM_EMAIL for your sending domain.",
            )
        return RegisterPendingResponse(user_id=pending.id)


@router.post("/login", response_model=Token)
def login(request: Request, data: UserLogin, db: Session = Depends(get_db)):
    if not data.role:
        candidates = db.query(User).filter(User.email == data.email).all()
        if len(candidates) > 1:
            raise HTTPException(
                status_code=400,
                detail="This email is registered as both property owner and guest. Use the Owner Login or Guest Login page and try again.",
            )
        user = candidates[0] if candidates else None
    else:
        user = db.query(User).filter(User.email == data.email, User.role == data.role).first()
    if not user or not verify_password(data.password, user.hashed_password):
        ip = request.client.host if request.client else None
        ua = (request.headers.get("user-agent") or "").strip() or None
        create_log(
            db,
            CATEGORY_FAILED_ATTEMPT,
            "Login failed",
            f"Failed login attempt for email: {data.email}.",
            actor_email=data.email,
            ip_address=ip,
            user_agent=ua,
            meta={"reason": "invalid_email_or_password"},
        )
        db.commit()
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if user.role == UserRole.owner and not getattr(user, "email_verified", True):
        raise HTTPException(
            status_code=401,
            detail="Please verify your email first. Check your inbox or use the verification page to resend the code.",
        )
    token = create_access_token(user.id, user.email, user.role)
    return Token(access_token=token, user=_user_to_response(user, db))


def _complete_pending_owner(db: Session, pending: PendingRegistration) -> User:
    """Create User from pending owner, link POA, delete pending. Returns the new User."""
    from app.models.user import OwnerType
    extra = pending.extra_data or {}
    poa_id = extra.get("poa_signature_id")
    owner_type_val = extra.get("owner_type")
    owner_type = OwnerType(owner_type_val) if owner_type_val in ("owner_of_record", "authorized_agent") else None
    user = User(
        email=pending.email,
        hashed_password=pending.hashed_password,
        role=UserRole.owner,
        full_name=pending.full_name,
        phone=pending.phone,
        state=pending.state,
        city=pending.city,
        country=pending.country,
        email_verified=True,
        email_verification_code=None,
        email_verification_expires_at=None,
        owner_type=owner_type,
    )
    db.add(user)
    db.flush()
    if poa_id:
        poa = db.query(OwnerPOASignature).filter(OwnerPOASignature.id == poa_id).first()
        if poa and poa.owner_email.strip().lower() == user.email.strip().lower():
            poa.used_by_user_id = user.id
            poa.used_at = datetime.now(timezone.utc)
    db.delete(pending)
    db.commit()
    db.refresh(user)
    return user


def _complete_pending_guest(
    request: Request, db: Session, pending: PendingRegistration
) -> User:
    """Create User and GuestProfile from pending guest; handle invite/stay; delete pending. Returns the new User."""
    extra = pending.extra_data or {}
    code = (extra.get("invitation_code") or "").strip().upper()
    inv = None
    if code:
        inv = db.query(Invitation).filter(
            Invitation.invitation_code == code,
            Invitation.status.in_(["pending", "ongoing"]),
            Invitation.token_state != "BURNED",
        ).first()
    sig = None
    sig_id = extra.get("agreement_signature_id")
    if sig_id and code:
        sig = db.query(AgreementSignature).filter(AgreementSignature.id == sig_id).first()
        if sig and (sig.invitation_code or "").strip().upper() != code:
            sig = None
        if sig and (sig.guest_email or "").strip().lower() != (pending.email or "").strip().lower():
            sig = None
        if sig and sig.used_by_user_id is not None:
            sig = None
        if sig and not (sig.acks_read and sig.acks_temporary and sig.acks_vacate and sig.acks_electronic):
            sig = None

    user = User(
        email=pending.email,
        hashed_password=pending.hashed_password,
        role=UserRole.guest,
        full_name=pending.full_name,
        phone=pending.phone,
        state=extra.get("permanent_state"),
        city=extra.get("permanent_city"),
        country="USA",
        email_verified=True,
        email_verification_code=None,
        email_verification_expires_at=None,
    )
    db.add(user)
    db.flush()
    permanent_address = extra.get("permanent_address") or ""
    permanent_city = extra.get("permanent_city") or ""
    permanent_state = extra.get("permanent_state") or ""
    permanent_zip = extra.get("permanent_zip") or ""
    permanent_home = f"{permanent_address}, {permanent_city}, {permanent_state} {permanent_zip}".strip()
    profile = GuestProfile(
        user_id=user.id,
        full_legal_name=pending.full_name or "",
        permanent_home_address=permanent_home,
        gps_checkin_acknowledgment=False,
    )
    db.add(profile)
    db.flush()

    prop = None
    if code and inv and sig:
        duration = (inv.stay_end_date - inv.stay_start_date).days
        if duration <= 0:
            duration = 1
        stay = Stay(
            guest_id=user.id,
            owner_id=inv.owner_id,
            property_id=inv.property_id,
            stay_start_date=inv.stay_start_date,
            stay_end_date=inv.stay_end_date,
            intended_stay_duration_days=duration,
            purpose_of_stay=inv.purpose_of_stay,
            relationship_to_owner=inv.relationship_to_owner,
            region_code=inv.region_code,
        )
        db.add(stay)
        inv.status = "accepted"
        sig.used_by_user_id = user.id
        sig.used_at = datetime.now(timezone.utc)
        # Occupancy is set to OCCUPIED only when guest checks in (guest_check_in endpoint).
        db.flush()
        ip = request.client.host if request.client else None
        ua = (request.headers.get("user-agent") or "").strip() or None
        create_log(
            db,
            CATEGORY_STATUS_CHANGE,
            "Invitation accepted (stay created)",
            f"Guest registered and accepted invitation {code}; stay {stay.id} created for property {inv.property_id}. Occupancy will be set when guest checks in.",
            property_id=inv.property_id,
            stay_id=stay.id,
            invitation_id=inv.id,
            actor_user_id=user.id,
            actor_email=user.email,
            ip_address=ip,
            user_agent=ua,
            meta={"invitation_code": code, "signature_id": sig.id},
        )
        prop = db.query(Property).filter(Property.id == inv.property_id).first()
        property_name = (prop.name if prop else None) or (f"{prop.city}, {prop.state}".strip(", ") if prop and (prop.city or prop.state) else None) or "the property"
        send_guest_welcome_email(user.email, user.full_name, property_name=property_name, stay_end_date=str(inv.stay_end_date))
    elif code and inv:
        pending_inv = GuestPendingInvite(user_id=user.id, invitation_id=inv.id)
        db.add(pending_inv)
    if not (code and inv and sig):
        send_guest_signup_welcome_email(user.email, user.full_name)

    db.delete(pending)
    db.commit()
    db.refresh(user)
    if prop:
        try:
            profile = db.query(OwnerProfile).filter(OwnerProfile.id == prop.owner_profile_id).first()
            if profile:
                sync_subscription_quantities(db, profile)
        except Exception:
            pass
    return user


def _normalize_verification_code(raw: str | None) -> str:
    """Return stripped string, or empty string if not exactly 6 digits."""
    s = (raw or "").strip()
    if len(s) != 6 or not s.isdigit():
        return ""
    return s


@router.post("/verify-email", response_model=Token)
def verify_email(request: Request, data: VerifyEmailRequest, db: Session = Depends(get_db)):
    """Verify email with the 6-digit code. Creates user only after verification (from pending) or marks existing user verified (legacy)."""
    raw_code = (data.code or "").strip()
    code = _normalize_verification_code(data.code)
    if raw_code and not code:
        raise HTTPException(status_code=400, detail="Verification code must be exactly 6 digits.")
    pending = db.query(PendingRegistration).filter(PendingRegistration.id == data.user_id).first()
    if pending:
        stored_code = _normalize_verification_code(pending.verification_code)
        if not code or not stored_code or stored_code != code:
            create_log(
                db,
                CATEGORY_FAILED_ATTEMPT,
                "Email verification failed",
                f"Invalid or wrong verification code for pending_id={data.user_id}.",
                actor_email=pending.email,
                ip_address=request.client.host if request.client else None,
                user_agent=(request.headers.get("user-agent") or "").strip() or None,
                meta={"pending_id": data.user_id, "reason": "invalid_or_expired_code"},
            )
            db.commit()
            raise HTTPException(status_code=400, detail="Invalid or expired verification code.")
        if pending.expires_at < datetime.now(timezone.utc):
            create_log(
                db,
                CATEGORY_FAILED_ATTEMPT,
                "Email verification failed",
                f"Expired verification code for pending_id={data.user_id}.",
                actor_email=pending.email,
                ip_address=request.client.host if request.client else None,
                user_agent=(request.headers.get("user-agent") or "").strip() or None,
                meta={"pending_id": data.user_id, "reason": "expired_code"},
            )
            db.commit()
            raise HTTPException(status_code=400, detail="Verification code has expired. Please request a new one.")
        if pending.role == UserRole.owner:
            # Owner: do NOT create user yet. Mark email verified, return pending-owner token. User is created after identity + POA.
            # Assign new dict so SQLAlchemy persists JSONB (in-place mutation may not be detected).
            pending.extra_data = {**(pending.extra_data or {}), "email_verified_at": datetime.now(timezone.utc).isoformat()}
            db.commit()
            db.refresh(pending)
            token = create_pending_owner_token(pending.id, pending.email)
            fake_user = UserResponse(
                id=0,
                email=pending.email,
                role=UserRole.owner,
                full_name=pending.full_name,
                phone=pending.phone,
                state=pending.state,
                city=pending.city,
                identity_verified=False,
                poa_linked=False,
            )
            return Token(access_token=token, user=fake_user)
        user = _complete_pending_guest(request, db, pending)
        token = create_access_token(user.id, user.email, user.role)
        return Token(access_token=token, user=_user_to_response(user, db))

    # Legacy: already-created unverified user (from before pending flow)
    user = db.query(User).filter(User.id == data.user_id).first()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid request")
    # Only skip code check when user is already verified AND no code was provided (re-requesting token).
    # If a code was provided we must validate it so a wrong code never returns success.
    if getattr(user, "email_verified", False) and (not code or len(code) != 6):
        token = create_access_token(user.id, user.email, user.role)
        return Token(access_token=token, user=_user_to_response(user, db))
    stored_user_code = _normalize_verification_code(user.email_verification_code)
    if not code or not stored_user_code or stored_user_code != code:
        create_log(
            db,
            CATEGORY_FAILED_ATTEMPT,
            "Email verification failed",
            f"Invalid or wrong verification code for user_id={data.user_id}.",
            actor_email=user.email,
            ip_address=request.client.host if request.client else None,
            user_agent=(request.headers.get("user-agent") or "").strip() or None,
            meta={"user_id": data.user_id, "reason": "invalid_or_expired_code"},
        )
        db.commit()
        raise HTTPException(status_code=400, detail="Invalid or expired verification code")
    if user.email_verification_expires_at and user.email_verification_expires_at < datetime.now(timezone.utc):
        create_log(
            db,
            CATEGORY_FAILED_ATTEMPT,
            "Email verification failed",
            f"Expired verification code for user_id={data.user_id}.",
            actor_email=user.email,
            ip_address=request.client.host if request.client else None,
            user_agent=(request.headers.get("user-agent") or "").strip() or None,
            meta={"user_id": data.user_id, "reason": "expired_code"},
        )
        db.commit()
        raise HTTPException(status_code=400, detail="Verification code has expired. Please request a new one.")
    user.email_verified = True
    user.email_verification_code = None
    user.email_verification_expires_at = None
    db.commit()
    db.refresh(user)
    if user.role == UserRole.owner:
        send_owner_welcome_email(user.email, user.full_name)
    token = create_access_token(user.id, user.email, user.role)
    return Token(access_token=token, user=_user_to_response(user, db))


@router.post("/resend-verification")
def resend_verification(data: ResendVerificationRequest, db: Session = Depends(get_db)):
    """Send a new verification code. Works for pending registration or legacy unverified user."""
    pending = db.query(PendingRegistration).filter(PendingRegistration.id == data.user_id).first()
    if pending:
        code = _generate_verification_code()
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=VERIFICATION_CODE_EXPIRE_MINUTES)
        pending.verification_code = code
        pending.expires_at = expires_at
        db.commit()
        sent = send_verification_email(pending.email, code)
        if not sent:
            print(f"Resend verification email not sent to {pending.email}", flush=True)
            raise HTTPException(
                status_code=503,
                detail="We could not send the verification email. Check MAILGUN_DOMAIN and MAILGUN_FROM_EMAIL in .env and restart the server, then try again.",
            )
        return {"status": "ok", "message": "Verification code sent. Check your email."}

    user = db.query(User).filter(User.id == data.user_id).first()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid request")
    if getattr(user, "email_verified", False):
        return {"status": "ok", "message": "Email is already verified."}
    code = _generate_verification_code()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=VERIFICATION_CODE_EXPIRE_MINUTES)
    user.email_verification_code = code
    user.email_verification_expires_at = expires_at
    db.commit()
    sent = send_verification_email(user.email, code)
    if not sent:
        print(f"Resend verification email not sent to {user.email}", flush=True)
        raise HTTPException(
            status_code=503,
            detail="We could not send the verification email. Check MAILGUN_DOMAIN and MAILGUN_FROM_EMAIL in .env and restart the server, then try again.",
        )
    return {"status": "ok", "message": "Verification code sent. Check your email."}


@router.post("/forgot-password")
def forgot_password(data: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """
    Request a password reset email. Role (owner or guest) is required so we target the correct
    account when the same email is registered as both owner and guest. Frontend passes role based
    on which sign-in page the user came from.
    """
    user = db.query(User).filter(User.email == data.email, User.role == data.role).first()
    if not user:
        role_label = "owner" if data.role == UserRole.owner else "guest"
        raise HTTPException(
            status_code=404,
            detail=f"No account found for this email as an {role_label}. Use Owner Login or Guest Login depending on which account you have, or register first.",
        )
    base_url = (get_settings().frontend_base_url or "").strip().rstrip("/")
    if not base_url:
        # No frontend URL configured; cannot build reset link. Return same message (no email enumeration).
        return {"status": "ok", "message": "If an account exists for this email, you will receive a password reset link shortly."}
    reset_secret = secrets.token_urlsafe(32)
    user.password_reset_token = reset_secret
    user.password_reset_expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
    db.commit()
    token = create_password_reset_token(user.id, user.email, user.role, reset_secret)
    reset_link = f"{base_url}/#reset-password?token={token}&role={user.role.value}"
    sent = send_password_reset_email(user.email, reset_link, user.role.value)
    if not sent:
        print(f"[Auth] Password reset email not sent to {user.email}", flush=True)
        raise HTTPException(
            status_code=503,
            detail="We could not send the password reset email. Please try again later or contact support.",
        )
    return {"status": "ok", "message": "If an account exists for this email, you will receive a password reset link shortly."}


@router.post("/reset-password")
def reset_password(data: ResetPasswordRequest, db: Session = Depends(get_db)):
    """Set new password using the token from the reset email. Token is one-time use; invalid after first use."""
    payload, err = decode_token_with_error(data.token)
    if err or not payload:
        raise HTTPException(status_code=400, detail="Invalid or expired reset link. Please request a new password reset.")
    if payload.get("type") != "password_reset":
        raise HTTPException(status_code=400, detail="Invalid reset link. Please use the link from your email.")
    reset_secret = payload.get("reset_secret")
    if not reset_secret:
        raise HTTPException(status_code=400, detail="Invalid reset link. Please request a new password reset.")
    try:
        user_id = int(payload.get("sub") or 0)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid reset link.")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid reset link. Please request a new password reset.")
    now = datetime.now(timezone.utc)
    if not user.password_reset_token or user.password_reset_token != reset_secret:
        raise HTTPException(status_code=400, detail="This reset link has already been used. Request a new password reset if needed.")
    if user.password_reset_expires_at and user.password_reset_expires_at < now:
        user.password_reset_token = None
        user.password_reset_expires_at = None
        db.commit()
        raise HTTPException(status_code=400, detail="This reset link has expired. Please request a new password reset.")
    user.hashed_password = get_password_hash(data.new_password)
    user.password_reset_token = None
    user.password_reset_expires_at = None
    db.commit()
    return {"status": "ok", "message": "Password updated. You can sign in now."}


@router.get("/me", response_model=UserResponse)
def me(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return _user_to_response(current_user, db)


def _stripe_identity_configured():
    s = get_settings()
    return bool(s.stripe_secret_key and (s.stripe_identity_return_url or s.stripe_identity_flow_id))


def _log_stripe_session(session, stage: str) -> None:
    """Print Stripe VerificationSession fields so we can decide based on success/failure."""
    try:
        sid = getattr(session, "id", None) or (session.get("id") if hasattr(session, "get") and callable(session.get) else None)
        status = getattr(session, "status", None) or (session.get("status") if hasattr(session, "get") and callable(session.get) else None)
        last_error = getattr(session, "last_error", None) or (session.get("last_error") if hasattr(session, "get") and callable(session.get) else None)
        meta = getattr(session, "metadata", None) or (session.get("metadata") if hasattr(session, "get") and callable(session.get) else None)
        err_code = getattr(last_error, "code", None) if last_error else (last_error.get("code") if isinstance(last_error, dict) else None)
        err_reason = getattr(last_error, "reason", None) if last_error else (last_error.get("reason") if isinstance(last_error, dict) else None)
        print(f"[Stripe Identity] {stage} -> id={sid} status={status} last_error.code={err_code} last_error.reason={err_reason} metadata={meta}")
        if status == "verified":
            print(f"[Stripe Identity] SUCCESS verification completed for session_id={sid}")
        elif status == "requires_input" and stage == "CREATE":
            print(f"[Stripe Identity] CREATE: requires_input is expected (user has not verified yet)")
        elif status and status != "verified":
            print(f"[Stripe Identity] NOT_VERIFIED status={status} (use last_error above for failure reason)")
    except Exception as e:
        print(f"[Stripe Identity] {stage} -> log parse error: {e}")


def _stripe_session_failure_detail(session) -> str:
    """Build user-facing failure message from Stripe session. Success is session.status == 'verified'; anything else is failure."""
    status = getattr(session, "status", None) or (session.get("status") if hasattr(session, "get") and callable(session.get) else None)
    last_error = getattr(session, "last_error", None) or (session.get("last_error") if hasattr(session, "get") and callable(session.get) else None)
    err_reason = None
    err_code = None
    if last_error:
        err_code = getattr(last_error, "code", None) if not isinstance(last_error, dict) else last_error.get("code")
        err_reason = getattr(last_error, "reason", None) if not isinstance(last_error, dict) else last_error.get("reason")
    parts = [f"Verification not completed. Status: {status or 'unknown'}."]
    if err_reason:
        parts.append(f" Reason: {err_reason}.")
    if err_code and not err_reason:
        parts.append(f" Code: {err_code}.")
    parts.append(" Please complete the verification flow or try again.")
    return "".join(parts)


@router.post("/pending-owner/identity-session", response_model=PendingOwnerIdentitySessionResponse)
def pending_owner_create_identity_session(
    data: PendingOwnerIdentitySessionRequest | None = Body(None),
    db: Session = Depends(get_db),
    pending: PendingRegistration = Depends(get_pending_owner),
):
    """Create Stripe Identity session for pending owner (after email verified). return_url from frontend ensures Stripe redirects to same origin (preserves localStorage token)."""
    if not _stripe_identity_configured():
        raise HTTPException(status_code=503, detail="Identity verification is not configured.")
    import stripe
    settings = get_settings()
    stripe.api_key = settings.stripe_secret_key
    # Use STRIPE_IDENTITY_RETURN_URL or FRONTEND_BASE_URL from .env; no hardcoded localhost.
    base_url = (settings.stripe_identity_return_url or settings.frontend_base_url or "").strip().split("#")[0].rstrip("/")
    candidate = (data.return_url or "").strip().split("#")[0].rstrip("/") if data and data.return_url else ""
    if candidate and (candidate.startswith("http://") or candidate.startswith("https://")):
        return_url = f"{candidate.rstrip('/')}/onboarding/identity-complete"
    elif base_url:
        return_url = f"{base_url}/onboarding/identity-complete"
    else:
        raise HTTPException(
            status_code=503,
            detail="Identity verification is not configured. Set STRIPE_IDENTITY_RETURN_URL or FRONTEND_BASE_URL in .env.",
        )
    try:
        flow_id = (settings.stripe_identity_flow_id or "").strip()
        if flow_id:
            create_params = {"verification_flow": flow_id, "return_url": return_url, "metadata": {"pending_id": str(pending.id)}}
        else:
            create_params = {
                "type": "document",
                "return_url": return_url,
                "metadata": {"pending_id": str(pending.id)},
                "options": {"document": {"allowed_types": ["driving_license", "passport", "id_card"], "require_matching_selfie": True}},
            }
        idempotency_key = (
            f"identity_pending_{pending.id}_new_{int(datetime.now(timezone.utc).timestamp())}"
            if (data and getattr(data, "force_new_session", False))
            else f"identity_pending_{pending.id}"
        )
        session = stripe.identity.VerificationSession.create(**create_params, idempotency_key=idempotency_key)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Stripe error: {getattr(e, 'message', str(e))}")
    _url = getattr(session, "url", None) or (session.get("url") if hasattr(session, "get") and callable(session.get) else None)
    url = str(_url).strip() if _url else None
    if not url or not url.startswith("http"):
        raise HTTPException(status_code=502, detail="Stripe did not return a verification URL. Check Stripe Identity and return_url configuration.")
    _log_stripe_session(session, "CREATE")
    sid = getattr(session, "id", None) or (session.get("id") if hasattr(session, "get") and callable(session.get) else None)
    if sid:
        # Assign a new dict so SQLAlchemy detects the JSONB change (in-place mutation may not be persisted).
        pending.extra_data = {**(pending.extra_data or {}), "last_identity_session_id": str(sid)}
        db.commit()
        print(f"[Auth] Stripe Identity session created and stored: id={sid} pending_id={pending.id} url={url[:70]}...")
    else:
        print(f"[Auth] Stripe Identity session created (no id to store): url={url[:70]}...")
    return PendingOwnerIdentitySessionResponse(client_secret=str(session.client_secret), url=url)


@router.post("/pending-owner/confirm-identity")
def pending_owner_confirm_identity(
    data: PendingOwnerConfirmIdentityRequest,
    db: Session = Depends(get_db),
    pending: PendingRegistration = Depends(get_pending_owner),
):
    """After Stripe redirect: verify session and mark pending as identity-verified."""
    if not _stripe_identity_configured():
        raise HTTPException(status_code=503, detail="Identity verification is not configured.")
    import stripe
    settings = get_settings()
    stripe.api_key = settings.stripe_secret_key
    session_id = (data.verification_session_id or "").strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="verification_session_id is required.")
    try:
        session = stripe.identity.VerificationSession.retrieve(session_id)
    except Exception as e:
        print(f"[Stripe Identity] RETRIEVE FAILED session_id={session_id} error={type(e).__name__}: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid verification session: {getattr(e, 'message', str(e))}")
    _log_stripe_session(session, "RETRIEVE")
    if session.metadata.get("pending_id") != str(pending.id):
        raise HTTPException(status_code=403, detail="This verification session does not match your signup.")
    # Success = Stripe status "verified"; any other status (requires_input, processing, canceled, etc.) = failure.
    if session.status != "verified":
        print(f"[Stripe Identity] VERIFICATION NOT COMPLETED status={session.status} session_id={session_id} (use status/last_error above to decide)")
        # Do NOT delete pending; user can retry via identity-retry endpoint.
        detail_msg = _stripe_session_failure_detail(session)
        last_error = getattr(session, "last_error", None) or (session.get("last_error") if hasattr(session, "get") and callable(session.get) else None)
        err_code = None
        if last_error:
            err_code = getattr(last_error, "code", None) if not isinstance(last_error, dict) else last_error.get("code")
        raise HTTPException(
            status_code=400,
            detail={
                "detail": detail_msg,
                "error_code": err_code,
                "session_id": session_id,
            },
        )
    print(f"[Stripe Identity] SUCCESS confirm-identity: marking pending_id={pending.id} as identity-verified")
    pending.extra_data = {
        **(pending.extra_data or {}),
        "identity_verified_at": datetime.now(timezone.utc).isoformat(),
        "stripe_verification_session_id": session_id,
    }
    db.commit()
    return {"status": "ok", "message": "Identity verified. Now sign the Master POA to complete signup."}


@router.get("/pending-owner/me", response_model=PendingOwnerMeResponse)
def pending_owner_me(pending: PendingRegistration = Depends(get_pending_owner)):
    """Return email and full_name for the pending owner (e.g. for POA sign modal)."""
    return PendingOwnerMeResponse(email=pending.email, full_name=pending.full_name)


@router.get("/pending-owner/latest-identity-session", response_model=PendingOwnerLatestIdentitySessionResponse)
def pending_owner_latest_identity_session(pending: PendingRegistration = Depends(get_pending_owner)):
    """Return the verification_session_id we stored when creating the identity session. Use when Stripe redirects without session_id in URL (e.g. some test or redirect flows)."""
    extra = pending.extra_data or {}
    sid = extra.get("last_identity_session_id")
    if not sid:
        raise HTTPException(status_code=404, detail="No identity session found for this signup. Start verification from the identity step.")
    return PendingOwnerLatestIdentitySessionResponse(verification_session_id=sid)


@router.post("/pending-owner/identity-retry", response_model=PendingOwnerIdentityRetryResponse)
def pending_owner_identity_retry(
    data: PendingOwnerIdentityRetryRequest,
    pending: PendingRegistration = Depends(get_pending_owner),
):
    """Return a fresh Stripe Identity URL for the same session so the user can retry verification (e.g. after requires_input)."""
    if not _stripe_identity_configured():
        raise HTTPException(status_code=503, detail="Identity verification is not configured.")
    import stripe
    settings = get_settings()
    stripe.api_key = settings.stripe_secret_key
    session_id = (data.verification_session_id or "").strip()
    if not session_id:
        raise HTTPException(status_code=400, detail="verification_session_id is required.")
    try:
        session = stripe.identity.VerificationSession.retrieve(session_id)
    except Exception as e:
        print(f"[Stripe Identity] RETRIEVE (retry) FAILED session_id={session_id} error={type(e).__name__}: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid or expired verification session: {getattr(e, 'message', str(e))}")
    _log_stripe_session(session, "RETRIEVE_RETRY")
    meta = getattr(session, "metadata", None) or (session.get("metadata") if hasattr(session, "get") and callable(session.get) else {})
    if meta.get("pending_id") != str(pending.id):
        raise HTTPException(status_code=403, detail="This verification session does not match your signup.")
    status = getattr(session, "status", None) or (session.get("status") if hasattr(session, "get") and callable(session.get) else None)
    if status == "canceled":
        raise HTTPException(
            status_code=400,
            detail="This verification link is no longer valid. Please start verification again.",
        )
    if status == "verified":
        return PendingOwnerIdentityRetryResponse(
            url=None,
            already_verified=True,
            message="Identity is already verified. You can continue to sign the Master POA.",
        )
    if status == "requires_input":
        _url = getattr(session, "url", None) or (session.get("url") if hasattr(session, "get") and callable(session.get) else None)
        url = str(_url).strip() if _url else None
        if not url or not url.startswith("http"):
            raise HTTPException(status_code=502, detail="Stripe did not return a retry URL. Please start verification again.")
        return PendingOwnerIdentityRetryResponse(url=url, already_verified=False)
    raise HTTPException(
        status_code=400,
        detail=f"Verification session is not ready for retry (status: {status}). Please complete the flow or start verification again.",
    )


@router.post("/pending-owner/complete-signup", response_model=Token)
def complete_owner_signup(
    data: CompleteOwnerSignupRequest,
    db: Session = Depends(get_db),
    pending: PendingRegistration = Depends(get_pending_owner),
):
    """After identity + POA: create User, link POA, delete pending, return real token. User is taken to dashboard."""
    extra = dict(pending.extra_data or {})
    # One-time backfill for pendings created before JSONB persistence fix: they have the token (so email was verified) and may have last_identity_session_id (so identity was completed) but keys were never saved.
    if not extra.get("email_verified_at"):
        extra["email_verified_at"] = datetime.now(timezone.utc).isoformat()
    if not extra.get("identity_verified_at") and extra.get("last_identity_session_id"):
        extra["identity_verified_at"] = datetime.now(timezone.utc).isoformat()
        extra["stripe_verification_session_id"] = extra["last_identity_session_id"]
    if extra != (pending.extra_data or {}):
        pending.extra_data = extra
        db.commit()
    has_email = bool(extra.get("email_verified_at"))
    has_identity = bool(extra.get("identity_verified_at"))
    if not has_email:
        print(f"[Auth] complete-signup 400: pending_id={pending.id} email={pending.email} missing email_verified_at in extra_data (keys={list(extra.keys())})")
        raise HTTPException(status_code=400, detail="Email not verified. Please complete the flow from the start.")
    if not has_identity:
        print(f"[Auth] complete-signup 400: pending_id={pending.id} missing identity_verified_at in extra_data (keys={list(extra.keys())})")
        raise HTTPException(status_code=400, detail="Identity not verified. Please complete identity verification first.")
    try:
        _validate_and_claim_owner_poa(
            db, data.poa_signature_id, pending.email,
            dropbox_incomplete_message="Please complete signing in Dropbox before completing signup.",
        )
    except HTTPException as e:
        print(f"[Auth] complete-signup 400: pending_id={pending.id} poa_signature_id={data.poa_signature_id} detail={e.detail}")
        raise
    from app.models.user import OwnerType
    owner_type_val = extra.get("owner_type")
    owner_type = OwnerType(owner_type_val) if owner_type_val in ("owner_of_record", "authorized_agent") else None
    user = User(
        email=pending.email,
        hashed_password=pending.hashed_password,
        role=UserRole.owner,
        full_name=pending.full_name,
        phone=pending.phone,
        state=pending.state,
        city=pending.city,
        country=pending.country,
        email_verified=True,
        email_verification_code=None,
        email_verification_expires_at=None,
        identity_verified_at=datetime.fromisoformat(extra["identity_verified_at"].replace("Z", "+00:00")) if isinstance(extra.get("identity_verified_at"), str) else datetime.now(timezone.utc),
        stripe_verification_session_id=extra.get("stripe_verification_session_id"),
        owner_type=owner_type,
    )
    db.add(user)
    db.flush()
    poa = db.query(OwnerPOASignature).filter(OwnerPOASignature.id == data.poa_signature_id).first()
    if poa:
        poa.used_by_user_id = user.id
        poa.used_at = datetime.now(timezone.utc)
    db.delete(pending)
    db.commit()
    db.refresh(user)
    send_owner_welcome_email(user.email, user.full_name)
    token = create_access_token(user.id, user.email, user.role)
    return Token(access_token=token, user=_user_to_response(user, db))


@router.post("/owner/link-poa")
def link_owner_poa(
    data: LinkPOARequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner),
):
    """Link a Master POA signature to the current owner. Requires identity verification first. Call after owner has signed the POA (e.g. from onboarding POA step)."""
    if not getattr(current_user, "identity_verified_at", None):
        raise HTTPException(
            status_code=403,
            detail="Complete identity verification before linking your Master POA. Go to Identity Verification.",
        )
    from app.models.user import OwnerType
    if getattr(current_user, "owner_type", None) == OwnerType.authorized_agent and not data.authorized_agent_certified:
        raise HTTPException(
            status_code=400,
            detail="As an Authorized Agent you must certify that you have authority under your management agreement to delegate documentation authority to DocuStay.",
        )
    _validate_and_claim_owner_poa(
        db, data.poa_signature_id, current_user.email,
        dropbox_incomplete_message="Please complete signing in Dropbox before linking your Master POA.",
    )
    poa = db.query(OwnerPOASignature).filter(OwnerPOASignature.id == data.poa_signature_id).first()
    if poa:
        poa.used_by_user_id = current_user.id
        poa.used_at = datetime.now(timezone.utc)
        if getattr(current_user, "owner_type", None) == OwnerType.authorized_agent:
            current_user.authorized_agent_certified_at = datetime.now(timezone.utc)
            create_log(
                db,
                CATEGORY_STATUS_CHANGE,
                "Authorized Agent certification",
                f"Authorized Agent certified authority under management agreement to delegate documentation authority to DocuStay (user_id={current_user.id}, email={current_user.email}).",
                actor_user_id=current_user.id,
                actor_email=current_user.email,
            )
        db.commit()
    return {"status": "ok", "message": "Master POA linked to your account."}


@router.post("/register/guest")
def register_guest(request: Request, data: GuestRegister, db: Session = Depends(get_db)):
    """Register a guest. When Mailgun is configured, stores pending and returns user_id for verification (same flow as owner); user is created on verify. Invitation code is optional and not validated until after verification."""
    code = (data.invitation_code or data.invitation_id or "").strip().upper()

    # Same email can have both owner and guest accounts (unique on email+role).
    existing_guest = db.query(User).filter(User.email == data.email, User.role == UserRole.guest).first()
    if existing_guest:
        raise HTTPException(status_code=400, detail="This email is already registered as a guest. Please log in on the Guest Login page.")

    if _mailgun_configured():
        # Store pending; user is created only after email verification (same UI flow as owner signup).
        # Do not require or validate invitation code here; we'll apply it at verify time.
        verification_code = _generate_verification_code()
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=VERIFICATION_CODE_EXPIRE_MINUTES)
        extra = {
            "invitation_code": code,
            "agreement_signature_id": data.agreement_signature_id,
            "permanent_address": data.permanent_address,
            "permanent_city": data.permanent_city,
            "permanent_state": data.permanent_state,
            "permanent_zip": data.permanent_zip,
            "guest_status_acknowledged": data.guest_status_acknowledged,
            "no_tenancy_acknowledged": data.no_tenancy_acknowledged,
            "vacate_acknowledged": data.vacate_acknowledged,
        }
        pending = PendingRegistration(
            email=data.email,
            hashed_password=get_password_hash(data.password),
            role=UserRole.guest,
            full_name=data.full_name or None,
            phone=data.phone or None,
            state=data.permanent_state or None,
            city=data.permanent_city or None,
            country="USA",
            verification_code=verification_code,
            expires_at=expires_at,
            extra_data=extra,
        )
        db.add(pending)
        db.commit()
        db.refresh(pending)
        sent = send_verification_email(data.email, verification_code)
        if not sent:
            db.delete(pending)
            db.commit()
            raise HTTPException(
                status_code=503,
                detail="We could not send the verification email. Please try again later.",
            )
        return RegisterPendingResponse(user_id=pending.id)

    # No verification: create user immediately (e.g. Mailgun not configured). Validate invite if provided.
    inv = None
    if code:
        inv = db.query(Invitation).filter(
            Invitation.invitation_code == code,
            Invitation.status.in_(["pending", "ongoing"]),
            Invitation.token_state != "BURNED",
        ).first()
        if not inv:
            create_log(
                db,
                CATEGORY_FAILED_ATTEMPT,
                "Guest register: invalid or expired invitation code",
                f"Guest registration attempted with invalid or expired invitation code: {code}.",
                property_id=None,
                actor_email=data.email,
                ip_address=request.client.host if request.client else None,
                user_agent=(request.headers.get("user-agent") or "").strip() or None,
                meta={"invitation_code_attempted": code},
            )
            db.commit()
            raise HTTPException(status_code=400, detail="Invalid or expired invitation code")

    sig = None
    if data.agreement_signature_id and data.agreement_signature_id > 0:
        sig = db.query(AgreementSignature).filter(AgreementSignature.id == data.agreement_signature_id).first()
        if sig and (sig.invitation_code or "").strip().upper() != code:
            sig = None
        if sig and (sig.guest_email or "").strip().lower() != (data.email or "").strip().lower():
            sig = None
        if sig and sig.used_by_user_id is not None:
            sig = None
        if sig and not (sig.acks_read and sig.acks_temporary and sig.acks_vacate and sig.acks_electronic):
            sig = None

    user = User(
        email=data.email,
        hashed_password=get_password_hash(data.password),
        role=UserRole.guest,
        full_name=data.full_name or None,
        phone=data.phone or None,
        state=data.permanent_state or None,
        city=data.permanent_city or None,
        country="USA",
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        msg = str(getattr(getattr(e, "orig", None), "args", [""])[0] if hasattr(e, "orig") and e.orig else str(e))
        if "email" in msg.lower() or "unique" in msg.lower():
            raise HTTPException(
                status_code=400,
                detail="This email is already registered. Please log in instead.",
            )
        raise
    db.refresh(user)
    permanent_home = f"{data.permanent_address}, {data.permanent_city}, {data.permanent_state} {data.permanent_zip}".strip()
    profile = GuestProfile(
        user_id=user.id,
        full_legal_name=data.full_name,
        permanent_home_address=permanent_home,
        gps_checkin_acknowledgment=False,
    )
    db.add(profile)
    db.commit()

    # Full accept path: code + valid signature -> create stay, mark inv accepted, token BURNED
    if code and inv and sig:
        duration = (inv.stay_end_date - inv.stay_start_date).days
        if duration <= 0:
            duration = 1
        stay = Stay(
            guest_id=user.id,
            owner_id=inv.owner_id,
            property_id=inv.property_id,
            invitation_id=inv.id,
            stay_start_date=inv.stay_start_date,
            stay_end_date=inv.stay_end_date,
            intended_stay_duration_days=duration,
            purpose_of_stay=inv.purpose_of_stay,
            relationship_to_owner=inv.relationship_to_owner,
            region_code=inv.region_code,
            dead_mans_switch_enabled=0,  # DMS turns on 2 min after guest checks in (see guest_check_in)
            dead_mans_switch_alert_email=getattr(inv, "dead_mans_switch_alert_email", 1) or 1,
            dead_mans_switch_alert_sms=getattr(inv, "dead_mans_switch_alert_sms", 0) or 0,
            dead_mans_switch_alert_dashboard=getattr(inv, "dead_mans_switch_alert_dashboard", 1) or 1,
            dead_mans_switch_alert_phone=getattr(inv, "dead_mans_switch_alert_phone", 0) or 0,
        )
        db.add(stay)
        inv.status = "accepted"
        prev_token_state = getattr(inv, "token_state", None) or "STAGED"
        inv.token_state = "BURNED"
        sig.used_by_user_id = user.id
        sig.used_at = datetime.now(timezone.utc)
        # Occupancy is set to OCCUPIED only when guest checks in (guest_check_in endpoint).
        db.commit()
        db.refresh(stay)
        # Shield Mode turns off when a new guest accepts an invitation.
        prop_for_shield = db.query(Property).filter(Property.id == inv.property_id).first()
        if prop_for_shield and getattr(prop_for_shield, "shield_mode_enabled", 0) == 1:
            prop_for_shield.shield_mode_enabled = 0
        ip = request.client.host if request.client else None
        ua = (request.headers.get("user-agent") or "").strip() or None
        create_log(
            db,
            CATEGORY_STATUS_CHANGE,
            "Invitation accepted (stay created)",
            f"Invite ID {code} token_state {prev_token_state} -> BURNED; guest registered, stay {stay.id} created for property {inv.property_id}. Occupancy will be set when guest checks in.",
            property_id=inv.property_id,
            stay_id=stay.id,
            invitation_id=inv.id,
            actor_user_id=user.id,
            actor_email=user.email,
            ip_address=ip,
            user_agent=ua,
            meta={"invitation_code": code, "token_state_previous": prev_token_state, "token_state_new": "BURNED", "signature_id": sig.id},
        )
        db.commit()
        prop = db.query(Property).filter(Property.id == inv.property_id).first()
        property_name = (prop.name if prop else None) or (f"{prop.city}, {prop.state}".strip(", ") if prop and (prop.city or prop.state) else None) or "the property"
        send_guest_welcome_email(
            user.email,
            user.full_name,
            property_name=property_name,
            stay_end_date=str(inv.stay_end_date),
        )
    elif code and inv:
        # Invite provided but not signed: add to pending so dashboard shows agreement modal
        pending = GuestPendingInvite(user_id=user.id, invitation_id=inv.id)
        db.add(pending)
        db.commit()

    # Send welcome email when guest did not get the stay-specific welcome (no invite or invite not yet accepted)
    if not (code and inv and sig):
        send_guest_signup_welcome_email(user.email, user.full_name)

    token = create_access_token(user.id, user.email, user.role)
    return Token(access_token=token, user=_user_to_response(user, db))


@router.post("/accept-invite")
def accept_invite(
    request: Request,
    data: AcceptInvite,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_guest),
):
    """Accept an invitation as an existing guest: create Stay and mark invitation accepted."""
    code = (data.invitation_code or "").strip().upper()
    if not code:
        raise HTTPException(status_code=400, detail="Invitation code is required")
    inv = db.query(Invitation).filter(
        Invitation.invitation_code == code,
        Invitation.status.in_(["pending", "ongoing"]),
        Invitation.token_state != "BURNED",
    ).first()
    if not inv:
        create_log(
            db,
            CATEGORY_FAILED_ATTEMPT,
            "Accept invite: invalid or expired invitation code",
            f"Accept-invite attempted with invalid or expired code: {code}.",
            property_id=None,
            actor_user_id=current_user.id,
            actor_email=current_user.email,
            ip_address=request.client.host if request.client else None,
            user_agent=(request.headers.get("user-agent") or "").strip() or None,
            meta={"invitation_code_attempted": code},
        )
        db.commit()
        raise HTTPException(status_code=400, detail="Invalid or expired invitation code")

    sig = db.query(AgreementSignature).filter(AgreementSignature.id == data.agreement_signature_id).first()
    if not sig:
        create_log(
            db,
            CATEGORY_FAILED_ATTEMPT,
            "Accept invite: missing or invalid signature",
            f"Accept-invite for {code} with invalid or missing agreement_signature_id.",
            property_id=inv.property_id,
            invitation_id=inv.id,
            actor_user_id=current_user.id,
            actor_email=current_user.email,
            ip_address=request.client.host if request.client else None,
            user_agent=(request.headers.get("user-agent") or "").strip() or None,
            meta={"invitation_code": code, "signature_id_attempted": data.agreement_signature_id},
        )
        db.commit()
        raise HTTPException(status_code=400, detail="Agreement must be signed before accepting invitation")
    if (sig.invitation_code or "").strip().upper() != code:
        create_log(
            db,
            CATEGORY_FAILED_ATTEMPT,
            "Accept invite: signature does not match invitation",
            f"Accept-invite for {code}: signature {sig.id} does not match invitation.",
            property_id=inv.property_id,
            invitation_id=inv.id,
            actor_user_id=current_user.id,
            actor_email=current_user.email,
            ip_address=request.client.host if request.client else None,
            user_agent=(request.headers.get("user-agent") or "").strip() or None,
            meta={"invitation_code": code, "signature_id": sig.id},
        )
        db.commit()
        raise HTTPException(status_code=400, detail="Agreement signature does not match this invitation")
    if (sig.guest_email or "").strip().lower() != (current_user.email or "").strip().lower():
        create_log(
            db,
            CATEGORY_FAILED_ATTEMPT,
            "Accept invite: signature email does not match",
            f"Accept-invite for {code}: signature email does not match current user.",
            property_id=inv.property_id,
            invitation_id=inv.id,
            actor_user_id=current_user.id,
            actor_email=current_user.email,
            ip_address=request.client.host if request.client else None,
            user_agent=(request.headers.get("user-agent") or "").strip() or None,
            meta={"invitation_code": code},
        )
        db.commit()
        raise HTTPException(status_code=400, detail="Agreement signature email does not match current user")
    if sig.used_by_user_id is not None and sig.used_by_user_id != current_user.id:
        create_log(
            db,
            CATEGORY_FAILED_ATTEMPT,
            "Accept invite: signature already used",
            f"Accept-invite for {code}: signature {sig.id} already used by another user.",
            property_id=inv.property_id,
            invitation_id=inv.id,
            actor_user_id=current_user.id,
            actor_email=current_user.email,
            ip_address=request.client.host if request.client else None,
            user_agent=(request.headers.get("user-agent") or "").strip() or None,
            meta={"invitation_code": code, "signature_id": sig.id},
        )
        db.commit()
        raise HTTPException(status_code=400, detail="Agreement signature has already been used")
    # If signature was sent to Dropbox, require the signed PDF before accepting (try fetch once)
    if getattr(sig, "dropbox_sign_request_id", None) and not getattr(sig, "signed_pdf_bytes", None):
        pdf_bytes = get_signed_pdf(sig.dropbox_sign_request_id)
        if pdf_bytes:
            sig.signed_pdf_bytes = pdf_bytes
            db.commit()
        else:
            create_log(
                db,
                CATEGORY_FAILED_ATTEMPT,
                "Accept invite: Dropbox signing not complete",
                f"Accept-invite for {code}: signature {sig.id} sent to Dropbox but not yet signed.",
                property_id=inv.property_id,
                invitation_id=inv.id,
                actor_user_id=current_user.id,
                actor_email=current_user.email,
                ip_address=request.client.host if request.client else None,
                user_agent=(request.headers.get("user-agent") or "").strip() or None,
                meta={"invitation_code": code, "signature_id": sig.id},
            )
            db.commit()
            raise HTTPException(
                status_code=400,
                detail="Please complete signing in Dropbox before accepting the invitation.",
            )
    if not (sig.acks_read and sig.acks_temporary and sig.acks_vacate and sig.acks_electronic):
        create_log(
            db,
            CATEGORY_FAILED_ATTEMPT,
            "Accept invite: not all acknowledgments accepted",
            f"Accept-invite for {code}: agreement acknowledgments incomplete.",
            property_id=inv.property_id,
            invitation_id=inv.id,
            actor_user_id=current_user.id,
            actor_email=current_user.email,
            ip_address=request.client.host if request.client else None,
            user_agent=(request.headers.get("user-agent") or "").strip() or None,
            meta={"invitation_code": code},
        )
        db.commit()
        raise HTTPException(status_code=400, detail="All agreement acknowledgments must be accepted")

    # Reject if this invite overlaps any existing stay for this guest
    existing_stays = db.query(Stay).filter(Stay.guest_id == current_user.id).all()
    for s in existing_stays:
        # Ranges overlap if start1 < end2 and end1 > start2
        if inv.stay_start_date < s.stay_end_date and inv.stay_end_date > s.stay_start_date:
            raise HTTPException(
                status_code=400,
                detail="This invitation overlaps with an existing stay. Only one stay can be accepted at a time.",
            )

    duration = (inv.stay_end_date - inv.stay_start_date).days
    if duration <= 0:
        duration = 1
    inv_dms = getattr(inv, "dead_mans_switch_enabled", 0) or 0
    # DMS is always off at stay creation; it turns on 2 min after guest checks in (see guest_check_in)
    stay = Stay(
        guest_id=current_user.id,
        owner_id=inv.owner_id,
        property_id=inv.property_id,
        invitation_id=inv.id,
        stay_start_date=inv.stay_start_date,
        stay_end_date=inv.stay_end_date,
        intended_stay_duration_days=duration,
        purpose_of_stay=inv.purpose_of_stay,
        relationship_to_owner=inv.relationship_to_owner,
        region_code=inv.region_code,
        dead_mans_switch_enabled=0,
        dead_mans_switch_alert_email=getattr(inv, "dead_mans_switch_alert_email", 1) or 1,
        dead_mans_switch_alert_sms=getattr(inv, "dead_mans_switch_alert_sms", 0) or 0,
        dead_mans_switch_alert_dashboard=getattr(inv, "dead_mans_switch_alert_dashboard", 1) or 1,
        dead_mans_switch_alert_phone=getattr(inv, "dead_mans_switch_alert_phone", 0) or 0,
    )
    db.add(stay)
    inv.status = "accepted"
    prev_token_state = getattr(inv, "token_state", None) or "STAGED"
    inv.token_state = "BURNED"
    # Occupancy is set to OCCUPIED only when guest checks in (guest_check_in endpoint).
    if sig.used_by_user_id is None:
        sig.used_by_user_id = current_user.id
        sig.used_at = datetime.now(timezone.utc)
    db.query(GuestPendingInvite).filter(
        GuestPendingInvite.user_id == current_user.id,
        GuestPendingInvite.invitation_id == inv.id,
    ).delete(synchronize_session="fetch")
    db.commit()
    db.refresh(stay)
    # Shield Mode turns off when a new guest accepts an invitation.
    _prop = db.query(Property).filter(Property.id == inv.property_id).first()
    if _prop and getattr(_prop, "shield_mode_enabled", 0) == 1:
        _prop.shield_mode_enabled = 0
    ip = request.client.host if request.client else None
    ua = (request.headers.get("user-agent") or "").strip() or None
    create_log(
        db,
        CATEGORY_STATUS_CHANGE,
        "Invitation accepted",
        f"Invite ID {code} token_state {prev_token_state} -> BURNED; stay {stay.id} created for property {inv.property_id}. Occupancy will be set when guest checks in.",
        property_id=inv.property_id,
        stay_id=stay.id,
        invitation_id=inv.id,
        actor_user_id=current_user.id,
        actor_email=current_user.email,
        ip_address=ip,
        user_agent=ua,
        meta={"invitation_code": code, "token_state_previous": prev_token_state, "token_state_new": "BURNED", "signature_id": sig.id},
    )
    db.commit()
    _prop = db.query(Property).filter(Property.id == inv.property_id).first()
    if _prop:
        try:
            profile = db.query(OwnerProfile).filter(OwnerProfile.id == _prop.owner_profile_id).first()
            if profile:
                sync_subscription_quantities(db, profile)
        except Exception:
            pass
    prop = db.query(Property).filter(Property.id == inv.property_id).first()
    property_name = (prop.name if prop else None) or (f"{prop.city}, {prop.state}".strip(", ") if prop and (prop.city or prop.state) else None) or "Property"
    send_guest_stay_added_email(
        current_user.email,
        current_user.full_name,
        property_name=property_name,
        stay_end_date=str(inv.stay_end_date),
    )
    # DMS is turned on 2 min after guest checks in (see guest_check_in), not at accept
    return {"status": "success", "message": "Invitation accepted"}
