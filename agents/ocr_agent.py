"""
OCR Agent — extracts structured data from PDF invoices using pdfplumber
and an LLM for entity extraction.
"""

import os
import json
import re
import pdfplumber
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
_MODEL      = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
_MAX_TOKENS = int(os.environ.get("GROQ_MAX_TOKENS", "1024"))


def extract_text_from_pdf(pdf_path: str) -> str:
    text_parts = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                text_parts.append(text)
    return "\n".join(text_parts)


EXTRACTION_PROMPT = """You are an invoice OCR agent. Extract the following fields from the invoice text below.

Return ONLY a valid JSON object with these exact keys:
- invoice_id: string (invoice number/ID, or "UNKNOWN" if not found)
- vendor: string (vendor/supplier name)
- date: string (invoice date in YYYY-MM-DD format, or original format if unclear)
- amount: float (total amount as a number, no currency symbol)
- currency: string (3-letter currency code, default "USD")
- category: string (one of: Travel, Accommodation, Meals, Office Supplies, Software, Professional Services, Other)
- line_items: array of objects with keys "description" (string) and "amount" (float)
- confidence: float (0.0 to 1.0, your confidence in the extraction accuracy)
- raw_text: string (first 300 characters of the raw text)

Invoice text:
{text}

Return only the JSON object, no markdown, no other text."""


def run_ocr_agent(pdf_path: str) -> dict:
    raw_text = extract_text_from_pdf(pdf_path)

    if not raw_text.strip():
        return {
            "invoice_id": "UNKNOWN",
            "vendor": "UNKNOWN",
            "date": "UNKNOWN",
            "amount": 0.0,
            "currency": "USD",
            "category": "Other",
            "line_items": [],
            "confidence": 0.0,
            "raw_text": "",
            "error": "No text could be extracted from the PDF",
        }

    response = client.chat.completions.create(
        model=_MODEL,
        messages=[{"role": "user", "content": EXTRACTION_PROMPT.format(text=raw_text[:3000])}],
        max_tokens=_MAX_TOKENS,
    )

    response_text = response.choices[0].message.content.strip()
    json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
    if json_match:
        response_text = json_match.group()

    extracted = json.loads(response_text)
    extracted["raw_text"] = raw_text[:300]
    extracted["source_file"] = os.path.basename(pdf_path)
    return extracted
