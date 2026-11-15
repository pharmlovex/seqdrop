"""GET /samples/{sample_id} — return one sample record."""
import json
import os
from decimal import Decimal

import boto3

table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])


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
    sample_id = (event.get("pathParameters") or {}).get("sample_id")
    if not sample_id:
        return _response(400, {"error": "sample_id is required"})

    item = table.get_item(Key={"sample_id": sample_id}).get("Item")
    if not item:
        return _response(404, {"error": "Sample not found"})

    # Return metadata as an object rather than the stored JSON string.
    if "metadata_json" in item:
        item["metadata"] = json.loads(item.pop("metadata_json"))
    return _response(200, item)
