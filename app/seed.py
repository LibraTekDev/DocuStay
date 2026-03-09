"""Module D: Seed region rules (NYC, FL, CA, TX), jurisdiction SOT, and optional admin user."""
import os
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from app.models.region_rule import RegionRule, StayClassification, RiskLevel
from app.models.jurisdiction import Jurisdiction, JurisdictionStatute, JurisdictionZipMapping


def seed_region_rules(db: Session) -> None:
    if db.query(RegionRule).count() > 0:
        return
    rules = [
        RegionRule(
            region_code="NYC",
            max_stay_days=29,
            stay_classification_label=StayClassification.guest,
            risk_level=RiskLevel.high,
            statute_reference="NYC Admin Code § 26-521",
            plain_english_explanation="Occupying a dwelling for 30 consecutive days creates tenancy rights. Max 29 days.",
            allow_extended_if_owner_occupied=False,
        ),
        RegionRule(
            region_code="FL",
            max_stay_days=30,
            stay_classification_label=StayClassification.guest,
            risk_level=RiskLevel.medium,
            statute_reference="FL Statute § 82.036 (HB 621)",
            plain_english_explanation="Sheriff may remove unauthorized person with signed affidavit; no lease.",
            allow_extended_if_owner_occupied=False,
        ),
        RegionRule(
            region_code="CA",
            max_stay_days=29,
            stay_classification_label=StayClassification.guest,
            risk_level=RiskLevel.medium,
            statute_reference="CA Civil Code § 1940.1, AB 1482",
            plain_english_explanation="Transient occupancy; 30+ days creates tenancy. Lodger if owner lives in.",
            allow_extended_if_owner_occupied=True,
        ),
        RegionRule(
            region_code="TX",
            max_stay_days=29,
            stay_classification_label=StayClassification.guest,
            risk_level=RiskLevel.medium,
            statute_reference="Texas Property Code § 92.001, Penal Code § 30.05",
            plain_english_explanation="Transient housing exempt from landlord-tenant; criminal trespass after notice.",
            allow_extended_if_owner_occupied=False,
        ),
        RegionRule(
            region_code="WA",
            max_stay_days=29,
            stay_classification_label=StayClassification.guest,
            risk_level=RiskLevel.medium,
            statute_reference="RCW 9A.52.105",
            plain_english_explanation="Tenancy is fact-specific; owner declaration can assist police removal in defined cases.",
            allow_extended_if_owner_occupied=False,
        ),
    ]
    for r in rules:
        db.add(r)
    db.commit()


def seed_jurisdiction_sot(db: Session) -> None:
    """Seed jurisdiction SOT tables: jurisdictions, statutes, zip mapping. Idempotent."""
    if db.query(Jurisdiction).count() > 0:
        return

    jurisdictions = [
        Jurisdiction(
            region_code="NYC",
            state_code="NY",
            name="New York",
            max_stay_days=29,
            tenancy_threshold_days=30,
            warning_days=5,
            agreement_type="REVOCABLE_LICENSE",
            removal_guest_text="Immediate with license termination",
            removal_tenant_text="30-60 day court process",
            stay_classification_label=StayClassification.guest,
            risk_level=RiskLevel.high,
            allow_extended_if_owner_occupied=False,
        ),
        Jurisdiction(
            region_code="FL",
            state_code="FL",
            name="Florida",
            max_stay_days=29,
            tenancy_threshold_days=30,
            warning_days=5,
            agreement_type="HB621_DECLARATION",
            removal_guest_text="Immediate Sheriff removal with HB621 declaration",
            removal_tenant_text="Standard eviction process",
            stay_classification_label=StayClassification.guest,
            risk_level=RiskLevel.medium,
            allow_extended_if_owner_occupied=False,
        ),
        Jurisdiction(
            region_code="CA",
            state_code="CA",
            name="California",
            max_stay_days=29,
            tenancy_threshold_days=30,
            warning_days=5,
            agreement_type="TRANSIENT_LODGER",
            removal_guest_text="Police removal as trespasser (if single lodger)",
            removal_tenant_text="30-60 day process",
            stay_classification_label=StayClassification.guest,
            risk_level=RiskLevel.medium,
            allow_extended_if_owner_occupied=True,
        ),
        Jurisdiction(
            region_code="TX",
            state_code="TX",
            name="Texas",
            max_stay_days=29,
            tenancy_threshold_days=7,
            warning_days=3,
            agreement_type="TRANSIENT_GUEST",
            removal_guest_text="24-hour notice",
            removal_tenant_text="3-day notice + JP Court",
            stay_classification_label=StayClassification.guest,
            risk_level=RiskLevel.medium,
            allow_extended_if_owner_occupied=False,
        ),
        Jurisdiction(
            region_code="WA",
            state_code="WA",
            name="Washington",
            max_stay_days=29,
            tenancy_threshold_days=30,
            warning_days=5,
            agreement_type="ANTI_SQUATTER_DECLARATION",
            removal_guest_text="Police removal with RCW declaration",
            removal_tenant_text="20-day notice + court",
            stay_classification_label=StayClassification.guest,
            risk_level=RiskLevel.medium,
            allow_extended_if_owner_occupied=False,
        ),
    ]
    for j in jurisdictions:
        db.add(j)
    db.flush()

    statutes = [
        ("NYC", "NYC Admin Code § 26-521", "Occupying a dwelling for 30 consecutive days creates tenancy rights. Max 29 days.", 0),
        ("NYC", "RPAPL § 711", "License vs tenancy; no landlord-tenant relationship under this section.", 1),
        ("FL", "FL Statute § 82.036 (HB 621)", "Sheriff may remove unauthorized person with signed affidavit; no lease.", 0),
        ("FL", "F.S. § 82.036", "Verified complaint and guest authorization.", 1),
        ("CA", "CA Civil Code § 1940.1, AB 1482", "Transient occupancy; 30+ days creates tenancy.", 0),
        ("CA", "CA Civil Code § 1946.5", "Single lodger; owner-occupied; removal as trespasser after notice.", 1),
        ("TX", "Texas Property Code § 92.001, Penal Code § 30.05", "Transient housing exempt from landlord-tenant; criminal trespass after notice.", 0),
        ("TX", "Property Code Chapter 92", "Transient guest; no tenancy.", 1),
        ("WA", "RCW 9A.52.105", "Tenancy is fact-specific; owner declaration can assist police removal in defined cases.", 0),
    ]
    for region_code, citation, plain_english, sort_order in statutes:
        db.add(
            JurisdictionStatute(
                region_code=region_code,
                citation=citation,
                plain_english=plain_english,
                use_in_authority_package=True,
                sort_order=sort_order,
            )
        )
    db.flush()

    # Zip -> region_code. Representative 5-digit zips per region (NYC, FL, CA, TX, WA).
    zip_mappings = []
    for zip_code in ("10001", "10002", "10003", "11201", "11238", "10451"):  # NYC
        zip_mappings.append((zip_code, "NYC"))
    for zip_code in ("33101", "33139", "32034", "33001", "33401", "32801"):  # FL
        zip_mappings.append((zip_code, "FL"))
    for zip_code in ("90210", "94102", "90001", "92101", "95814", "95110"):  # CA
        zip_mappings.append((zip_code, "CA"))
    for zip_code in ("77001", "75201", "78701", "78205", "76102", "79901"):  # TX
        zip_mappings.append((zip_code, "TX"))
    for zip_code in ("98101", "98102", "98104", "98122", "99201", "98402"):  # WA
        zip_mappings.append((zip_code, "WA"))
    for zip_code, region_code in zip_mappings:
        db.add(JurisdictionZipMapping(zip_code=zip_code, region_code=region_code))

    db.commit()


def seed_admin_user(db: Session) -> None:
    """Create default admin user for fresh installs (admin@docustay.com). Uses ADMIN_EMAIL/ADMIN_PASSWORD if set."""
    from app.models.user import User, UserRole
    from app.services.auth import get_password_hash

    admin_email = (os.environ.get("ADMIN_EMAIL") or "admin@docustay.com").strip().lower()
    admin_password = os.environ.get("ADMIN_PASSWORD") or "DreamsOfDreams89"
    admin_full_name = os.environ.get("ADMIN_FULL_NAME", "Admin").strip() or "Admin"

    existing = db.query(User).filter(User.email == admin_email, User.role == UserRole.admin).first()
    hashed = get_password_hash(admin_password)
    now = datetime.now(timezone.utc)

    if existing:
        existing.hashed_password = hashed
        existing.email_verified = True
        existing.identity_verified_at = now
        existing.poa_waived_at = now
        db.commit()
        return

    user = User(
        email=admin_email,
        hashed_password=hashed,
        role=UserRole.admin,
        full_name=admin_full_name,
        email_verified=True,
        identity_verified_at=now,
        poa_waived_at=now,
    )
    db.add(user)
    db.commit()
