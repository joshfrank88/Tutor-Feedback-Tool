"""Webhook server: auth (secret header)."""

import os
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


def test_auth_no_secret_set_accepts_without_header(client, temp_dir):
    """When TUTOR_FEEDBACK_WEBHOOK_SECRET is not set, requests without header are accepted (422 for missing body, not 401)."""
    with patch.dict(os.environ, {}, clear=False):
        # Remove secret if set
        os.environ.pop("TUTOR_FEEDBACK_WEBHOOK_SECRET", None)
        os.environ.pop("TUTOR_FEEDBACK_SECRET", None)
    # POST with no body -> 422 (validation), not 401
    r = client.post("/trigger", json={})
    assert r.status_code == 422


def test_auth_secret_set_rejects_without_header(client, temp_dir):
    """When secret is set, requests without header return 401."""
    with patch.dict(os.environ, {"TUTOR_FEEDBACK_WEBHOOK_SECRET": "test-secret-123"}, clear=False):
        r = client.post(
            "/trigger",
            json={"recording_path": "/tmp/any.m4a", "student": "A", "platforms": ["private"]},
        )
        assert r.status_code == 401
        assert "secret" in (r.json().get("detail") or "").lower()


def test_auth_secret_set_accepts_with_header(client, temp_dir):
    """When secret is set, requests with correct header return 200/400 (not 401)."""
    with patch.dict(os.environ, {"TUTOR_FEEDBACK_WEBHOOK_SECRET": "test-secret-123"}, clear=False):
        # File not found -> 400, but auth passed
        r = client.post(
            "/trigger",
            json={"recording_path": "/nonexistent.m4a", "student": "A", "platforms": ["private"]},
            headers={SECRET_HEADER: "test-secret-123"},
        )
        assert r.status_code == 400
        assert "not found" in (r.json().get("detail") or "").lower()
