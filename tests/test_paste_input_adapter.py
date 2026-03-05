"""Paste input adapter: raw text -> SessionInput (transcript vs notes heuristic)."""

import pytest

from tutor_feedback.inputs.paste_input import paste_to_session_input


def test_raw_text_with_timestamps_populates_transcript():
    """Raw text with timestamp lines -> transcript_text populated."""
    raw = "[0:00] Hello, today we covered algebra.\n[1:30] The student understood quadratic equations."
    out = paste_to_session_input(raw, student_name="Andy")
    assert out.transcript_text is not None
    assert "algebra" in (out.transcript_text or "")
    assert "[0:00]" in (out.transcript_text or "") or "0:00" in (out.transcript_text or "")


def test_raw_text_without_timestamps_populates_notes_only():
    """Raw text without timestamps -> notes_text populated, transcript_text null."""
    raw = "Session with Andy. We went over chapter 5. He struggled with problem 3. Set homework: exercises 1-4."
    out = paste_to_session_input(raw, student_name="Andy")
    assert out.notes_text is not None
    assert "chapter 5" in (out.notes_text or "")
    assert out.transcript_text is None


def test_empty_raw_text():
    """Empty input -> notes_text and transcript_text null."""
    out = paste_to_session_input("   \n  ", student_name="Unknown")
    assert out.raw_text == ""
    assert out.notes_text is None
    assert out.transcript_text is None


def test_transcript_marker_heading():
    """Text containing 'Transcript' heading triggers transcript path."""
    raw = "Notes before.\n\nTranscript\n[0:00] First line.\n[1:00] Second line."
    out = paste_to_session_input(raw, student_name="Bob")
    assert out.transcript_text is not None
    assert "First line" in (out.transcript_text or "")
