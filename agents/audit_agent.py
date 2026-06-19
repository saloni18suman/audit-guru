"""
Audit Agent — uses Groq + RAG policy context to produce a final audit decision
with reasoning, recommendation, and policy references.
"""

import os
import json
import re
from groq import Groq
from dotenv import load_dotenv
from rag.policy_rag import get_policy_context

load_dotenv()

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
_MODEL      = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
_MAX_TOKENS = int(os.environ.get("GROQ_MAX_TOKENS", "1024"))

AUDIT_PROMPT = """You are a senior financial auditor reviewing an expense invoice against company policy.

INVOICE DATA:
{invoice_json}

VALIDATION FLAGS:
{flags}

RELEVANT POLICY SECTIONS:
{policy_context}

Based on the invoice data, validation flags, and policy context above, provide an audit decision.

Return ONLY a valid JSON object with these exact keys:
- invoice_id: string
- audit_status: string (one of: "APPROVED", "REJECTED", "NEEDS_REVIEW")
- reasoning: string (2-4 sentences explaining your decision)
- recommendation: string (one clear action the employee or manager should take)
- confidence: float (0.0 to 1.0, your confidence in this audit decision)
- policy_references: array of strings (list the specific policy sections you referenced)
- risk_level: string (one of: "LOW", "MEDIUM", "HIGH")

Return only the JSON object, no markdown, no other text."""


def run_audit_agent(invoice: dict, validation_result: dict) -> dict:
    invoice_id = invoice.get("invoice_id", "UNKNOWN")
    amount = invoice.get("amount", 0)
    category = invoice.get("category", "Other")
    vendor = invoice.get("vendor", "")

    query = f"{category} expenses vendor {vendor} amount {amount}"
    policy_context = get_policy_context(query)

    flags_text = "\n".join(validation_result.get("flags", [])) or "No flags"

    response = client.chat.completions.create(
        model=_MODEL,
        messages=[{"role": "user", "content": AUDIT_PROMPT.format(
            invoice_json=json.dumps(invoice, indent=2),
            flags=flags_text,
            policy_context=policy_context,
        )}],
        max_tokens=_MAX_TOKENS,
    )

    response_text = response.choices[0].message.content.strip()
    json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
    if json_match:
        response_text = json_match.group()

    audit_result = json.loads(response_text)
    audit_result["invoice_id"] = invoice_id
    return audit_result
