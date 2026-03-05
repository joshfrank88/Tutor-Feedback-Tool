"""Load and manage platform style cards (YAML)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field

log = logging.getLogger("tutor_feedback")


class StyleField(BaseModel):
    """A named field for structured-output platforms like Intergreat."""
    name: str
    label: str = ""
    description: str = ""
    word_limit: int = 0
    required: bool = True


class StyleCard(BaseModel):
    name: str
    tone: str = "warm and professional"
    word_limit: int = 400
    required_sections: list[str] = Field(default_factory=list)
    format: str = "mixed"  # "bullets" | "narrative" | "mixed" | "fields" | "chat"
    do_rules: list[str] = Field(default_factory=list)
    dont_rules: list[str] = Field(default_factory=list)
    fields: list[StyleField] = Field(default_factory=list)
    output_format: str = "text"  # "text" | "fields"
    examples: list[str] = Field(default_factory=list)


def load_style(name: str, styles_dir: Path) -> StyleCard:
    """Load a single style card by name from the styles directory."""
    path = styles_dir / f"{name}.yaml"
    if not path.is_file():
        path = styles_dir / f"{name}.yml"
    if not path.is_file():
        raise FileNotFoundError(
            f"Style card '{name}' not found in {styles_dir}. "
            f"Available: {', '.join(list_styles(styles_dir))}"
        )
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    card = StyleCard(**raw)

    # Load example files from styles/<name>/examples/*.txt
    examples_dir = styles_dir / name / "examples"
    if examples_dir.is_dir():
        for txt in sorted(examples_dir.glob("*.txt")):
            if txt.name.lower() == "readme.txt":
                continue
            content = txt.read_text(encoding="utf-8").strip()
            if content:
                card.examples.append(content)
        if card.examples:
            log.debug("Loaded %d example(s) for style '%s'", len(card.examples), name)

    return card


def list_styles(styles_dir: Path) -> list[str]:
    """Return sorted list of available style names."""
    names: list[str] = []
    for ext in ("*.yaml", "*.yml"):
        for p in styles_dir.glob(ext):
            names.append(p.stem)
    return sorted(set(names))


def get_example_count(name: str, styles_dir: Path) -> int:
    """Return number of example files for a style."""
    examples_dir = styles_dir / name / "examples"
    if not examples_dir.is_dir():
        return 0
    return len([f for f in examples_dir.glob("*.txt") if f.name.lower() != "readme.txt"])
