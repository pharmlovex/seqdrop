"""POST /samples — register a sample and return a presigned S3 POST for the upload.

Request body:  {"filename": "NA12878_R1.fastq.gz", "sample_name": "NA12878"}
Response 201:  {"sample_id": ..., "status": "AWAITING_UPLOAD", "upload": {"url": ..., "fields": {...}}}
"""
import base64
import json
import os
import re
import uuid
from datetime import datetime, timezone

import boto3
from botocore.config import Config

BUCKET = os.environ["BUCKET_NAME"]
MAX_BYTES = int(os.environ["MAX_FILE_BYTES"])
TTL = int(os.environ.get("UPLOAD_URL_TTL_SECONDS", "900"))
ALLOWED_SUFFIXES = (".fastq", ".fq", ".fastq.gz", ".fq.gz", ".vcf", ".vcf.gz")

# Sign against the regional endpoint. The global s3.amazonaws.com host answers
# with a 307 redirect for buckets outside us-east-1 (especially new ones), and
# clients don't re-POST multipart form uploads across a redirect.
REGION = os.environ["AWS_REGION"]
s3 = boto3.client(
    "s3",
    region_name=REGION,
    endpoint_url=f"https://s3.{REGION}.amazonaws.com",
    config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
)
table = boto3.resource("dynamodb").Table(os.environ["TABLE_NAME"])


def _response(status, body):
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body),
    }


def _parse_body(event):
    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    return json.loads(raw)


def safe_filename(name):
    """Keep keys predictable: no paths, only [A-Za-z0-9._-]. This also means S3
    event keys never need URL-decoding downstream."""
    base = os.path.basename(name or "").strip()
    return re.sub(r"[^A-Za-z0-9._-]", "_", base)[:200]


def handler(event, context):
    try:
        body = _parse_body(event)
    except (ValueError, UnicodeDecodeError):
        return _response(400, {"error": "Body must be JSON"})

    filename = safe_filename(body.get("filename"))
    if not filename or not filename.lower().endswith(ALLOWED_SUFFIXES):
        return _response(400, {"error": f"filename must end with one of {', '.join(ALLOWED_SUFFIXES)}"})

    sample_name = str(body.get("sample_name") or filename)[:200]
    sample_id = str(uuid.uuid4())
    key = f"incoming/{sample_id}/{filename}"
    now = datetime.now(timezone.utc).isoformat()

    table.put_item(
        Item={
            "sample_id": sample_id,
            "sample_name": sample_name,
            "filename": filename,
            "status": "AWAITING_UPLOAD",
            "created_at": now,
            "updated_at": now,
        }
    )

    # Presigned POST (not PUT) so S3 itself enforces the size limit.
    upload = s3.generate_presigned_post(
        Bucket=BUCKET,
        Key=key,
        Conditions=[["content-length-range", 1, MAX_BYTES]],
        ExpiresIn=TTL,
    )

    return _response(
        201,
        {
            "sample_id": sample_id,
            "status": "AWAITING_UPLOAD",
            "max_bytes": MAX_BYTES,
            "expires_in": TTL,
            "upload": upload,
        },
    )
