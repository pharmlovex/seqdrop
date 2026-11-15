# SeqDrop: a serverless front door for sequencing data

*Weekend Challenge: No Pipeline, No Problem. Seven serverless services, one `terraform apply`, no servers.*

## The problem

Sequencing files reach a lab from core facilities, collaborators and laptops. A truncated FASTQ still looks like a FASTQ, and a broken VCF header can kill a pipeline hours later. I wanted one place to drop a file and learn straight away: is it intact, what's in it, and where did it go? Uploads come in bursts, so I didn't want to pay for idle time. That meant serverless.

## How it works

1. `POST /samples` registers the sample in DynamoDB and returns a presigned S3 POST with a size limit.
2. The file goes straight to S3, never through Lambda.
3. S3 notifies EventBridge, which starts a Step Functions workflow.
4. Lambda validates the file (computing MD5 and SHA-256 while streaming it), extracts metadata, and moves it to `validated/` or `quarantine/`.
5. Step Functions writes the result to DynamoDB and publishes to SNS directly.
6. `GET /samples/{id}` returns the outcome.

Every task has a `Catch`, so no sample is left stuck in `PROCESSING`.

## No pipeline, no problem

All 60 resources deploy with one `terraform apply`: no CI/CD, containers or instances. It costs almost nothing when idle, scales one execution per upload, and every record links to its execution for tracing.

## Design decisions

- **Lambda only where code is needed.** Three functions; DynamoDB and SNS calls are direct service integrations, and intrinsic functions parse the S3 key.
- **Register before upload.** A conditional DynamoDB update quarantines any file that wasn't registered through the API.
- **Presigned POST, not PUT,** so `content-length-range` rejects oversized files.
- **Least privilege:** one IAM role per function, scoped to its prefixes.

## Results

- `good_R1.fastq.gz`: ✅ validated, 200 reads, GC 49.75%
- `good_tumour_normal.vcf`: ✅ validated, 4 variants
- `bad_length_mismatch.fastq`: 🚫 "Record 6: sequence length 75 != quality length 70"
- `bad_corrupt.vcf.gz`: 🚫 "File is not valid gzip"

A precise rejection message beats "pipeline failed".

## What bit me

Uploads failed with HTTP 307: boto3 signed against the global S3 endpoint, and new buckets outside us-east-1 redirect it. Signing against the regional endpoint fixed it.

## Next

Fargate or Batch for multi-GB files, Cognito auth, FastQC reports, and paired-end support.

Code: [github.com/pharmlovex/seqdrop](https://github.com/pharmlovex/seqdrop)

*#serverless #stepfunctions #lambda #terraform #bioinformatics*
