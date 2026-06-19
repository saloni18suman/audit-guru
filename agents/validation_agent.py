"""
Validation Agent — checks for duplicates, missing fields, and basic policy violations.
Operates on structured JSON output from the OCR Agent.
"""

from datetime import datetime, timedelta


REQUIRED_FIELDS = ["invoice_id", "vendor", "date", "amount", "category"]

APPROVED_CATEGORIES = {
    "Travel", "Accommodation", "Meals", "Office Supplies",
    "Software", "Professional Services", "Other"
}

CATEGORY_LIMITS = {
    "Meals": 150.0,
    "Travel": 5000.0,
    "Accommodation": 300.0,
    "Office Supplies": 500.0,
    "Software": 2000.0,
    "Professional Services": 10000.0,
}


def _check_missing_fields(invoice: dict) -> list[str]:
    flags = []
    for field in REQUIRED_FIELDS:
        val = invoice.get(field)
        if val is None or val == "" or val == "UNKNOWN" or val == 0:
            flags.append(f"MISSING_FIELD:{field}")
    return flags


def _check_duplicate(invoice: dict, existing_invoices: list[dict]) -> list[str]:
    flags = []
    inv_id = invoice.get("invoice_id", "").strip().upper()
    vendor = invoice.get("vendor", "").strip().lower()
    amount = invoice.get("amount", 0)
    date = invoice.get("date", "")

    for existing in existing_invoices:
        ex_id = existing.get("invoice_id", "").strip().upper()
        ex_vendor = existing.get("vendor", "").strip().lower()
        ex_amount = existing.get("amount", 0)
        ex_date = existing.get("date", "")

        if inv_id != "UNKNOWN" and inv_id == ex_id:
            flags.append(f"DUPLICATE_INVOICE_ID:{inv_id}")
            break

        if (
            vendor == ex_vendor
            and abs(amount - ex_amount) < 0.01
            and date == ex_date
            and inv_id != ex_id
        ):
            flags.append(f"POSSIBLE_DUPLICATE:same_vendor_amount_date")
            break

    return flags


def _check_policy_violations(invoice: dict) -> list[str]:
    flags = []
    amount = invoice.get("amount", 0)
    category = invoice.get("category", "Other")

    if category not in APPROVED_CATEGORIES:
        flags.append(f"UNAPPROVED_CATEGORY:{category}")

    limit = CATEGORY_LIMITS.get(category)
    if limit and amount > limit:
        flags.append(f"EXCEEDS_LIMIT:{category}:${amount:.2f}_limit_${limit:.2f}")

    date_str = invoice.get("date", "")
    if date_str and date_str != "UNKNOWN":
        try:
            invoice_date = datetime.strptime(date_str, "%Y-%m-%d")
            days_old = (datetime.now() - invoice_date).days
            if days_old > 30:
                flags.append(f"LATE_SUBMISSION:{days_old}_days_since_invoice")
        except ValueError:
            flags.append("INVALID_DATE_FORMAT")

    if amount > 2000:
        flags.append("REQUIRES_FINANCE_VP_APPROVAL")
    elif amount > 500:
        flags.append("REQUIRES_DEPT_HEAD_APPROVAL")
    elif amount > 100:
        flags.append("REQUIRES_MANAGER_APPROVAL")

    return flags


def run_validation_agent(invoice: dict, processed_invoices: list[dict]) -> dict:
    flags = []

    flags.extend(_check_missing_fields(invoice))
    flags.extend(_check_duplicate(invoice, processed_invoices))
    flags.extend(_check_policy_violations(invoice))

    critical_flags = [f for f in flags if f.startswith(("MISSING_FIELD", "DUPLICATE", "UNAPPROVED"))]
    warning_flags = [f for f in flags if f not in critical_flags]

    if critical_flags:
        validation_status = "FAILED"
    elif warning_flags:
        validation_status = "WARNING"
    else:
        validation_status = "PASSED"

    return {
        "invoice_id": invoice.get("invoice_id"),
        "validation_status": validation_status,
        "flags": flags,
        "critical_flags": critical_flags,
        "warning_flags": warning_flags,
        "flag_count": len(flags),
    }
