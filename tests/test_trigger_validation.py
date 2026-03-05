"""Webhook server: trigger validation (recording_path vs recording_url, extension)."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from tutor_feedback.automation.webhook_server import app

SECRET_HEADER = "x-tutor-feedback-secret"


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def temp_dir(tmp_path):
    os.environ["TUTOR_FEEDBACK_DATA_DIR"] = str(tmp_path)
    try:
        yield tmp_path
    finally:
        os.environ.pop("TUTOR_FEEDBACK_DATA_DIR", None)


def test_trigger_both_missing_returns_422(client, temp_dir):
    with patch.dict(os.environ, {"TUTOR_FEEDBACK_WEBHOOK_SECRET": "s"}, clear=False):
        r = client.post(
            "/trigger",
            json={"student": "A", "platforms": ["private"]},
            headers={SECRET_HEADER: "s"},
        )
        assert r.status_code == 422
        assert "exactly one" in (r.json().get("detail") or "").lower()


def test_trigger_both_provided_returns_422(client, temp_dir):
    with patch.dict(os.environ, {"TUTOR_FEEDBACK_WEBHOOK_SECRET": "s"}, clear=False):
        r = client.post(
            "/trigger",
            json={
                "recording_path": "/a.m4a",
                "recording_url": "https://example.com/a.m4a",
                "student": "A",
                "platforms": ["private"],
            },
            headers={SECRET_HEADER: "s"},
        )
        assert r.status_code == 422
        assert "exactly one" in (r.json().get("detail") or "").lower()


def test_trigger_invalid_extension_returns_422(client, temp_dir):
    f = temp_dir / "bad.xyz"
    f.write_bytes(b"x")
    with patch.dict(os.environ, {"TUTOR_FEEDBACK_WEBHOOK_SECRET": "s"}, clear=False):
        r = client.post(
            "/trigger",
            json={
                "recording_path": str(f),
                "student": "A",
                "platforms": ["private"],
            },
            headers={SECRET_HEADER: "s"},
        )
        assert r.status_code == 422
        detail = (r.json().get("detail") or "").lower()
        assert "invalid" in detail or "allowed" in detail
