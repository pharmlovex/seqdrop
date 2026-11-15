"""Workflow step: validate an uploaded FASTQ/VCF (optionally gzipped) and checksum it.

Input:  {"bucket", "key", "size", "sample_id", ...}
Output: {"valid": bool, "format": "fastq|fastq.gz|vcf|vcf.gz", "reason": str|None,
         "md5": str, "sha256": str}

The file is streamed once: bytes feed MD5/SHA-256 while the (decompressed) text
is checked record by record, so memory stays flat regardless of file size.
"""
import gzip
import hashlib
import io
import os
import re
import zlib

MAX_BYTES = int(os.environ.get("MAX_FILE_BYTES", str(100 * 1024 * 1024)))

SEQ_RE = re.compile(r"[ACGTNacgtn.\-]*")  # IUPAC 'N' plus '.'/'-' placeholders
QUAL_RE = re.compile(r"[!-~]*")           # Phred+33: ASCII 33..126
VCF_FIXED_COLS = ["#CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO"]

_s3 = None


def s3():
    global _s3
    if _s3 is None:
        import boto3
        _s3 = boto3.client("s3")
    return _s3


def detect_format(key):
    k = key.lower()
    gz = k.endswith(".gz")
    if gz:
        k = k[:-3]
    if k.endswith((".fastq", ".fq")):
        return "fastq", gz
    if k.endswith(".vcf"):
        return "vcf", gz
    return None, gz


class HashingReader(io.RawIOBase):
    """Wraps a byte stream and hashes everything read through it."""

    def __init__(self, raw):
        self.raw = raw
        self.md5 = hashlib.md5()
        self.sha256 = hashlib.sha256()

    def readable(self):
        return True

    def readinto(self, b):
        chunk = self.raw.read(len(b))
        if not chunk:
            return 0
        self.md5.update(chunk)
        self.sha256.update(chunk)
        n = len(chunk)
        b[:n] = chunk
        return n

    def drain(self):
        while self.read(1 << 20):
            pass


def check_fastq(lines):
    count = 0
    it = iter(lines)
    while True:
        header = next(it, None)
        if header is None:
            break
        if not header.strip():
            # Allow trailing blank lines only.
            if any(line.strip() for line in it):
                return False, f"Blank line inside the file before record {count + 1}"
            break
        seq, plus, qual = next(it, None), next(it, None), next(it, None)
        if qual is None:
            return False, f"Truncated record {count + 1}: expected 4 lines"
        if not header.startswith("@"):
            return False, f"Record {count + 1}: header must start with '@'"
        if not plus.startswith("+"):
            return False, f"Record {count + 1}: separator line must start with '+'"
        seq, qual = seq.rstrip("\r\n"), qual.rstrip("\r\n")
        if not SEQ_RE.fullmatch(seq):
            return False, f"Record {count + 1}: sequence contains invalid characters"
        if len(seq) != len(qual):
            return False, f"Record {count + 1}: sequence length {len(seq)} != quality length {len(qual)}"
        if not QUAL_RE.fullmatch(qual):
            return False, f"Record {count + 1}: quality string outside Phred+33 range"
        count += 1
    if count == 0:
        return False, "No FASTQ records found"
    return True, None


def check_vcf(lines):
    it = iter(lines)
    first = next(it, None)
    if not first or not first.startswith("##fileformat=VCF"):
        return False, "Missing '##fileformat=VCF' first line"

    ncols = None
    for line in it:
        if line.startswith("##"):
            continue
        if line.startswith("#CHROM"):
            cols = line.rstrip("\r\n").split("\t")
            if cols[:8] != VCF_FIXED_COLS:
                return False, "#CHROM header must start with the 8 fixed tab-separated VCF columns"
            ncols = len(cols)
            break
        return False, "Data line found before the #CHROM header"
    if ncols is None:
        return False, "No #CHROM header line"

    for n, line in enumerate(it, start=1):
        if not line.strip():
            continue
        fields = line.rstrip("\r\n").split("\t")
        if len(fields) != ncols:
            return False, f"Variant {n}: {len(fields)} columns but header has {ncols}"
        if not fields[1].isdigit():
            return False, f"Variant {n}: POS '{fields[1]}' is not an integer"
        if not fields[3] or fields[3] == ".":
            return False, f"Variant {n}: REF is empty"
    return True, None


def validate_stream(raw, fmt, gz):
    """Validate a byte stream. Returns (valid, reason, md5, sha256)."""
    reader = HashingReader(raw)
    buffered = io.BufferedReader(reader, buffer_size=1 << 20)
    try:
        byte_stream = gzip.GzipFile(fileobj=buffered) if gz else buffered
        text = io.TextIOWrapper(byte_stream, encoding="utf-8", errors="strict", newline="")
        ok, reason = (check_fastq if fmt == "fastq" else check_vcf)(text)
    except (OSError, EOFError, zlib.error):
        ok, reason = False, "File is not valid gzip (corrupt or truncated)"
    except UnicodeDecodeError:
        ok, reason = False, "File is not UTF-8/ASCII text"
    buffered.read()  # consume anything the parser didn't
    reader.drain()
    return ok, reason, reader.md5.hexdigest(), reader.sha256.hexdigest()


def handler(event, context):
    bucket, key, size = event["bucket"], event["key"], int(event.get("size", 0))
    fmt, gz = detect_format(key)

    def invalid(reason):
        return {"valid": False, "format": fmt or "unknown", "reason": reason, "md5": None, "sha256": None}

    if fmt is None:
        return invalid("Unsupported file extension")
    if size == 0:
        return invalid("File is empty")
    if size > MAX_BYTES:
        return invalid(
            f"File is {size} bytes; the Lambda path accepts up to {MAX_BYTES}. "
            "Large files belong on a Fargate/Batch path."
        )

    body = s3().get_object(Bucket=bucket, Key=key)["Body"]
    ok, reason, md5, sha256 = validate_stream(body, fmt, gz)
    full_format = fmt + (".gz" if gz else "")
    if not ok:
        return {"valid": False, "format": full_format, "reason": reason, "md5": md5, "sha256": sha256}
    return {"valid": True, "format": full_format, "reason": None, "md5": md5, "sha256": sha256}
