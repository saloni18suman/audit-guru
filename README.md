# Audit Guru

AI-powered invoice audit system that processes PDF invoices through an OCR → Validation → Audit pipeline and presents results in a review dashboard.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Project Structure](#project-structure)
4. [Pipeline](#pipeline)
   - [OCR Agent](#1-ocr-agent)
   - [Validation Agent](#2-validation-agent)
   - [Audit Agent](#3-audit-agent)
   - [RAG Policy Store](#rag-policy-store)
5. [Data Storage](#data-storage)
6. [Frontend](#frontend)
7. [Configuration](#configuration)
8. [Setup & Installation](#setup--installation)
9. [Running the App](#running-the-app)
10. [API Reference](#api-reference)

---

## Overview

Audit Guru automates the expense invoice review workflow:

1. A user uploads one or more PDF invoices.
2. The pipeline extracts structured data (OCR), validates it against policy rules, then sends it to an LLM for an audit decision enriched with company policy context via RAG.
3. Results are persisted in SQLite and displayed in a dashboard with charts, an invoice table, and a human review queue for flagged invoices.

**Tech stack:** Python · Streamlit · LangGraph · Groq (Llama 3.3 70B) · pdfplumber · FAISS · sentence-transformers · SQLite · Plotly · LocalStack S3 (boto3)

---

## Architecture

```
┌──────────────────────────────────────────────────┐
│                  Streamlit UI (app.py)            │
│  Dashboard │ Upload │ Review Queue │ Reports      │
└───────────────────┬──────────────────────────────┘
                    │ process_invoice()
                    ▼
┌──────────────────────────────────────────────────┐
│           LangGraph Pipeline (pipeline.py)        │
│                                                   │
│   ┌─────────┐   ┌────────────┐   ┌─────────────┐ │
│   │   OCR   │──▶│ Validation │──▶│    Audit    │ │
│   │  Agent  │   │   Agent    │   │    Agent    │ │
│   └────┬────┘   └─────┬──────┘   └──────┬──────┘ │
│        │              │                  │        │
│   pdfplumber    Policy rules        Groq LLM      │
│   + Groq LLM                        + RAG         │
└──────────────────────────────────────────────────┘
                    │
                    ▼
          SQLite (audit.db)
          Session state cache
```

State flows through a `TypedDict` (`PipelineState`). Each node receives the full state, enriches it, and passes it to the next node. If any node sets `error`, downstream nodes skip processing.

---

## Project Structure

```
capstone/
├── app.py                  # Streamlit frontend (4 tabs)
├── pipeline.py             # LangGraph pipeline definition
├── db.py                   # SQLite persistence layer
├── agents/
│   ├── ocr_agent.py        # PDF text extraction + LLM field extraction
│   ├── validation_agent.py # Rule-based policy validation (no LLM)
│   └── audit_agent.py      # LLM audit decision + RAG context
├── rag/
│   ├── policy_rag.py       # FAISS vector store + similarity search
│   └── __init__.py
├── data/
│   ├── expense_policy.txt  # Company policy document (RAG source)
│   └── faiss_index/        # Auto-generated vector index (gitignored)
├── audit.db                # SQLite database (auto-created, gitignored)
├── requirements.txt
├── .env                    # Local secrets and config (gitignored)
└── .env.example            # Config template
```

---

## Pipeline

### 1. OCR Agent

**File:** `agents/ocr_agent.py`

Extracts raw text from a PDF using `pdfplumber`, then sends up to 3 000 characters to the Groq LLM to extract structured fields.

**Input:** `pdf_path: str`

**Output:**

| Field | Type | Description |
|---|---|---|
| `invoice_id` | `str` | Invoice number, or `"UNKNOWN"` |
| `vendor` | `str` | Vendor / supplier name |
| `date` | `str` | Date in `YYYY-MM-DD` or original format |
| `amount` | `float` | Total amount (no currency symbol) |
| `currency` | `str` | 3-letter code, default `"USD"` |
| `category` | `str` | One of: Travel, Accommodation, Meals, Office Supplies, Software, Professional Services, Other |
| `line_items` | `list[dict]` | `[{description, amount}]` |
| `confidence` | `float` | 0.0 – 1.0 extraction confidence |
| `raw_text` | `str` | First 300 chars of extracted PDF text |
| `source_file` | `str` | Original filename |

---

### 2. Validation Agent

**File:** `agents/validation_agent.py`

Pure Python — no LLM calls. Runs three checks in sequence:

#### Missing Fields
Flags any of `invoice_id`, `vendor`, `date`, `amount`, `category` that are empty, `"UNKNOWN"`, or `0`.

```
MISSING_FIELD:<field_name>
```

#### Duplicate Detection
Checks against all previously processed invoices in the session:
- Exact `invoice_id` match → `DUPLICATE_INVOICE_ID:<id>`
- Same vendor + amount + date with a different ID → `POSSIBLE_DUPLICATE:same_vendor_amount_date`

#### Policy Violations

| Check | Flag |
|---|---|
| Category not in approved list | `UNAPPROVED_CATEGORY:<category>` |
| Amount exceeds category limit | `EXCEEDS_LIMIT:<category>:$<amount>_limit_$<limit>` |
| Invoice older than 30 days | `LATE_SUBMISSION:<n>_days_since_invoice` |
| Amount > $2 000 | `REQUIRES_FINANCE_VP_APPROVAL` |
| Amount $500 – $2 000 | `REQUIRES_DEPT_HEAD_APPROVAL` |
| Amount $100 – $500 | `REQUIRES_MANAGER_APPROVAL` |

**Category spending limits:**

| Category | Limit |
|---|---|
| Meals | $150 |
| Accommodation | $300 |
| Office Supplies | $500 |
| Travel | $5 000 |
| Software | $2 000 |
| Professional Services | $10 000 |

**Output:**

| Field | Type | Description |
|---|---|---|
| `validation_status` | `str` | `PASSED` / `WARNING` / `FAILED` |
| `flags` | `list[str]` | All raised flags |
| `critical_flags` | `list[str]` | MISSING_FIELD, DUPLICATE, UNAPPROVED |
| `warning_flags` | `list[str]` | Non-critical flags |
| `flag_count` | `int` | Total flag count |

---

### 3. Audit Agent

**File:** `agents/audit_agent.py`

Queries the RAG store for relevant policy sections, then sends invoice data + validation flags + policy context to the Groq LLM for a final audit decision.

**Input:** `invoice: dict`, `validation_result: dict`

**Output:**

| Field | Type | Description |
|---|---|---|
| `audit_status` | `str` | `APPROVED` / `REJECTED` / `NEEDS_REVIEW` |
| `reasoning` | `str` | 2–4 sentence explanation |
| `recommendation` | `str` | One clear action for the employee or manager |
| `confidence` | `float` | 0.0 – 1.0 audit confidence |
| `policy_references` | `list[str]` | Policy sections referenced |
| `risk_level` | `str` | `LOW` / `MEDIUM` / `HIGH` |

---

### RAG Policy Store

**File:** `rag/policy_rag.py`

Loads `data/expense_policy.txt` and builds a FAISS vector index using `sentence-transformers` (`all-MiniLM-L6-v2`). The index is cached to `data/faiss_index/` on first run.

`get_policy_context(query, k=4)` returns the top-4 most semantically similar policy chunks as a single string, which is injected into the Audit Agent's prompt.

The vector store is a module-level singleton — it is built once per process.

---

## Data Storage

**File:** `db.py`  
**Database:** `audit.db` (SQLite, path configurable via `DB_PATH` in `.env`)

### Schema

```sql
CREATE TABLE invoices (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    filename         TEXT,
    invoice_id       TEXT,
    ocr_json         TEXT,       -- JSON blob: full OCR result
    validation_json  TEXT,       -- JSON blob: validation result
    audit_json       TEXT,       -- JSON blob: audit result
    review_decision  TEXT,       -- NULL | 'APPROVED' | 'REJECTED'
    review_notes     TEXT,       -- Free-text reviewer notes
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
```

### API

| Function | Description |
|---|---|
| `init_db()` | Creates the table if it does not exist |
| `save_result(result)` | Inserts a new invoice record |
| `load_all_results()` | Returns all rows ordered by `created_at DESC` |
| `save_review(db_id, decision, notes)` | Updates reviewer decision |
| `delete_result(db_id)` | Deletes a record by primary key |

---

## Frontend

**File:** `app.py`  
**Framework:** Streamlit 1.45  
**URL:** `http://localhost:8501`

### Tab 1 — Dashboard

- **Primary KPIs:** Total Invoices, Approved, Rejected, Pending Review
- **Secondary KPIs:** Avg Invoice Amount, Approval Rate %, Total Flags, Avg AI Confidence
- **Charts (Plotly):**
  - Spend by Category (horizontal bar)
  - Top Vendors by Spend (horizontal bar, gold)
  - Status Distribution (donut)
  - Risk Level Distribution (bar)
  - Flag Type Breakdown (bar)
  - Amount vs AI Confidence (scatter, colored by status)
- **Invoice Table:** HTML table with all invoices, status pills, risk badges
- **Detailed View:** Collapsible expanders with full per-invoice breakdown
- **Export CSV:** Top-right button, downloads all invoice data

### Tab 2 — Upload Invoice

- Pipeline diagram (OCR → Validate → Audit → Decision)
- PDF file uploader (multi-file)
- "Run Audit Pipeline" button processes each file sequentially through LangGraph

### Tab 3 — Review Queue

- Shows only invoices with `audit_status = NEEDS_REVIEW`
- Each invoice renders as a case card with:
  - Dark navy header: vendor, invoice ID, amount, risk badge
  - Left column: invoice details, line items, validation flags
  - Right column: AI reasoning, recommendation, policy references
  - Footer: reviewer notes text input + Approve / Reject buttons
- Decided cases shown in a compact list below

### Tab 4 — Reports

- Total, Approved, Rejected, Pending metrics
- Grouped lists: Approved / Rejected / Pending with amounts and recommendations
- Export CSV button

---

## Configuration

All configuration lives in `.env`. Copy `.env.example` to `.env` and fill in values.

| Variable | Default | Description |
|---|---|---|
| `GROQ_API_KEY` | — | **Required.** Your Groq API key |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | Groq model for OCR and Audit agents |
| `GROQ_MAX_TOKENS` | `1024` | Max tokens per LLM response |
| `DB_PATH` | `audit.db` | SQLite file path (relative to project root or absolute) |
| `APP_NAME` | `Audit Guru` | Application display name |
| `S3_ENDPOINT_URL` | `http://localhost:4566` | LocalStack S3 endpoint |
| `S3_BUCKET_NAME` | `audit-guru-invoices` | S3 bucket where PDFs are stored |
| `AWS_ACCESS_KEY_ID` | `test` | LocalStack access key (any string works) |
| `AWS_SECRET_ACCESS_KEY` | `test` | LocalStack secret key (any string works) |
| `AWS_REGION` | `us-east-1` | AWS region |

To switch to a faster/cheaper model: `GROQ_MODEL=llama-3.1-8b-instant`

---

## Setup & Installation

### Prerequisites

- Python 3.11+
- A free Groq API key from [console.groq.com](https://console.groq.com)
- Docker (for LocalStack S3)

### Steps

```bash
# 1. Clone / navigate to the project
cd capstone

# 2. Create and activate virtual environment
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS / Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
copy .env.example .env         # Windows
# cp .env.example .env         # macOS / Linux
# Then open .env and add your GROQ_API_KEY

# 5. Start LocalStack via Docker
docker compose up -d      # starts LocalStack S3 on port 4566
# Wait until healthy:
docker compose ps         # STATUS should show "healthy"

# 6. (Optional) Verify the FAISS index is built
#    It auto-builds on first run, but you can pre-build:
python -c "from rag.policy_rag import get_policy_context; print('RAG ready')"
```

---

## Running the App

```bash
# 1. Start LocalStack (S3)
docker compose up -d

# 2. Start the app (activate venv first)
streamlit run app.py
```

Open `http://localhost:8501` in your browser.

To run headless (background):

```powershell
Start-Process -NoNewWindow -FilePath "venv\Scripts\streamlit.exe" -ArgumentList "run","app.py"
```

---

## API Reference

### `pipeline.process_invoice(pdf_path, processed_invoices=[])`

Main entry point. Runs the full LangGraph pipeline on a single PDF.

```python
from pipeline import process_invoice

state = process_invoice("invoice.pdf", previously_processed_list)
# state keys: pdf_path, ocr_result, validation_result, audit_result, error
```

### `db.save_result(result)` / `db.load_all_results()`

```python
from db import save_result, load_all_results

save_result({
    "filename": "invoice.pdf",
    "ocr": {...},
    "validation": {...},
    "audit": {...},
})

results = load_all_results()  # list of dicts with db_id, ocr, validation, audit, review_decision
```

### `rag.policy_rag.get_policy_context(query, k=4)`

```python
from rag.policy_rag import get_policy_context

context = get_policy_context("travel expenses hotel accommodation", k=4)
# returns top-4 policy chunks as a newline-separated string
```
