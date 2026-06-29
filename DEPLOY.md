# Deploying AnomaGuard on AWS EC2

This guide deploys the full system on a single EC2 instance. The app is AWS-native:
PDFs live in **S3**, jobs flow through **SQS**, results and the audit trail live in
**DynamoDB**, and secrets come from **SSM Parameter Store** via an instance IAM role
(no secrets on disk).

```
                ┌────────────────── EC2 instance ──────────────────┐
   Browser ───▶ │  Streamlit (app.py, :8501) ──put──▶ SQS queue    │
                │                                        │          │
                │  Queue worker (queue_worker.py) ◀──poll┘          │
                │     │  download PDF        write results          │
                └─────┼──────────────────────────┼──────────────────┘
                      ▼                           ▼
                  S3 bucket                   DynamoDB
              anomaguard-invoices      audit-invoices / audit-trail
```

The two processes run as **systemd** services so they restart on crash and on reboot.

---

## 1. Provision AWS resources

You can let the app create S3/SQS/DynamoDB on first use (the code calls
`ensure_bucket`, `create_queue`, and `create_table` when missing), **or** pre-create them.
Names must match the defaults in the code (override via SSM if you change them):

| Resource | Name | Created by |
|---|---|---|
| S3 bucket | `anomaguard-invoices` | `s3_store.ensure_bucket()` |
| SQS queue | `anomaguard-jobs` (visibility timeout 300s) | `sqs_queue.get_queue_url()` |
| DynamoDB table | `audit-invoices` (PK `id`, on-demand) | `db.init_db()` |
| DynamoDB table | `audit-trail` (PK `invoice_id`, SK `timestamp`) | `db.init_db()` |

## 2. Create the IAM role

Create an IAM role for EC2 using the least-privilege policy in
[`deploy/iam-policy.json`](deploy/iam-policy.json) (SSM read, S3 on the invoice bucket,
SQS on the job queue, DynamoDB on the two tables). Attach it to the instance in step 4.

## 3. Store configuration in SSM Parameter Store

`config.py` loads every `/anomaguard/*` parameter into the environment at startup
(decrypting SecureStrings) and falls back to `.env` only for local dev. Create:

```bash
aws ssm put-parameter --name /anomaguard/GROQ_API_KEY   --type SecureString --value "gsk_your_real_key"
aws ssm put-parameter --name /anomaguard/GROQ_MODEL      --type String --value "llama-3.3-70b-versatile"
aws ssm put-parameter --name /anomaguard/S3_BUCKET_NAME  --type String --value "anomaguard-invoices"
aws ssm put-parameter --name /anomaguard/APP_NAME        --type String --value "AnomaGuard"
# App login passwords (optional — defaults exist in app.py):
aws ssm put-parameter --name /anomaguard/ADMIN_PASSWORD  --type SecureString --value "<set-a-strong-one>"
```

`AWS_REGION` is provided by the systemd unit files; on EC2 the IAM role supplies
credentials, so `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` are **not** needed.

> Note: `config.py` currently lists `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` as
> required. On an instance using the IAM role, drop those two from the `_REQUIRED`
> list (the role provides credentials automatically) or set placeholder SSM values.

## 4. Launch the EC2 instance

- **AMI:** Amazon Linux 2023 · **Type:** t3.medium (the embedding model for RAG wants ~2 GB RAM)
- **IAM instance profile:** the role from step 2
- **Security group:** inbound TCP **22** (SSH, your IP) and **8501** (Streamlit, your IP)

## 5. Deploy the app

```bash
ssh ec2-user@<public-ip>
git clone <your-repo-url> anomaguard
cd anomaguard
bash deploy/setup-ec2.sh
```

[`deploy/setup-ec2.sh`](deploy/setup-ec2.sh) installs Python 3.11, builds the venv,
pre-builds the FAISS policy index, installs the two systemd units, and starts them:

- [`deploy/anomaguard-web.service`](deploy/anomaguard-web.service) — Streamlit on `0.0.0.0:8501`
- [`deploy/anomaguard-worker.service`](deploy/anomaguard-worker.service) — `queue_worker.py`

## 6. Verify

```bash
sudo systemctl status anomaguard-web anomaguard-worker
journalctl -u anomaguard-worker -f          # watch jobs being processed
```

Open `http://<public-ip>:8501`, sign in as `admin` / `admin123` (change this in SSM),
upload a PDF from `data/invoices/` or `data/reimbursements/`, and confirm it moves
QUEUED → PROCESSING → DONE and appears on the Dashboard.

## Operations

```bash
sudo systemctl restart anomaguard-web      # after a code change + git pull
git pull && sudo systemctl restart anomaguard-web anomaguard-worker
```

To scale throughput, run the worker on additional instances pointed at the same SQS
queue — SQS distributes jobs across all workers automatically.

## Cost note

S3, SQS, and on-demand DynamoDB cost cents at this volume; the main cost is the EC2
instance. Stop the instance when idle. Groq API usage is billed separately by Groq.
