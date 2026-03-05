"""Folder watch: detect new recordings, debounce, enqueue and process."""

from __future__ import annotations

import json
import queue
import logging
import shutil
import signal
import threading
import time
from pathlib import Path
from typing import Callable, List, Optional

# Only these extensions for watch (pipeline supports more via ffmpeg)
WATCH_EXTENSIONS = {".m4a", ".mp3", ".wav", ".mp4", ".mov"}

from tutor_feedback.automation.state import init_db
from tutor_feedback.automation.jobs import Job, enqueue, get_queue
from tutor_feedback.automation.runner import run_job
from tutor_feedback.config import get_settings

log = logging.getLogger("tutor_feedback.automation")

STABLE_CHECK_INTERVAL = 1.0


def _is_watch_file(path: Path) -> bool:
    return path.suffix.lower() in WATCH_EXTENSIONS and path.is_file()


def _student_from_filename(path: Path) -> str:
    """Derive student name from filename, e.g. Andy_2026-03-05.m4a -> Andy. Fallback Unknown."""
    stem = path.stem
    for sep in ("_", "-", " "):
        if sep in stem:
            name = stem.split(sep)[0].strip()
            return name or "Unknown"
    return stem or "Unknown"


def _debounce_wait(file_path: Path, stable_seconds: float) -> bool:
    """Return when file size has been stable for `stable_seconds`. Returns True when stable."""
    try:
        last_size = -1
        stable_since = time.monotonic()
        while True:
            if not file_path.is_file():
                return False
            size = file_path.stat().st_size
            if size != last_size:
                last_size = size
                stable_since = time.monotonic()
            elif time.monotonic() - stable_since >= stable_seconds:
                return True
            time.sleep(STABLE_CHECK_INTERVAL)
    except Exception:
        return False


def process_job(job: Job) -> None:
    """Run job via runner.run_job; move file to processed/ or failed/ and write error JSON if failed."""
    settings = get_settings()
    data_dir = Path(settings.data_dir)
    init_db(data_dir)
    watch_dir = Path(job.metadata.get("watch_dir", "")).resolve() if job.metadata.get("watch_dir") else None
    move = job.metadata.get("move", True)
    input_path = Path(job.input_path)
    if not input_path.is_file():
        log.warning("Recording file no longer exists: %s", input_path)
        return

    processed_dir = watch_dir / "processed" if watch_dir else None
    failed_dir = watch_dir / "failed" if watch_dir else None
    if processed_dir:
        processed_dir.mkdir(parents=True, exist_ok=True)
    if failed_dir:
        failed_dir.mkdir(parents=True, exist_ok=True)

    try:
        result = run_job(job)
        log.info("Job %s succeeded -> %s", job.job_id, result.outputs.session_folder)
        if move and watch_dir and input_path.resolve().parent == watch_dir and processed_dir:
            dest = processed_dir / input_path.name
            try:
                shutil.move(str(input_path), str(dest))
            except Exception as e:
                log.warning("Move to processed failed: %s", e)
    except Exception as exc:
        err_msg = str(exc)
        log.exception("Job %s failed: %s", job.job_id, err_msg)
        if move and watch_dir and input_path.resolve().parent == watch_dir and failed_dir:
            dest = failed_dir / input_path.name
            try:
                shutil.move(str(input_path), str(dest))
                error_json = failed_dir / f"error_{input_path.name}.json"
                error_json.write_text(
                    json.dumps({"job_id": job.job_id, "error": err_msg}, indent=2),
                    encoding="utf-8",
                )
            except Exception as e:
                log.warning("Move to failed / write error JSON failed: %s", e)


def run_watch(
    watch_folder: Path,
    platforms: List[str],
    student_from_filename: bool = False,
    default_student: str = "Student",
    move: bool = True,
    stable_seconds: float = 10.0,
    force: bool = False,
    on_stop: Optional[Callable[[], None]] = None,
) -> None:
    """Start folder watch and consumer loop. Blocks until Ctrl+C."""
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
    except ImportError:
        raise RuntimeError("watchdog is required for folder watch. Install with: pip install watchdog")

    watch_folder = Path(watch_folder).resolve()
    if not watch_folder.is_dir():
        raise ValueError(f"Watch folder is not a directory: {watch_folder}")

    (watch_folder / "processed").mkdir(parents=True, exist_ok=True)
    (watch_folder / "failed").mkdir(parents=True, exist_ok=True)

    settings = get_settings()
    data_dir = Path(settings.data_dir)
    init_db(data_dir)
    q = get_queue()
    stop = threading.Event()

    class Handler(FileSystemEventHandler):
        def on_created(self, event):
            if event.is_directory:
                return
            path = Path(event.src_path)
            if not _is_watch_file(path):
                return
            log.info("New file detected: %s (debouncing %s s)", path.name, stable_seconds)
            if not _debounce_wait(path, stable_seconds):
                log.warning("File disappeared or changed during debounce: %s", path)
                return
            student = _student_from_filename(path) if student_from_filename else default_student
            enqueue(
                input_path=str(path),
                student=student,
                platforms=platforms,
                trigger="watch",
                force=force,
                metadata={
                    "watch_dir": str(watch_folder),
                    "move": move,
                },
            )

    observer = Observer()
    observer.schedule(Handler(), str(watch_folder), recursive=False)
    observer.start()
    log.info(
        "Watching %s for new recordings (extensions: %s, stable_seconds=%s)",
        watch_folder,
        ", ".join(sorted(WATCH_EXTENSIONS)),
        stable_seconds,
    )

    def consume():
        while not stop.is_set():
            try:
                job = q.get(timeout=1.0)
                if job is None:
                    break
                process_job(job)
            except queue.Empty:
                continue
            except Exception as e:
                log.exception("Consumer error: %s", e)

    def shutdown(sig=None, frame=None):
        log.info("Shutting down...")
        stop.set()
        observer.stop()
        observer.join(timeout=5)
        if on_stop:
            on_stop()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        consume()
    finally:
        shutdown()
