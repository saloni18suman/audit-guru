"""
Loads config from AWS SSM Parameter Store (EC2 with IAM role),
falls back to .env for local development.
Validates required env vars at startup to fail fast with clear errors.
"""

import logging
import os

import boto3
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

SSM_PREFIX = "/audit-guru"

_REQUIRED = [
    "GROQ_API_KEY",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_REGION",
    "S3_BUCKET_NAME",
]


def _load_from_ssm() -> bool:
    try:
        ssm = boto3.client("ssm", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        paginator = ssm.get_paginator("get_parameters_by_path")
        for page in paginator.paginate(Path=SSM_PREFIX, WithDecryption=True):
            for param in page["Parameters"]:
                key = param["Name"].replace(f"{SSM_PREFIX}/", "")
                if key not in os.environ:
                    os.environ[key] = param["Value"]
        logger.info("Config loaded from SSM (%s)", SSM_PREFIX)
        return True
    except Exception as exc:
        logger.debug("SSM unavailable (%s), falling back to .env", exc)
        return False


def _validate() -> None:
    missing = [k for k in _REQUIRED if not os.environ.get(k)]
    if missing:
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing)}. "
            "Set them in .env (local) or SSM Parameter Store (EC2)."
        )


def load_config() -> None:
    if not _load_from_ssm():
        load_dotenv()
    _validate()
