"""Validate result.json schema (Result model)."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from tutor_feedback.automation.result_schema import (
    Result,
    InputRecording,
    Outputs,
    FeedbackEntry,
    TimingsMs,
)


def test_result_schema_valid():
    """A sample result matching the spec validates against the Result model."""
    data = {
        "session_id": "20260301_120000_abc12345",
        "student": "Andy",
        "created_at_iso": "2026-03-01T12:00:00",
        "trigger": "watch",
        "input_recording": {
            "original_path": "/recordings/inbox/Andy_2026-03-05.m4a",
            "processed_path": None,
            "sha256": "a" * 64,
            "size_bytes": 1234567,
            "mtime": 1709280000.0,
        },
        "outputs": {
            "session_folder": "/data/sessions/2026-03-01__Andy__120000",
            "transcript_txt": "[0:00] Hello world",
            "transcript_json": "[{\"text\": \"Hello\"}]",
            "extracted_json": "{}",
            "homework_txt": "Homework items",
            "feedback": {
                "keystone": {"path": "/data/sessions/.../feedback_keystone.txt", "text_preview": "Short preview under 240 chars."},
                "private": {"path": "/data/sessions/.../feedback_private.txt", "text_preview": "Another preview."},
            },
        },
        "timings_ms": {
            "transcribe": 5000,
            "extract": 2000,
            "render": 3000,
            "total": 10000,
        },
    }
    result = Result.model_validate(data)
    assert result.session_id == data["session_id"]
    assert result.student == "Andy"
    assert result.trigger == "watch"
    assert result.input_recording.original_path == data["input_recording"]["original_path"]
    assert result.input_recording.sha256 == "a" * 64
    assert result.input_recording.size_bytes == 1234567
    assert result.outputs.session_folder == data["outputs"]["session_folder"]
    assert "keystone" in result.outputs.feedback
    assert result.outputs.feedback["keystone"].text_preview == "Short preview under 240 chars."
    assert result.timings_ms.transcribe == 5000
    assert result.timings_ms.total == 10000


def test_result_schema_text_preview_max_240():
    """FeedbackEntry text_preview is limited to 240 chars."""
    FeedbackEntry(path="/f.txt", text_preview="x" * 240)
    with pytest.raises(ValidationError):
        FeedbackEntry(path="/f.txt", text_preview="x" * 241)


def test_result_schema_roundtrip():
    """Result serializes to JSON and parses back."""
    result = Result(
        session_id="sid",
        student="Bob",
        created_at_iso="2026-03-01T10:00:00",
        trigger="watch",
        input_recording=InputRecording(
            original_path="/in.m4a",
            processed_path=None,
            sha256="",
            size_bytes=100,
            mtime=0.0,
        ),
        outputs=Outputs(
            session_folder="/out",
            transcript_txt=None,
            transcript_json=None,
            extracted_json=None,
            homework_txt=None,
            feedback={"p": FeedbackEntry(path="/f.txt", text_preview="preview")},
        ),
        timings_ms=TimingsMs(transcribe=1, extract=2, render=3, total=6),
    )
    js = result.model_dump_json(indent=2)
    parsed = Result.model_validate_json(js)
    assert parsed.session_id == result.session_id
    assert parsed.outputs.feedback["p"].text_preview == "preview"
    assert parsed.timings_ms.total == 6
