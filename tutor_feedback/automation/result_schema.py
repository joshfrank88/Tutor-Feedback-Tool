"""Machine-readable result schema for automation (result.json)."""

from __future__ import annotations

from typing import Dict, Literal, Optional

from pydantic import BaseModel, Field


class InputRecording(BaseModel):
    original_path: str
    processed_path: Optional[str] = None
    sha256: str = ""
    size_bytes: int = 0
    mtime: float = 0.0


class FeedbackEntry(BaseModel):
    path: str
    text_preview: str = Field(..., max_length=240)


class Outputs(BaseModel):
    session_folder: str
    transcript_txt: Optional[str] = None
    transcript_json: Optional[str] = None
    extracted_json: Optional[str] = None
    homework_txt: Optional[str] = None
    feedback: Dict[str, FeedbackEntry] = Field(default_factory=dict)


class TimingsMs(BaseModel):
    transcribe: Optional[int] = None
    extract: Optional[int] = None
    render: Optional[int] = None
    total: Optional[int] = None


class Result(BaseModel):
    """Schema for result.json emitted after successful pipeline run."""
    session_id: str
    student: str
    created_at_iso: str
    trigger: Literal["watch", "paste"] = "watch"
    input_recording: InputRecording
    outputs: Outputs
    timings_ms: TimingsMs = Field(default_factory=TimingsMs)
