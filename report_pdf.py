"""
Builds a one-page PDF audit report from processed invoice records, for the Reports tab's
"Export PDF" button. Uses reportlab (already a project dependency).
"""

import io
import re
from datetime import datetime, timezone

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
)

# Fieldguide-aligned palette
INK    = colors.HexColor("#111827")
GREEN  = colors.HexColor("#16B364")
SLATE  = colors.HexColor("#667085")
BORDER = colors.HexColor("#E5E7EB")
HEADBG = colors.HexColor("#111827")


def _effective_status(r: dict) -> str:
    return r.get("review_decision") or r.get("audit", {}).get("audit_status", "UNKNOWN")


def _styles():
    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle("FGTitle",  parent=ss["Title"],   textColor=INK,   fontSize=20, spaceAfter=2))
    ss.add(ParagraphStyle("FGSub",    parent=ss["Normal"],  textColor=SLATE, fontSize=9,  spaceAfter=12))
    ss.add(ParagraphStyle("FGH2",     parent=ss["Heading2"],textColor=INK,   fontSize=12, spaceBefore=12, spaceAfter=6))
    ss.add(ParagraphStyle("FGBody",   parent=ss["Normal"],  textColor=INK,   fontSize=9,  leading=14))
    ss.add(ParagraphStyle("FGCell",   parent=ss["Normal"],  textColor=INK,   fontSize=8,  leading=11))
    return ss


def _markdown_to_para(text: str, style) -> list:
    """Very small markdown→reportlab converter: **bold**, bullet lines, blank-line breaks."""
    out, S = [], style
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            out.append(Spacer(1, 4))
            continue
        line = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", line)
        if line.startswith(("- ", "* ", "•")):
            line = "&bull; " + line.lstrip("-*• ").strip()
        out.append(Paragraph(line, S))
    return out


def build_report_pdf(results: list[dict], summary: dict | None = None) -> bytes:
    done = [r for r in results if r.get("queue_status", "DONE") == "DONE"]
    ss = _styles()
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=letter,
        leftMargin=0.7 * inch, rightMargin=0.7 * inch,
        topMargin=0.7 * inch, bottomMargin=0.7 * inch,
        title="AnomaGuard — Expense Audit Report",
    )
    story = []

    story.append(Paragraph("AnomaGuard — Expense Audit Report", ss["FGTitle"]))
    story.append(Paragraph(
        "Generated " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), ss["FGSub"]))

    # KPI summary line
    total = sum(r["ocr"].get("amount", 0) for r in done)
    approved = [r for r in done if _effective_status(r) == "APPROVED"]
    rejected = [r for r in done if _effective_status(r) == "REJECTED"]
    pending  = [r for r in done if _effective_status(r) == "NEEDS_REVIEW"]
    kpi = [[
        Paragraph(f"<b>{len(done)}</b><br/>Documents", ss["FGCell"]),
        Paragraph(f"<b>${total:,.2f}</b><br/>Total Value", ss["FGCell"]),
        Paragraph(f"<b>{len(approved)}</b><br/>Approved", ss["FGCell"]),
        Paragraph(f"<b>{len(rejected)}</b><br/>Rejected", ss["FGCell"]),
        Paragraph(f"<b>{len(pending)}</b><br/>Pending", ss["FGCell"]),
    ]]
    kt = Table(kpi, colWidths=[1.34 * inch] * 5)
    kt.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(kt)

    # AI narrative (if generated)
    if summary and not summary.get("error") and summary.get("narrative"):
        story.append(Paragraph("AI Expense Summary", ss["FGH2"]))
        story.extend(_markdown_to_para(summary["narrative"], ss["FGBody"]))

    # Invoice table
    story.append(Paragraph("Invoices", ss["FGH2"]))
    header = ["Invoice ID", "Vendor", "Date", "Amount", "Category", "Status", "Risk", "Flags"]
    data = [header]
    for r in done:
        o, a, v = r.get("ocr", {}), r.get("audit", {}), r.get("validation", {})
        data.append([
            str(o.get("invoice_id", "-"))[:16],
            str(o.get("vendor", "-"))[:22],
            str(o.get("date", "-"))[:10],
            f"${o.get('amount', 0):,.2f}",
            str(o.get("category", "-"))[:16],
            _effective_status(r),
            a.get("risk_level", "-"),
            str(len(v.get("flags", []))),
        ])
    tbl = Table(data, repeatRows=1, colWidths=[
        0.95*inch, 1.4*inch, 0.8*inch, 0.85*inch, 1.05*inch, 1.0*inch, 0.6*inch, 0.45*inch])
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), HEADBG),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 1), (-1, -1), INK),
        ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F9FAFB")]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    # color the Status cells
    for i, r in enumerate(done, start=1):
        st_ = _effective_status(r)
        c = {"APPROVED": "#027A48", "REJECTED": "#912018", "NEEDS_REVIEW": "#B54708"}.get(st_)
        if c:
            style.append(("TEXTCOLOR", (5, i), (5, i), colors.HexColor(c)))
    tbl.setStyle(TableStyle(style))
    story.append(tbl)

    doc.build(story)
    return buf.getvalue()
