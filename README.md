# Audit Guru — AI Expense Audit Assistant

AI-powered expense-audit system that processes PDF invoices and employee reimbursement
forms through an **OCR → Validation → Audit** agent pipeline, generates AI expense
summaries, and presents everything in a role-based review dashboard.

Built for **RFP Theme 14 — AI Expense Audit Assistant**: expense auditing takes
significant manual effort, so this tool automates extraction, duplicate detection,
policy-violation detection, AI summarization, and human-in-the-loop review.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Project Structure](#project-structure)
4. [Pipeline (Agents)](#pipeline-agents)
5. [AI Expense Summarization](#ai-expense-summarization)
6. [Data Storage (AWS)](#data-storage-aws)
7. [Frontend](#frontend)
8. [Test Data Generators](#test-data-generators)
9. [Configuration](#configuration)
10. [Setup & Local Run](#setup--local-run)
11. [AWS EC2 Deployment](#aws-ec2-deployment)
12. [API Reference](#api-reference)

---

## Overview

1. An admin uploads one or more PDF documents (vendor invoices **or** employee
   reimbursement forms).
2. Each file is stored in **S3** and a job is placed on an **SQS** queue.
3. A **queue worker** runs the LangGraph pipeline: OCR extracts structured fields,
   the Validation Agent applies policy rules (missing fields, duplicates, limits), and
   the Audit Agent makes an LLM decision enriched with company-policy context via RAG.
4. Results and an immutable audit trail are persisted in **DynamoDB**.
5. The dashboard shows KPIs and charts, a filterable invoice table, a human review
   queue for flagged items, and an **AI-generated expense summary**.

**RFP Theme 14 coverage**

| Requirement | Where |
|---|---|
| Synthetic invoices | `generate_test_invoices.py` |
| Fake reimbursement forms | `generate_test_reimbursements.py` |
| Expense summarization | `agents/summary_agent.py` → Reports tab |
| Duplicate detection | `agents/validation_agent.py` |
| Policy violation detection | `agents/validation_agent.py` + RAG (`rag/policy_rag.py`) |
| OCR / Validation / Audit agents | `agents/` |
| Sequential workflow | `pipeline.py` (LangGraph, linear) |
| AWS EC2 deployment | `DEPLOY.md`, `deploy/` |

**Tech stack:** Python · Streamlit · LangGraph · Groq (Llama 3.3 70B) · pdfplumber ·
FAISS · sentence-transformers · AWS S3 / SQS / DynamoDB / SSM · boto3 · Plotly · reportlab

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                    Streamlit UI (app.py)                       │
│   Dashboard │ Upload │ Invoices │ Review Queue │ Reports       │
│   (role-based: Admin / Reviewer / Viewer)                      │
└───────────┬───────────────────────────────────┬───────────────┘
            │ upload → S3 + enqueue              │ read results
            ▼                                    ▼
       SQS queue  ──poll──▶  Queue Worker     DynamoDB
   (audit-guru-jobs)        (queue_worker.py)  ├─ audit-invoices
                                  │             └─ audit-trail
                                  ▼
            ┌───────── LangGraph Pipeline (pipeline.py) ─────────┐
            │   ┌─────┐    ┌────────────┐    ┌─────────────┐     │
            │   │ OCR │──▶ │ Validation │──▶ │    Audit    │     │
            │   └──┬──┘    └─────┬──────┘    └──────┬──────┘     │
            │  pdfplumber   policy rules        Groq LLM         │
            │  + Groq LLM                       + RAG (FAISS)    │
            └────────────────────────────────────────────────────┘
```

Pipeline state flows through a `TypedDict` (`PipelineState`). Each node enriches the
state and passes it on; if any node sets `error`, downstream nodes skip processing.
Upload/processing are **decoupled via SQS**, so the UI stays responsive and the worker
can be scaled horizontally.

For local development you can point S3/SQS/DynamoDB at LocalStack via the
`*_ENDPOINT_URL` env vars; in production they are real AWS services.

---

## Project Structure

```
audit-guru/
├── app.py                       # Streamlit frontend (5 tabs, role-based auth)
├── pipeline.py                  # LangGraph pipeline (OCR → Validation → Audit)
├── queue_worker.py              # SQS consumer: runs the pipeline, writes results
├── config.py                   # Config loader (SSM on EC2, .env locally)
├── db.py                        # DynamoDB persistence + audit trail
├── s3_store.py                  # S3 upload / presigned URLs
├── sqs_queue.py                 # SQS send/receive
├── main.py                      # Groq connectivity smoke test
├── agents/
│   ├── ocr_agent.py             # PDF text extraction + LLM field extraction
│   ├── validation_agent.py      # Rule-based policy validation (no LLM)
│   ├── audit_agent.py           # LLM audit decision + RAG context
│   └── summary_agent.py         # LLM expense summarization (batch-level)
├── rag/
│   └── policy_rag.py            # FAISS vector store + similarity search
├── data/
│   ├── expense_policy.txt       # Company policy document (RAG source)
│   ├── invoices/                # Generated synthetic invoices
│   └── reimbursements/          # Generated reimbursement forms
├── deploy/                      # systemd units, IAM policy, EC2 bootstrap
├── generate_test_invoices.py    # 20 synthetic invoice PDFs
├── generate_test_reimbursements.py  # 6 reimbursement-form PDFs
├── DEPLOY.md                    # AWS EC2 deployment guide
├── requirements.txt
└── .env.example                 # Config template (no real secrets)
```

---

## Pipeline (Agents)

### 1. OCR Agent — `agents/ocr_agent.py`
Extracts raw text with `pdfplumber`, sends up to 3 000 characters to the Groq LLM, and
returns structured fields: `invoice_id`, `vendor`, `date`, `amount`, `currency`,
`category`, `line_items`, `confidence`, `raw_text`, `source_file`.

### 2. Validation Agent — `agents/validation_agent.py`
Pure Python, no LLM. Runs three checks:
- **Missing fields** — `MISSING_FIELD:<field>`
- **Duplicates** — `DUPLICATE_INVOICE_ID:<id>` or `POSSIBLE_DUPLICATE:same_vendor_amount_date`
- **Policy violations** — unapproved category, per-category spend limits, late submission
  (>30 days), and approval-tier flags by amount.

Category limits: Meals $150 · Accommodation $300 · Office Supplies $500 · Software $2 000 ·
Travel $5 000 · Professional Services $10 000.
Output: `validation_status` (PASSED/WARNING/FAILED), `flags`, `critical_flags`,
`warning_flags`, `flag_count`.

### 3. Audit Agent — `agents/audit_agent.py`
Queries the RAG store for relevant policy sections, then sends invoice data +
validation flags + policy context to the Groq LLM. Output: `audit_status`
(APPROVED/REJECTED/NEEDS_REVIEW), `reasoning`, `recommendation`, `confidence`,
`policy_references`, `risk_level`.

### RAG Policy Store — `rag/policy_rag.py`
Loads `data/expense_policy.txt`, builds a FAISS index with sentence-transformers
(`all-MiniLM-L6-v2`), cached on first run. `get_policy_context(query, k=4)` returns the
top policy chunks injected into the Audit Agent prompt.

### 4. Summarization Agent — `agents/summarization_agent.py`

## AI Expense Summarization

`agents/summary_agent.py` provides the **expense summarization** feature. It aggregates
a batch of processed documents *deterministically in Python* (totals, spend by category
and vendor, duplicate count, policy flags, high-risk count, average confidence, date
range) and then has the Groq LLM write an executive narrative from those exact figures —
so the numbers are always correct and the model never does arithmetic.

- `run_summary_agent(results)` → `{"narrative": <markdown>, "stats": <dict>}`
- Surfaced in the **Reports** tab via the “✨ Generate” button, with metric chips and a
  downloadable `expense_summary.md`.

**File:** `app.py` · **Framework:** Streamlit · **URL:** `http://localhost:8501`

## Data Storage (AWS)

**DynamoDB** (`db.py`) — CP-positioned (consistent reads, optimistic locking via a
`version` attribute):
- `audit-invoices` — one record per document (OCR/validation/audit JSON, review decision,
  corrections, S3 pointer, queue status). PK `id` (UUID).
- `audit-trail` — immutable action log (QUEUED, UPLOADED, CORRECTED, APPROVED, …).
  PK `invoice_id`, SK `timestamp`.

**S3** (`s3_store.py`) — invoice PDFs under `invoices/YYYY-MM-DD/<uuid>_<file>`; presigned
URLs power the in-app PDF preview.

**SQS** (`sqs_queue.py`) — `audit-guru-jobs` decouples upload from processing.

Tables, bucket, and queue are auto-created on first use if missing.

### Tab 5 — Reports

- **KPI bar** + CSV/XLSX export
- **AI Executive Summary** — Groq-generated narrative (on-demand button)
- **Vendor Summary** — spend, invoice count, approved/rejected/flagged per vendor
- **Category Summary** — spend, %, avg invoice per category
- **Monthly Summary** — spend and flag count grouped by invoice month
- **Exception Summary** — amount at risk, high-risk exposure, violation type breakdown table
- **Invoice list** by status (Approved / Rejected / Pending)

`app.py` · Streamlit · `http://localhost:8501`. Role-based login (Admin / Reviewer /
Viewer; defaults in `app.py`, override via env/SSM).

- **Dashboard** — primary & secondary KPIs; Plotly charts (spend by category, top
  vendors, status donut, risk bars, flag breakdown, amount-vs-confidence scatter).
- **Upload** (Admin) — multi-file PDF upload → S3 + SQS, with a live queue-status panel.
- **Invoices** — filterable table (status/risk/category/vendor/amount), per-document
  detail with PDF preview, field correction, and audit trail; CSV/XLSX export.
- **Review Queue** — case cards for `NEEDS_REVIEW` items with AI reasoning and
  Approve/Reject (single or bulk), with optimistic-lock conflict handling.
- **Reports** — value totals, grouped approved/rejected/pending lists, CSV export, and
  the **AI Expense Summary**.

---

## Test Data Generators

```bash
python generate_test_invoices.py        # 20 invoices → data/invoices/
python generate_test_reimbursements.py  # 6 reimbursement forms → data/reimbursements/
```

Both cover valid, duplicate, and policy-violation scenarios so the full pipeline can be
exercised end-to-end. (Both require `reportlab`, included in `requirements.txt`.)

---

## Configuration

All config lives in `.env` locally (copy `.env.example`) or in **SSM Parameter Store**
under `/audit-guru/*` on EC2 (`config.py` loads SSM first, then validates).

| Variable | Required | Description |
|---|---|---|
| `GROQ_API_KEY` | — | **Required.** Groq API key |
| `GROQ_MODEL` | `llama-3.3-70b-versatile` | Model for OCR, Audit, Summary agents |
| `GROQ_MAX_TOKENS` | `1024` | Max tokens per LLM response |
| `APP_NAME` | `Audit Guru` | Display name |
| `AWS_REGION` | `us-east-1` | AWS region |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | — | Local dev only; omit on EC2 (IAM role) |
| `S3_BUCKET_NAME` | `audit-guru-invoices` | Invoice PDF bucket |
| `DYNAMODB_TABLE_NAME` | `audit-invoices` | Results table |
| `SQS_QUEUE_NAME` | `audit-guru-jobs` | Job queue |
| `*_ENDPOINT_URL` | — | Optional LocalStack endpoints for local dev |
| `ADMIN_PASSWORD` / `REVIEWER_PASSWORD` / `VIEWER_PASSWORD` | dev defaults | App login passwords |

To switch to a faster/cheaper model: `GROQ_MODEL=llama-3.1-8b-instant`.

---

## Setup & Local Run

### Prerequisites
- Python 3.11+
- A free Groq API key from [console.groq.com](https://console.groq.com)
- AWS credentials (real AWS) **or** Docker + LocalStack for a fully local stack

```bash
# 1. Create and activate a virtual environment
python -m venv venv
venv\Scripts\activate            # Windows
# source venv/bin/activate       # macOS / Linux

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure
copy .env.example .env           # Windows  (cp on macOS/Linux)
#   add GROQ_API_KEY and AWS creds (or LocalStack endpoints)

# 4. Verify LLM connectivity
python main.py                   # prints "Audit Guru LLM OK"

# 5. Generate test data (optional)
python generate_test_invoices.py
python generate_test_reimbursements.py

# 6. Start the worker (separate terminal) and the app
python queue_worker.py
streamlit run app.py
```

Open `http://localhost:8501` and sign in as `admin` / `admin123`.

> The queue worker must be running for uploads to move from QUEUED → DONE.

---

## AWS EC2 Deployment

See **[DEPLOY.md](DEPLOY.md)** for the full guide: IAM role
([`deploy/iam-policy.json`](deploy/iam-policy.json)), SSM parameters, S3/SQS/DynamoDB,
and the two **systemd** services
([`deploy/audit-guru-web.service`](deploy/audit-guru-web.service),
[`deploy/audit-guru-worker.service`](deploy/audit-guru-worker.service)) installed by
[`deploy/setup-ec2.sh`](deploy/setup-ec2.sh).

---

## API Reference

```python
from pipeline import process_invoice
state = process_invoice("invoice.pdf", previously_processed_list)
# keys: pdf_path, ocr_result, validation_result, audit_result, error

from agents.summary_agent import run_summary_agent
summary = run_summary_agent(load_all_results())   # {"narrative": ..., "stats": ...}

from db import save_queued_job, update_queued_job, load_all_results, save_review
from s3_store import upload_invoice, get_presigned_url
from sqs_queue import send_job, receive_job
from rag.policy_rag import get_policy_context
```
