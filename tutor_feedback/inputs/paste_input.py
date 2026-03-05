"""Adapter: pasted text -> SessionInput (Phase 2: swap for Granola MCP)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from tutor_feedback.inputs.base import SessionInput


TIMESTAMP_LINE = re.compile(r"^\[?\d{1,2}:\d{2}(?::\d{2})?\]?\s*.+", re.MULTILINE)


def _looks_like_transcript(text: str) -> bool:
    """True if text has transcript markers (timestamps or 'Transcript' heading)."""
    if not text or len(text.strip()) < 20:
        return False
    if "Transcript" in text or "TRANSCRIPT" in text:
        return True
    return bool(TIMESTAMP_LINE.search(text.strip()))


def paste_to_session_input(
    raw_text: str,
    student_name: str = "Unknown",
    session_datetime_iso: Optional[str] = None,
    source: str = "granola",
    meeting_source: Optional[str] = None,
) -> SessionInput:
    """
    Convert pasted raw text into SessionInput.
    If raw_text contains transcript markers, set transcript_text and optionally notes;
    otherwise treat entire content as notes_text, transcript_text null.
    """
    raw_text = raw_text.strip()
    if not raw_text:
        return SessionInput(
            student_name=student_name,
            session_datetime_iso=session_datetime_iso or datetime.now().isoformat(),
            source=source if source in ("granola", "mcp", "other") else "other",
            meeting_source=meeting_source,
            raw_text="",
            transcript_text=None,
            notes_text=None,
        )

    transcript_text: Optional[str] = None
    notes_text: Optional[str] = None

    if _looks_like_transcript(raw_text):
        lines = raw_text.split("\n")
        transcript_lines: list[str] = []
        notes_lines: list[str] = []
        in_transcript = False
        for line in lines:
            if TIMESTAMP_LINE.match(line.strip()) or (
                line.strip() and line.strip().lower() in ("transcript", "transcript:")
            ):
                in_transcript = True
                if TIMESTAMP_LINE.match(line.strip()):
                    transcript_lines.append(line)
                elif transcript_lines:
                    transcript_lines.append(line)
            elif in_transcript and line.strip():
                transcript_lines.append(line)
            else:
                notes_lines.append(line)
        if transcript_lines:
            transcript_text = "\n".join(transcript_lines).strip()
        if notes_lines:
            notes_text = "\n".join(notes_lines).strip() or None
        if not transcript_text and notes_lines:
            transcript_text = None
            notes_text = raw_text
    else:
        notes_text = raw_text

    return SessionInput(
        student_name=student_name,
        session_datetime_iso=session_datetime_iso or datetime.now().isoformat(),
        source=source if source in ("granola", "mcp", "other") else "other",
        meeting_source=meeting_source,
        raw_text=raw_text,
        transcript_text=transcript_text,
        notes_text=notes_text,
    )
