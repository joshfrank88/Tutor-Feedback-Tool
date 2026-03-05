"""Base types for input adapters (paste, Granola MCP, etc.)."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class SessionInput(BaseModel):
    """Normalized input for the EXTRACT + RENDER pipeline."""

    student_name: str
    session_datetime_iso: Optional[str] = None
    source: Literal["granola", "mcp", "other"] = "granola"
    meeting_source: Optional[str] = None  # e.g. "zoom", "gmeet"; metadata only
    raw_text: str
    transcript_text: Optional[str] = None
    notes_text: Optional[str] = None
