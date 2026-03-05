"""Intergreat paste format: 6 headings in order, 50–140 words."""

import pytest
from unittest.mock import patch, MagicMock

from tutor_feedback.styles import load_style
from tutor_feedback.claude_render import _validate_render
from tutor_feedback.models import ExtractedSession

REQUIRED_HEADINGS = [
    "Knowledge reviewed",
    "New knowledge",
    "Areas for improvement",
    "Progress made",
    "Homework assigned",
    "Next lesson preview",
]


def test_intergreat_paste_style_has_six_headings():
    """Style card intergreat_paste has exactly these 6 required_sections in order."""
    from pathlib import Path
    from tutor_feedback.config import get_settings
    styles_dir = Path(get_settings().styles_dir)
    style = load_style("intergreat_paste", styles_dir)
    assert style.required_sections == REQUIRED_HEADINGS
    assert style.word_min == 50
    assert style.word_limit == 140


def test_validate_render_accepts_valid_intergreat_output():
    """Output with all 6 headings and word count in range passes validation."""
    text_parts = [f"## {h}\nSome content here." for h in REQUIRED_HEADINGS]
    text = "\n\n".join(text_parts)
    # ~7 words per section * 6 = 42, add more to reach 50+
    text += "\n\nAdditional evidence-based points for each section to meet the minimum word count."
    style = MagicMock()
    style.word_limit = 140
    style.word_min = 50
    style.required_sections = REQUIRED_HEADINGS
    errors = _validate_render(text, style)
    assert not errors


def test_validate_render_rejects_missing_heading():
    """Missing one required heading fails validation."""
    text_parts = [f"{h}\nContent." for h in REQUIRED_HEADINGS[:-1]]
    text = " ".join(text_parts) + " " + "word " * 50
    style = MagicMock()
    style.word_limit = 140
    style.word_min = 50
    style.required_sections = REQUIRED_HEADINGS
    errors = _validate_render(text, style)
    assert any("Next lesson preview" in str(e) or "Missing" in str(e) for e in errors)


def test_validate_render_rejects_over_word_limit():
    """Word count over limit fails validation."""
    text = " ".join(["word"] * 200)
    for h in REQUIRED_HEADINGS:
        text = f"{h}\n" + text
    style = MagicMock()
    style.word_limit = 140
    style.word_min = 50
    style.required_sections = REQUIRED_HEADINGS
    errors = _validate_render(text, style)
    assert any("exceeds" in str(e).lower() for e in errors)
