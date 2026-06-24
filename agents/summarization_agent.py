"""
Summarization Agent — generates an AI narrative summary of a batch of invoices.
"""

import json
import os
import re

from groq import Groq

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

_PROMPT = """You are a senior finance analyst. Summarize the following expense data into a concise, professional executive summary.

EXPENSE BATCH DATA:
{data}

Write a 3-5 sentence narrative that covers:
- Total spend and invoice count
- Top spending categories and vendors
- Any compliance concerns or flagged invoices
- Overall risk assessment and recommendation

Be specific with numbers. Use a professional tone. Plain text only, no bullet points, no markdown."""


def generate_summary(invoices: list[dict]) -> str:
    if not invoices:
        return "No invoice data available to summarize."

    vendor_spend: dict = {}
    cat_spend: dict = {}
    total = 0.0
    flagged = 0
    high_risk = 0
    approved = rejected = pending = 0

    for r in invoices:
        o = r.get("ocr", {})
        a = r.get("audit", {})
        v = r.get("validation", {})
        amt = float(o.get("amount", 0) or 0)
        total += amt

        vendor = o.get("vendor") or "Unknown"
        cat    = o.get("category") or "Other"
        vendor_spend[vendor] = vendor_spend.get(vendor, 0) + amt
        cat_spend[cat]       = cat_spend.get(cat, 0) + amt

        if v.get("flags"):
            flagged += 1
        if a.get("risk_level") == "HIGH":
            high_risk += 1

        dec = r.get("review_decision") or a.get("audit_status", "")
        if dec == "APPROVED":   approved  += 1
        elif dec == "REJECTED": rejected  += 1
        else:                   pending   += 1

    top_vendors = sorted(vendor_spend.items(), key=lambda x: x[1], reverse=True)[:3]
    top_cats    = sorted(cat_spend.items(),    key=lambda x: x[1], reverse=True)[:3]

    data = {
        "total_invoices":    len(invoices),
        "total_spend":       f"${total:,.2f}",
        "approved":          approved,
        "rejected":          rejected,
        "pending_review":    pending,
        "flagged_invoices":  flagged,
        "high_risk_invoices":high_risk,
        "top_vendors":       [{"vendor": v, "spend": f"${s:,.2f}"} for v, s in top_vendors],
        "top_categories":    [{"category": c, "spend": f"${s:,.2f}"} for c, s in top_cats],
    }

    response = client.chat.completions.create(
        model=_MODEL,
        messages=[{"role": "user", "content": _PROMPT.format(data=json.dumps(data, indent=2))}],
        max_tokens=300,
    )
    return response.choices[0].message.content.strip()
