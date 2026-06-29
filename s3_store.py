"""
S3 storage for invoice PDFs.
Works with real AWS S3 (no endpoint) or LocalStack (set S3_ENDPOINT_URL).
"""

import os
import uuid
from datetime import date
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

_ENDPOINT   = os.environ.get("S3_ENDPOINT_URL") or None   # None → real AWS
_BUCKET     = os.environ.get("S3_BUCKET_NAME",  "audit-guru-invoices")
_REGION     = os.environ.get("AWS_REGION",       "us-east-1")
_ACCESS_KEY = os.environ.get("AWS_ACCESS_KEY_ID")     or None
_SECRET_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY") or None


def _client():
    return boto3.client(
        "s3",
        endpoint_url=_ENDPOINT,
        aws_access_key_id=_ACCESS_KEY,
        aws_secret_access_key=_SECRET_KEY,
        region_name=_REGION,
        config=Config(connect_timeout=3, read_timeout=10, retries={"max_attempts": 2}),
    )


def _s3_url(key: str) -> str:
    """Return the canonical URL for an S3 object."""
    if _ENDPOINT:
        # LocalStack / custom endpoint
        return f"{_ENDPOINT}/{_BUCKET}/{key}"
    # Real AWS virtual-hosted URL
    return f"https://{_BUCKET}.s3.{_REGION}.amazonaws.com/{key}"


def ensure_bucket() -> None:
    s3 = _client()
    try:
        s3.head_bucket(Bucket=_BUCKET)
    except ClientError:
        try:
            if _REGION == "us-east-1":
                s3.create_bucket(Bucket=_BUCKET)
            else:
                s3.create_bucket(
                    Bucket=_BUCKET,
                    CreateBucketConfiguration={"LocationConstraint": _REGION},
                )
        except ClientError as e:
            if e.response["Error"]["Code"] not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                raise


def upload_invoice(file_bytes: bytes, filename: str) -> tuple[str, str]:
    """
    Upload PDF bytes to S3 under invoices/YYYY-MM-DD/<uuid>_<filename>.
    Returns (s3_key, s3_url).
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
    return key, _s3_url(key)


def get_presigned_url(s3_key: str, expires_in: int = 3600) -> str:
    """Generate a pre-signed URL valid for expires_in seconds (default 1 hour)."""
    return _client().generate_presigned_url(
        "get_object",
        Params={"Bucket": _BUCKET, "Key": s3_key},
        ExpiresIn=expires_in,
    )


def delete_object(s3_key: str) -> None:
    _client().delete_object(Bucket=_BUCKET, Key=s3_key)


def is_available() -> bool:
    try:
        _client().list_buckets()
        return True
    except Exception:
        return False
