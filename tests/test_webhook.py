"""Test webhook auth and trigger validation."""

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client_no_secret():
    os.environ.pop("TUTOR_FEEDBACK_WEBHOOK_SECRET", None)
    os.environ.pop("TUTOR_FEEDBACK_SECRET", None)
    from tutor_feedback.automation.webhook_server import app
    return TestClient(app)


@pytest.fixture
def client_with_secret():
    os.environ["TUTOR_FEEDBACK_WEBHOOK_SECRET"] = "test-secret-123"
    os.environ.pop("TUTOR_FEEDBACK_SECRET", None)
    from importlib import reload
    import tutor_feedback.automation.webhook_server as mod
    reload(mod)
    return TestClient(mod.app)


def test_trigger_requires_platforms(client_no_secret):
    r = client_no_secret.post("/trigger", json={})
    assert r.status_code == 422 or r.status_code == 400
    r = client_no_secret.post("/trigger", json={"platforms": []})
    assert r.status_code == 400


def test_trigger_requires_path_or_url(client_no_secret):
    r = client_no_secret.post("/trigger", json={"student": "Andy", "platforms": ["intergreat"]})
    assert r.status_code == 400
    assert "recording_path" in r.text or "recording_url" in r.text


def test_webhook_auth_rejection_when_secret_set(client_with_secret, tmp_path):
    (tmp_path / "rec.m4a").write_bytes(b"fake")
    r = client_with_secret.post(
        "/trigger",
        json={
            "recording_path": str(tmp_path / "rec.m4a"),
            "student": "Andy",
            "platforms": ["intergreat"],
        },
    )
    assert r.status_code == 401
    r = client_with_secret.post(
        "/trigger",
        json={
            "recording_path": str(tmp_path / "rec.m4a"),
            "student": "Andy",
            "platforms": ["intergreat"],
        },
        headers={"X-TUTOR-FEEDBACK-SECRET": "test-secret-123"},
    )
    assert r.status_code != 401
