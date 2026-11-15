#!/usr/bin/env bash
# End-to-end demo: register a sample, upload the file, poll until the workflow finishes.
# Usage: scripts/demo.sh samples/good_R1.fastq.gz [sample_name]
# Needs: curl, jq, and a deployed stack (reads the API URL from terraform output).
set -euo pipefail

FILE="${1:?usage: $0 <file> [sample_name]}"
NAME="${2:-$(basename "$FILE")}"
# Find the project root (the folder containing infra/) wherever this script lives.
ROOT="$(cd "$(dirname "$0")" && pwd)"
while [ "$ROOT" != "/" ] && [ ! -d "$ROOT/infra" ]; do ROOT="$(dirname "$ROOT")"; done
[ -d "$ROOT/infra" ] || { echo "Could not find infra/ above $(dirname "$0")"; exit 1; }
API="${API_URL:-$(terraform -chdir="$ROOT/infra" output -raw api_url)}"

echo "→ Registering $NAME"
resp=$(curl -sS -X POST "$API/samples" \
  -H 'content-type: application/json' \
  -d "$(jq -n --arg f "$(basename "$FILE")" --arg n "$NAME" '{filename: $f, sample_name: $n}')")
sample_id=$(echo "$resp" | jq -r '.sample_id // empty')
[ -n "$sample_id" ] || { echo "Registration failed: $resp"; exit 1; }
echo "  sample_id: $sample_id"

echo "→ Uploading via presigned POST"
url=$(echo "$resp" | jq -r '.upload.url')
form=()
while IFS= read -r field; do form+=(-F "$field"); done < <(echo "$resp" | jq -r '.upload.fields | to_entries[] | "\(.key)=\(.value)"')
code=$(curl -sS -o /dev/null -w '%{http_code}' "${form[@]}" -F "file=@$FILE" "$url")
[ "$code" = "204" ] || { echo "Upload failed with HTTP $code"; exit 1; }
echo "  uploaded (HTTP $code)"

echo "→ Waiting for the intake workflow"
for _ in $(seq 1 30); do
  sample=$(curl -sS "$API/samples/$sample_id")
  status=$(echo "$sample" | jq -r '.status')
  case "$status" in
    VALIDATED|QUARANTINED|ERROR) echo "$sample" | jq .; exit 0 ;;
    *) printf '  %s...\n' "$status"; sleep 2 ;;
  esac
done
echo "Timed out; last state:"; echo "$sample" | jq .
