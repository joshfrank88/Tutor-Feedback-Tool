"""SQLite state for automation: files table (fingerprints), jobs table."""

from __future__ import annotations

import hashlib
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

log = logging.getLogger("tutor_feedback.automation")

AUTOMATION_DB = "automation.db"
STATE_DIR = "state"

_CREATE = """
CREATE TABLE IF NOT EXISTS files (
    fingerprint TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime REAL NOT NULL,
    sha256 TEXT,
    session_id TEXT,
    session_path TEXT,
    status TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_files_status ON files(status);

CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    input_path TEXT NOT NULL,
    status TEXT NOT NULL,
    retries INTEGER DEFAULT 0,
    error TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_fingerprint ON jobs(fingerprint);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
"""


def _state_dir(data_dir: Path) -> Path:
    d = data_dir / STATE_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _conn(data_dir: Path) -> sqlite3.Connection:
    path = _state_dir(data_dir) / AUTOMATION_DB
    conn = sqlite3.connect(str(path))
    conn.executescript(_CREATE)
    conn.commit()
    return conn


def init_db(data_dir: Path) -> None:
    """Ensure DB and tables exist."""
    _conn(data_dir).close()


def compute_fingerprint(path: Path, include_sha256: bool = True) -> Dict[str, Any]:
    """Return dict with size, mtime, sha256 (optional). Path must exist and be file."""
    path = Path(path).resolve()
    st = path.stat()
    out = {"size": st.st_size, "mtime": st.st_mtime}
    if include_sha256:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        out["sha256"] = h.hexdigest()
    else:
        out["sha256"] = ""
    return out


def _fingerprint_key(fp: Dict[str, Any]) -> str:
    """Stable key for idempotency: size + mtime + sha256 if present."""
    if fp.get("sha256"):
        return f"{fp['size']}_{fp['mtime']}_{fp['sha256']}"
    return f"{fp['size']}_{fp['mtime']}"


def lookup_by_fingerprint(
    data_dir: Path,
    fingerprint_key: str,
) -> Optional[Tuple[str, str]]:
    """If a file with this fingerprint succeeded, return (session_id, session_path)."""
    conn = _conn(data_dir)
    try:
        row = conn.execute(
            "SELECT session_id, session_path FROM files WHERE fingerprint = ? AND status = 'succeeded' LIMIT 1",
            (fingerprint_key,),
        ).fetchone()
        return (row[0], row[1]) if row and row[0] else None
    finally:
        conn.close()


def get_or_create_job(
    data_dir: Path,
    job_id: str,
    input_path: str,
    fingerprint_key: str,
    fp_dict: Dict[str, Any],
) -> None:
    """Insert job and file row (idempotent by job_id)."""
    now = time.time()
    conn = _conn(data_dir)
    try:
        conn.execute(
            """INSERT OR IGNORE INTO jobs (job_id, fingerprint, input_path, status, retries, error, created_at, updated_at)
               VALUES (?, ?, ?, 'queued', 0, NULL, ?, ?)""",
            (job_id, fingerprint_key, input_path, now, now),
        )
        conn.execute(
            """INSERT OR REPLACE INTO files (fingerprint, path, size, mtime, sha256, session_id, session_path, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, NULL, NULL, 'queued', ?, ?)""",
            (
                fingerprint_key,
                input_path,
                fp_dict["size"],
                fp_dict["mtime"],
                fp_dict.get("sha256") or "",
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def mark_job_running(data_dir: Path, job_id: str) -> None:
    now = time.time()
    conn = _conn(data_dir)
    try:
        conn.execute("UPDATE jobs SET status = 'running', updated_at = ? WHERE job_id = ?", (now, job_id))
        conn.execute(
            "UPDATE files SET status = 'running', updated_at = ? WHERE fingerprint = (SELECT fingerprint FROM jobs WHERE job_id = ?)",
            (now, job_id),
        )
        conn.commit()
    finally:
        conn.close()


def mark_job_succeeded(
    data_dir: Path,
    job_id: str,
    session_id: str,
    session_path: str,
) -> None:
    now = time.time()
    conn = _conn(data_dir)
    try:
        conn.execute(
            "UPDATE jobs SET status = 'succeeded', error = NULL, updated_at = ? WHERE job_id = ?",
            (now, job_id),
        )
        conn.execute(
            """UPDATE files SET session_id = ?, session_path = ?, status = 'succeeded', updated_at = ?
               WHERE fingerprint = (SELECT fingerprint FROM jobs WHERE job_id = ?)""",
            (session_id, session_path, now, job_id),
        )
        conn.commit()
    finally:
        conn.close()


def mark_job_failed(data_dir: Path, job_id: str, error: str) -> None:
    now = time.time()
    conn = _conn(data_dir)
    try:
        conn.execute(
            "UPDATE jobs SET status = 'failed', error = ?, updated_at = ? WHERE job_id = ?",
            (error, now, job_id),
        )
        conn.execute(
            "UPDATE files SET status = 'failed', updated_at = ? WHERE fingerprint = (SELECT fingerprint FROM jobs WHERE job_id = ?)",
            (now, job_id),
        )
        conn.commit()
    finally:
        conn.close()


def get_job_fingerprint(data_dir: Path, job_id: str) -> Optional[str]:
    conn = _conn(data_dir)
    try:
        row = conn.execute("SELECT fingerprint FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def get_job(data_dir: Path, job_id: str) -> Optional[Dict[str, Any]]:
    """Return job row as dict for API: job_id, status, error, session_id, session_path, created_at, updated_at."""
    conn = _conn(data_dir)
    try:
        row = conn.execute(
            """SELECT j.job_id, j.status, j.retries, j.error, j.created_at, j.updated_at, f.session_id, f.session_path
               FROM jobs j LEFT JOIN files f ON j.fingerprint = f.fingerprint WHERE j.job_id = ?""",
            (job_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "job_id": row[0],
            "status": row[1],
            "retries": row[2] or 0,
            "last_error": row[3],
            "created_at": row[4],
            "updated_at": row[5],
            "session_id": row[6],
            "session_path": row[7],
        }
    finally:
        conn.close()


def fingerprint_key_from_dict(fp: Dict[str, Any]) -> str:
    """Stable key for idempotency: size + mtime + sha256 if present."""
    return _fingerprint_key(fp)


def insert_job_succeeded_existing(
    data_dir: Path,
    job_id: str,
    input_path: str,
    fingerprint_key: str,
) -> None:
    """Create a job record with status=succeeded that points to existing session via fingerprint."""
    now = time.time()
    conn = _conn(data_dir)
    try:
        conn.execute(
            """INSERT INTO jobs (job_id, fingerprint, input_path, status, retries, error, created_at, updated_at)
               VALUES (?, ?, ?, 'succeeded', 0, NULL, ?, ?)""",
            (job_id, fingerprint_key, input_path, now, now),
        )
        conn.commit()
    finally:
        conn.close()
