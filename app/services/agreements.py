"""Agreement document generation for invitation flows. Uses JurisdictionInfo from DB SOT when available."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.invitation import Invitation
from app.models.owner import Property
from app.models.unit import Unit
from app.models.user import User
from app.services.jurisdiction_sot import JurisdictionInfo, get_jurisdiction_for_property


def fill_guest_signature_in_content(
    content: str, guest_name: str, signed_date: str, ip_address: str | None = None
) -> str:
    """Replace the blank guest or tenant signature line with the signer's name, date, and optionally IP."""
    result = content
    # New template (guidance): **Guest Signature:** ___ or **Tenant Signature:** ___ and **Date:** ___ on same or next line
    result = re.sub(r"\*\*Guest Signature:\*\*\s*_{10,}", f"**Guest Signature:** {guest_name}", result, count=1)
    result = re.sub(r"\*\*Tenant Signature:\*\*\s*_{10,}", f"**Tenant Signature:** {guest_name}", result, count=1)
    result = re.sub(r"\*\*Date:\*\*\s*_{10,}", f"**Date:** {signed_date}", result, count=1)
    # Legacy patterns (Signed:/Guest:/ etc.)
    legacy = [
        (r"Guest Signature:\s*_{10,}\s+Date:\s*_{10,}", f"Guest Signature: {guest_name}   Date: {signed_date}"),
        (r"Signed:\s*_{10,}\s+Date:\s*_{10,}", f"Signed: {guest_name}   Date: {signed_date}"),
        (r"Licensee:\s*_{10,}\s+Date:\s*_{10,}", f"Licensee: {guest_name}   Date: {signed_date}"),
        (r"Occupant:\s*_{10,}\s+Date:\s*_{10,}", f"Occupant: {guest_name}   Date: {signed_date}"),
        (r"Guest:\s*_{10,}\s+Date:\s*_{10,}", f"Guest: {guest_name}   Date: {signed_date}"),
    ]
    for pattern, replacement in legacy:
        result = re.sub(pattern, replacement, result, count=1)
    if ip_address is not None and "IP Address:" in result:
        result = re.sub(r"IP Address:\s*_{10,}", f"IP Address: {ip_address}", result, count=1)
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
        return "NY"
    return rc or "US"


# --- Jurisdiction-aware Guest Acknowledgment (guidance: Guest Acknowledgment and Revocable License to Occupy) ---

GUEST_ACK_TITLE = "Guest Acknowledgment and Revocable License to Occupy"

TENANT_ACK_TITLE = "Tenant Invitation Acceptance"

# Tenant invitation: primary resident acceptance. No guest stay language.
def _build_tenant_invitation_acceptance(
    property_address: str | None,
    tenant_name: str,
    unit_info: str,
) -> str:
    return f"""**Tenant Invitation Acceptance**

DocuStay is a documentation platform for property status and guest authorizations. This document confirms your acceptance of an invitation to be the primary resident of a unit.

**1. Acceptance of Invitation**
You accept this invitation to access and occupy the unit at the property as the assigned tenant/resident. You understand you are the primary resident of this unit.

**2. Platform Use**
You agree to use the DocuStay platform in accordance with the Terms of Service and Privacy Policy. You may use the platform to manage your own guest authorizations for temporary visitors to your unit.

**3. Documentation Only**
This acceptance documents your status as the tenant/resident of the unit. DocuStay does not manage leases or tenancy agreements; your lease or rental agreement with the property owner governs your tenancy.

**Property:** {property_address or '[Property Address]'}
**Unit:** {unit_info or '[Unit]'}
**Tenant:** {tenant_name}

**Tenant Signature:** __________________________
**Date:** __________________________
IP Address: ______________________
"""

# Shared sections 1, 2, 4, 5 (same for all jurisdictions)
def _section1_authority() -> str:
    return """**1. Acknowledgment of Authority:** You acknowledge that the Property Owner has granted a limited Power of Attorney to DocuStay, a third-party documentation platform, authorizing it to maintain records of property status, including your occupancy as a guest."""

def _section2_revocable_license() -> str:
    return """**2. Grant of Revocable License:** You acknowledge that your authorization to be on the property is a **revocable license** and does not create a tenancy or any other interest in the property. This license is personal to you and may not be assigned or transferred. You may not sublet any part of the property."""

def _section4_no_hold_over() -> str:
    return """**4. No Right to Hold Over:** You have no right to remain on the property after the "End Date" of your authorized stay. Holding over may subject you to legal action."""

def _section5_revocation() -> str:
    return """**5. Revocation:** You acknowledge that this license is revocable at the will of the Property Owner. The Owner may terminate your occupancy at any time, for any reason, without notice."""

def _section3_california() -> str:
    return """**3. Acknowledgment of Transient Occupancy (California):** You acknowledge that your occupancy is transient in nature. In accordance with California legal principles, you agree that your stay will not exceed fourteen (14) days within any six-month period or seven (7) consecutive nights. Any stay exceeding these limits requires a separate, written lease agreement with the Property Owner."""

def _section3_florida() -> str:
    return """**3. Acknowledgment of Status under Florida Law:** You hereby acknowledge and declare that:
a. You are not a current or former tenant under any written or oral lease with the Property Owner.
b. You are not an owner, co-owner, or immediate family member of the Property Owner.
c. Your occupancy is temporary, and you have been directed to leave the property upon the expiration of your authorized stay.
d. You understand that if you remain on the property without authorization after your license is revoked or expires, the Property Owner may seek your immediate removal by law enforcement pursuant to **Florida Statutes § 82.036**."""

def _section3_new_york() -> str:
    return """**3. Acknowledgment of Occupancy Limits (New York):** You acknowledge that your occupancy is temporary and will not exceed twenty-nine (29) consecutive days. Under New York law, occupancy of thirty (30) consecutive days or more can create a tenancy. You agree that any stay beyond 29 consecutive days requires a separate, written lease agreement with the Property Owner."""

def _section3_generic(statute_citation: str) -> str:
    return f"""**3. Acknowledgment of Guest Status:** You acknowledge that your stay does not exceed the maximum permitted guest stay under applicable state and local law. Under {statute_citation}, a written lease is required for tenancy. You agree that any stay beyond the permitted guest period requires a separate, written lease agreement with the Property Owner."""

def _disclaimer_phrase(region_code: str, state_name: str) -> str:
    """Return the state/law phrase for section 6 disclaimer."""
    rc = (region_code or "").strip().upper()
    if rc == "CA":
        return "California law"
    if rc == "FL":
        return "the Florida Residential Landlord and Tenant Act"
    if rc in ("NY", "NYC"):
        return "New York Real Property Law"
    return "applicable state and local law"

def _build_guest_acknowledgment(
    region_code: str,
    jinfo: JurisdictionInfo,
    *,
    property_address: str | None,
    guest_name: str,
    checkin: str,
    checkout: str,
) -> str:
    """Build full Guest Acknowledgment content with jurisdiction-specific section 3 and disclaimer. Uses ** for bold labels."""
    prop_display = (property_address or "[Address, Unit]").strip()
    statute_citation = "applicable state and local law"
    if jinfo.statutes:
        statute_citation = jinfo.statutes[0].citation
    state_name = jinfo.name or ""

    rc = (region_code or "").strip().upper()
    if rc == "CA":
        section3 = _section3_california()
    elif rc == "FL":
        section3 = _section3_florida()
    elif rc in ("NY", "NYC"):
        section3 = _section3_new_york()
    else:
        section3 = _section3_generic(statute_citation)

    disclaimer_law = _disclaimer_phrase(rc, state_name)
    section6 = f"""**6. Disclaimer:** This document is a record of your authorized occupancy as a guest under a revocable license. It is not a lease and does not grant you any rights of a tenant under {disclaimer_law}. DocuStay is not a law firm and does not provide legal advice."""

    return f"""**{GUEST_ACK_TITLE}**

**Property:** {prop_display}
**Guest:** {guest_name}
**Authorized Stay:** {checkin} to {checkout}

{_section1_authority()}

{_section2_revocable_license()}

{section3}

{_section4_no_hold_over()}

{_section5_revocation()}

{section6}

**Guest Signature:** __________________________
**Date:** __________________________
IP Address: ______________________
"""


def _build_agreement_from_jurisdiction(
    jinfo: JurisdictionInfo,
    *,
    owner_name: str,
    guest_name: str,
    today: str,
    checkin: str,
    checkout: str,
    property_address: str | None,
) -> tuple[str, str]:
    """Build Guest Acknowledgment title and content from JurisdictionInfo (SOT). Returns (title, content)."""
    content = _build_guest_acknowledgment(
        jinfo.region_code,
        jinfo,
        property_address=property_address,
        guest_name=guest_name,
        checkin=checkin,
        checkout=checkout,
    )
    return (GUEST_ACK_TITLE, content)


def _build_guest_acknowledgment_fallback(
    *,
    property_address: str | None,
    guest_name: str,
    checkin: str,
    checkout: str,
) -> str:
    """Fallback when no jurisdiction: generic Guest Acknowledgment with applicable state and local law."""
    prop_display = (property_address or "[Address, Unit]").strip()
    section3 = _section3_generic("applicable state and local law")
    section6 = """**6. Disclaimer:** This document is a record of your authorized occupancy as a guest under a revocable license. It is not a lease and does not grant you any rights of a tenant under applicable state and local law. DocuStay is not a law firm and does not provide legal advice."""

    return f"""**{GUEST_ACK_TITLE}**

**Property:** {prop_display}
**Guest:** {guest_name}
**Authorized Stay:** {checkin} to {checkout}

{_section1_authority()}

{_section2_revocable_license()}

{section3}

{_section4_no_hold_over()}

{_section5_revocation()}

{section6}

**Guest Signature:** __________________________
**Date:** __________________________
IP Address: ______________________
"""


def build_invitation_agreement(
    db: Session,
    invitation_code: str,
    guest_full_name: str | None = None,
) -> AgreementDoc | None:
    code = (invitation_code or "").strip().upper()
    if not code:
        return None

    # Guest invites: only STAGED (not yet signed). Tenant invites: created as BURNED and must still be able to load/sign.
    inv = db.query(Invitation).filter(
        Invitation.invitation_code == code,
        Invitation.status.in_(["pending", "ongoing"]),
        or_(
            Invitation.invitation_kind == "tenant",
            Invitation.token_state != "BURNED",
        ),
    ).first()
    if not inv:
        return None

    inv_kind = (getattr(inv, "invitation_kind", None) or "").strip().lower()

    # Tenant invite: primary resident acceptance. No guest stay language.
    if inv_kind == "tenant":
        prop = db.query(Property).filter(Property.id == inv.property_id).first()
        owner = db.query(User).filter(User.id == inv.owner_id).first()
        property_address = _format_address(prop)
        host_name = (owner.full_name if owner else None) or (owner.email if owner else None)
        tenant_name = (guest_full_name or "[Tenant Name]").strip() or "[Tenant Name]"
        unit_info = ""
        if inv.unit_id:
            unit = db.query(Unit).filter(Unit.id == inv.unit_id).first()
            if unit:
                unit_info = unit.unit_label or str(inv.unit_id)
        content = _build_tenant_invitation_acceptance(
            property_address=property_address,
            tenant_name=tenant_name,
            unit_info=unit_info,
        )
        region = _normalize_region(inv.region_code or (prop.region_code if prop else ""))
        document_id = f"DSA-Tenant-{code}"
        doc_hash = _sha256_hex(content)
        return AgreementDoc(
            document_id=document_id,
            region_code=region,
            title=TENANT_ACK_TITLE,
            content=content,
            document_hash=doc_hash,
            property_address=property_address,
            stay_start_date=str(inv.stay_start_date) if inv.stay_start_date else None,
            stay_end_date=str(inv.stay_end_date) if inv.stay_end_date else None,
            host_name=host_name,
        )

    prop = db.query(Property).filter(Property.id == inv.property_id).first()
    owner = db.query(User).filter(User.id == inv.owner_id).first()

    region = _normalize_region(inv.region_code or (prop.region_code if prop else ""))
    host_name = (owner.full_name if owner else None) or (owner.email if owner else None)
    property_address = _format_address(prop)

    # Use provided guest name when building for display/PDF; otherwise placeholder for hashing.
    guest_name = (guest_full_name or "[Guest Name]").strip() or "[Guest Name]"
    owner_name = (host_name or "").strip() or "[Owner Name]"
    today = date.today().strftime("%B %d, %Y")
    checkin = str(inv.stay_start_date) if inv.stay_start_date else "[Check-in Date]"
    checkout = str(inv.stay_end_date) if inv.stay_end_date else "[Check-out Date]"

    # Prefer JurisdictionInfo from DB SOT so statute citations and removal text are dynamic.
    jinfo = get_jurisdiction_for_property(db, prop.zip_code if prop else None, region)
    if jinfo is not None:
        title, content = _build_agreement_from_jurisdiction(
            jinfo,
            owner_name=owner_name,
            guest_name=guest_name,
            today=today,
            checkin=checkin,
            checkout=checkout,
            property_address=property_address,
        )
        document_id = f"DSA-{code}-{jinfo.region_code}"
        doc_hash = _sha256_hex(content)
        return AgreementDoc(
            document_id=document_id,
            region_code=jinfo.region_code,
            title=title,
            content=content,
            document_hash=doc_hash,
            property_address=property_address,
            stay_start_date=str(inv.stay_start_date) if inv.stay_start_date else None,
            stay_end_date=str(inv.stay_end_date) if inv.stay_end_date else None,
            host_name=host_name,
        )

    # Fallback: no jurisdiction found; use generic template.
    content = _build_guest_acknowledgment_fallback(
        property_address=property_address,
        guest_name=guest_name,
        checkin=checkin,
        checkout=checkout,
    )
    document_id = f"DSA-{code}-{region}"
    doc_hash = _sha256_hex(content)

    return AgreementDoc(
        document_id=document_id,
        region_code=region,
        title=GUEST_ACK_TITLE,
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

POA_CONTENT = """**Master Power of Attorney (POA)**

**Overview**
This is a one-time authorization you sign when you set up your DocuStay account. It lets DocuStay act on your behalf for documentation and utility-related steps so the platform can help you manage your rental properties.

**1. Who Signs This?**
Only property owners sign this Master POA when they join DocuStay.
Guests do not sign this document; they sign a separate Guest Agreement for their stay.

**2. When Do You Sign?**
You sign this once during account setup, before you can add properties.
One signature applies to all properties you add to your account, now and later.

**3. What Does DocuStay Do With This?**
With your authorization, DocuStay can:
- Create and send utility authorization tokens (e.g. USAT) so providers can verify occupancy
- Contact utility companies when needed to confirm or update service for your properties
- Put together documentation packages (e.g. occupancy, dates, guest info) for your records
- Keep dated records of property status and actions for your reference

**4. How Does Location Matter?**
DocuStay uses each property’s address (zip code and state/region) to show relevant local information on that property’s page and to tailor guest agreements and any letters or forms to that location.

**SIGNATURE (ELECTRONIC)**
Owner: ________________________   Date: __________
"""


def build_owner_poa_document() -> tuple[str, str, str, str]:
    """Return (document_id, title, content, document_hash) for the Master POA."""
    content = POA_CONTENT.strip()
    doc_hash = _sha256_hex(content)
    return (POA_DOCUMENT_ID, POA_TITLE, content, doc_hash)


def fill_owner_poa_signature_line(content: str, owner_name: str, signed_date: str) -> str:
    """Fill Owner: ___ and Date: ___ in the POA signature block with actual name and date."""
    result = re.sub(r"Owner:\s*_+", f"Owner: {owner_name}", content, count=1)
    result = re.sub(r"Date:\s*_+", f"Date: {signed_date}", result, count=1)
    return result


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


def _content_to_reportlab_paragraph(line: str, body_style) -> "Paragraph":
    """Convert a line that may contain **bold** to a ReportLab Paragraph with bold segments."""
    from reportlab.platypus import Paragraph

    parts = re.split(r"\*\*(.+?)\*\*", line)
    if len(parts) == 1:
        return Paragraph(_escape_for_reportlab(line), body_style)
    # parts alternate: [normal, bold, normal, bold, ...]
    frags = []
    for i, seg in enumerate(parts):
        if not seg:
            continue
        escaped = _escape_for_reportlab(seg)
        if i % 2 == 1:
            frags.append(f"<b>{escaped}</b>")
        else:
            frags.append(escaped)
    return Paragraph("".join(frags), body_style)


def agreement_content_to_pdf(title: str, content: str) -> bytes:
    """Generate a PDF from agreement title and content using reportlab. Content wraps to page width and is justified. Supports **bold** in content."""
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
        line_stripped = line.strip()
        if line_stripped:
            story.append(_content_to_reportlab_paragraph(line_stripped, body_style))
        else:
            story.append(Spacer(1, 0.12 * inch))

    doc.build(story)
    return buf.getvalue()
