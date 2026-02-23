"""Shared dependencies: DB session, current user."""
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.user import User, UserRole
from app.models.owner_poa_signature import OwnerPOASignature
from app.models.pending_registration import PendingRegistration
from app.services.auth import decode_token_with_error

security = HTTPBearer(auto_error=False)


def get_current_user(
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> User:
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    token_str = (credentials.credentials or "").strip()
    payload, _ = decode_token_with_error(token_str)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    if payload.get("sub") == "pending":
        raise HTTPException(status_code=401, detail="Use the pending-owner flow to complete signup.")
    try:
        user_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid token")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def get_pending_owner(
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> PendingRegistration:
    """Requires a pending-owner JWT (from verify-email for owner). Returns the PendingRegistration."""
    if not credentials:
        raise HTTPException(status_code=401, detail="Not authenticated")
    token_str = (credentials.credentials or "").strip()
    payload, _ = decode_token_with_error(token_str)
    if not payload or payload.get("sub") != "pending" or "pending_id" not in payload:
        raise HTTPException(status_code=401, detail="Invalid or expired signup session. Please start over from registration.")
    try:
        pending_id = int(payload.get("pending_id"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Invalid token")
    pending = db.query(PendingRegistration).filter(PendingRegistration.id == pending_id).first()
    if not pending or pending.role != UserRole.owner:
        raise HTTPException(status_code=401, detail="Signup session not found. Please start over from registration.")
    return pending


def require_owner(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != UserRole.owner:
        raise HTTPException(status_code=403, detail="Owner role required")
    return current_user


def require_owner_identity_verified(
    current_user: User = Depends(require_owner),
) -> User:
    """Owner must have completed Stripe Identity verification (before POA and dashboard)."""
    if not getattr(current_user, "identity_verified_at", None):
        raise HTTPException(
            status_code=403,
            detail="Complete identity verification to continue. You cannot sign the Master POA or access the dashboard until your identity is verified.",
        )
    return current_user


def require_owner_onboarding_complete(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_owner_identity_verified),
) -> User:
    """Owner must have completed identity verification and linked Master POA (required for dashboard and properties). Legacy owners may have poa_waived_at instead."""
    poa = db.query(OwnerPOASignature).filter(OwnerPOASignature.used_by_user_id == current_user.id).first()
    poa_waived = bool(getattr(current_user, "poa_waived_at", None))
    if not poa and not poa_waived:
        raise HTTPException(
            status_code=403,
            detail="Sign and link the Master POA to complete onboarding. You cannot add properties or access the dashboard until the Master POA is linked.",
        )
    return current_user


def require_guest(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != UserRole.guest:
        raise HTTPException(status_code=403, detail="Guest role required")
    return current_user
