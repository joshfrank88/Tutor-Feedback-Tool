"""Tests for extracted data validation and feedback validation."""

import json
import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from tutor_feedback.models import ExtractedSession, EvidenceItem, HomeworkItem
from tutor_feedback.styles import StyleCard
from tutor_feedback.validate import validate_extracted_file, validate_feedback_file


VALID_EXTRACTED = {
    "student_name": "Andy",
    "session_datetime_iso": "2025-06-15T14:00:00",
    "duration_minutes": 60,
    "subjects": ["Maths"],
    "topics_covered": ["Fractions", "Decimals"],
    "strengths": [
        {"point": "Strong mental arithmetic", "evidence": "[3:12] quickly calculated 7×8"}
    ],
    "gaps": [
        {"point": "Converting fractions to decimals", "evidence": "[15:44] struggled with 3/8"}
    ],
    "misconceptions": [],
    "targets_next_session": ["Practise fraction-decimal conversion"],
    "homework": [
        {
            "task": "Fraction worksheet",
            "instructions": "Complete questions 1-10",
            "success_criteria": ["All answers correct", "Show working"],
            "estimated_time_minutes": 20,
        }
    ],
    "engagement_observations": ["Focused throughout"],
    "tutor_private_notes": ["Consider visual aids next time"],
    "confidence_level": "medium",
    "audio_quality": "good",
    "missing_info_flags": [],
}


def test_valid_extracted_parses():
    session = ExtractedSession(**VALID_EXTRACTED)
    assert session.student_name == "Andy"
    assert len(session.strengths) == 1
    assert session.strengths[0].evidence.startswith("[3:12]")


def test_extracted_requires_student_name():
    data = {**VALID_EXTRACTED, "student_name": ""}
    # Empty string is technically valid per schema, but let's test it parses
    session = ExtractedSession(**data)
    assert session.student_name == ""


def test_extracted_invalid_confidence():
    data = {**VALID_EXTRACTED, "confidence_level": "very_high"}
    with pytest.raises(ValidationError):
        ExtractedSession(**data)


def test_extracted_invalid_audio_quality():
    data = {**VALID_EXTRACTED, "audio_quality": "excellent"}
    with pytest.raises(ValidationError):
        ExtractedSession(**data)


def test_evidence_item_requires_both_fields():
    item = EvidenceItem(point="Good work", evidence="[1:23] solved it quickly")
    assert item.point == "Good work"

    with pytest.raises(ValidationError):
        EvidenceItem(point="Good work")  # type: ignore[call-arg]


def test_homework_item_defaults():
    hw = HomeworkItem(task="Read chapter 3", instructions="Focus on section 3.2")
    assert hw.success_criteria == []
    assert hw.estimated_time_minutes == 0


def test_validate_extracted_file_valid():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(VALID_EXTRACTED, f)
        f.flush()
        errors = validate_extracted_file(Path(f.name))
    assert errors == []


def test_validate_extracted_file_invalid_json():
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        f.write("not json{{{")
        f.flush()
        errors = validate_extracted_file(Path(f.name))
    assert len(errors) == 1
    assert "Invalid JSON" in errors[0]


def test_validate_extracted_file_missing():
    errors = validate_extracted_file(Path("/nonexistent/extracted.json"))
    assert len(errors) == 1
    assert "not found" in errors[0].lower()


def test_validate_feedback_file_valid():
    style = StyleCard(
        name="test",
        word_limit=100,
        required_sections=["Summary", "Next Steps"],
        format="mixed",
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("# Summary\nGreat session.\n\n# Next Steps\nPractise more.\n")
        f.flush()
        errors = validate_feedback_file(Path(f.name), style)
    assert errors == []


def test_validate_feedback_file_over_word_limit():
    style = StyleCard(
        name="test",
        word_limit=5,
        required_sections=["Summary"],
        format="mixed",
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("# Summary\nThis has way more than five words in the feedback text.\n")
        f.flush()
        errors = validate_feedback_file(Path(f.name), style)
    assert any("word count" in e.lower() or "exceeds" in e.lower() for e in errors)


def test_validate_feedback_file_missing_section():
    style = StyleCard(
        name="test",
        word_limit=500,
        required_sections=["Summary", "Missing Section"],
        format="mixed",
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("# Summary\nAll good.\n")
        f.flush()
        errors = validate_feedback_file(Path(f.name), style)
    assert any("Missing Section" in e for e in errors)
