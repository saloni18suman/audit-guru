"""
Run once: pushes all .env values to AWS SSM Parameter Store as SecureStrings.
Usage: python push_secrets.py
"""
import boto3, os
from dotenv import dotenv_values, load_dotenv

load_dotenv()
secrets = dotenv_values(".env")

ssm = boto3.client("ssm",
    region_name=secrets.get("AWS_REGION", "us-east-1"),
    aws_access_key_id=secrets.get("AWS_ACCESS_KEY_ID"),
    aws_secret_access_key=secrets.get("AWS_SECRET_ACCESS_KEY"),
)
PREFIX = "/anomaguard"

for key, value in secrets.items():
    if not value:
        continue
    name = f"{PREFIX}/{key}"
    ssm.put_parameter(
        Name=name,
        Value=value,
        Type="SecureString",
        Overwrite=True,
    )
    print(f"  stored {name}")

print("\nAll secrets pushed to SSM Parameter Store.")
print(f"Prefix: {PREFIX}")
