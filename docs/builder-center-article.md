# SeqDrop: a serverless front door for sequencing data

*Weekend Challenge: No Pipeline, No Problem. Seven serverless services (API Gateway, Lambda, S3, Step Functions, DynamoDB, EventBridge and SNS), one `terraform apply`, and nothing to manage afterwards.*

## The problem

In a research lab, sequencing files arrive from many places: core facilities, collaborators, public archives, someone's laptop. They are big, they are precious, and a fair number of them are subtly broken. A FASTQ file truncated mid-transfer still looks like a FASTQ file. A VCF with a mangled header might only fail three hours into an analysis pipeline, long after the person who uploaded it has gone home.

What I wanted was a front door: one place to drop a FASTQ or VCF that answers three questions immediately. **Is this file intact? What is in it? Where is it now?** Bad files should be set aside with a reason a human can act on, and good files should come back checksummed and catalogued. The intake step is bursty and idle most of the time, so I also wanted it to cost nothing between uploads. That made it a natural fit for serverless.

## What it does

1. A researcher calls `POST /samples` with a filename and sample name. SeqDrop registers the sample in DynamoDB as `AWAITING_UPLOAD` and returns a **presigned S3 POST** with a size limit.
2. The file is uploaded straight to S3 and never passes through Lambda or API Gateway.
3. S3 emits an *Object Created* event, and an EventBridge rule starts a **Step Functions** workflow.
4. The workflow validates the file, computes MD5 and SHA-256 in the same streaming pass, and extracts metadata. It then moves the file to `validated/` or `quarantine/`.
5. The sample record is updated with status, checksums, metadata or rejection reason, and an SNS notification goes out.
6. `GET /samples/{id}` returns the result, and `GET /samples?status=QUARANTINED` lists everything that needs attention.

| Format | Validation | Metadata extracted |
|---|---|---|
| FASTQ / FASTQ.gz | 4-line records, `@`/`+` lines, valid bases, sequence length = quality length, Phred+33 range, gzip integrity | reads, total bases, read length min/max/mean, GC%, first read ID |
| VCF / VCF.gz | `##fileformat=VCF`, 8 fixed `#CHROM` columns, consistent column count, integer POS, non-empty REF | variant count, VCF version, sample names, chromosomes, SNV/indel/other counts |

## Architecture

![SeqDrop intake workflow in the Step Functions console](stepfunctions_graph.png)

The workflow has two happy endings and one unhappy one:

- **Valid file:** `Validate → ExtractMetadata → Promote → RecordValidated → NotifyValidated`
- **Invalid file:** `Validate → Quarantine → RecordQuarantined → NotifyQuarantined`
- **Unexpected error:** any task's `Catch` leads to `RecordError`, so the sample record always says what went wrong rather than sitting in `PROCESSING` forever.

## No pipeline, no problem

There is nothing to run, patch or babysit. The whole stack (59 resources) goes up with a single `terraform apply` from a laptop, with no CI/CD pipeline, no containers and no instances. Once it's deployed:

- **Idle cost is effectively zero.** Lambda, Step Functions, API Gateway and pay-per-request DynamoDB bill only when a file arrives. Between uploads, the only cost is storage.
- **Scaling is someone else's problem.** Ten files or ten thousand, each upload gets its own workflow execution.
- **Every run is auditable.** Each sample record links to its Step Functions execution, so you can see exactly which state a file passed or failed.

I used Terraform rather than SAM or CDK because the rest of my infrastructure already lives there. The state machine is plain Amazon States Language in `infra/statemachine/intake.asl.json`, so it opens directly in Workflow Studio.

## Design decisions I'd defend

**Lambda only where code is needed.** Three Lambdas do the real work: validate, extract metadata and move the object. Every DynamoDB write and SNS publish is a **direct Step Functions service integration**. Even the sample ID is pulled out of the S3 key with intrinsic functions (`States.ArrayGetItem(States.StringSplit(...))`), with no Lambda involved. Fewer functions means less code, fewer cold starts and fewer IAM roles to get wrong.

**Register before upload.** `MarkProcessing` is a conditional DynamoDB update that only succeeds if the sample was registered through the API. A file dropped into the bucket any other way fails that condition, and the `ConditionalCheckFailedException` is caught and routed to quarantine. The bucket can't be used as an anonymous drop box.

**Presigned POST, not PUT.** A POST policy can carry a `content-length-range` condition, so S3 itself rejects oversized uploads before a single byte is stored.

**Streaming validation.** Files are read as a stream, and the checksums are computed in the same pass as validation. Memory use stays flat regardless of file size.

**Least privilege, one role per function.** Each Lambda can touch only the S3 prefixes and actions it uses. The workflow role can invoke exactly three functions, update one table and publish to one topic.

**Cheap to leave running.** The stack uses pay-per-request DynamoDB, arm64 Lambdas, throttling on the public API stage (10 requests/s, burst 20), and S3 lifecycle rules that clear abandoned uploads after 7 days and quarantined files after 30.

## It works

The repo includes good and deliberately broken sample files and a demo script that runs the whole round trip. Against the live stack:

| File | Result |
|---|---|
| `good_R1.fastq.gz` | ✅ **VALIDATED**: 200 reads, 75 bp, GC 49.75%, MD5 and SHA-256 recorded |
| `good_tumour_normal.vcf` | ✅ **VALIDATED**: 4 variants, samples TUMOUR and NORMAL, 2 SNVs and 2 indels |
| `bad_length_mismatch.fastq` | 🚫 **QUARANTINED**: "Record 6: sequence length 75 != quality length 70" |
| `bad_corrupt.vcf.gz` | 🚫 **QUARANTINED**: "File is not valid gzip (corrupt or truncated)" |

The rejection reasons are the point. "Record 6: sequence length 75 != quality length 70" tells a researcher exactly what to go and fix. "Pipeline failed" does not.

## What bit me

**The 307 that wasn't in any tutorial.** My first live uploads failed with HTTP 307. boto3 had signed the presigned POST against the global `s3.amazonaws.com` endpoint. For a bucket outside us-east-1, and especially a newly created one, S3 answers that host with a temporary redirect, and clients don't re-send a multipart form across a redirect. The fix was a single client setting: sign against the regional endpoint `s3.<region>.amazonaws.com` with virtual-hosted addressing. It's worth knowing if you build anything with presigned uploads outside us-east-1.

**Provider deprecations.** AWS provider v6 deprecates `hash_key` and `range_key` on DynamoDB global secondary indexes in favour of `key_schema` blocks. It's a small change, but it's the kind of warning you want to clear before it becomes an error.

**Plan noise from `for_each`.** Building the workflow's IAM policy from `aws_lambda_function.fn[...].arn` means any code change to *any* Lambda in that `for_each` makes Terraform show the policy as "known after apply". The policy doesn't actually change, but it looks alarming in a plan. Building the ARNs from known names would avoid it.

## What's next

- **Large files.** Lambda's 15-minute limit makes it the wrong tool for multi-gigabyte FASTQs. The plan is a size-based `Choice` state that hands big files to an ECS Fargate or AWS Batch task with the same input and output contract, inside the same state machine.
- **Auth.** Add a Cognito JWT authoriser on the HTTP API and scope samples to projects.
- **Deeper QC.** Add a FastQC or `bcftools stats` container step and store the report next to the file.
- **Paired-end awareness.** Link R1 and R2 under one sample and check that their read counts match.
- **Data protection.** Turn on DynamoDB deletion protection, Terraform `prevent_destroy`, and S3 versioning for anything holding real data.

## Try it

```bash
cd infra
cp terraform.tfvars.example terraform.tfvars   # set aws_profile (+ optional notification_email)
terraform init && terraform apply
cd ..
src/scripts/demo.sh samples/good_R1.fastq.gz NA-demo-01
src/scripts/demo.sh samples/bad_length_mismatch.fastq
```

Code: **[github.com/pharmlovex/seqdrop](https://github.com/pharmlovex/seqdrop)**

*#serverless #stepfunctions #lambda #terraform #bioinformatics*
