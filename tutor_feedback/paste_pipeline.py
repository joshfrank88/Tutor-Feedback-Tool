"""Paste pipeline: SessionInput -> EXTRACT -> RENDER -> session folder + result.json."""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from tutor_feedback.config import get_settings
from tutor_feedback.inputs.base import SessionInput
from tutor_feedback.claude_extract import extract_session_from_text
from tutor_feedback.claude_render import render_feedback, render_homework
from tutor_feedback.styles import load_style
from tutor_feedback.storage import create_session_folder, save_meta, save_to_db
from tutor_feedback.models import SessionMeta
from tutor_feedback.automation.result_schema import (
    Result,
    InputRecording,
    Outputs,
    FeedbackEntry,
    TimingsMs,
)

log = logging.getLogger("tutor_feedback")

PASTE_PLATFORM_TO_STYLE: Dict[str, str] = {
    "humanities": "humanities_explained",
    "intergreat": "intergreat_paste",
    "private": "private",
    "keystone-quick": "keystone_quick",
}

TEXT_PREVIEW_MAX = 240


def _text_for_extract(session_input: SessionInput) -> str:
    parts = []
    if session_input.transcript_text:
        parts.append(session_input.transcript_text)
    if session_input.notes_text:
        parts.append(session_input.notes_text)
    return "\n\n".join(parts) if parts else session_input.raw_text


def process_pasted_text(
    session_input: SessionInput,
    platforms: List[str],
    *,
    settings=None,
) -> Path:
    """Run EXTRACT then RENDER; write all outputs to session folder. Returns session_dir."""
    settings = settings or get_settings()
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set.")

    now = datetime.now()
    session_id = f"{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    session_dir = create_session_folder(
        settings.data_dir, session_input.student_name, now
    )
    timings: Dict[str, float] = {}
    timings_ms: Dict[str, int] = {}

    meta = SessionMeta(
        session_id=session_id,
        student_name=session_input.student_name,
        input_file="(pasted)",
        session_folder=str(session_dir),
        whisper_model="",
        claude_model=settings.claude_model,
        platforms=platforms,
    )

    (session_dir / "input_raw.txt").write_text(session_input.raw_text, encoding="utf-8")
    if session_input.notes_text:
        (session_dir / "notes.txt").write_text(session_input.notes_text, encoding="utf-8")
    if session_input.transcript_text:
        (session_dir / "transcript.txt").write_text(
            session_input.transcript_text, encoding="utf-8"
        )

    text = _text_for_extract(session_input)
    t0 = time.time()
    extracted, extract_elapsed = extract_session_from_text(
        text,
        session_input.student_name,
        session_input.session_datetime_iso or now.isoformat(),
        0.0,
        api_key=settings.anthropic_api_key,
        model=settings.claude_model,
    )
    timings["extract"] = round(time.time() - t0, 2)
    timings_ms["extract"] = int(extract_elapsed * 1000)
    (session_dir / "extracted.json").write_text(
        json.dumps(extracted.model_dump(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    for p in platforms:
        style_name = PASTE_PLATFORM_TO_STYLE.get(p, p)
        style = load_style(style_name, settings.styles_dir)
        t0 = time.time()
        feedback_text, _ = render_feedback(
            extracted,
            style,
            api_key=settings.anthropic_api_key,
            model=settings.claude_model,
            max_retries=2,
        )
        timings[f"render_{p}"] = round(time.time() - t0, 2)
        timings_ms[f"render_{p}"] = int((time.time() - t0) * 1000)
        (session_dir / f"feedback_{p}.txt").write_text(feedback_text, encoding="utf-8")

    hw_text = render_homework(extracted)
    (session_dir / "homework.txt").write_text(hw_text, encoding="utf-8")

    meta.timings = timings
    meta_dict = meta.model_dump()
    meta_dict["source"] = session_input.source
    meta_dict["meeting_source"] = session_input.meeting_source
    (session_dir / "meta.json").write_text(
        json.dumps(meta_dict, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    save_to_db(settings.data_dir, meta)

    feedback_entries: Dict[str, FeedbackEntry] = {}
    for p in platforms:
        fb_path = session_dir / f"feedback_{p}.txt"
        if fb_path.exists():
            text_preview = fb_path.read_text(encoding="utf-8").replace("\n", " ").strip()
            if len(text_preview) > TEXT_PREVIEW_MAX:
                text_preview = text_preview[: TEXT_PREVIEW_MAX - 3] + "..."
            feedback_entries[p] = FeedbackEntry(
                path=str(fb_path.resolve()), text_preview=text_preview
            )
    total_ms = timings_ms.get("extract", 0) + sum(
        timings_ms.get(f"render_{p}", 0) for p in platforms
    )
    result = Result(
        session_id=session_id,
        student=session_input.student_name,
        created_at_iso=now.isoformat(),
        trigger="paste",
        input_recording=InputRecording(
            original_path="(pasted)",
            processed_path=None,
            sha256="",
            size_bytes=0,
            mtime=0.0,
        ),
        outputs=Outputs(
            session_folder=str(session_dir.resolve()),
            transcript_txt=session_input.transcript_text,
            extracted_json=(session_dir / "extracted.json").read_text(encoding="utf-8"),
            homework_txt=(session_dir / "homework.txt").read_text(encoding="utf-8"),
            feedback=feedback_entries,
        ),
        timings_ms=TimingsMs(
            transcribe=None,
            extract=timings_ms.get("extract"),
            render=sum(timings_ms.get(f"render_{p}", 0) for p in platforms),
            total=total_ms,
        ),
    )
    (session_dir / "result.json").write_text(
        result.model_dump_json(indent=2), encoding="utf-8"
    )

    return session_dir
