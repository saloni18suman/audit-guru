"""
SQS queue operations for the invoice processing pipeline.
Queue name: anomaguard-jobs (standard queue, not FIFO)
"""

import json
import logging
import os

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

_QUEUE_NAME = os.environ.get("SQS_QUEUE_NAME", "anomaguard-jobs")
_REGION     = os.environ.get("AWS_REGION",      "us-east-1")
_ACCESS_KEY = os.environ.get("AWS_ACCESS_KEY_ID")     or None
_SECRET_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY") or None
_ENDPOINT   = os.environ.get("SQS_ENDPOINT_URL") or None

_CFG = Config(connect_timeout=5, read_timeout=10, retries={"max_attempts": 3})

_queue_url_cache: str | None = None


def _client():
    return boto3.client(
        "sqs",
        endpoint_url=_ENDPOINT,
        region_name=_REGION,
        aws_access_key_id=_ACCESS_KEY,
        aws_secret_access_key=_SECRET_KEY,
        config=_CFG,
    )


def get_queue_url() -> str:
    global _queue_url_cache
    if _queue_url_cache:
        return _queue_url_cache
    sqs = _client()
    try:
        resp = sqs.get_queue_url(QueueName=_QUEUE_NAME)
        _queue_url_cache = resp["QueueUrl"]
    except ClientError as e:
        if e.response["Error"]["Code"] == "AWS.SimpleQueueService.NonExistentQueue":
            resp = sqs.create_queue(
                QueueName=_QUEUE_NAME,
                Attributes={"VisibilityTimeout": "300"},  # 5 min — max pipeline time
            )
            _queue_url_cache = resp["QueueUrl"]
            logger.info("Created SQS queue: %s", _QUEUE_NAME)
        else:
            raise
    return _queue_url_cache


def send_job(db_id: str, filename: str, s3_key: str, s3_url: str) -> str:
    """Enqueue one invoice processing job. Returns SQS message ID."""
    body = json.dumps({
        "db_id":    db_id,
        "filename": filename,
        "s3_key":   s3_key,
        "s3_url":   s3_url,
    })
    resp = _client().send_message(QueueUrl=get_queue_url(), MessageBody=body)
    logger.info("Queued job %s (msg %s)", db_id, resp["MessageId"])
    return resp["MessageId"]


def receive_job(wait_seconds: int = 10) -> dict | None:
    """
    Long-poll for one message. Returns the raw SQS message dict or None.
    Caller must call delete_job() after successful processing.
    """
    resp = _client().receive_message(
        QueueUrl=get_queue_url(),
        MaxNumberOfMessages=1,
        WaitTimeSeconds=wait_seconds,
        AttributeNames=["ApproximateReceiveCount"],
    )
    messages = resp.get("Messages", [])
    return messages[0] if messages else None


def delete_job(receipt_handle: str) -> None:
    _client().delete_message(
        QueueUrl=get_queue_url(),
        ReceiptHandle=receipt_handle,
    )


def queue_depth() -> int:
    """Approximate number of messages visible in the queue."""
    try:
        resp = _client().get_queue_attributes(
            QueueUrl=get_queue_url(),
            AttributeNames=["ApproximateNumberOfMessages"],
        )
        return int(resp["Attributes"].get("ApproximateNumberOfMessages", 0))
    except Exception:
        return 0
