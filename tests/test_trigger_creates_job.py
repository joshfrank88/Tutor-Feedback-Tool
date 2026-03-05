"""Webhook server: POST /trigger creates a job record in DB."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from tutor_feedback.automation.webhook_server import app
from tutor_feedback.automation.state import get_job, init_db

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


def test_trigger_creates_job_record(client, temp_dir):
    """POST /trigger with a temp local file creates a job record in DB with status queued (or running/failed after worker)."""
    rec = temp_dir / "dummy.m4a"
    rec.write_bytes(b"fake audio")
    with patch.dict(os.environ, {"TUTOR_FEEDBACK_WEBHOOK_SECRET": "s"}, clear=False):
        r = client.post(
            "/trigger",
            json={
                "recording_path": str(rec),
                "student": "Andy",
                "platforms": ["private"],
            },
            headers={SECRET_HEADER: "s"},
        )
    assert r.status_code == 200
    data = r.json()
    assert "job_id" in data
    assert data.get("status") == "queued"
    job_id = data["job_id"]

    # Job record exists in DB (may be queued, running, or failed if worker already ran)
    from tutor_feedback.config import get_settings
    data_dir = Path(get_settings().data_dir)
    init_db(data_dir)
    row = get_job(data_dir, job_id)
    assert row is not None
    assert row["job_id"] == job_id
    assert row["status"] in ("queued", "running", "succeeded", "failed")
