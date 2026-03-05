"""Pydantic models for the extracted session data and metadata."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal, Union

from pydantic import BaseModel, Field


# ── Extraction sub-models ──────────────────────────────────────────────


class EvidenceItem(BaseModel):
    point: str
    evidence: str = Field(
        ...,
        description="Short quoted snippet OR timestamp reference like '[12:34]'",
    )


class HomeworkItem(BaseModel):
    task: str
    instructions: str
    success_criteria: list[str] = Field(default_factory=list)
    estimated_time_minutes: Union[int, float] = 0


class ConfidenceLevel(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class AudioQuality(str, Enum):
    poor = "poor"
    ok = "ok"
    good = "good"


# ── Main extraction schema ─────────────────────────────────────────────


class ExtractedSession(BaseModel):
    student_name: str
    session_datetime_iso: str
    duration_minutes: Union[int, float]
    subjects: list[str] = Field(default_factory=list)
    topics_covered: list[str] = Field(default_factory=list)
    strengths: list[EvidenceItem] = Field(default_factory=list)
    gaps: list[EvidenceItem] = Field(default_factory=list)
    misconceptions: list[EvidenceItem] = Field(default_factory=list)
    targets_next_session: list[str] = Field(default_factory=list)
    homework: list[HomeworkItem] = Field(default_factory=list)
    engagement_observations: list[str] = Field(default_factory=list)
    tutor_private_notes: list[str] = Field(default_factory=list)
    confidence_level: Literal["low", "medium", "high"] = "medium"
    audio_quality: Literal["poor", "ok", "good"] = "ok"
    missing_info_flags: list[str] = Field(default_factory=list)


# ── Transcript segment ─────────────────────────────────────────────────


class TranscriptSegment(BaseModel):
    start: float
    end: float
    text: str


# ── Session run metadata ───────────────────────────────────────────────


class SessionMeta(BaseModel):
    session_id: str
    student_name: str
    input_file: str
    session_folder: str
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    whisper_model: str = ""
    claude_model: str = ""
    platforms: list[str] = Field(default_factory=list)
    timings: dict[str, float] = Field(default_factory=dict)
    dry_run: bool = False
