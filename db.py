"""
Persistence layer — DynamoDB via real AWS or LocalStack.

CAP positioning: CP (Consistent + Partition Tolerant)
  - All reads use ConsistentRead=True (no stale data)
  - Writes use conditional expressions (optimistic locking via `version`)
  - Single boto3 resource per process (connection reuse)

Tables:
  audit-invoices  — invoice records        (PK: id UUID)
  audit-trail     — immutable action log   (PK: invoice_id, SK: timestamp)
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.config import Config
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_ENDPOINT    = os.environ.get("DYNAMODB_ENDPOINT_URL") or None
_TABLE_NAME  = os.environ.get("DYNAMODB_TABLE_NAME",   "audit-invoices")
_TRAIL_TABLE = "audit-trail"
_REGION      = os.environ.get("AWS_REGION",             "us-east-1")
_ACCESS_KEY  = os.environ.get("AWS_ACCESS_KEY_ID")  or None
_SECRET_KEY  = os.environ.get("AWS_SECRET_ACCESS_KEY") or None

_CFG = Config(
    connect_timeout=5,
    read_timeout=10,
    retries={"max_attempts": 3, "mode": "adaptive"},
)

# ── Singleton resource (connection reuse) ─────────────────────────────────────
_resource_instance = None


def _resource():
    global _resource_instance
    if _resource_instance is None:
        _resource_instance = boto3.resource(
            "dynamodb",
            endpoint_url=_ENDPOINT,
            region_name=_REGION,
            aws_access_key_id=_ACCESS_KEY,
            aws_secret_access_key=_SECRET_KEY,
            config=_CFG,
        )
    return _resource_instance


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Table init ────────────────────────────────────────────────────────────────

def _create_table_safe(name: str, key_schema: list, attr_defs: list) -> None:
    try:
        _resource().create_table(
            TableName=name,
            KeySchema=key_schema,
            AttributeDefinitions=attr_defs,
            BillingMode="PAY_PER_REQUEST",
        )
        logger.info("Created DynamoDB table: %s", name)
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceInUseException":
            raise


def init_db() -> None:
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

def log_action(invoice_id: str, action: str, details: dict | None = None) -> None:
    try:
        _resource().Table(_TRAIL_TABLE).put_item(Item={
            "invoice_id": invoice_id,
            "timestamp":  _now_iso(),
            "action":     action,
            "details":    json.dumps(details or {}),
        })
    except ClientError:
        logger.exception("Failed to write audit trail for %s / %s", invoice_id, action)


def get_audit_trail(invoice_id: str) -> list[dict]:
    try:
        response = _resource().Table(_TRAIL_TABLE).query(
            KeyConditionExpression=Key("invoice_id").eq(invoice_id),
            ConsistentRead=True,   # CAP: always read latest state
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
    except ClientError:
        logger.exception("Failed to fetch audit trail for %s", invoice_id)
        return []


# ── Invoice CRUD ──────────────────────────────────────────────────────────────

def save_result(result: dict) -> str:
    ocr = result.get("ocr", {})
    record_id = str(uuid.uuid4())
    try:
        _resource().Table(_TABLE_NAME).put_item(
            Item={
                "id":               record_id,
                "version":          1,                     # optimistic locking seed
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
                "created_at":       _now_iso(),
            },
            ConditionExpression=Attr("id").not_exists(),   # idempotency guard
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            logger.warning("Duplicate write ignored for record %s", record_id)
            return record_id
        raise

    log_action(record_id, "UPLOADED", {
        "filename":   result.get("filename", ""),
        "invoice_id": ocr.get("invoice_id", "UNKNOWN"),
        "amount":     ocr.get("amount", 0),
        "vendor":     ocr.get("vendor", ""),
    })
    return record_id


def load_all_results() -> list[dict]:
    table = _resource().Table(_TABLE_NAME)
    try:
        response = table.scan(ConsistentRead=True)   # CAP: strong consistency
        items = response.get("Items", [])
        while "LastEvaluatedKey" in response:
            response = table.scan(
                ExclusiveStartKey=response["LastEvaluatedKey"],
                ConsistentRead=True,
            )
            items.extend(response.get("Items", []))
    except ClientError:
        logger.exception("Failed to scan invoice table")
        return []

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
            "version":         int(item.get("version", 1)),
        }
        for item in items
    ]


def save_review(db_id: str, decision: str, notes: str, version: int = 1) -> bool:
    """
    Optimistic locking: only updates if version matches.
    Returns True on success, False if another user already updated the record.
    """
    try:
        _resource().Table(_TABLE_NAME).update_item(
            Key={"id": db_id},
            UpdateExpression="SET review_decision = :d, review_notes = :n, #v = #v + :one",
            ConditionExpression=Attr("version").eq(version),   # CAP: optimistic lock
            ExpressionAttributeNames={"#v": "version"},
            ExpressionAttributeValues={":d": decision, ":n": notes, ":one": 1},
        )
        log_action(db_id, decision, {"notes": notes})
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            logger.warning("Version conflict on save_review for %s — record was modified", db_id)
            return False
        raise


def save_corrections(db_id: str, corrections: dict, original_ocr: dict) -> None:
    changes = {
        k: {"from": str(original_ocr.get(k, "")), "to": str(v)}
        for k, v in corrections.items()
        if str(original_ocr.get(k, "")) != str(v)
    }
    if not changes:
        return
    try:
        _resource().Table(_TABLE_NAME).update_item(
            Key={"id": db_id},
            UpdateExpression="SET corrections_json = :c, #v = #v + :one",
            ExpressionAttributeNames={"#v": "version"},
            ExpressionAttributeValues={":c": json.dumps(corrections), ":one": 1},
        )
        log_action(db_id, "CORRECTED", {"changes": changes})
    except ClientError:
        logger.exception("Failed to save corrections for %s", db_id)
        raise


def delete_result(db_id: str) -> None:
    try:
        _resource().Table(_TABLE_NAME).delete_item(Key={"id": db_id})
    except ClientError:
        logger.exception("Failed to delete record %s", db_id)
        raise
