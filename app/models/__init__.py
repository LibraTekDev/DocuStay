"""
All SQLAlchemy models. Schema is the source of truth for new DBs.
Base.metadata.create_all() creates every table; no migration scripts needed for fresh installs.
"""
from app.models.user import User
from app.models.owner import OwnerProfile, Property
from app.models.guest import GuestProfile
from app.models.stay import Stay
from app.models.region_rule import RegionRule
from app.models.invitation import Invitation
from app.models.guest_pending_invite import GuestPendingInvite
from app.models.agreement_signature import AgreementSignature
from app.models.reference_option import ReferenceOption
from app.models.audit_log import AuditLog
from app.models.owner_poa_signature import OwnerPOASignature
from app.models.pending_registration import PendingRegistration
from app.models.property_utility import PropertyUtilityProvider, PropertyAuthorityLetter

__all__ = [
    "User",
    "OwnerProfile",
    "Property",
    "GuestProfile",
    "Stay",
    "RegionRule",
    "Invitation",
    "GuestPendingInvite",
    "AgreementSignature",
    "ReferenceOption",
    "AuditLog",
    "OwnerPOASignature",
    "PendingRegistration",
    "PropertyUtilityProvider",
    "PropertyAuthorityLetter",
]
