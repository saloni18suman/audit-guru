"""
Summary Agent — produces a natural-language *expense summarization* across a batch
of audited invoices.

This is the "Expense summarization" AI feature from the project brief. It complements
the per-invoice Audit Agent (`agents/audit_agent.py`) with a portfolio-level view:
spend overview, category/vendor highlights, duplicates, policy exceptions, and
recommended finance actions.

Design: figures are aggregated deterministically in Python first (so the numbers are
always correct and the LLM never has to do arithmetic), then the Groq LLM writes the
narrative from that compact aggregate. Returns both the narrative and the stats so the
UI can render trustworthy metric chips alongside the prose.
"""

import os
from collections import defaultdict

from groq import Groq
from dotenv import load_dotenv

load_dotenv()

client      = Groq(api_key=os.environ.get("GROQ_API_KEY"))
_MODEL      = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
_MAX_TOKENS = int(os.environ.get("GROQ_MAX_TOKENS", "1024"))

_DUPLICATE_FLAGS = ("DUPLICATE_INVOICE_ID", "POSSIBLE_DUPLICATE")


def _effective_status(r: dict) -> str:
    """A human review decision overrides the AI audit status."""
    return r.get("review_decision") or r.get("audit", {}).get("audit_status", "UNKNOWN")


def build_expense_stats(results: list[dict]) -> dict:
    """
    Aggregate a list of processed invoice records (the dicts returned by
    db.load_all_results()) into a compact, JSON-serialisable stats block.
    """
    done = [r for r in results if r.get("queue_status", "DONE") == "DONE"]

    stats = {
        "total_invoices": len(done),
        "total_amount":   0.0,
        "status_counts":  {"APPROVED": 0, "REJECTED": 0, "NEEDS_REVIEW": 0},
        "by_category":    {},
        "top_vendors":    [],
        "flag_counts":    {},
        "duplicates":     0,
        "high_risk":      0,
        "avg_confidence": 0.0,
        "date_range":     {"earliest": None, "latest": None},
    }

    vendor_spend: dict = defaultdict(float)
    conf_sum = 0.0
    dates: list[str] = []

    for r in done:
        o = r.get("ocr", {}) or {}
        v = r.get("validation", {}) or {}
        a = r.get("audit", {}) or {}

        amt = o.get("amount", 0) or 0
        stats["total_amount"] += amt

        status = _effective_status(r)
        if status in stats["status_counts"]:
            stats["status_counts"][status] += 1

        cat = o.get("category") or "Other"
        bucket = stats["by_category"].setdefault(cat, {"count": 0, "amount": 0.0})
        bucket["count"]  += 1
        bucket["amount"] += amt

        vendor_spend[o.get("vendor") or "Unknown"] += amt

        flags = v.get("flags", []) or []
        for f in flags:
            key = f.split(":")[0]
            stats["flag_counts"][key] = stats["flag_counts"].get(key, 0) + 1
        if any(f.split(":")[0] in _DUPLICATE_FLAGS for f in flags):
            stats["duplicates"] += 1

        if a.get("risk_level") == "HIGH":
            stats["high_risk"] += 1

        conf_sum += a.get("confidence", 0) or 0

        d = o.get("date")
        if d and d != "UNKNOWN":
            dates.append(d)

    if done:
        stats["avg_confidence"] = round(conf_sum / len(done), 3)
    stats["total_amount"] = round(stats["total_amount"], 2)
    for bucket in stats["by_category"].values():
        bucket["amount"] = round(bucket["amount"], 2)
    stats["top_vendors"] = sorted(
        ({"vendor": k, "amount": round(val, 2)} for k, val in vendor_spend.items()),
        key=lambda x: x["amount"],
        reverse=True,
    )[:5]
    if dates:
        ordered = sorted(dates)
        stats["date_range"] = {"earliest": ordered[0], "latest": ordered[-1]}

    return stats


SUMMARY_PROMPT = """You are a senior financial controller preparing an executive expense-audit summary for company management.

The figures below were aggregated from a batch of expense documents processed through an automated OCR -> Validation -> Audit pipeline. Every number is already computed for you.

AGGREGATED EXPENSE DATA:
{stats_block}

Write a concise, scannable expense summary in markdown with exactly these four bold section headers, each followed by 2-4 short bullet points (start each bullet with "- "):

**Overview** - total spend, number of documents, the period covered, and the overall approval posture.
**Spend Highlights** - the top spending categories and vendors.
**Risk & Compliance** - duplicates detected, policy violations / exceptions raised, and high-risk items, with concrete numbers.
**Recommended Actions** - 2 to 3 specific, prioritised actions for the finance team.

Formatting rules:
- Use short bullet points, not dense paragraphs.
- **Bold** key entities: vendor/payee names, dollar amounts, and flag names like **Duplicate Invoice**.
- Use ONLY the data provided - never invent numbers or names.
Be direct, quantitative, and write for an executive audience."""


def _format_stats_for_prompt(stats: dict) -> str:
    lines = [
        f"- Total documents: {stats['total_invoices']}",
        f"- Total spend: ${stats['total_amount']:,.2f}",
        f"- Status: {stats['status_counts']['APPROVED']} approved, "
        f"{stats['status_counts']['REJECTED']} rejected, "
        f"{stats['status_counts']['NEEDS_REVIEW']} needs review",
        f"- Average AI audit confidence: {stats['avg_confidence']:.0%}",
        f"- Duplicate documents flagged: {stats['duplicates']}",
        f"- High-risk documents: {stats['high_risk']}",
    ]
    dr = stats["date_range"]
    if dr["earliest"]:
        lines.append(f"- Date range: {dr['earliest']} to {dr['latest']}")

    if stats["by_category"]:
        cats = sorted(stats["by_category"].items(), key=lambda x: x[1]["amount"], reverse=True)
        lines.append("- Spend by category: " + "; ".join(
            f"{c} ${d['amount']:,.2f} ({d['count']} docs)" for c, d in cats))

    if stats["top_vendors"]:
        lines.append("- Top vendors/payees by spend: " + "; ".join(
            f"{v['vendor']} ${v['amount']:,.2f}" for v in stats["top_vendors"]))

    if stats["flag_counts"]:
        flags = sorted(stats["flag_counts"].items(), key=lambda x: x[1], reverse=True)
        lines.append("- Validation flags raised: " + "; ".join(f"{k} x{n}" for k, n in flags))

    return "\n".join(lines)


def run_summary_agent(results: list[dict]) -> dict:
    """
    Produce an executive expense summary for a batch of processed invoices.

    Returns:
        {"narrative": <markdown str>, "stats": <stats dict>}
    """
    stats = build_expense_stats(results)

    if stats["total_invoices"] == 0:
        return {"narrative": "_No processed documents available to summarise yet._", "stats": stats}

    response = client.chat.completions.create(
        model=_MODEL,
        messages=[{"role": "user", "content": SUMMARY_PROMPT.format(
            stats_block=_format_stats_for_prompt(stats),
        )}],
        max_tokens=_MAX_TOKENS,
    )
    narrative = response.choices[0].message.content.strip()
    return {"narrative": narrative, "stats": stats}
