"""Quick smoke-test — runs the full pipeline on a single generated invoice."""

import os
import sys
import json
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(__file__))
from pipeline import process_invoice

INVOICE_DIR = os.path.join(os.path.dirname(__file__), "data", "invoices")


def main():
    invoices = sorted(f for f in os.listdir(INVOICE_DIR) if f.endswith(".pdf"))
    if not invoices:
        print("No invoices found. Run generate_test_invoices.py first.")
        return

    test_file = os.path.join(INVOICE_DIR, invoices[0])
    print(f"Testing pipeline on: {test_file}\n")

    state = process_invoice(test_file)

    print("── OCR Result ──────────────────────────────")
    print(json.dumps(state["ocr_result"], indent=2))

    print("\n── Validation Result ───────────────────────")
    print(json.dumps(state["validation_result"], indent=2))

    print("\n── Audit Result ────────────────────────────")
    print(json.dumps(state["audit_result"], indent=2))

    if state.get("error"):
        print(f"\nERROR: {state['error']}")


if __name__ == "__main__":
    main()
