"""Run the pipeline (reuse existing modules) and emit result.json."""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from tutor_feedback.config import get_settings
from tutor_feedback.ffmpeg_utils import SUPPORTED_EXTENSIONS, check_ffmpeg, convert_to_wav, get_audio_duration
from tutor_feedback.transcribe import transcribe, save_transcript, load_transcript_json
from tutor_feedback.claude_extract import extract_session
from tutor_feedback.claude_render import render_feedback, render_homework
from tutor_feedback.styles import load_style
from tutor_feedback.storage import create_session_folder, save_meta, save_to_db
from tutor_feedback.models import SessionMeta
from tutor_feedback.automation.result_schema import (
    Result,
    InputRecording,
    Outputs,
    FeedbackEntry,
    TimingsMs,
)
from tutor_feedback.automation.jobs import Job
from tutor_feedback.automation import state as automation_state

log = logging.getLogger("tutor_feedback.automation")

TEXT_PREVIEW_MAX = 240


def _validate_input_path(path: Path) -> None:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"File not found: {path}")
    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type '{path.suffix}'. "
            f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
        )


def run_pipeline(
    input_path: Path,
    student: str,
    platforms: List[str],
    trigger: str = "watch",
    metadata: Optional[Dict[str, Any]] = None,
    transcript_path: Optional[Path] = None,
    settings=None,
    fp_dict: Optional[Dict[str, Any]] = None,
) -> Tuple[Path, Result]:
    """
    Run the full pipeline. Uses existing tutor_feedback modules only.
    If fp_dict is provided (size, mtime, sha256), used for result.json input_recording.

    Returns (session_dir, result).
    Raises on failure.
    """
    settings = settings or get_settings()
    metadata = metadata or {}
    input_path = Path(input_path).expanduser().resolve()
    _validate_input_path(input_path)

    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set. Add it to your .env file.")
    check_ffmpeg()

    for p in platforms:
        from tutor_feedback.styles import list_styles
        if p not in list_styles(settings.styles_dir):
            raise ValueError(f"Unknown platform: {p}")

    now = datetime.now()
    session_id = f"{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    session_dir = create_session_folder(settings.data_dir, student, now)
    timings: Dict[str, float] = {}
    transcribe_ms: Optional[int] = None
    extract_ms: Optional[int] = None
    render_ms: Optional[int] = None

    meta = SessionMeta(
        session_id=session_id,
        student_name=student,
        input_file=str(input_path),
        session_folder=str(session_dir),
        whisper_model=settings.whisper_model,
        claude_model=settings.claude_model,
        platforms=platforms,
    )

    # Convert
    t0 = time.time()
    wav_path = session_dir / "audio.wav"
    convert_to_wav(input_path, wav_path)
    timings["convert"] = round(time.time() - t0, 2)
    duration_minutes = get_audio_duration(wav_path) / 60.0

    # Transcribe
    if transcript_path and Path(transcript_path).is_file():
        segments = load_transcript_json(Path(transcript_path))
        plain_lines = []
        for seg in segments:
            m, s = divmod(int(seg.get("start", 0)), 60)
            plain_lines.append(f"[{m}:{s:02d}] {seg.get('text', '')}")
        plain_text = "\n".join(plain_lines)
        save_transcript(session_dir, plain_text, segments)
        timings["transcribe"] = 0.0
        transcribe_ms = 0
    else:
        t0 = time.time()
        plain_text, segments = transcribe(wav_path, settings.whisper_model)
        transcribe_ms = int((time.time() - t0) * 1000)
        timings["transcribe"] = round((time.time() - t0), 2)
        save_transcript(session_dir, plain_text, segments)

    # Extract
    t0 = time.time()
    extracted = extract_session(
        transcript_json=segments,
        student_name=student,
        session_datetime=now.isoformat(),
        duration_minutes=duration_minutes,
        api_key=settings.anthropic_api_key,
        model=settings.claude_model,
    )
    extract_ms = int((time.time() - t0) * 1000)
    timings["extract"] = round(time.time() - t0, 2)
    (session_dir / "extracted.json").write_text(
        json.dumps(extracted.model_dump(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Render
    feedback_entries: Dict[str, FeedbackEntry] = {}
    for p in platforms:
        t0 = time.time()
        style = load_style(p, settings.styles_dir)
        feedback_text, _ = render_feedback(
            extracted,
            style,
            api_key=settings.anthropic_api_key,
            model=settings.claude_model,
        )
        timings[f"render_{p}"] = round(time.time() - t0, 2)
        fb_path = session_dir / f"feedback_{p}.txt"
        fb_path.write_text(feedback_text, encoding="utf-8")
        preview = feedback_text.replace("\n", " ").strip()
        if len(preview) > TEXT_PREVIEW_MAX:
            preview = preview[: TEXT_PREVIEW_MAX - 3] + "..."
        feedback_entries[p] = FeedbackEntry(path=str(fb_path.resolve()), text_preview=preview)
    render_ms = sum(
        int((timings.get(f"render_{p}", 0)) * 1000) for p in platforms
    ) or None

    # Homework
    hw_text = render_homework(extracted)
    (session_dir / "homework.txt").write_text(hw_text, encoding="utf-8")

    meta.timings = timings
    save_meta(session_dir, meta)
    save_to_db(settings.data_dir, meta)

    # Build result.json (new schema)
    transcript_txt_path = session_dir / "transcript.txt"
    transcript_json_path = session_dir / "transcript.json"
    extracted_json_path = session_dir / "extracted.json"
    homework_txt_path = session_dir / "homework.txt"
    transcript_txt = transcript_txt_path.read_text(encoding="utf-8") if transcript_txt_path.exists() else None
    transcript_json_str = transcript_json_path.read_text(encoding="utf-8") if transcript_json_path.exists() else None
    extracted_json_str = extracted_json_path.read_text(encoding="utf-8") if extracted_json_path.exists() else None
    homework_txt = homework_txt_path.read_text(encoding="utf-8") if homework_txt_path.exists() else None

    st = input_path.stat()
    input_recording = InputRecording(
        original_path=str(input_path.resolve()),
        processed_path=None,
        sha256=fp_dict.get("sha256", "") if fp_dict else "",
        size_bytes=fp_dict.get("size", st.st_size) if fp_dict else st.st_size,
        mtime=fp_dict.get("mtime", st.st_mtime) if fp_dict else st.st_mtime,
    )
    total_ms = (transcribe_ms or 0) + (extract_ms or 0) + (render_ms or 0)
    result = Result(
        session_id=session_id,
        student=student,
        created_at_iso=now.isoformat(),
        trigger=trigger,
        input_recording=input_recording,
        outputs=Outputs(
            session_folder=str(session_dir.resolve()),
            transcript_txt=transcript_txt,
            transcript_json=transcript_json_str,
            extracted_json=extracted_json_str,
            homework_txt=homework_txt,
            feedback=feedback_entries,
        ),
        timings_ms=TimingsMs(
            transcribe=transcribe_ms,
            extract=extract_ms,
            render=render_ms,
            total=total_ms if (transcribe_ms is not None and extract_ms is not None and render_ms is not None) else None,
        ),
    )
    (session_dir / "result.json").write_text(
        result.model_dump_json(indent=2),
        encoding="utf-8",
    )
    return session_dir, result


def run_job(job: Job) -> Result:
    """
    Run a single job with idempotency: if the same file already succeeded and force=False,
    return the existing Result without reprocessing.
    """
    settings = get_settings()
    data_dir = Path(settings.data_dir)
    automation_state.init_db(data_dir)
    input_path = Path(job.input_path).expanduser().resolve()
    _validate_input_path(input_path)

    fp_dict = automation_state.compute_fingerprint(input_path, include_sha256=True)
    fingerprint_key = automation_state.fingerprint_key_from_dict(fp_dict)

    if not job.force:
        existing = automation_state.lookup_by_fingerprint(data_dir, fingerprint_key)
        if existing:
            session_id, session_path = existing
            result_path = Path(session_path) / "result.json"
            if result_path.is_file():
                log.info("Idempotent skip: returning existing result for %s", input_path.name)
                return Result.model_validate_json(result_path.read_text(encoding="utf-8"))
    else:
        existing = None

    automation_state.get_or_create_job(
        data_dir,
        job.job_id,
        str(input_path),
        fingerprint_key,
        fp_dict,
    )
    automation_state.mark_job_running(data_dir, job.job_id)

    try:
        session_dir, result = run_pipeline(
            input_path,
            job.student,
            job.platforms,
            trigger=job.trigger,
            metadata=job.metadata,
            fp_dict=fp_dict,
        )
        automation_state.mark_job_succeeded(
            data_dir,
            job.job_id,
            result.session_id,
            str(session_dir),
        )
        return result
    except Exception as e:
        automation_state.mark_job_failed(data_dir, job.job_id, str(e))
        raise


def write_error_json(
    data_dir: Path,
    job_id: str,
    error_message: str,
    stack_trace: str,
    recording_path: str = "",
    user_facing: Optional[str] = None,
) -> Path:
    """Write error.json into data/dead_letter/<job_id>/ (e.g. for webhook)."""
    dead_letter = data_dir / "dead_letter" / job_id
    dead_letter.mkdir(parents=True, exist_ok=True)
    payload = {
        "job_id": job_id,
        "error": error_message,
        "user_message": user_facing or error_message,
        "recording_path": recording_path,
        "stack_trace": stack_trace,
    }
    path = dead_letter / "error.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    log.warning("Wrote %s", path)
    return path
