"""Invitation from owner to guest; links to Stay when guest accepts."""
from sqlalchemy import Column, Integer, String, Date, ForeignKey, Enum as SQLEnum, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
from app.models.guest import PurposeOfStay, RelationshipToOwner


class Invitation(Base):
    __tablename__ = "invitations"

    id = Column(Integer, primary_key=True, index=True)
    invitation_code = Column(String(64), unique=True, nullable=False, index=True)

    owner_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    property_id = Column(Integer, ForeignKey("properties.id"), nullable=False)
    guest_name = Column(String(255), nullable=True)  # name owner entered when creating invite
    guest_email = Column(String(255), nullable=True)

    stay_start_date = Column(Date, nullable=False)
    stay_end_date = Column(Date, nullable=False)
    purpose_of_stay = Column(SQLEnum(PurposeOfStay), nullable=False)
    relationship_to_owner = Column(SQLEnum(RelationshipToOwner), nullable=False)
    region_code = Column(String(20), nullable=False)

    status = Column(String(20), nullable=False, default="pending")  # pending, ongoing (e.g. CSV occupied), accepted, cancelled

    # Invite-as-token state (Invite ID = invitation_code; used as Stay ID for display)
    # STAGED=created, BURNED=guest accepted+signed MoA, EXPIRED=stay ended/checked out, REVOKED=cancelled by owner/guest
    token_state = Column(String(20), nullable=False, default="STAGED", server_default="STAGED")

    # Dead Man's Switch: auto-protect when stay end passes without owner response
    dead_mans_switch_enabled = Column(Integer, nullable=False, default=0)  # 0 | 1 (SQLite-friendly)
    dead_mans_switch_alert_email = Column(Integer, nullable=False, default=1)
    dead_mans_switch_alert_sms = Column(Integer, nullable=False, default=0)
    dead_mans_switch_alert_dashboard = Column(Integer, nullable=False, default=1)
    dead_mans_switch_alert_phone = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    owner = relationship("User", backref="invitations_sent")
    property_ref = relationship("Property", backref="invitations")
