"""Agreement document generation for invitation flows."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.models.invitation import Invitation
from app.models.owner import Property
from app.models.user import User


def fill_guest_signature_in_content(content: str, guest_name: str, signed_date: str) -> str:
    """Replace the blank guest signature line with the signer's name and date."""
    # Patterns for guest line (Licensee, Occupant, Guest) with blank underscores and date
    patterns = [
        (r"Licensee:\s*_{10,}\s+Date:\s*_{10,}", f"Licensee: {guest_name}   Date: {signed_date}"),
        (r"Occupant:\s*_{10,}\s+Date:\s*_{10,}", f"Occupant: {guest_name}   Date: {signed_date}"),
        (r"Guest:\s*_{10,}\s+Date:\s*_{10,}", f"Guest: {guest_name}   Date: {signed_date}"),
    ]
    result = content
    for pattern, replacement in patterns:
        result = re.sub(pattern, replacement, result, count=1)
    return result


@dataclass(frozen=True)
class AgreementDoc:
    document_id: str
    region_code: str
    title: str
    content: str
    document_hash: str
    property_address: str | None
    stay_start_date: str | None
    stay_end_date: str | None
    host_name: str | None


def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _format_address(prop: Property | None) -> str | None:
    if not prop:
        return None
    parts = [prop.street, prop.city, prop.state]
    if prop.zip_code:
        parts.append(prop.zip_code)
    return ", ".join([p for p in parts if p])


def _normalize_region(region_code: str) -> str:
    rc = (region_code or "").strip().upper()
    if rc in {"NY", "NYC"}:
        return "NYC"
    if rc in {"FL", "CA", "TX", "WA"}:
        return rc
    return rc or "US"


def build_invitation_agreement(
    db: Session,
    invitation_code: str,
    guest_full_name: str | None = None,
) -> AgreementDoc | None:
    code = (invitation_code or "").strip().upper()
    if not code:
        return None

    inv = db.query(Invitation).filter(Invitation.invitation_code == code, Invitation.status.in_(["pending", "ongoing"])).first()
    if not inv:
        return None

    prop = db.query(Property).filter(Property.id == inv.property_id).first()
    owner = db.query(User).filter(User.id == inv.owner_id).first()

    region = _normalize_region(inv.region_code or (prop.region_code if prop else ""))
    host_name = (owner.full_name if owner else None) or (owner.email if owner else None)
    property_address = _format_address(prop)

    # Keep the canonical agreement text stable for hashing/verification. We record
    # the signer's identity separately in the signature record.
    guest_name = "[Guest Name]"
    owner_name = (host_name or "").strip() or "[Owner Name]"
    today = date.today().strftime("%B %d, %Y")
    checkin = str(inv.stay_start_date) if inv.stay_start_date else "[Check-in Date]"
    checkout = str(inv.stay_end_date) if inv.stay_end_date else "[Check-out Date]"

    # Core templates (plain text) — intentionally concise, but aligned to the user's provided drafts.
    if region == "NYC":
        title = "REVOCABLE LICENSE FOR TEMPORARY OCCUPANCY (NEW YORK CITY)"
        content = f"""TITLE: REVOCABLE LICENSE FOR TEMPORARY OCCUPANCY (NYC)

1. PARTIES & PROPERTY
This Revocable License ("Agreement") is entered into on {today} between {owner_name} ("Licensor") and {guest_name} ("Licensee") for the temporary use of the property located at: {property_address or "[Full Property Address]"}.

2. NATURE OF THE RELATIONSHIP (CRITICAL NYC CLAUSE)
This Agreement is a License, not a Lease. Licensee acknowledges that:
- No landlord-tenant relationship is created under NY RPAPL § 711.
- Licensor retains legal possession, custody, and control of the Premises at all times.
- Licensee receives a personal, non-assignable privilege to enter the Premises for a temporary stay only.

3. NON-EXCLUSIVE POSSESSION
Licensee shall not have exclusive possession of any portion of the Premises. Licensor (and Licensor's agents) may enter any area used by Licensee at any time, for any reason, without notice. This is a shared-occupancy arrangement.

4. TIME-BOUND LIMIT (NYC 30-DAY GUARDRAIL)
This license begins on {checkin} and terminates automatically on {checkout}. Under no circumstances shall this license exceed 29 consecutive days. Licensee agrees to vacate and remove all personal belongings by the termination date/time set by Licensor.

5. REVOCABILITY
This license is revocable at will by the Licensor. Upon notice of revocation (via DocuStay notification or SMS), Licensee must vacate within the stated timeframe. Remaining after revocation or expiration may constitute trespass under NY law.

6. UTILITY, MAIL, AND RESIDENCY RESTRICTIONS
- Licensee shall not establish or modify utility accounts at this address.
- Licensee shall not use the Premises for receipt of personal mail, voter registration, or government records.
- Licensee shall not claim the Premises as a residence or domicile.

SIGNATURES (ELECTRONIC)
Licensor: ________________________   Date: __________
Licensee: ________________________   Date: __________
"""
    elif region == "FL":
        title = "VERIFIED COMPLAINT AND GUEST AUTHORIZATION (FLORIDA F.S. § 82.036)"
        content = f"""TITLE: VERIFIED COMPLAINT AND GUEST AUTHORIZATION (PURSUANT TO F.S. § 82.036)

1. IDENTIFICATION OF PARTIES
This agreement is between {owner_name} ("Owner") and {guest_name} ("Occupant") regarding the dwelling located at: {property_address or "[Full Address]"}.

2. OCCUPANT STATUS (TRANSIENT GUEST; NOT A TENANT)
Occupant affirms they are a transient guest and NOT a tenant, and that no written or oral lease agreement has been authorized by the Owner.

3. STATUTORY ACKNOWLEDGMENTS (UNDER PENALTY OF PERJURY)
Occupant declares:
- I am not an immediate family member of the Owner.
- I am not a co-owner and am not listed on title.
- There is no pending litigation regarding this property between myself and the Owner.

4. AUTHORIZATION OF REMOVAL
Occupant's authorization to remain expires on {checkout}. If Occupant remains past this time, they become an unauthorized person under Florida law and authorize the County Sheriff to remove them upon Owner's verified complaint as allowed by F.S. § 82.036.

5. UTILITY FRAUD WAIVER & DAMAGES NOTICE
Occupant has no authority to establish utilities for this property. Any attempt may constitute a criminal offense under Florida law. Intentional property damage may increase criminal exposure.

SIGNATURES (ELECTRONIC; UNDER PENALTY OF PERJURY)
Owner: ________________________   Date: __________
Occupant: _____________________   Date: __________
"""
    elif region == "CA":
        title = "TRANSIENT LODGER & TEMPORARY OCCUPANCY AGREEMENT (CALIFORNIA)"
        content = f"""TITLE: TRANSIENT LODGER & TEMPORARY OCCUPANCY AGREEMENT (CALIFORNIA)

1. PROPERTY & PARTIES
This Agreement is made on {today} between {owner_name} ("Owner") and {guest_name} ("Lodger/Guest") for the property at: {property_address or "[Full Address]"}.

2. TRANSIENT OCCUPANCY STATUS (CA CIV. CODE § 1940.1)
This occupancy is transient in nature. Guest is not hiring the dwelling as a permanent resident and maintains a primary residence elsewhere.

3. OWNER RIGHT OF ACCESS (NO EXCLUSIVE POSSESSION)
Owner retains unrestricted access to and control of the dwelling. Guest does not have exclusive possession of any part of the premises.

4. STAY DURATION & TERMINATION
This license begins on {checkin} and ends on {checkout}. Guest agrees to vacate on or before the 29th day of occupancy to preserve transient status, unless otherwise required by law.

5. SINGLE LODGER PROVISION (IF OWNER-OCCUPIED)
If Owner resides on-site, Guest may be treated as a single lodger under CA Civ. Code § 1946.5 and may be subject to removal as a trespasser after proper notice.

6. PROHIBITED ACTIONS
Guest shall not receive mail/packages at the address, register a vehicle or business here, or activate/modify utilities.

SIGNATURES (ELECTRONIC)
Owner: ________________________   Date: __________
Guest: ________________________   Date: __________
"""
    elif region == "TX":
        title = "TRANSIENT GUEST AGREEMENT & NO-TENANCY WAIVER (TEXAS)"
        content = f"""TITLE: TEXAS TRANSIENT GUEST AGREEMENT & NO-TENANCY WAIVER

1. STATUS OF OCCUPANCY
Guest acknowledges they are staying at {property_address or "[Property Address]"} as a transient guest only. This arrangement is NOT a residential lease under Texas Property Code Chapter 92.

2. NO CONSIDERATION (THE “CHORES” TRAP)
Guest agrees that performing chores, buying groceries, or contributing to utilities does not constitute rent and does not create a landlord-tenant relationship. Any such actions are voluntary gifts.

3. PROHIBITION OF RESIDENCY SIGNS
Guest agrees NOT to:
- Receive personal mail/packages at this address.
- Use this address for any government ID, voter registration, or business registration.
- Move in large furniture or permanent appliances.

4. RIGHT TO VACATE
Owner may request Guest to leave at any time for any reason. Guest agrees to vacate within 24 hours of receiving a DocuStay notice. Occupancy after {checkout} is unauthorized.

SIGNATURES (ELECTRONIC)
Owner: ________________________   Date: __________
Guest: ________________________   Date: __________
"""
    else:  # WA or fallback
        title = "DECLARATION OF UNAUTHORIZED OCCUPANCY (WASHINGTON RCW 9A.52.105)"
        content = f"""TITLE: DECLARATION OF UNAUTHORIZED OCCUPANCY (RCW 9A.52.105) — WASHINGTON

1. DECLARATION OF OWNERSHIP
{owner_name} declares under penalty of perjury that they are the record owner or authorized agent of the property at: {property_address or "[Address]"}.

2. UNAUTHORIZED STATUS
{guest_name} entered the property as a temporary guest only. They are not a tenant and have no valid rental agreement for an indefinite period.

3. DEMAND TO VACATE
Guest must vacate by {checkout}. Remaining past the authorized date/time is unauthorized occupancy.

4. INDEMNITY
Owner agrees to indemnify and hold harmless any law enforcement agency that relies on this sworn declaration as permitted by law.

SIGNATURES (ELECTRONIC)
Owner: ________________________   Date: __________
Guest: ________________________   Date: __________
"""

    document_id = f"DSA-{code}-{region}"
    doc_hash = _sha256_hex(content)

    return AgreementDoc(
        document_id=document_id,
        region_code=region,
        title=title,
        content=content,
        document_hash=doc_hash,
        property_address=property_address,
        stay_start_date=str(inv.stay_start_date) if inv.stay_start_date else None,
        stay_end_date=str(inv.stay_end_date) if inv.stay_end_date else None,
        host_name=host_name,
    )


# --- Master Power of Attorney (owner onboarding) ---

POA_DOCUMENT_ID = "DSA-Master-POA"
POA_TITLE = "Master Power of Attorney (POA)"

POA_CONTENT = """Master Power of Attorney (POA)

Overview
The Master POA is a one-time, account-level legal document signed during initial onboarding that establishes DocuStay as the property owner's legal representative for all property protection activities.

1. Who Signs What?
Property Owners ONLY sign the Master POA
Guests DO NOT sign the Master POA
Guests sign a completely different document called the "Guest Agreement" (covered separately)

2. When Is It Signed?
During initial account registration (onboarding)
Before any properties can be added to the system
This is a one-time signature - it covers ALL properties the owner adds, now and in the future

3. What Does It Actually Do?
The Master POA legally designates DocuStay as the owner's "Authorized Agent" to:
- Issue utility authorization tokens (USAT)
- Communicate with utility companies on owner's behalf
- Generate legal evidence packages
- Maintain forensic audit trails
- Act as the "official record keeper" for property status

SIGNATURE (ELECTRONIC)
Owner: ________________________   Date: __________
"""


def build_owner_poa_document() -> tuple[str, str, str, str]:
    """Return (document_id, title, content, document_hash) for the Master POA."""
    content = POA_CONTENT.strip()
    doc_hash = _sha256_hex(content)
    return (POA_DOCUMENT_ID, POA_TITLE, content, doc_hash)


def poa_content_with_signature(content: str, signer_name: str, signed_date: str) -> str:
    """Append signature line to POA content for generating a signed PDF."""
    return content.rstrip() + f"\n\nSigned by {signer_name} on {signed_date}"


def _escape_for_reportlab(s: str) -> str:
    """Escape text for ReportLab Paragraph (XML-like markup)."""
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def agreement_content_to_pdf(title: str, content: str) -> bytes:
    """Generate a PDF from agreement title and content using reportlab. Content wraps to page width and is justified."""
    from io import BytesIO
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.enums import TA_JUSTIFY
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer

    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )
    styles = getSampleStyleSheet()
    title_style = styles["Title"]
    body_style = styles["Normal"].clone("JustifiedBody", alignment=TA_JUSTIFY, spaceAfter=6)

    story = [Paragraph(_escape_for_reportlab(title.replace("\n", " ")), title_style), Spacer(1, 0.2 * inch)]

    for line in content.splitlines():
        line = line.strip()
        if line:
            story.append(Paragraph(_escape_for_reportlab(line), body_style))
        else:
            story.append(Spacer(1, 0.12 * inch))

    doc.build(story)
    return buf.getvalue()
