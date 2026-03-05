"""Idempotency: run_job(force=False) returns existing result without running pipeline."""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from tutor_feedback.automation.state import (
    init_db,
    compute_fingerprint,
    fingerprint_key_from_dict,
    get_or_create_job,
    mark_job_succeeded,
    lookup_by_fingerprint,
)
from tutor_feedback.automation.jobs import Job
from tutor_feedback.automation.runner import run_job
from tutor_feedback.automation.result_schema import Result, InputRecording, Outputs, TimingsMs


def test_idempotency_returns_existing_without_pipeline(tmp_path):
    """When fingerprint already succeeded and force=False, run_job returns existing Result without calling pipeline."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    init_db(data_dir)

    rec = tmp_path / "rec.m4a"
    rec.write_bytes(b"fake audio content")
    fp_dict = compute_fingerprint(rec, include_sha256=True)
    fingerprint_key = fingerprint_key_from_dict(fp_dict)

    session_id = "20260301_120000_abc"
    session_path = tmp_path / "sessions" / "2026-03-01__Andy__120000"
    session_path.mkdir(parents=True)
    existing_result = Result(
        session_id=session_id,
        student="Andy",
        created_at_iso="2026-03-01T12:00:00",
        trigger="watch",
        input_recording=InputRecording(
            original_path=str(rec),
            processed_path=None,
            sha256=fp_dict["sha256"],
            size_bytes=fp_dict["size"],
            mtime=fp_dict["mtime"],
        ),
        outputs=Outputs(
            session_folder=str(session_path),
            transcript_txt="existing",
            transcript_json=None,
            extracted_json=None,
            homework_txt=None,
            feedback={},
        ),
        timings_ms=TimingsMs(transcribe=1, extract=2, render=3, total=6),
    )
    (session_path / "result.json").write_text(existing_result.model_dump_json(indent=2))

    get_or_create_job(data_dir, "job1", str(rec), fingerprint_key, fp_dict)
    mark_job_succeeded(data_dir, "job1", session_id, str(session_path))

    assert lookup_by_fingerprint(data_dir, fingerprint_key) == (session_id, str(session_path))

    job = Job(
        job_id="job1",
        input_path=str(rec),
        student="Andy",
        platforms=["simpletext"],
        trigger="watch",
        force=False,
    )

    with patch("tutor_feedback.automation.runner.run_pipeline") as mock_pipeline:
        with patch("tutor_feedback.automation.runner.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(data_dir=str(data_dir))
            out = run_job(job)
        mock_pipeline.assert_not_called()
    assert out.session_id == session_id
    assert out.outputs.transcript_txt == "existing"
    assert out.timings_ms.total == 6


def test_idempotency_force_true_calls_pipeline(tmp_path):
    """When force=True, run_job calls the pipeline (mock run_pipeline and assert it was called)."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    init_db(data_dir)

    rec = tmp_path / "rec2.m4a"
    rec.write_bytes(b"more fake audio")
    fp_dict = compute_fingerprint(rec, include_sha256=True)

    session_path = tmp_path / "sessions" / "out"
    session_path.mkdir(parents=True)
    fake_result = Result(
        session_id="new_session",
        student="Andy",
        created_at_iso="2026-03-01T12:00:00",
        trigger="watch",
        input_recording=InputRecording(
            original_path=str(rec),
            processed_path=None,
            sha256=fp_dict["sha256"],
            size_bytes=fp_dict["size"],
            mtime=fp_dict["mtime"],
        ),
        outputs=Outputs(session_folder=str(session_path), feedback={}),
        timings_ms=TimingsMs(transcribe=1, extract=2, render=3, total=6),
    )

    job = Job(
        job_id="job2",
        input_path=str(rec),
        student="Andy",
        platforms=["simpletext"],
        trigger="watch",
        force=True,
    )

    with patch("tutor_feedback.automation.runner.get_settings") as mock_settings:
        mock_settings.return_value = MagicMock(data_dir=str(data_dir))
        with patch("tutor_feedback.automation.runner.run_pipeline") as mock_pipeline:
            mock_pipeline.return_value = (session_path, fake_result)
            out = run_job(job)
            mock_pipeline.assert_called_once()
    assert out.session_id == "new_session"
