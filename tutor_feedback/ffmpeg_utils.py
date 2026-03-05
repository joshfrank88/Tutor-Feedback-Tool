"""FFmpeg detection and audio conversion."""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
from pathlib import Path

log = logging.getLogger("tutor_feedback")

SUPPORTED_EXTENSIONS = {".m4a", ".mp3", ".wav", ".mp4", ".webm", ".ogg", ".flac", ".aac"}


def check_ffmpeg() -> None:
    """Verify ffmpeg is on PATH; exit with guidance if not."""
    if shutil.which("ffmpeg") is None:
        from rich.console import Console

        Console(stderr=True).print(
            "[bold red]Error:[/] ffmpeg not found on PATH.\n"
            "Install it with:  [bold]brew install ffmpeg[/]"
        )
        sys.exit(1)


def validate_input_file(path: Path) -> Path:
    """Ensure the input file exists and has a supported extension."""
    path = path.expanduser().resolve()
    if not path.is_file():
        from rich.console import Console

        Console(stderr=True).print(f"[bold red]Error:[/] File not found: {path}")
        sys.exit(1)
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        from rich.console import Console

        Console(stderr=True).print(
            f"[bold red]Error:[/] Unsupported file type '{path.suffix}'.\n"
            f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )
        sys.exit(1)
    return path


def convert_to_wav(input_path: Path, output_path: Path) -> Path:
    """Convert any supported audio/video file to 16 kHz mono WAV."""
    log.info("Converting %s → %s", input_path.name, output_path.name)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-vn",                  # drop video stream
        "-acodec", "pcm_s16le", # 16-bit PCM
        "-ar", "16000",         # 16 kHz sample rate
        "-ac", "1",             # mono
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        log.error("ffmpeg stderr:\n%s", result.stderr)
        from rich.console import Console

        Console(stderr=True).print("[bold red]Error:[/] ffmpeg conversion failed.")
        sys.exit(1)
    log.info("Conversion complete (%s)", _human_size(output_path.stat().st_size))
    return output_path


def get_audio_duration(path: Path) -> float:
    """Return duration of an audio file in seconds via ffprobe."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return float(result.stdout.strip())
    except (ValueError, AttributeError):
        return 0.0


def _human_size(nbytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if nbytes < 1024:
            return f"{nbytes:.1f} {unit}"
        nbytes /= 1024  # type: ignore[assignment]
    return f"{nbytes:.1f} TB"
