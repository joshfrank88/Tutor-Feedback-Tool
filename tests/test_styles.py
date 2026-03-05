"""Tests for style card loading and validation."""

from pathlib import Path

import pytest

from tutor_feedback.styles import StyleCard, load_style, list_styles

STYLES_DIR = Path(__file__).resolve().parent.parent / "styles"

PLATFORMS = ["intergreat", "politicsexplained", "simpletext"]


def test_list_styles_returns_three():
    names = list_styles(STYLES_DIR)
    assert len(names) >= 3
    for p in PLATFORMS:
        assert p in names


@pytest.mark.parametrize("name", PLATFORMS)
def test_load_style_valid(name: str):
    style = load_style(name, STYLES_DIR)
    assert isinstance(style, StyleCard)
    assert style.name == name
    assert style.word_limit > 0
    assert style.format in ("bullets", "narrative", "mixed", "fields", "chat")


@pytest.mark.parametrize("name", PLATFORMS)
def test_style_has_do_and_dont_rules(name: str):
    style = load_style(name, STYLES_DIR)
    assert len(style.do_rules) >= 1, f"{name} must have at least one do_rule"
    assert len(style.dont_rules) >= 1, f"{name} must have at least one dont_rule"


def test_intergreat_has_fields():
    style = load_style("intergreat", STYLES_DIR)
    assert style.output_format == "fields"
    assert len(style.fields) >= 5
    field_names = [f.name for f in style.fields]
    assert "session_summary" in field_names
    assert "topics_covered" in field_names
    assert "progress" in field_names
    assert "homework_set" in field_names
    for f in style.fields:
        if f.required:
            assert f.word_limit > 0, f"Required field '{f.name}' should have a word limit"


def test_politicsexplained_is_short_narrative():
    style = load_style("politicsexplained", STYLES_DIR)
    assert style.output_format == "text"
    assert style.format == "narrative"
    assert 100 <= style.word_limit <= 200


def test_simpletext_is_very_short():
    style = load_style("simpletext", STYLES_DIR)
    assert style.output_format == "text"
    assert style.format == "chat"
    assert style.word_limit <= 60


def test_load_missing_style_raises():
    with pytest.raises(FileNotFoundError, match="nonexistent"):
        load_style("nonexistent", STYLES_DIR)


def test_style_card_from_dict():
    card = StyleCard(
        name="test",
        tone="friendly",
        word_limit=200,
        required_sections=["Summary", "Next Steps"],
        format="bullets",
        do_rules=["Be kind"],
        dont_rules=["No jargon"],
    )
    assert card.name == "test"
    assert card.word_limit == 200
    assert card.output_format == "text"
    assert card.fields == []
