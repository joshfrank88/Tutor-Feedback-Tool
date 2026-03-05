"""Webhook server for n8n / external triggers."""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from tutor_feedback.config import get_settings
from tutor_feedback.automation.jobs import Job, enqueue, get_queue
from tutor_feedback.automation.state import (
    init_db,
    get_job,
    get_or_create_job,
    compute_fingerprint,
    fingerprint_key_from_dict,
    lookup_by_fingerprint,
    insert_job_succeeded_existing,
)
from tutor_feedback.automation.runner import run_job

log = logging.getLogger("tutor_feedback.automation")

# Same as watcher: only these extensions for webhook trigger
WEBHOOK_ALLOWED_EXTENSIONS = {".m4a", ".mp3", ".wav", ".mp4", ".mov"}

MAX_DOWNLOAD_BYTES = 500 * 1024 * 1024  # 500 MB
DOWNLOAD_TIMEOUT = 120.0  # seconds

SECRET_HEADER = "x-tutor-feedback-secret"

# In-memory map job_id -> Job for POST /jobs/{id}/run (queued jobs)
_jobs_by_id: Dict[str, Job] = {}
_jobs_lock = threading.Lock()


def _get_secret() -> Optional[str]:
    return os.environ.get("TUTOR_FEEDBACK_WEBHOOK_SECRET") or os.environ.get("TUTOR_FEEDBACK_SECRET")


def _check_auth(request: Request) -> None:
    secret = _get_secret()
    if not secret:
        return
    value = request.headers.get(SECRET_HEADER) or request.headers.get("X-TUTOR-FEEDBACK-SECRET")
    if value != secret:
        raise HTTPException(status_code=401, detail="Invalid or missing webhook secret")


def _download_to_inbox(url: str) -> Path:
    """Download URL to data/inbox with a unique name. Enforce max size and timeout."""
    settings = get_settings()
    inbox = Path(settings.data_dir) / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    # Prefer extension from URL path
    path = Path(url)
    suf = path.suffix.lower() if path.suffix.lower() in WEBHOOK_ALLOWED_EXTENSIONS else ".m4a"
    dest = inbox / f"{uuid.uuid4().hex}{suf}"

    total = 0
    with httpx.stream(
        "GET",
        url,
        follow_redirects=True,
        timeout=DOWNLOAD_TIMEOUT,
        headers={"User-Agent": "TutorFeedback/1.0"},
    ) as resp:
        resp.raise_for_status()
        content_length = resp.headers.get("content-length")
        if content_length and int(content_length) > MAX_DOWNLOAD_BYTES:
            raise ValueError(f"Recording too large (max {MAX_DOWNLOAD_BYTES // (1024*1024)} MB)")
        with open(dest, "wb") as f:
            for chunk in resp.iter_bytes(chunk_size=1 << 20):
                total += len(chunk)
                if total > MAX_DOWNLOAD_BYTES:
                    dest.unlink(missing_ok=True)
                    raise ValueError(f"Recording too large (max {MAX_DOWNLOAD_BYTES // (1024*1024)} MB)")
                f.write(chunk)
    return dest


def _worker_run() -> None:
    """Background worker: pull jobs from queue and run them sequentially."""
    settings = get_settings()
    data_dir = Path(settings.data_dir)
    init_db(data_dir)
    q = get_queue()
    while True:
        try:
            job = q.get()
            if job is None:
                break
            with _jobs_lock:
                _jobs_by_id.pop(job.job_id, None)
            log.info("Job %s running (trigger=%s)", job.job_id, job.trigger)
            try:
                run_job(job)
                log.info("Job %s succeeded", job.job_id)
            except Exception as e:
                log.exception("Job %s failed: %s", job.job_id, e)
        except Exception as e:
            log.exception("Worker error: %s", e)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    worker = threading.Thread(target=_worker_run, daemon=True)
    worker.start()
    log.info("Webhook background worker started")
    yield
    get_queue().put(None)


app = FastAPI(title="Tutor Feedback Webhook", version="1.0", lifespan=_lifespan)


@app.post("/trigger")
async def trigger(request: Request):
    """
    Enqueue a job. Body: exactly one of recording_path or recording_url;
    optional student, platforms (default ["private"]), force, move_processed, metadata.
    """
    _check_auth(request)
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    recording_path = body.get("recording_path")
    recording_url = body.get("recording_url")
    student = (body.get("student") or "").strip() or "Student"
    platforms = body.get("platforms")
    force = bool(body.get("force", False))
    move_processed = bool(body.get("move_processed", True))
    metadata = body.get("metadata") or {}

    if bool(recording_path) == bool(recording_url):
        raise HTTPException(
            status_code=422,
            detail="Exactly one of recording_path or recording_url must be provided",
        )

    if not platforms or not isinstance(platforms, list):
        platforms = ["private"]
    platforms = [str(p).strip() for p in platforms if str(p).strip()]
    if not platforms:
        platforms = ["private"]

    settings = get_settings()
    data_dir = Path(settings.data_dir)
    init_db(data_dir)
    job_id = uuid.uuid4().hex[:12]

    if recording_url:
        try:
            path = _download_to_inbox(recording_url)
            recording_path = str(path)
            metadata["downloaded_from"] = recording_url
        except Exception as e:
            log.exception("Download failed: %s", e)
            raise HTTPException(status_code=400, detail=f"Download failed: {e}")

    path = Path(recording_path)
    if not path.is_file():
        raise HTTPException(status_code=400, detail=f"File not found: {recording_path}")
    if path.suffix.lower() not in WEBHOOK_ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid file type '{path.suffix}'. Allowed: {', '.join(sorted(WEBHOOK_ALLOWED_EXTENSIONS))}",
        )

    fp_dict = compute_fingerprint(path, include_sha256=True)
    fingerprint_key = fingerprint_key_from_dict(fp_dict)

    if not force:
        existing = lookup_by_fingerprint(data_dir, fingerprint_key)
        if existing:
            session_id, session_path = existing
            insert_job_succeeded_existing(data_dir, job_id, str(path), fingerprint_key)
            log.info("Job %s already_processed (fingerprint match) -> %s", job_id, session_path)
            return JSONResponse(
                status_code=200,
                content={
                    "job_id": job_id,
                    "status": "succeeded",
                    "already_processed": True,
                    "session_id": session_id,
                    "session_path": session_path,
                },
            )

    get_or_create_job(data_dir, job_id, str(path), fingerprint_key, fp_dict)
    job = enqueue(
        input_path=str(path),
        student=student,
        platforms=platforms,
        trigger="webhook",
        force=force,
        metadata={**metadata, "move_processed": move_processed},
        job_id=job_id,
    )
    with _jobs_lock:
        _jobs_by_id[job_id] = job
    log.info("Job %s queued (trigger=webhook)", job_id)
    return JSONResponse({"job_id": job_id, "status": "queued"})


@app.get("/jobs/{job_id}")
async def job_status(job_id: str, request: Request):
    """Return job status. When completed, include result (Result schema) or null."""
    _check_auth(request)
    settings = get_settings()
    data_dir = Path(settings.data_dir)
    row = get_job(data_dir, job_id)
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")

    out = {
        "job_id": row["job_id"],
        "status": row["status"],
        "retries": row.get("retries", 0),
        "error": row.get("last_error"),
        "result": None,
    }
    if row.get("session_path"):
        out["session_id"] = row["session_id"]
        out["session_path"] = row["session_path"]
        result_path = Path(row["session_path"]) / "result.json"
        if result_path.is_file():
            try:
                out["result"] = json.loads(result_path.read_text(encoding="utf-8"))
            except Exception:
                out["result"] = None
    return JSONResponse(out)


@app.post("/jobs/{job_id}/run")
async def job_run_now(job_id: str, request: Request):
    """Manually run a queued job immediately (e.g. for local dev). Protected by secret if set."""
    _check_auth(request)
    settings = get_settings()
    data_dir = Path(settings.data_dir)
    row = get_job(data_dir, job_id)
    if not row:
        raise HTTPException(status_code=404, detail="Job not found")
    if row["status"] != "queued":
        raise HTTPException(
            status_code=400,
            detail=f"Job is not queued (status={row['status']}). Only queued jobs can be run.",
        )
    with _jobs_lock:
        job = _jobs_by_id.get(job_id)
    if not job:
        raise HTTPException(
            status_code=400,
            detail="Job not found in queue (may already be running). Poll GET /jobs/{job_id}.",
        )

    def run():
        try:
            run_job(job)
        except Exception as e:
            log.exception("Manual run job %s failed: %s", job_id, e)

    threading.Thread(target=run, daemon=True).start()
    return JSONResponse({"job_id": job_id, "status": "running", "message": "Job started."})
