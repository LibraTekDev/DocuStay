"""Tenant assignment: links a tenant user to a unit."""
from sqlalchemy import Column, Integer, Date, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class TenantAssignment(Base):
    __tablename__ = "tenant_assignments"

    id = Column(Integer, primary_key=True, index=True)
    unit_id = Column(Integer, ForeignKey("units.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    invited_by_user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=True)  # null = ongoing
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    unit = relationship("Unit", backref="tenant_assignments")
    user = relationship("User", foreign_keys=[user_id])
    invited_by = relationship("User", foreign_keys=[invited_by_user_id])
