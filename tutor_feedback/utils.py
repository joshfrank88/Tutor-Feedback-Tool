"""Shared utility helpers."""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

from rich.logging import RichHandler


def setup_logging(verbose: bool = False) -> logging.Logger:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, markup=True)],
        force=True,
    )
    return logging.getLogger("tutor_feedback")


def open_in_finder(path: Path) -> None:
    """Open a folder in macOS Finder."""
    subprocess.run(["open", str(path)], check=False)


def fmt_duration(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m}m {s}s"


def require_key(key: str) -> None:
    """Abort with a clear message if an env-var / config value is empty."""
    if not key:
        from rich.console import Console

        Console(stderr=True).print(
            "[bold red]Error:[/] ANTHROPIC_API_KEY is not set.\n"
            "Export it or add it to your .env file.  See .env.example."
        )
        sys.exit(1)
