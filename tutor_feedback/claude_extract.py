"""Stage A – extract structured session data from a transcript via Claude."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import anthropic

from tutor_feedback.models import ExtractedSession

log = logging.getLogger("tutor_feedback")

EXTRACT_SYSTEM = """\
You are an expert tutor feedback analyst. Your job is to read a tutoring \
session transcript and extract structured data. You MUST output ONLY valid \
JSON matching the schema below — no markdown fences, no commentary, no \
preamble.

RULES:
1. Every "strengths", "gaps", and "misconceptions" entry MUST include an \
   "evidence" field with either a short quoted snippet from the transcript \
   OR a timestamp reference like "[12:34]".
2. If the audio quality is poor or parts are unclear, set "audio_quality" \
   accordingly and add items to "missing_info_flags".
3. Keep "tutor_private_notes" separate — these are only for the tutor. \
   Do NOT include medical, psychological, or speculative claims.
4. Do NOT guess or fabricate information. Only extract what is present in \
   the transcript.
5. If the student's name is not mentioned in the transcript, use the name \
   provided in the user message.

OUTPUT SCHEMA (output ONLY this JSON object):
{
  "student_name": "<string>",
  "session_datetime_iso": "<ISO 8601 string>",
  "duration_minutes": <number>,
  "subjects": ["<string>", ...],
  "topics_covered": ["<string>", ...],
  "strengths": [{"point": "<string>", "evidence": "<string>"}, ...],
  "gaps": [{"point": "<string>", "evidence": "<string>"}, ...],
  "misconceptions": [{"point": "<string>", "evidence": "<string>"}, ...],
  "targets_next_session": ["<string>", ...],
  "homework": [{
    "task": "<string>",
    "instructions": "<string>",
    "success_criteria": ["<string>", ...],
    "estimated_time_minutes": <number>
  }, ...],
  "engagement_observations": ["<string>", ...],
  "tutor_private_notes": ["<string>", ...],
  "confidence_level": "low"|"medium"|"high",
  "audio_quality": "poor"|"ok"|"good",
  "missing_info_flags": ["<string>", ...]
}\
"""


def build_extract_prompt(
    transcript_json: list[dict],
    student_name: str,
    session_datetime: str,
    duration_minutes: float,
) -> str:
    transcript_text = json.dumps(transcript_json, indent=2, ensure_ascii=False)
    return (
        f"Student name (use if not mentioned in transcript): {student_name}\n"
        f"Session date/time: {session_datetime}\n"
        f"Approximate duration: {duration_minutes:.0f} minutes\n\n"
        f"TRANSCRIPT (JSON segments with start/end timestamps):\n{transcript_text}"
    )


def extract_session(
    transcript_json: list[dict],
    student_name: str,
    session_datetime: str,
    duration_minutes: float,
    *,
    api_key: str,
    model: str = "claude-sonnet-4-20250514",
    max_retries: int = 2,
) -> tuple[ExtractedSession, float]:
    """
    Call Claude to extract structured session data.

    Returns (ExtractedSession, elapsed_seconds).
    Retries up to `max_retries` times on validation failure.
    """
    client = anthropic.Anthropic(api_key=api_key)
    user_msg = build_extract_prompt(transcript_json, student_name, session_datetime, duration_minutes)

    errors: list[str] = []
    for attempt in range(1, max_retries + 2):
        prompt = user_msg
        if errors:
            prompt += (
                "\n\n--- VALIDATION ERRORS FROM PREVIOUS ATTEMPT ---\n"
                + "\n".join(f"- {e}" for e in errors)
                + "\n\nPlease fix these errors and output corrected JSON only."
            )

        log.info("Claude extract – attempt %d/%d", attempt, max_retries + 1)
        t0 = time.time()

        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=EXTRACT_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        elapsed = time.time() - t0

        raw_text = response.content[0].text.strip()

        # Strip markdown fences if Claude adds them despite instructions
        if raw_text.startswith("```"):
            lines = raw_text.split("\n")
            lines = [l for l in lines if not l.startswith("```")]
            raw_text = "\n".join(lines)

        try:
            data = json.loads(raw_text)
            extracted = ExtractedSession(**data)
            log.info("Extraction validated on attempt %d (%.1fs)", attempt, elapsed)
            return extracted, elapsed
        except (json.JSONDecodeError, Exception) as exc:
            errors = [str(exc)]
            log.warning("Attempt %d failed validation: %s", attempt, exc)

    raise RuntimeError(
        f"Claude extraction failed after {max_retries + 1} attempts. "
        f"Last errors: {errors}"
    )
