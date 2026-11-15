"""GET /samples[?status=VALIDATED|QUARANTINED|PROCESSING|AWAITING_UPLOAD|ERROR]

With ?status=, queries the by_status GSI (newest first). Without it, returns a
page from a table scan, which is fine at demo scale.
"""
import json
import os
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])
VALID_STATUSES = {"AWAITING_UPLOAD", "PROCESSING", "VALIDATED", "QUARANTINED", "ERROR"}
SUMMARY_FIELDS = ("sample_id", "sample_name", "filename", "status", "file_format", "record_count", "created_at", "updated_at")


def _default(o):
    if isinstance(o, Decimal):
        return int(o) if o == o.to_integral_value() else float(o)
    raise TypeError(type(o))


def _response(status, body):
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body, default=_default),
    }


def handler(event, context):
    params = event.get("queryStringParameters") or {}
    status = (params.get("status") or "").upper()

    if status:
        if status not in VALID_STATUSES:
            return _response(400, {"error": f"status must be one of {sorted(VALID_STATUSES)}"})
        result = table.query(
            IndexName="by_status",
            KeyConditionExpression=Key("status").eq(status),
            ScanIndexForward=False,
            Limit=50,
        )
        items = result["Items"]
    else:
        items = table.scan(Limit=50)["Items"]
        items.sort(key=lambda i: i.get("created_at", ""), reverse=True)

    summaries = [{k: i[k] for k in SUMMARY_FIELDS if k in i} for i in items]
    return _response(200, {"count": len(summaries), "samples": summaries})
