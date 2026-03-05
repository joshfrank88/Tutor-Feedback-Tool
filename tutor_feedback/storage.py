"""Filesystem layout and optional SQLite session metadata store."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from tutor_feedback.models import SessionMeta

log = logging.getLogger("tutor_feedback")

DB_NAME = "sessions.db"

_CREATE_TABLE = """\
CREATE TABLE IF NOT EXISTS sessions (
    session_id   TEXT PRIMARY KEY,
    student_name TEXT NOT NULL,
    input_file   TEXT NOT NULL,
    session_folder TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    whisper_model TEXT,
    claude_model TEXT,
    platforms    TEXT,
    timings      TEXT,
    dry_run      INTEGER DEFAULT 0
);
"""


def create_session_folder(
    data_dir: Path,
    student_name: str,
    dt: Optional[datetime] = None,
) -> Path:
    """
    Create and return a session output folder.

    Layout: data_dir/sessions/YYYY-MM-DD__StudentName__HHMMSS/
    """
    dt = dt or datetime.now()
    safe_name = student_name.strip().replace(" ", "_")
    folder_name = f"{dt.strftime('%Y-%m-%d')}__{safe_name}__{dt.strftime('%H%M%S')}"
    folder = data_dir / "sessions" / folder_name
    folder.mkdir(parents=True, exist_ok=True)
    log.info("Session folder: %s", folder)
    return folder


def save_meta(session_dir: Path, meta: SessionMeta) -> Path:
    """Write meta.json into the session folder."""
    path = session_dir / "meta.json"
    path.write_text(
        json.dumps(meta.model_dump(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def save_to_db(data_dir: Path, meta: SessionMeta) -> None:
    """Insert session metadata into the SQLite database."""
    db_path = data_dir / DB_NAME
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(_CREATE_TABLE)
        conn.execute(
            """\
            INSERT OR REPLACE INTO sessions
                (session_id, student_name, input_file, session_folder,
                 created_at, whisper_model, claude_model, platforms,
                 timings, dry_run)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                meta.session_id,
                meta.student_name,
                meta.input_file,
                meta.session_folder,
                meta.created_at,
                meta.whisper_model,
                meta.claude_model,
                json.dumps(meta.platforms),
                json.dumps(meta.timings),
                int(meta.dry_run),
            ),
        )
        conn.commit()
        log.debug("Session saved to DB: %s", meta.session_id)
    finally:
        conn.close()
