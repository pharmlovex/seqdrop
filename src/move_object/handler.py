"""Workflow step: move incoming/<id>/<file> to <dest_prefix>/<id>/<file>.

Input:  {"bucket", "key", "dest_prefix": "validated" | "quarantine"}
Output: {"s3_uri", "key"}
"""
import boto3

ALLOWED_DESTINATIONS = {"validated", "quarantine"}
s3 = boto3.client("s3")


def handler(event, context):
    bucket, key, dest = event["bucket"], event["key"], event["dest_prefix"]
    if dest not in ALLOWED_DESTINATIONS:
        raise ValueError(f"dest_prefix must be one of {ALLOWED_DESTINATIONS}")
    if not key.startswith("incoming/"):
        raise ValueError("Only objects under incoming/ can be moved")

    new_key = f"{dest}/{key.split('/', 1)[1]}"
    s3.copy_object(Bucket=bucket, Key=new_key, CopySource={"Bucket": bucket, "Key": key})
    s3.delete_object(Bucket=bucket, Key=key)
    return {"s3_uri": f"s3://{bucket}/{new_key}", "key": new_key}
