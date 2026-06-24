# Audit Guru

AI-powered invoice audit platform. Bulk-upload PDF invoices, run them through an OCR → Validation → Audit pipeline via an async queue, and review results in a role-gated dashboard backed by AWS.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Project Structure](#project-structure)
4. [Pipeline](#pipeline)
5. [Queue System](#queue-system)
6. [Data Storage](#data-storage)
7. [File Storage](#file-storage)
8. [Frontend](#frontend)
9. [Roles & Access](#roles--access)
10. [Configuration](#configuration)
11. [Setup & Installation](#setup--installation)
12. [Running the App](#running-the-app)

---

## Overview

Audit Guru automates the expense invoice review workflow:

1. Admin uploads one or more PDF invoices — files go straight to **S3**, jobs land in **SQS**.
2. A background **queue worker** pulls each job, runs the audit pipeline (OCR → Validation → Audit), and writes results to **DynamoDB**.
3. Reviewers approve or reject flagged invoices in the dashboard. All decisions are captured in an immutable **audit trail**.
4. The Reports tab generates per-vendor, per-category, monthly, exception, and AI-written executive summaries.

**Tech stack:** Python · Streamlit · LangGraph · Groq (Llama 3.3 70B) · pdfplumber · FAISS · sentence-transformers · AWS S3 · AWS DynamoDB · AWS SQS · AWS SSM Parameter Store · Plotly · openpyxl

---

## Architecture

```
Browser (Streamlit UI)
        │
        │ 1. Upload PDFs
        ▼
   app.py (Upload tab)
        │
        ├─── upload_invoice() ──► S3 bucket (invoices/YYYY-MM-DD/<uuid>_file.pdf)
        ├─── save_queued_job() ─► DynamoDB (status = QUEUED)
        └─── send_job() ────────► SQS Queue (audit-guru-jobs)
                                        │
                              queue_worker.py (separate process)
                                        │
                              ┌─────────▼──────────┐
                              │  LangGraph Pipeline  │
                              │  OCR → Validate → Audit │
                              └─────────┬──────────┘
                                        │
                              update_queued_job() ──► DynamoDB (status = DONE)

UI polls DynamoDB for status updates (↻ Refresh button)
```

**CAP positioning: CP (Consistent + Partition Tolerant)**
- All DynamoDB reads use `ConsistentRead=True`
- All writes use optimistic locking via a `version` attribute + `ConditionExpression`
- Single boto3 resource per process (connection reuse)

---

## Project Structure

```
capstone/
├── app.py                       # Streamlit UI (5 tabs, login, role-based access)
├── pipeline.py                  # LangGraph pipeline definition
├── queue_worker.py              # SQS consumer — runs as a separate process
│
├── agents/
│   ├── ocr_agent.py             # PDF text extraction + LLM field extraction
│   ├── validation_agent.py      # Rule-based policy validation (no LLM)
│   ├── audit_agent.py           # LLM audit decision + RAG context
│   └── summarization_agent.py  # AI executive summary generator
│
├── rag/
│   ├── policy_rag.py            # Downloads policy from S3, builds FAISS index
│   └── __init__.py
│
├── data/
│   ├── expense_policy.txt       # Local fallback policy (authoritative copy is in S3)
│   └── faiss_index/             # Auto-generated vector index (gitignored)
│
├── db.py                        # DynamoDB persistence layer (CAP-compliant)
├── s3_store.py                  # S3 upload, presigned URL generation
├── sqs_queue.py                 # SQS send / receive / delete / depth
├── config.py                    # Loads secrets from SSM → falls back to .env
├── push_secrets.py              # One-time script: pushes .env → SSM Parameter Store
│
├── generate_test_invoices.py    # Generates fake PDF invoices for testing
├── test_pipeline.py             # Runs pipeline against a single test invoice
├── requirements.txt
├── .env                         # Local secrets (gitignored)
└── .env.example                 # Config template
```

---

## Pipeline

The pipeline is a LangGraph `StateGraph` that flows through three agents. State is a `TypedDict` (`PipelineState`). If any node sets `error`, downstream nodes skip.

### 1. OCR Agent — `agents/ocr_agent.py`

Extracts raw text from a PDF using `pdfplumber`, sends up to 3 000 characters to Groq to extract structured fields.

| Output field | Type | Description |
|---|---|---|
| `invoice_id` | str | Invoice number or `"UNKNOWN"` |
| `vendor` | str | Vendor / supplier name |
| `date` | str | Date in `YYYY-MM-DD` |
| `amount` | float | Total amount (no currency symbol) |
| `currency` | str | 3-letter code, default `"USD"` |
| `category` | str | Travel / Accommodation / Meals / Office Supplies / Software / Professional Services / Other |
| `line_items` | list | `[{description, amount}]` |
| `confidence` | float | 0.0 – 1.0 extraction confidence |

### 2. Validation Agent — `agents/validation_agent.py`

Pure Python — no LLM. Checks missing fields, duplicate detection, and policy violations.

| Flag | Trigger |
|---|---|
| `MISSING_FIELD:<field>` | Empty / UNKNOWN / 0 on required fields |
| `DUPLICATE_INVOICE_ID:<id>` | Exact invoice_id seen before |
| `POSSIBLE_DUPLICATE` | Same vendor + amount + date, different ID |
| `UNAPPROVED_CATEGORY:<cat>` | Category not in approved list |
| `EXCEEDS_LIMIT:<cat>` | Amount over category spending limit |
| `LATE_SUBMISSION:<n>_days` | Invoice date > 30 days ago |
| `REQUIRES_FINANCE_VP_APPROVAL` | Amount > $2 000 |
| `REQUIRES_DEPT_HEAD_APPROVAL` | Amount $500 – $2 000 |
| `REQUIRES_MANAGER_APPROVAL` | Amount $100 – $500 |

### 3. Audit Agent — `agents/audit_agent.py`

Queries the RAG store for relevant policy sections, then sends invoice + flags + policy context to Groq for a final audit decision.

| Output field | Type | Description |
|---|---|---|
| `audit_status` | str | `APPROVED` / `REJECTED` / `NEEDS_REVIEW` |
| `reasoning` | str | 2–4 sentence explanation |
| `recommendation` | str | One clear action |
| `confidence` | float | 0.0 – 1.0 |
| `policy_references` | list[str] | Policy sections cited |
| `risk_level` | str | `LOW` / `MEDIUM` / `HIGH` |

### 4. Summarization Agent — `agents/summarization_agent.py`

On-demand — called from the Reports tab. Aggregates spend stats and sends them to Groq to produce a 3–5 sentence executive summary narrative.

### RAG Policy Store — `rag/policy_rag.py`

On startup, downloads `config/expense_policy.txt` from S3, builds a FAISS vector index using `all-MiniLM-L6-v2`. Falls back to the local `data/expense_policy.txt` if S3 is unreachable. Index is cached to `data/faiss_index/` after the first build.

**To update the policy:** upload a new version to `s3://audit-guru-invoices/config/expense_policy.txt` and delete `data/faiss_index/`.

---

## Queue System

Bulk uploads are non-blocking. Files land in S3 and SQS in seconds; the worker processes them independently.

```
app.py (Upload tab)
  │
  ├── upload_invoice()    →  S3: invoices/YYYY-MM-DD/<uuid>_filename.pdf
  ├── save_queued_job()   →  DynamoDB: status = QUEUED
  └── send_job()         →  SQS: audit-guru-jobs

queue_worker.py (always-on background process)
  │
  ├── receive_job()       ←  SQS long-poll (10s)
  ├── set_job_status()    →  DynamoDB: status = PROCESSING
  ├── download from S3
  ├── process_invoice()   →  LangGraph pipeline
  ├── update_queued_job() →  DynamoDB: status = DONE (full OCR/audit data)
  └── delete_job()        →  SQS: message deleted
```

**Job status lifecycle:** `QUEUED` → `PROCESSING` → `DONE` / `ERROR`

The Upload tab shows a live status panel for in-flight jobs with a **↻ Refresh** button.

---

## Data Storage

### DynamoDB — `db.py`

**Table: `audit-invoices`** (PK: `id` UUID)

| Attribute | Description |
|---|---|
| `id` | UUID (partition key) |
| `version` | Optimistic lock counter (increments on every write) |
| `filename` | Original PDF filename |
| `invoice_id` | Extracted invoice number |
| `ocr_json` | Full OCR result (JSON) |
| `validation_json` | Validation result + flags (JSON) |
| `audit_json` | Audit decision + reasoning (JSON) |
| `corrections_json` | Manual field corrections by reviewer (JSON) |
| `review_decision` | `APPROVED` / `REJECTED` / empty |
| `review_notes` | Free-text reviewer notes |
| `s3_key` | Object key inside S3 bucket |
| `s3_url` | Canonical S3 URL |
| `queue_status` | `QUEUED` / `PROCESSING` / `DONE` / `ERROR` |
| `queue_error` | Error message if status = ERROR |
| `created_at` | ISO 8601 UTC timestamp |

**Table: `audit-trail`** (PK: `invoice_id`, SK: `timestamp`)

Immutable log of every action: `QUEUED`, `UPLOADED`, `CORRECTED`, `APPROVED`, `REJECTED`.

### Key functions

| Function | Description |
|---|---|
| `init_db()` | Creates both tables if they don't exist |
| `save_queued_job()` | Phase 1: creates placeholder record (status=QUEUED) |
| `update_queued_job()` | Phase 2: fills in pipeline results (status=DONE) |
| `set_job_status()` | Worker updates PROCESSING / ERROR |
| `load_all_results()` | Full table scan with strong consistency |
| `save_review()` | Optimistic-locked approval/rejection |
| `save_corrections()` | Saves manual field edits, logs CORRECTED event |
| `get_audit_trail()` | Queries trail by invoice_id |
| `log_action()` | Appends to audit trail |

---

## File Storage

**S3 bucket:** `audit-guru-invoices`

```
audit-guru-invoices/
  config/
    expense_policy.txt          ← expense policy (RAG source)
  invoices/
    YYYY-MM-DD/
      <uuid>_filename.pdf       ← uploaded invoice PDFs
```

PDF previews in the Invoices tab use **presigned URLs** (30-minute expiry) so the bucket stays private.

---

## Frontend

**File:** `app.py` · **Framework:** Streamlit · **URL:** `http://localhost:8501`

### Login

Dark navy login page. Three roles — Admin, Reviewer, Viewer. Credentials are configured via environment variables or AWS SSM Parameter Store. Contact your administrator for access.

### Tab 1 — Dashboard

Analytics only. KPI cards, 6 Plotly charts (spend by category, top vendors, status donut, risk bar, flag breakdown, amount vs confidence scatter).

### Tab 2 — Upload Invoice *(Admin only)*

- PDF magic-byte validation (rejects renamed non-PDFs)
- Multi-file uploader — queues all files instantly to S3 + SQS
- Live queue status panel showing QUEUED / PROCESSING / ERROR per file

### Tab 3 — Invoices

- Filter bar: status, risk level, category, vendor search, amount range
- Summary HTML table + CSV/XLSX export
- Per-invoice expander with 3 inner tabs:
  - **Details** — extracted data, validation flags, audit decision, PDF preview (iframe via presigned URL)
  - **Correct Fields** — editable form (Admin/Reviewer only), saves corrections + logs to audit trail
  - **Audit Trail** — timestamped event timeline

### Tab 4 — Review Queue

- Pending cases: case cards with AI reasoning, policy references, reviewer notes, Approve/Reject buttons
- Bulk Approve All / Reject All with optimistic locking conflict detection
- Decided cases shown in a compact list

### Tab 5 — Reports

- **KPI bar** + CSV/XLSX export
- **AI Executive Summary** — Groq-generated narrative (on-demand button)
- **Vendor Summary** — spend, invoice count, approved/rejected/flagged per vendor
- **Category Summary** — spend, %, avg invoice per category
- **Monthly Summary** — spend and flag count grouped by invoice month
- **Exception Summary** — amount at risk, high-risk exposure, violation type breakdown table
- **Invoice list** by status (Approved / Rejected / Pending)

---

## Roles & Access

| Feature | Admin | Reviewer | Viewer |
|---|---|---|---|
| Dashboard | ✓ | ✓ | ✓ |
| Upload Invoice | ✓ | — | — |
| Invoices (view) | ✓ | ✓ | ✓ |
| Correct Fields | ✓ | ✓ | — |
| Review Queue (view) | ✓ | ✓ | ✓ |
| Approve / Reject | ✓ | ✓ | — |
| Reports | ✓ | ✓ | ✓ |

---

## Configuration

Secrets load from **AWS SSM Parameter Store** when running on EC2 (no credentials needed — uses IAM role). Falls back to `.env` for local development. App validates all required vars at startup and fails fast with a clear error.

| Variable | Required | Description |
|---|---|---|
| `GROQ_API_KEY` | Yes | Groq API key |
| `GROQ_MODEL` | No | Default: `llama-3.3-70b-versatile` |
| `GROQ_MAX_TOKENS` | No | Default: `1024` |
| `AWS_ACCESS_KEY_ID` | Yes | IAM user access key |
| `AWS_SECRET_ACCESS_KEY` | Yes | IAM user secret key |
| `AWS_REGION` | Yes | Default: `us-east-1` |
| `S3_BUCKET_NAME` | Yes | Default: `audit-guru-invoices` |
| `DYNAMODB_TABLE_NAME` | No | Default: `audit-invoices` |
| `SQS_QUEUE_NAME` | No | Default: `audit-guru-jobs` |
| `ADMIN_PASSWORD` | Yes | Admin account password |
| `REVIEWER_PASSWORD` | Yes | Reviewer account password |
| `VIEWER_PASSWORD` | Yes | Viewer account password |
| `APP_NAME` | No | Default: `Audit Guru` |

**Push secrets to SSM (run once):**

```bash
python push_secrets.py
```

---

## Setup & Installation

### Prerequisites

- Python 3.11+
- Groq API key — [console.groq.com](https://console.groq.com)
- AWS account with:
  - S3 bucket: `audit-guru-invoices`
  - DynamoDB tables auto-created by `init_db()` on first run
  - SQS queue auto-created by `sqs_queue.py` on first run
  - IAM user with S3, DynamoDB, SQS full access

### Steps

```bash
# 1. Clone and enter the project
cd capstone

# 2. Create virtual environment
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS / Linux

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
copy .env.example .env
# Fill in GROQ_API_KEY, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION, S3_BUCKET_NAME

# 5. (Optional) Push secrets to SSM for EC2 use
python push_secrets.py

# 6. Pre-build FAISS index
python -c "from rag.policy_rag import get_policy_context; print('RAG ready')"
```

---

## Running the App

Two processes must run simultaneously — the Streamlit UI and the queue worker.

**Terminal 1 — UI:**
```bash
streamlit run app.py
```

**Terminal 2 — Queue worker:**
```bash
python queue_worker.py
```

Open `http://localhost:8501` and log in as `admin` / `admin123`.

### On EC2 (production)

Run both as systemd services so they restart automatically on crash. A service template is included as a comment at the top of `queue_worker.py`.

```bash
# Copy and enable the worker service
sudo cp queue_worker.service /etc/systemd/system/
sudo systemctl enable --now queue_worker

# Run Streamlit
streamlit run app.py --server.port 8501 --server.headless true
```
