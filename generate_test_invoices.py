"""
Generates 20 synthetic test invoice PDFs in data/invoices/:
  - 5 valid invoices
  - 6 duplicate invoices (same invoice IDs as valids)
  - 5 policy violations (over-limit amounts or wrong categories)
  - 4 edge-case invoices (missing fields, late submission, etc.)

Requires: reportlab  (pip install reportlab)
"""

import os
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

OUT_DIR = os.path.join(os.path.dirname(__file__), "data", "invoices")
os.makedirs(OUT_DIR, exist_ok=True)


def make_invoice(filename: str, content_lines: list[str]):
    path = os.path.join(OUT_DIR, filename)
    c = canvas.Canvas(path, pagesize=letter)
    y = 720
    c.setFont("Helvetica-Bold", 14)
    c.drawString(72, y, "INVOICE")
    c.setFont("Helvetica", 11)
    y -= 30
    for line in content_lines:
        c.drawString(72, y, line)
        y -= 20
    c.save()
    print(f"Created {filename}")


invoices = [
    # ── 5 Valid ──────────────────────────────────────────────────────────────
    ("INV-001_valid.pdf", [
        "Invoice Number: INV-001",
        "Vendor: Delta Airlines",
        "Date: 2026-06-01",
        "Category: Travel",
        "Description: Economy flight NYC to SFO",
        "Amount: $450.00",
    ]),
    ("INV-002_valid.pdf", [
        "Invoice Number: INV-002",
        "Vendor: Marriott Hotels",
        "Date: 2026-06-02",
        "Category: Accommodation",
        "Description: 1 night stay, standard room",
        "Amount: $185.00",
    ]),
    ("INV-003_valid.pdf", [
        "Invoice Number: INV-003",
        "Vendor: Office Depot",
        "Date: 2026-06-03",
        "Category: Office Supplies",
        "Description: Printer paper and pens",
        "Amount: $42.50",
    ]),
    ("INV-004_valid.pdf", [
        "Invoice Number: INV-004",
        "Vendor: Zoom Video Communications",
        "Date: 2026-06-04",
        "Category: Software",
        "Description: Monthly subscription - Pro plan",
        "Amount: $149.90",
    ]),
    ("INV-005_valid.pdf", [
        "Invoice Number: INV-005",
        "Vendor: Deloitte Consulting",
        "Date: 2026-06-05",
        "Category: Professional Services",
        "Description: Strategy consulting - 4 hours",
        "Amount: $800.00",
    ]),

    # ── 6 Duplicates ─────────────────────────────────────────────────────────
    ("INV-001_dup1.pdf", [
        "Invoice Number: INV-001",
        "Vendor: Delta Airlines",
        "Date: 2026-06-01",
        "Category: Travel",
        "Description: Economy flight NYC to SFO (DUPLICATE)",
        "Amount: $450.00",
    ]),
    ("INV-002_dup2.pdf", [
        "Invoice Number: INV-002",
        "Vendor: Marriott Hotels",
        "Date: 2026-06-02",
        "Category: Accommodation",
        "Description: 1 night stay (DUPLICATE)",
        "Amount: $185.00",
    ]),
    ("INV-003_dup3.pdf", [
        "Invoice Number: INV-003",
        "Vendor: Office Depot",
        "Date: 2026-06-03",
        "Category: Office Supplies",
        "Description: Printer paper and pens (RESUBMITTED)",
        "Amount: $42.50",
    ]),
    ("INV-006_dup4.pdf", [
        "Invoice Number: INV-006",
        "Vendor: Uber",
        "Date: 2026-06-05",
        "Category: Travel",
        "Description: Airport transfer",
        "Amount: $55.00",
    ]),
    ("INV-006_dup5.pdf", [
        "Invoice Number: INV-006",
        "Vendor: Uber",
        "Date: 2026-06-05",
        "Category: Travel",
        "Description: Airport transfer (DUPLICATE SUBMISSION)",
        "Amount: $55.00",
    ]),
    ("INV-007_dup6.pdf", [
        "Invoice Number: INV-007",
        "Vendor: Lyft",
        "Date: 2026-06-06",
        "Category: Travel",
        "Description: City transport",
        "Amount: $38.00",
    ]),

    # ── 5 Policy Violations ───────────────────────────────────────────────────
    ("INV-008_violation_meal_overlimit.pdf", [
        "Invoice Number: INV-008",
        "Vendor: Le Bernardin Restaurant",
        "Date: 2026-06-07",
        "Category: Meals",
        "Description: Client dinner for 1 person",
        "Amount: $320.00",   # exceeds $150 per person limit
    ]),
    ("INV-009_violation_unapproved_category.pdf", [
        "Invoice Number: INV-009",
        "Vendor: Amazon Personal",
        "Date: 2026-06-07",
        "Category: Personal",
        "Description: Personal laptop stand and keyboard",
        "Amount: $210.00",   # unapproved category
    ]),
    ("INV-010_violation_hotel_overlimit.pdf", [
        "Invoice Number: INV-010",
        "Vendor: Four Seasons New York",
        "Date: 2026-06-08",
        "Category: Accommodation",
        "Description: 1 night luxury suite",
        "Amount: $950.00",   # exceeds $200 domestic limit
    ]),
    ("INV-011_violation_needs_vp_approval.pdf", [
        "Invoice Number: INV-011",
        "Vendor: McKinsey and Company",
        "Date: 2026-06-09",
        "Category: Professional Services",
        "Description: Strategic advisory services",
        "Amount: $15000.00",  # requires Finance VP approval
    ]),
    ("INV-012_violation_late_submission.pdf", [
        "Invoice Number: INV-012",
        "Vendor: Hilton Hotels",
        "Date: 2026-04-01",   # over 30 days ago
        "Category: Accommodation",
        "Description: Conference accommodation",
        "Amount: $195.00",
    ]),

    # ── 4 Edge Cases ─────────────────────────────────────────────────────────
    ("INV-013_missing_fields.pdf", [
        "Vendor: Unknown Supplier",
        "Description: Various office items",
        "Amount: $75.00",
        # No invoice number, no date, no category
    ]),
    ("INV-014_no_amount.pdf", [
        "Invoice Number: INV-014",
        "Vendor: Staples",
        "Date: 2026-06-10",
        "Category: Office Supplies",
        "Description: Office chair",
        # No amount listed
    ]),
    ("INV-015_valid_high_confidence.pdf", [
        "Invoice Number: INV-015",
        "Vendor: Microsoft Corporation",
        "Date: 2026-06-11",
        "Category: Software",
        "Description: Azure cloud subscription - monthly",
        "Amount: $499.00",
        "Tax ID: 91-1144442",
        "Payment Terms: Net 30",
    ]),
    ("INV-016_foreign_currency.pdf", [
        "Invoice Number: INV-016",
        "Vendor: Accenture UK Ltd",
        "Date: 2026-06-12",
        "Category: Professional Services",
        "Description: IT consulting - London office",
        "Amount: GBP 750.00",
        "Exchange Rate: 1 GBP = 1.27 USD",
        "USD Equivalent: $952.50",
    ]),
]


if __name__ == "__main__":
    try:
        from reportlab.lib.pagesizes import letter
    except ImportError:
        print("reportlab not installed. Run: pip install reportlab")
        exit(1)

    for filename, lines in invoices:
        make_invoice(filename, lines)

    print(f"\nGenerated {len(invoices)} test invoices in {OUT_DIR}")
