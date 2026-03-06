"""Shared dependencies: DB session, current user."""
import logging
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError, OperationalError as SQLOperationalError
from app.config import get_settings
from app.database import get_db
from app.models.user import User, UserRole
from app.models.owner_poa_signature import OwnerPOASignature
from app.models.pending_registration import PendingRegistration
from app.services.auth import decode_token_with_error

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)


def get_current_user(
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> User:
    try:
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
    except HTTPException:
        raise
    except (SQLAlchemyError, SQLOperationalError) as e:
        raise HTTPException(status_code=503, detail="Service temporarily unavailable") from e
    except Exception as e:
        if _is_connection_error(e):
            raise HTTPException(status_code=503, detail="Service temporarily unavailable") from e
        raise HTTPException(status_code=401, detail="Authentication failed") from e


def _is_connection_error(e: Exception) -> bool:
    """True if the exception is a DB/network connection failure (e.g. DNS, unreachable host)."""
    msg = (getattr(e, "message", "") or str(e)).lower()
    return (
        "could not translate host" in msg
        or "name or service not known" in msg
        or "connection refused" in msg
        or "network is unreachable" in msg
        or "operationalerror" in type(e).__name__.lower()
    )


def get_pending_owner(
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> PendingRegistration:
    """Requires a pending-owner JWT (from verify-email for owner). Returns the PendingRegistration."""
    try:
        if not credentials:
            return_url = (get_settings().stripe_identity_return_url or "").strip() or "(not set)"
            logger.warning(
                "Pending-owner auth failed: no credentials. Session may have been lost after Stripe redirect. "
                "Ensure STRIPE_IDENTITY_RETURN_URL (or FRONTEND_BASE_URL) matches your app URL in .env. "
                "Current STRIPE_IDENTITY_RETURN_URL=%s",
                return_url,
            )
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
    except HTTPException:
        raise
    except (SQLAlchemyError, SQLOperationalError) as e:
        raise HTTPException(status_code=503, detail="Service temporarily unavailable") from e
    except Exception as e:
        if _is_connection_error(e):
            raise HTTPException(status_code=503, detail="Service temporarily unavailable") from e
        raise HTTPException(status_code=401, detail="Authentication failed") from e


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
    try:
        poa = db.query(OwnerPOASignature).filter(OwnerPOASignature.used_by_user_id == current_user.id).first()
        poa_waived = bool(getattr(current_user, "poa_waived_at", None))
        if not poa and not poa_waived:
            raise HTTPException(
                status_code=403,
                detail="Sign and link the Master POA to complete onboarding. You cannot add properties or access the dashboard until the Master POA is linked.",
            )
        return current_user
    except HTTPException:
        raise
    except (SQLAlchemyError, SQLOperationalError) as e:
        raise HTTPException(status_code=503, detail="Service temporarily unavailable") from e
    except Exception as e:
        if _is_connection_error(e):
            raise HTTPException(status_code=503, detail="Service temporarily unavailable") from e
        raise HTTPException(status_code=503, detail="Service temporarily unavailable") from e


def require_guest(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != UserRole.guest:
        raise HTTPException(status_code=403, detail="Guest role required")
    return current_user


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Only users with role=admin can access admin routes. Returns 403 for non-admin."""
    if current_user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user
