"""Workflow step: extract searchable metadata from a validated FASTQ/VCF.

Input:  {"bucket", "key", "format": "fastq|fastq.gz|vcf|vcf.gz"}
Output: always includes "record_count"; the rest depends on format.
"""
import gzip
import io

MAX_LISTED = 50

_s3 = None


def s3():
    global _s3
    if _s3 is None:
        import boto3
        _s3 = boto3.client("s3")
    return _s3


def fastq_metadata(lines):
    reads = bases = gc = 0
    min_len = max_len = None
    first_read_id = None
    for i, line in enumerate(lines):
        pos = i % 4
        if pos == 0:
            if not line.strip():
                break
            if first_read_id is None:
                first_read_id = line[1:].split()[0] if len(line) > 1 else ""
        elif pos == 1:
            seq = line.rstrip("\r\n")
            n = len(seq)
            reads += 1
            bases += n
            gc += sum(seq.upper().count(b) for b in "GC")
            min_len = n if min_len is None else min(min_len, n)
            max_len = n if max_len is None else max(max_len, n)
    return {
        "record_count": reads,
        "total_bases": bases,
        "read_length_min": min_len or 0,
        "read_length_max": max_len or 0,
        "read_length_mean": round(bases / reads, 2) if reads else 0,
        "gc_percent": round(100 * gc / bases, 2) if bases else 0,
        "first_read_id": first_read_id,
    }


def vcf_metadata(lines):
    version = None
    samples = []
    variants = snvs = indels = other = 0
    chroms = []
    seen = set()
    for line in lines:
        if line.startswith("##"):
            if line.startswith("##fileformat="):
                version = line.strip().split("=", 1)[1]
            continue
        if line.startswith("#CHROM"):
            samples = line.rstrip("\r\n").split("\t")[9:]
            continue
        if not line.strip():
            continue
        f = line.rstrip("\r\n").split("\t")
        variants += 1
        if f[0] not in seen:
            seen.add(f[0])
            chroms.append(f[0])
        ref, alts = f[3], [a for a in f[4].split(",") if a not in (".", "*")]
        if alts and len(ref) == 1 and all(len(a) == 1 for a in alts):
            snvs += 1
        elif alts and all(a[0] != "<" for a in alts):
            indels += 1
        else:
            other += 1
    return {
        "record_count": variants,
        "vcf_version": version,
        "sample_count": len(samples),
        "samples": samples[:MAX_LISTED],
        "chromosomes": chroms[:MAX_LISTED],
        "snv_count": snvs,
        "indel_count": indels,
        "other_count": other,
    }


class _Raw(io.RawIOBase):
    """Adapts any object with .read(n) (e.g. botocore StreamingBody) to RawIOBase."""

    def __init__(self, src):
        self.src = src

    def readable(self):
        return True

    def readinto(self, b):
        chunk = self.src.read(len(b))
        n = len(chunk)
        b[:n] = chunk
        return n


def metadata_from_stream(raw, fmt):
    buffered = io.BufferedReader(_Raw(raw), buffer_size=1 << 20)
    stream = gzip.GzipFile(fileobj=buffered) if fmt.endswith(".gz") else buffered
    text = io.TextIOWrapper(stream, encoding="utf-8", newline="")
    return (fastq_metadata if fmt.startswith("fastq") else vcf_metadata)(text)


def handler(event, context):
    body = s3().get_object(Bucket=event["bucket"], Key=event["key"])["Body"]
    meta = metadata_from_stream(body, event["format"])
    meta["format"] = event["format"]
    return meta
