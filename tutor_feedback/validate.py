"""Output validation for extracted data and rendered feedback."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic import ValidationError

from tutor_feedback.models import ExtractedSession
from tutor_feedback.styles import StyleCard, load_style, list_styles

log = logging.getLogger("tutor_feedback")


def validate_extracted_file(path: Path) -> list[str]:
    """Validate an extracted.json file against the Pydantic schema."""
    errors: list[str] = []
    if not path.is_file():
        return [f"File not found: {path}"]

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"Invalid JSON: {exc}"]

    try:
        ExtractedSession(**data)
    except ValidationError as exc:
        for e in exc.errors():
            loc = " → ".join(str(x) for x in e["loc"])
            errors.append(f"{loc}: {e['msg']}")

    return errors


def validate_feedback_file(
    path: Path,
    style: StyleCard,
) -> list[str]:
    """Validate a rendered feedback file against its style card."""
    errors: list[str] = []
    if not path.is_file():
        return [f"File not found: {path}"]

    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return ["Feedback file is empty"]

    # Field-based styles validate field labels instead of sections/word count
    if style.output_format == "fields" and style.fields:
        for field in style.fields:
            label = field.label or field.name
            if field.required and f"[{label}]" not in text:
                errors.append(f"Missing required field: '{label}'")
        return errors

    word_count = len(text.split())
    limit = int(style.word_limit * 1.15)
    if word_count > limit:
        errors.append(f"Word count {word_count} exceeds limit {style.word_limit} (+15% = {limit})")

    for section in style.required_sections:
        if section.lower() not in text.lower():
            errors.append(f"Missing required section: '{section}'")

    return errors


def validate_session_folder(
    folder: Path,
    styles_dir: Path,
) -> dict[str, list[str]]:
    """
    Validate all outputs in a session folder.

    Returns a dict mapping filename → list of errors (empty list = valid).
    """
    results: dict[str, list[str]] = {}

    # Validate extracted.json
    extracted_path = folder / "extracted.json"
    results["extracted.json"] = validate_extracted_file(extracted_path)

    # Validate each feedback file
    for fb_file in sorted(folder.glob("feedback_*.txt")):
        platform = fb_file.stem.replace("feedback_", "")
        available = list_styles(styles_dir)
        if platform in available:
            style = load_style(platform, styles_dir)
            results[fb_file.name] = validate_feedback_file(fb_file, style)
        else:
            results[fb_file.name] = [f"No style card found for platform '{platform}'"]

    return results
