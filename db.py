"""
Persistence layer — DynamoDB via amazon/dynamodb-local or LocalStack.
Two tables:
  audit-invoices  — invoice records (partition key: id UUID)
  audit-trail     — immutable action log (partition key: invoice_id, sort key: timestamp)
"""

import json
import os
import uuid
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Key
from botocore.config import Config
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv()

_ENDPOINT    = os.environ.get("DYNAMODB_ENDPOINT_URL") or None   # None → real AWS
_TABLE_NAME  = os.environ.get("DYNAMODB_TABLE_NAME",   "audit-invoices")
_TRAIL_TABLE = "audit-trail"
_REGION      = os.environ.get("AWS_REGION",             "us-east-1")
_ACCESS_KEY  = os.environ.get("AWS_ACCESS_KEY_ID")  or None
_SECRET_KEY  = os.environ.get("AWS_SECRET_ACCESS_KEY") or None

_CFG = Config(connect_timeout=3, retries={"max_attempts": 1})


def _resource():
    return boto3.resource(
        "dynamodb",
        endpoint_url=_ENDPOINT,
        region_name=_REGION,
        aws_access_key_id=_ACCESS_KEY,
        aws_secret_access_key=_SECRET_KEY,
        config=_CFG,
    )


def _create_table_safe(name, key_schema, attr_defs):
    try:
        _resource().create_table(
            TableName=name,
            KeySchema=key_schema,
            AttributeDefinitions=attr_defs,
            BillingMode="PAY_PER_REQUEST",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceInUseException":
            raise


def init_db():
    _create_table_safe(
        _TABLE_NAME,
        [{"AttributeName": "id", "KeyType": "HASH"}],
        [{"AttributeName": "id", "AttributeType": "S"}],
    )
    _create_table_safe(
        _TRAIL_TABLE,
        [
            {"AttributeName": "invoice_id", "KeyType": "HASH"},
            {"AttributeName": "timestamp",  "KeyType": "RANGE"},
        ],
        [
            {"AttributeName": "invoice_id", "AttributeType": "S"},
            {"AttributeName": "timestamp",  "AttributeType": "S"},
        ],
    )


# ── Audit trail ───────────────────────────────────────────────────────────────

def log_action(invoice_id: str, action: str, details: dict = None):
    _resource().Table(_TRAIL_TABLE).put_item(Item={
        "invoice_id": invoice_id,
        "timestamp":  datetime.now(timezone.utc).isoformat(),
        "action":     action,
        "details":    json.dumps(details or {}),
    })


def get_audit_trail(invoice_id: str) -> list[dict]:
    response = _resource().Table(_TRAIL_TABLE).query(
        KeyConditionExpression=Key("invoice_id").eq(invoice_id)
    )
    items = sorted(response.get("Items", []), key=lambda x: x.get("timestamp", ""))
    return [
        {
            "action":    item["action"],
            "timestamp": item["timestamp"],
            "details":   json.loads(item.get("details", "{}")),
        }
        for item in items
    ]


# ── Invoice CRUD ──────────────────────────────────────────────────────────────

def save_result(result: dict) -> str:
    ocr = result.get("ocr", {})
    record_id = str(uuid.uuid4())
    _resource().Table(_TABLE_NAME).put_item(Item={
        "id":               record_id,
        "filename":         result.get("filename", ""),
        "invoice_id":       ocr.get("invoice_id", "UNKNOWN"),
        "ocr_json":         json.dumps(result.get("ocr", {})),
        "validation_json":  json.dumps(result.get("validation", {})),
        "audit_json":       json.dumps(result.get("audit", {})),
        "corrections_json": "{}",
        "review_decision":  result.get("review_decision") or "",
        "review_notes":     result.get("review_notes") or "",
        "s3_key":           result.get("s3_key") or "",
        "s3_url":           result.get("s3_url") or "",
        "created_at":       datetime.now(timezone.utc).isoformat(),
    })
    log_action(record_id, "UPLOADED", {
        "filename":   result.get("filename", ""),
        "invoice_id": ocr.get("invoice_id", "UNKNOWN"),
        "amount":     ocr.get("amount", 0),
        "vendor":     ocr.get("vendor", ""),
    })
    return record_id


def load_all_results() -> list[dict]:
    table = _resource().Table(_TABLE_NAME)
    response = table.scan()
    items = response.get("Items", [])
    while "LastEvaluatedKey" in response:
        response = table.scan(ExclusiveStartKey=response["LastEvaluatedKey"])
        items.extend(response.get("Items", []))

    items.sort(key=lambda x: x.get("created_at", ""), reverse=True)

    return [
        {
            "db_id":           item["id"],
            "filename":        item.get("filename", ""),
            "ocr":             json.loads(item.get("ocr_json", "{}")),
            "validation":      json.loads(item.get("validation_json", "{}")),
            "audit":           json.loads(item.get("audit_json", "{}")),
            "corrections":     json.loads(item.get("corrections_json", "{}") or "{}"),
            "review_decision": item.get("review_decision") or None,
            "review_notes":    item.get("review_notes") or None,
            "s3_key":          item.get("s3_key") or None,
            "s3_url":          item.get("s3_url") or None,
        }
        for item in items
    ]


def save_review(db_id: str, decision: str, notes: str):
    _resource().Table(_TABLE_NAME).update_item(
        Key={"id": db_id},
        UpdateExpression="SET review_decision = :d, review_notes = :n",
        ExpressionAttributeValues={":d": decision, ":n": notes},
    )
    log_action(db_id, decision, {"notes": notes})


def save_corrections(db_id: str, corrections: dict, original_ocr: dict):
    changes = {
        k: {"from": str(original_ocr.get(k, "")), "to": str(v)}
        for k, v in corrections.items()
        if str(original_ocr.get(k, "")) != str(v)
    }
    if not changes:
        return
    _resource().Table(_TABLE_NAME).update_item(
        Key={"id": db_id},
        UpdateExpression="SET corrections_json = :c",
        ExpressionAttributeValues={":c": json.dumps(corrections)},
    )
    log_action(db_id, "CORRECTED", {"changes": changes})


def delete_result(db_id: str):
    _resource().Table(_TABLE_NAME).delete_item(Key={"id": db_id})
