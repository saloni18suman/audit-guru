"""
S3 storage for invoice PDFs via LocalStack.
Bucket and credentials are configured through environment variables.
"""

import os
import uuid
from datetime import date
from dotenv import load_dotenv
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

load_dotenv()

_ENDPOINT   = os.environ.get("S3_ENDPOINT_URL")       or None   # None → real AWS
_BUCKET     = os.environ.get("S3_BUCKET_NAME",         "audit-guru-invoices")
_REGION     = os.environ.get("AWS_REGION",              "us-east-1")
_ACCESS_KEY = os.environ.get("AWS_ACCESS_KEY_ID")      or None
_SECRET_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY")  or None


def _client():
    return boto3.client(
        "s3",
        endpoint_url=_ENDPOINT,
        aws_access_key_id=_ACCESS_KEY,
        aws_secret_access_key=_SECRET_KEY,
        region_name=_REGION,
        config=Config(connect_timeout=2, read_timeout=5, retries={"max_attempts": 1}),
    )


def ensure_bucket() -> None:
    s3 = _client()
    try:
        s3.head_bucket(Bucket=_BUCKET)
    except ClientError:
        try:
            s3.create_bucket(Bucket=_BUCKET)
        except ClientError as e:
            # Ignore "already exists" responses from MinIO
            if e.response["Error"]["Code"] not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                raise


def upload_invoice(file_bytes: bytes, filename: str) -> tuple[str, str]:
    """
    Upload raw PDF bytes to S3.
    Returns (s3_key, s3_url).
    s3_key  — the object key inside the bucket
    s3_url  — direct URL to the object via the LocalStack endpoint
    """
    s3 = _client()
    ensure_bucket()

    key = f"invoices/{date.today().isoformat()}/{uuid.uuid4().hex}_{filename}"
    s3.put_object(
        Bucket=_BUCKET,
        Key=key,
        Body=file_bytes,
        ContentType="application/pdf",
        Metadata={"original_filename": filename},
    )
    url = f"{_ENDPOINT}/{_BUCKET}/{key}"
    return key, url


def get_download_url(s3_key: str, expires_in: int = 3600) -> str:
    """Generate a pre-signed download URL (valid for expires_in seconds)."""
    s3 = _client()
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": _BUCKET, "Key": s3_key},
        ExpiresIn=expires_in,
    )


def delete_object(s3_key: str) -> None:
    """Remove an object from the bucket."""
    _client().delete_object(Bucket=_BUCKET, Key=s3_key)


def is_available() -> bool:
    """Return True if LocalStack S3 is reachable."""
    try:
        _client().list_buckets()
        return True
    except Exception:
        return False
