"""
Generates synthetic *employee expense reimbursement forms* as PDFs in
data/reimbursements/.

These complement the vendor invoices from `generate_test_invoices.py`. A
reimbursement form is a different document type: it is filled out by an employee
who already paid out of pocket and is claiming the money back, and it usually
bundles several individual expenses into one report with a manager-approval line.

The set deliberately covers the same audit scenarios as the invoice set so the
OCR -> Validation -> Audit pipeline can be exercised on this document type too:
  - 3 clean / valid reimbursements
  - 1 duplicate report (same Report ID resubmitted)
  - 2 policy violations (meals over per-person limit / late submission)

Requires: reportlab  (pip install reportlab)
"""

import os

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

OUT_DIR = os.path.join(os.path.dirname(__file__), "data", "reimbursements")
os.makedirs(OUT_DIR, exist_ok=True)


def make_form(filename: str, header: dict, expenses: list[tuple[str, str, float]],
              footer_note: str = "") -> None:
    """
    header   : {report_id, payee, department, date}
    expenses : list of (description, category, amount)
    """
    path = os.path.join(OUT_DIR, filename)
    c = canvas.Canvas(path, pagesize=letter)
    y = 740

    c.setFont("Helvetica-Bold", 15)
    c.drawString(72, y, "EXPENSE REIMBURSEMENT FORM")
    y -= 30

    c.setFont("Helvetica", 11)
    total = sum(amt for _, _, amt in expenses)
    # The field labels are chosen so the OCR agent maps them onto its invoice schema:
    #   Report ID -> invoice_id, Payee -> vendor, Total Reimbursement -> amount.
    for label, value in [
        ("Report ID", header["report_id"]),
        ("Vendor / Payee (Employee)", header["payee"]),
        ("Department", header["department"]),
        ("Submission Date", header["date"]),
        ("Primary Category", header["category"]),
    ]:
        c.drawString(72, y, f"{label}: {value}")
        y -= 20

    y -= 8
    c.setFont("Helvetica-Bold", 11)
    c.drawString(72, y, "Itemised Expenses:")
    y -= 20
    c.setFont("Helvetica", 11)
    for i, (desc, cat, amt) in enumerate(expenses, 1):
        c.drawString(86, y, f"{i}. {desc} ({cat}) - ${amt:,.2f}")
        y -= 18

    y -= 8
    c.setFont("Helvetica-Bold", 12)
    c.drawString(72, y, f"Total Reimbursement: ${total:,.2f}")
    y -= 30

    c.setFont("Helvetica", 11)
    c.drawString(72, y, f"Manager Approval: {header.get('approval', '____________________')}")
    if footer_note:
        y -= 24
        c.setFont("Helvetica-Oblique", 9)
        c.drawString(72, y, footer_note)

    c.save()
    print(f"Created {filename}  (total ${total:,.2f})")


forms = [
    # ── 3 Valid ───────────────────────────────────────────────────────────────
    ("RB-001_valid.pdf",
     {"report_id": "RB-2026-001", "payee": "Jane Doe", "department": "Sales",
      "date": "2026-06-14", "category": "Travel", "approval": "M. Patel"},
     [("Flight NYC to SFO", "Travel", 420.00),
      ("Airport taxi", "Travel", 48.00),
      ("Team lunch", "Meals", 62.50)]),

    ("RB-002_valid.pdf",
     {"report_id": "RB-2026-002", "payee": "Carlos Mendez", "department": "Engineering",
      "date": "2026-06-15", "category": "Office Supplies", "approval": "S. Cohen"},
     [("USB-C docking station", "Office Supplies", 129.00),
      ("Mechanical keyboard", "Office Supplies", 88.00)]),

    ("RB-003_valid.pdf",
     {"report_id": "RB-2026-003", "payee": "Aisha Khan", "department": "Marketing",
      "date": "2026-06-16", "category": "Accommodation", "approval": "R. Lewis"},
     [("Hotel, 1 night (conference)", "Accommodation", 175.00),
      ("Breakfast", "Meals", 22.00)]),

    # ── 1 Duplicate (RB-2026-001 resubmitted) ─────────────────────────────────
    ("RB-001_duplicate.pdf",
     {"report_id": "RB-2026-001", "payee": "Jane Doe", "department": "Sales",
      "date": "2026-06-14", "category": "Travel", "approval": "M. Patel"},
     [("Flight NYC to SFO", "Travel", 420.00),
      ("Airport taxi", "Travel", 48.00),
      ("Team lunch", "Meals", 62.50)],
     "Note: resubmitted copy of an earlier report (duplicate)."),

    # ── 2 Policy Violations ───────────────────────────────────────────────────
    ("RB-004_violation_meals_overlimit.pdf",
     {"report_id": "RB-2026-004", "payee": "Tom Becker", "department": "Sales",
      "date": "2026-06-17", "category": "Meals", "approval": "M. Patel"},
     [("Client dinner for 1 person", "Meals", 295.00)],   # exceeds $150 per-person meal limit
     "Note: single-person meal exceeds the per-person dining policy limit."),

    ("RB-005_violation_late_submission.pdf",
     {"report_id": "RB-2026-005", "payee": "Nina Rossi", "department": "Operations",
      "date": "2026-04-02", "category": "Travel", "approval": "____________________"},   # >30 days old, no approval
     [("Train fare", "Travel", 96.00),
      ("Hotel, 1 night", "Accommodation", 140.00)],
     "Note: submitted more than 30 days after the expense date; missing manager approval."),
]


if __name__ == "__main__":
    for entry in forms:
        if len(entry) == 4:
            filename, header, expenses, note = entry
        else:
            filename, header, expenses = entry
            note = ""
        make_form(filename, header, expenses, note)

    print(f"\nGenerated {len(forms)} reimbursement forms in {OUT_DIR}")
