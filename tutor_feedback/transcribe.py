"""Local transcription using faster-whisper (CTranslate2 backend)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from tutor_feedback.models import TranscriptSegment

log = logging.getLogger("tutor_feedback")


def transcribe(
    wav_path: Path,
    model_size: str = "base",
) -> tuple[str, list[dict]]:
    """
    Transcribe a WAV file and return (plain_text, segments_list).

    Each segment dict has keys: start, end, text.
    The first call downloads the model (~150 MB for 'base'); subsequent
    calls use the cached version.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        from rich.console import Console
        import sys

        Console(stderr=True).print(
            "[bold red]Error:[/] faster-whisper is not installed.\n"
            "Run:  [bold]pip install faster-whisper[/]"
        )
        sys.exit(1)

    log.info("Loading Whisper model '%s' …", model_size)
    model = WhisperModel(model_size, device="cpu", compute_type="int8")

    log.info("Transcribing %s …", wav_path.name)
    raw_segments, info = model.transcribe(
        str(wav_path),
        beam_size=5,
        language="en",
        vad_filter=True,
    )

    segments: list[dict] = []
    full_lines: list[str] = []

    for seg in raw_segments:
        s = TranscriptSegment(start=round(seg.start, 2), end=round(seg.end, 2), text=seg.text.strip())
        segments.append(s.model_dump())
        ts = _fmt_ts(seg.start)
        full_lines.append(f"[{ts}] {s.text}")

    plain_text = "\n".join(full_lines)
    log.info(
        "Transcription complete: %d segments, ~%.0f min detected",
        len(segments),
        info.duration / 60 if info.duration else 0,
    )
    return plain_text, segments


def save_transcript(
    session_dir: Path,
    plain_text: str,
    segments: list[dict],
) -> tuple[Path, Path]:
    """Write transcript.txt and transcript.json into the session folder."""
    txt_path = session_dir / "transcript.txt"
    json_path = session_dir / "transcript.json"

    txt_path.write_text(plain_text, encoding="utf-8")
    json_path.write_text(json.dumps(segments, indent=2, ensure_ascii=False), encoding="utf-8")

    log.info("Saved transcript.txt (%d chars) and transcript.json (%d segments)",
             len(plain_text), len(segments))
    return txt_path, json_path


def load_transcript_json(path: Path) -> list[dict]:
    """Load an existing transcript.json file."""
    return json.loads(path.read_text(encoding="utf-8"))


def _fmt_ts(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"
