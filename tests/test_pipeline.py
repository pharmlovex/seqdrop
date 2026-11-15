"""Local tests for the validation and metadata logic (no AWS needed).

Run:  python -m pytest -q tests/
"""
import hashlib
import importlib.util
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "samples"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "src" / name / "handler.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


validate = _load("validate")
metadata = _load("extract_metadata")


def run_validate(filename):
    fmt, gz = validate.detect_format(filename)
    with open(SAMPLES / filename, "rb") as f:
        return validate.validate_stream(f, fmt, gz)


@pytest.mark.parametrize("filename", ["good_R1.fastq", "good_R1.fastq.gz", "good_tumour_normal.vcf", "good_tumour_normal.vcf.gz"])
def test_good_files_pass_with_correct_checksums(filename):
    ok, reason, md5, sha256 = run_validate(filename)
    data = (SAMPLES / filename).read_bytes()
    assert ok, reason
    assert md5 == hashlib.md5(data).hexdigest()
    assert sha256 == hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize(
    "filename, expected",
    [
        ("bad_length_mismatch.fastq", "Record 6"),
        ("bad_truncated.fastq", "Truncated"),
        ("bad_missing_header.vcf", "fileformat=VCF"),
        ("bad_corrupt.vcf.gz", "gzip"),
    ],
)
def test_bad_files_are_rejected_with_reason(filename, expected):
    ok, reason, _, _ = run_validate(filename)
    assert not ok
    assert expected in reason


def test_detect_format():
    assert validate.detect_format("incoming/x/a.FQ.GZ") == ("fastq", True)
    assert validate.detect_format("incoming/x/a.vcf") == ("vcf", False)
    assert validate.detect_format("incoming/x/a.bam") == (None, False)


def test_fastq_metadata():
    with open(SAMPLES / "good_R1.fastq.gz", "rb") as f:
        meta = metadata.metadata_from_stream(f, "fastq.gz")
    assert meta["record_count"] == 200
    assert meta["total_bases"] == 200 * 75
    assert meta["read_length_min"] == meta["read_length_max"] == 75
    assert 0 < meta["gc_percent"] < 100
    assert meta["first_read_id"].startswith("SEQDROP:1:FC01")


def test_vcf_metadata():
    with open(SAMPLES / "good_tumour_normal.vcf", "rb") as f:
        meta = metadata.metadata_from_stream(f, "vcf")
    assert meta == {
        "record_count": 4,
        "vcf_version": "VCFv4.2",
        "sample_count": 2,
        "samples": ["TUMOUR", "NORMAL"],
        "chromosomes": ["chr1", "chr17"],
        "snv_count": 2,
        "indel_count": 2,
        "other_count": 0,
    }
