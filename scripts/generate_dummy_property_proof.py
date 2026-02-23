#!/usr/bin/env python3
"""Generate a dummy property proof PDF for testing.
Usage: python scripts/generate_dummy_property_proof.py [output_path]
  Default output: scripts/dummy_property_proof.pdf
"""
import sys
from pathlib import Path

# Project root
script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent
sys.path.insert(0, str(project_root))

DEFAULT_OUT = script_dir / "dummy_property_proof.pdf"


def main():
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

    out_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    out_path = out_path.resolve()

    doc = SimpleDocTemplate(str(out_path), pagesize=letter, topMargin=0.75 * inch, bottomMargin=0.75 * inch)
    styles = getSampleStyleSheet()
    story = []

    story.append(Paragraph("PROPERTY DEED – SAMPLE PROOF OF OWNERSHIP", styles["Title"]))
    story.append(Spacer(1, 0.3 * inch))
    story.append(Paragraph("This is a dummy document for testing purposes only.", styles["Normal"]))
    story.append(Paragraph("It is not a legal deed and has no legal effect.", styles["Normal"]))
    story.append(Spacer(1, 0.2 * inch))

    story.append(Paragraph("Property Address", styles["Heading2"]))
    story.append(Paragraph("123 Test Street", styles["Normal"]))
    story.append(Paragraph("Anytown, ST 12345", styles["Normal"]))
    story.append(Spacer(1, 0.2 * inch))

    story.append(Paragraph("Owner (as shown for test)", styles["Heading2"]))
    story.append(Paragraph("Test Owner Name", styles["Normal"]))
    story.append(Paragraph("test@example.com", styles["Normal"]))
    story.append(Spacer(1, 0.2 * inch))

    story.append(Paragraph("Document Type: Property Deed (Recommended)", styles["Normal"]))
    story.append(Paragraph("Date: For DocuStay testing only", styles["Normal"]))
    story.append(Spacer(1, 0.3 * inch))
    story.append(Paragraph("— End of sample proof —", styles["Italic"]))

    doc.build(story)
    print(f"Created: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
