"""Mark pending invitations that were not accepted in time as expired (status + token_state).
In test_mode: expire after 5 minutes. Otherwise: 12 hours."""
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.invitation import Invitation
from app.config import get_settings
from app.services.audit_log import create_log, CATEGORY_STATUS_CHANGE

logger = logging.getLogger("uvicorn.error")

PENDING_INVITATION_EXPIRE_HOURS = 12
PENDING_INVITATION_EXPIRE_MINUTES_TEST = 5


def get_invitation_expire_cutoff() -> datetime:
    """Return the cutoff datetime: pending invites with created_at < this are considered expired.
    In test_mode: 5 minutes. Otherwise: 12 hours."""
    now = datetime.now(timezone.utc)
    settings = get_settings()
    if getattr(settings, "test_mode", False):
        return now - timedelta(minutes=PENDING_INVITATION_EXPIRE_MINUTES_TEST)
    return now - timedelta(hours=PENDING_INVITATION_EXPIRE_HOURS)


def run_invitation_cleanup_job() -> None:
    """Mark pending invitations older than the configured window as expired: status='expired', token_state='EXPIRED'."""
    logger.info("Invitation cleanup job: started")
    db: Session = SessionLocal()
    try:
        threshold = get_invitation_expire_cutoff()
        invs = db.query(Invitation).filter(
            Invitation.status == "pending",
            Invitation.created_at < threshold,
        ).all()
        if invs:
            for inv in invs:
                inv.status = "expired"
                inv.token_state = "EXPIRED"
                db.add(inv)
                create_log(
                    db,
                    CATEGORY_STATUS_CHANGE,
                    "Invitation expired (not accepted in time)",
                    f"Background job marked invitation {inv.id} (code {getattr(inv, 'invitation_code', '')}) as expired; status=expired, token_state=EXPIRED.",
                    property_id=getattr(inv, "property_id", None),
                    invitation_id=inv.id,
                    meta={"invitation_id": inv.id, "invitation_code": getattr(inv, "invitation_code", None), "job": "invitation_cleanup"},
                )
            db.commit()
            logger.info("Invitation cleanup job: marked %d pending invitation(s) as expired (status=expired, token_state=EXPIRED).", len(invs))
        else:
            logger.info("Invitation cleanup job: no pending invitations past cutoff, done")
    except Exception as e:
        logger.exception("Invitation cleanup job: failed: %s", e)
    finally:
        db.close()
        logger.info("Invitation cleanup job: finished")
