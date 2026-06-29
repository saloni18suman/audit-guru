"""
Invoice queue worker — run as a separate process alongside app.py.

    python queue_worker.py

Polls SQS for jobs, downloads the PDF from S3, runs the audit pipeline,
and writes results back to DynamoDB.

On EC2: run as a systemd service (see below) so it restarts on crash.

    [Unit]
    Description=AnomaGuard Queue Worker
    After=network.target

    [Service]
    WorkingDirectory=/home/ec2-user/audit-guru
    ExecStart=/home/ec2-user/audit-guru/venv/bin/python queue_worker.py
    Restart=always
    RestartSec=5

    [Install]
    WantedBy=multi-user.target
"""

import json
import logging
import os
import signal
import sys
import tempfile
import time

import boto3

from config import load_config

load_config()

from db import set_job_status, update_queued_job, load_all_results
from pipeline import process_invoice
from sqs_queue import delete_job, receive_job

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("queue_worker")

_BUCKET     = os.environ.get("S3_BUCKET_NAME",  "audit-guru-invoices")
_REGION     = os.environ.get("AWS_REGION",       "us-east-1")
_ACCESS_KEY = os.environ.get("AWS_ACCESS_KEY_ID")     or None
_SECRET_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY") or None

_running = True


def _s3():
    return boto3.client(
        "s3",
        region_name=_REGION,
        aws_access_key_id=_ACCESS_KEY,
        aws_secret_access_key=_SECRET_KEY,
    )


def _handle_job(message: dict) -> None:
    body    = json.loads(message["Body"])
    db_id   = body["db_id"]
    s3_key  = body["s3_key"]
    filename= body["filename"]

    logger.info("Processing job %s (%s)", db_id, filename)
    set_job_status(db_id, "PROCESSING")

    tmp_path = None
    try:
        # Download PDF from S3 to a temp file
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        _s3().download_fileobj(_BUCKET, s3_key, tmp)
        tmp.close()
        tmp_path = tmp.name

        # Build the list of already-processed invoices so the Validation Agent can
        # detect duplicates. The worker handles each SQS job independently, so this
        # context must come from DynamoDB (not in-memory). Exclude this job's own
        # placeholder record and any without a real extracted invoice_id.
        prior_invoices = [
            r["ocr"] for r in load_all_results()
            if r["db_id"] != db_id
            and r.get("ocr", {}).get("invoice_id", "UNKNOWN") not in ("UNKNOWN", "QUEUED", None, "")
        ]

        # Run the full audit pipeline
        state = process_invoice(tmp_path, prior_invoices)

        result = {
            "filename":   filename,
            "ocr":        state.get("ocr_result", {}),
            "validation": state.get("validation_result", {}),
            "audit":      state.get("audit_result", {}),
        }
        update_queued_job(db_id, result)
        logger.info("Job %s done — status: %s", db_id, result["audit"].get("audit_status", "?"))

    except Exception as exc:
        logger.exception("Job %s failed", db_id)
        set_job_status(db_id, "ERROR", str(exc))
        # Don't re-raise — delete the message so it doesn't loop forever

    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _shutdown(sig, frame):
    global _running
    logger.info("Shutdown signal received — finishing current job then exiting.")
    _running = False


def main():
    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT,  _shutdown)
    logger.info("Queue worker started — polling SQS for jobs…")

    while _running:
        try:
            message = receive_job(wait_seconds=10)   # long-poll, up to 10s
            if message:
                _handle_job(message)
                delete_job(message["ReceiptHandle"])
            else:
                logger.debug("No messages — waiting…")
        except Exception:
            logger.exception("Unexpected worker error — retrying in 5s")
            time.sleep(5)

    logger.info("Worker stopped.")


if __name__ == "__main__":
    main()
