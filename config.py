"""
Loads config from AWS SSM Parameter Store when running on EC2,
falls back to .env for local development.
"""
import os
import boto3
from dotenv import load_dotenv

SSM_PREFIX = "/audit-guru"


def _load_from_ssm():
    try:
        ssm = boto3.client("ssm", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        paginator = ssm.get_paginator("get_parameters_by_path")
        for page in paginator.paginate(Path=SSM_PREFIX, WithDecryption=True):
            for param in page["Parameters"]:
                key = param["Name"].replace(f"{SSM_PREFIX}/", "")
                if key not in os.environ:
                    os.environ[key] = param["Value"]
        return True
    except Exception:
        return False


def load_config():
    # Try SSM first (works on EC2 with IAM role, no credentials needed)
    if _load_from_ssm():
        return
    # Fall back to .env for local development
    load_dotenv()
