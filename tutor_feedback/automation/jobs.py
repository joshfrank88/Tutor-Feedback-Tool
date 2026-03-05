"""Job model and in-memory queue for automation."""

from __future__ import annotations

import logging
import queue
import uuid
from pathlib import Path
from typing import Any, Dict, List

from pydantic import BaseModel, Field

log = logging.getLogger("tutor_feedback.automation")


class Job(BaseModel):
    job_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    input_path: str
    student: str
    platforms: List[str] = Field(default_factory=lambda: ["private"])
    trigger: str = "watch"
    force: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)


_job_queue: queue.Queue = queue.Queue()


def enqueue(
    input_path: str,
    student: str,
    platforms: List[str],
    trigger: str = "watch",
    force: bool = False,
    metadata: Dict[str, Any] | None = None,
    job_id: str | None = None,
) -> Job:
    job = Job(
        job_id=job_id or uuid.uuid4().hex[:12],
        input_path=input_path,
        student=student,
        platforms=platforms,
        trigger=trigger,
        force=force,
        metadata=metadata or {},
    )
    _job_queue.put(job)
    log.info("Enqueued job %s (trigger=%s)", job.job_id, trigger)
    return job


def get_queue() -> queue.Queue:
    return _job_queue
