# SeqDrop demo video: script (target 2:30, hard limit 3:00)

**Setup before recording**
- Terminal in the repo root, large font (about 18pt), dark theme. Run `clear`.
- Browser tabs, already logged in to the AWS console in eu-west-2:
  1. Step Functions → `seqdrop-intake` → Executions list
  2. DynamoDB → `seqdrop-samples` → Explore items
  3. S3 → the SeqDrop bucket
- Before you start, run one throwaway demo to warm the Lambdas, so there are no cold-start pauses on camera.
- Hide the account ID in the console (crop it, or blur it when editing). **Don't show the API URL**: the demo script reads it from Terraform, so it never needs to be on screen.
- Record with QuickTime (File → New Screen Recording) or OBS, and upload to YouTube as **Unlisted** or Public.

---

### 0:00–0:20 · The problem (talking over the README or architecture diagram)
> "Sequencing labs receive FASTQ and VCF files from everywhere, and some of them are quietly broken: truncated transfers, mangled headers. You usually find out hours later when a pipeline crashes. SeqDrop is a serverless front door that checks every file the moment it lands."

### 0:20–0:45 · Architecture (show the architecture diagram, then the Step Functions graph)
> "A researcher registers a sample through API Gateway and gets a size-limited presigned upload. The file goes straight to S3, EventBridge starts a Step Functions workflow, and three small Lambdas validate it, checksum it and extract metadata. DynamoDB writes and SNS notifications are direct service integrations, with no extra Lambdas. It's all deployed with one `terraform apply`, and nothing runs while it's idle."

### 0:45–1:25 · Good file, end to end (terminal)
```bash
src/scripts/demo.sh samples/good_tumour_normal.vcf TN-pair-01
```
> "I register a tumour–normal VCF and upload it… the workflow picks it up… and in a few seconds it's VALIDATED. We get MD5 and SHA-256, both sample names, and the SNV and indel split."

Point at `status`, `sha256`, `samples` and `snv/indel` in the JSON.

### 1:25–1:55 · Bad file gets quarantined (terminal)
```bash
src/scripts/demo.sh samples/bad_length_mismatch.fastq
```
> "Now a FASTQ with a subtle error. It's QUARANTINED, and the reason is specific: record 6 has a 75-base sequence but only 70 quality scores. That's something a researcher can act on."

### 1:55–2:25 · Proof in the console (browser)
- **Step Functions:** open the latest two executions. Show the green path through `Promote` for one, and the path through `Quarantine` for the other.
  > "Every upload gets its own execution, so you can see exactly which path each file took."
- **S3:** show `validated/` and `quarantine/`.
- **DynamoDB:** show the items with status, checksums and rejection reasons.

### 2:25–2:45 · Wrap up (README or "What's next")
> "No servers, no pipeline, nothing to manage after deploy, and it costs nothing when nobody's uploading. Next up: Fargate for multi-gigabyte files, Cognito auth, and R1/R2 pairing. The code is at github.com/pharmlovex/seqdrop."

---

**If you're running long, cut the DynamoDB view first, then shorten the architecture section.**
