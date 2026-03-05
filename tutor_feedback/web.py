"""FastAPI web interface for the tutor-feedback pipeline."""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, File, Form, UploadFile, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from tutor_feedback import __version__
from tutor_feedback.config import get_settings
from tutor_feedback.models import SessionMeta

log = logging.getLogger("tutor_feedback")

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Tutor Feedback Pipeline", version=__version__)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# In-memory job tracking: job_id → {status, logs, result, ...}
_jobs: Dict[str, dict] = {}


@app.get("/", response_class=HTMLResponse)
async def index():
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/api/styles")
async def get_styles():
    from tutor_feedback.styles import list_styles, load_style, get_example_count

    settings = get_settings()
    names = list_styles(settings.styles_dir)
    styles = []
    for name in names:
        s = load_style(name, settings.styles_dir)
        styles.append({
            "name": s.name,
            "format": s.format,
            "word_limit": s.word_limit,
            "sections": s.required_sections,
            "tone": s.tone,
            "examples": get_example_count(name, settings.styles_dir),
        })
    return styles


@app.get("/api/sessions")
async def get_sessions():
    settings = get_settings()
    sessions_dir = settings.data_dir / "sessions"
    if not sessions_dir.is_dir():
        return []
    results = []
    for folder in sorted(sessions_dir.iterdir(), reverse=True):
        if not folder.is_dir():
            continue
        meta_path = folder / "meta.json"
        if meta_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta["folder_name"] = folder.name
            meta["has_extracted"] = (folder / "extracted.json").is_file()
            feedback_files = [f.stem.replace("feedback_", "") for f in folder.glob("feedback_*.txt")]
            meta["feedback_platforms"] = feedback_files
            results.append(meta)
        else:
            results.append({"folder_name": folder.name, "session_folder": str(folder)})
    return results


@app.get("/api/sessions/{folder_name}/files")
async def get_session_files(folder_name: str):
    settings = get_settings()
    folder = settings.data_dir / "sessions" / folder_name
    if not folder.is_dir():
        raise HTTPException(404, "Session not found")
    files = {}
    for f in sorted(folder.iterdir()):
        if f.suffix in (".txt", ".json") and f.name != "audio.wav":
            files[f.name] = f.read_text(encoding="utf-8")
    return files


@app.post("/api/run")
async def start_run(
    file: UploadFile = File(...),
    student: str = Form(...),
    platforms: str = Form(...),
):
    """Accept upload and start pipeline in background. Returns a job ID for SSE tracking."""
    settings = get_settings()
    platform_list = [p.strip() for p in platforms.split(",") if p.strip()]

    if not platform_list:
        raise HTTPException(400, "At least one platform is required")
    if not student.strip():
        raise HTTPException(400, "Student name is required")

    from tutor_feedback.ffmpeg_utils import SUPPORTED_EXTENSIONS

    ext = Path(file.filename or "").suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(400, f"Unsupported file type '{ext}'")

    # Save uploaded file to a temp location
    upload_dir = settings.data_dir / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    tmp_path = upload_dir / f"{uuid.uuid4().hex}{ext}"
    with open(tmp_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    job_id = uuid.uuid4().hex[:12]
    _jobs[job_id] = {
        "status": "queued",
        "logs": [],
        "result": None,
        "error": None,
        "session_folder": None,
    }

    asyncio.get_event_loop().run_in_executor(
        None,
        _run_pipeline_sync,
        job_id,
        tmp_path,
        student.strip(),
        platform_list,
        settings,
    )

    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str):
    """SSE stream of pipeline progress for a given job."""
    if job_id not in _jobs:
        raise HTTPException(404, "Job not found")

    async def stream():
        last_idx = 0
        while True:
            job = _jobs[job_id]
            logs = job["logs"]
            while last_idx < len(logs):
                yield {"event": "log", "data": json.dumps(logs[last_idx])}
                last_idx += 1

            if job["status"] in ("done", "error"):
                if job["status"] == "done":
                    yield {"event": "done", "data": json.dumps(job["result"])}
                else:
                    yield {"event": "error", "data": json.dumps({"error": job["error"]})}
                break

            await asyncio.sleep(0.3)

    return EventSourceResponse(stream())


def _log_job(job_id: str, step: str, message: str, progress: int = 0):
    """Append a log entry to a running job."""
    entry = {
        "step": step,
        "message": message,
        "progress": progress,
        "timestamp": datetime.now().strftime("%H:%M:%S"),
    }
    _jobs[job_id]["logs"].append(entry)
    log.info("[job %s] %s: %s", job_id, step, message)


def _run_pipeline_sync(
    job_id: str,
    input_path: Path,
    student: str,
    platforms: List[str],
    settings,
):
    """Run the full pipeline synchronously (called from a thread)."""
    from tutor_feedback.ffmpeg_utils import check_ffmpeg, convert_to_wav, get_audio_duration
    from tutor_feedback.transcribe import transcribe, save_transcript
    from tutor_feedback.claude_extract import extract_session
    from tutor_feedback.claude_render import render_feedback, render_homework
    from tutor_feedback.styles import load_style
    from tutor_feedback.storage import create_session_folder, save_meta, save_to_db

    job = _jobs[job_id]
    job["status"] = "running"
    timings: Dict[str, float] = {}

    try:
        # Pre-flight
        _log_job(job_id, "preflight", "Checking ffmpeg...", 5)
        check_ffmpeg()

        if not settings.anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set. Add it to your .env file.")

        # Create session folder
        now = datetime.now()
        sid = f"{now.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        session_dir = create_session_folder(settings.data_dir, student, now)
        job["session_folder"] = str(session_dir)
        _log_job(job_id, "setup", f"Session: {session_dir.name}", 10)

        meta = SessionMeta(
            session_id=sid,
            student_name=student,
            input_file=str(input_path),
            session_folder=str(session_dir),
            whisper_model=settings.whisper_model,
            claude_model=settings.claude_model,
            platforms=platforms,
        )

        # Step 1: Convert audio
        _log_job(job_id, "convert", "Converting audio to WAV...", 15)
        wav_path = session_dir / "audio.wav"
        t0 = time.time()
        convert_to_wav(input_path, wav_path)
        timings["convert"] = round(time.time() - t0, 2)
        duration_minutes = get_audio_duration(wav_path) / 60.0
        _log_job(job_id, "convert", f"Done ({timings['convert']:.1f}s, {duration_minutes:.1f} min)", 20)

        # Step 2: Transcribe
        _log_job(job_id, "transcribe", f"Transcribing with Whisper ({settings.whisper_model})...", 25)
        t0 = time.time()
        plain_text, segments = transcribe(wav_path, settings.whisper_model)
        timings["transcribe"] = round(time.time() - t0, 2)
        save_transcript(session_dir, plain_text, segments)
        _log_job(job_id, "transcribe", f"Done ({len(segments)} segments, {timings['transcribe']:.1f}s)", 45)

        # Step 3: Extract
        _log_job(job_id, "extract", "Extracting session data with Claude...", 50)
        t0 = time.time()
        extracted, _ = extract_session(
            transcript_json=segments,
            student_name=student,
            session_datetime=now.isoformat(),
            duration_minutes=duration_minutes,
            api_key=settings.anthropic_api_key,
            model=settings.claude_model,
        )
        timings["extract"] = round(time.time() - t0, 2)
        (session_dir / "extracted.json").write_text(
            json.dumps(extracted.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        _log_job(job_id, "extract", f"Done ({timings['extract']:.1f}s)", 65)

        # Step 4: Render
        total_platforms = len(platforms)
        for i, p in enumerate(platforms):
            pct = 70 + int((i / total_platforms) * 25)
            _log_job(job_id, "render", f"Rendering {p} feedback...", pct)
            style = load_style(p, settings.styles_dir)
            t0 = time.time()
            feedback_text, _ = render_feedback(
                extracted, style,
                api_key=settings.anthropic_api_key,
                model=settings.claude_model,
            )
            timings[f"render_{p}"] = round(time.time() - t0, 2)
            (session_dir / f"feedback_{p}.txt").write_text(feedback_text, encoding="utf-8")
            _log_job(job_id, "render", f"{p} done ({len(feedback_text.split())} words, {timings[f'render_{p}']:.1f}s)", pct + 5)

        # Homework
        hw_text = render_homework(extracted)
        (session_dir / "homework.txt").write_text(hw_text, encoding="utf-8")

        # Save meta
        meta.timings = timings
        save_meta(session_dir, meta)
        save_to_db(settings.data_dir, meta)

        _log_job(job_id, "done", "Pipeline complete!", 100)
        job["status"] = "done"
        job["result"] = {
            "session_folder": session_dir.name,
            "student": student,
            "platforms": platforms,
            "timings": timings,
            "segments": len(segments),
            "subjects": extracted.subjects,
            "topics": extracted.topics_covered,
        }

    except Exception as exc:
        _log_job(job_id, "error", str(exc), 0)
        job["status"] = "error"
        job["error"] = str(exc)
    finally:
        # Clean up temp upload
        try:
            input_path.unlink(missing_ok=True)
        except Exception:
            pass
