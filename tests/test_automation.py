"""Tests for automation state and result schema."""

from pathlib import Path

import pytest

from tutor_feedback.automation.result_schema import (
    Result,
    InputRecording,
    Outputs,
    FeedbackEntry,
    TimingsMs,
)
from tutor_feedback.automation.state import (
    init_db,
    compute_fingerprint,
    fingerprint_key_from_dict,
    get_or_create_job,
    mark_job_succeeded,
    mark_job_failed,
    lookup_by_fingerprint,
    get_job,
)


def test_compute_fingerprint(tmp_path):
    f = tmp_path / "f.m4a"
    f.write_bytes(b"hello")
    fp = compute_fingerprint(f)
    assert "size" in fp
    assert "mtime" in fp
    assert "sha256" in fp
    key = fingerprint_key_from_dict(fp)
    assert "_" in key
    assert key == fingerprint_key_from_dict(fp)
    f.write_bytes(b"hello!")
    fp2 = compute_fingerprint(f)
    assert fingerprint_key_from_dict(fp2) != key


def test_state_idempotency(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    init_db(data_dir)

    rec = tmp_path / "rec.m4a"
    rec.write_bytes(b"content")
    fp_dict = compute_fingerprint(rec)
    fingerprint_key = fingerprint_key_from_dict(fp_dict)

    get_or_create_job(data_dir, "j1", str(rec), fingerprint_key, fp_dict)
    mark_job_succeeded(data_dir, "j1", "s1", "/data/sessions/s1")

    existing = lookup_by_fingerprint(data_dir, fingerprint_key)
    assert existing == ("s1", "/data/sessions/s1")
    assert lookup_by_fingerprint(data_dir, "other_key") is None


def test_get_job(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    init_db(data_dir)

    rec = tmp_path / "r.m4a"
    rec.write_bytes(b"x")
    fp_dict = compute_fingerprint(rec)
    fk = fingerprint_key_from_dict(fp_dict)
    get_or_create_job(data_dir, "j2", str(rec), fk, fp_dict)
    mark_job_failed(data_dir, "j2", "Something failed")

    row = get_job(data_dir, "j2")
    assert row is not None
    assert row["status"] == "failed"
    assert row["last_error"] == "Something failed"
    assert get_job(data_dir, "nonexistent") is None
