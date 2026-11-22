"""Durable checkpoints of a job's pipeline, so a restart can continue it (#407).

Each phase of the PDDL pipeline writes one JSON document under
``data_dir/jobs/<task_id>/checkpoints``. The document carries a schema version
and the SHA-256 of its payload, so a checkpoint written by another version or
left half-written is never used as if it were valid. Writes replace the file
atomically: a process killed mid-write leaves the previous checkpoint, never a
truncated one.

There is no checkpoint outside a job. The service gives a job's run its
checkpoints (``FileJobCheckpoints``, the core's ``JobCheckpoints`` port); the
benchmark and the CLI run without a job, so they write nothing.

Checkpoints are removed when the job reaches a terminal state (the worker does
it) and swept by the periodic cleanup if a job disappears without one. The
decision is recorded in ``docs/adr/0020-job-resumption-and-operation-journal.md``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import time
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from acessilia_core.logger import logger
from acessilia_core.ports import CHECKPOINT_PHASES, JobCheckpoints
from backend.config.settings import settings

#: Version of the checkpoint document. A job never resumes on another version:
#: the caller treats the phase as absent, or the recovery fails the job.
CHECKPOINT_VERSION = 1

#: Phase names written by the pipeline, in order; the core names them.
PHASES = CHECKPOINT_PHASES

#: Task ids reach a path, so only the shape the API generates is accepted.
_TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class CheckpointError(RuntimeError):
    """A checkpoint exists but cannot be trusted, so the phase cannot resume."""


def _directory(task_id: str) -> Path:
    if not _TASK_ID.fullmatch(task_id):
        raise CheckpointError(f"invalid task id for a checkpoint: {task_id!r}")
    return settings.data_dir / "jobs" / task_id / "checkpoints"


def _path(task_id: str, phase: str) -> Path:
    if phase not in PHASES:
        raise ValueError(f"unknown checkpoint phase: {phase!r}")
    return _directory(task_id) / f"{phase}.json"


def _digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def save(task_id: str, phase: str, payload: dict[str, Any]) -> None:
    """Replace the checkpoint of ``phase`` atomically.

    A failure is the caller's to handle: the pipeline treats a checkpoint that
    cannot be written as a warning, so a full disk does not fail the document.
    """
    destination = _path(task_id, phase)
    destination.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "version": CHECKPOINT_VERSION,
        "phase": phase,
        "saved_at": time.time(),
        "sha256": _digest(payload),
        "payload": payload,
    }
    data = json.dumps(document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    temporary = destination.with_name(f".{phase}.{uuid.uuid4().hex}.tmp")
    try:
        with open(temporary, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def load(task_id: str, phase: str) -> dict[str, Any] | None:
    """The payload of ``phase``, ``None`` when it was never written.

    Raises:
        CheckpointError: The file exists but is unreadable, from another
            schema version, or its payload does not match its hash.
    """
    path = _path(task_id, phase)
    if not path.is_file():
        return None
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CheckpointError(f"{path} is not readable: {exc}") from exc
    if not isinstance(document, dict):
        raise CheckpointError(f"{path} is not a checkpoint object")
    if document.get("version") != CHECKPOINT_VERSION:
        raise CheckpointError(
            f"{path} was written by checkpoint version {document.get('version')!r}, "
            f"not {CHECKPOINT_VERSION}"
        )
    payload = document.get("payload")
    if not isinstance(payload, dict):
        raise CheckpointError(f"{path} has no payload object")
    if document.get("sha256") != _digest(payload):
        raise CheckpointError(f"{path} does not match its payload hash")
    return payload


def resumable(task_id: str) -> bool:
    """Whether a job has at least one checkpoint and every one can be trusted.

    The recovery uses it before re-enqueuing a job left ``processing``: a job
    without a usable checkpoint fails as it did before resumption existed.
    """
    try:
        directory = _directory(task_id)
    except CheckpointError:
        return False
    if not directory.is_dir():
        return False
    found = False
    for path in sorted(directory.glob("*.json")):
        if path.stem not in PHASES:
            continue
        found = True
        try:
            load(task_id, path.stem)
        except CheckpointError as exc:
            logger.warning("Job {}: checkpoint {} is not usable: {}", task_id, path.name, exc)
            return False
    return found


def remove(task_id: str, phase: str) -> None:
    """Remove one phase's checkpoint, keeping the others (a replan replaces it)."""
    try:
        path = _path(task_id, phase)
    except (CheckpointError, ValueError):
        return
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("Job {}: checkpoint {} not removed: {}", task_id, phase, exc)


def clear(task_id: str) -> None:
    """Remove every checkpoint of a job that no longer needs to resume."""
    try:
        directory = _directory(task_id)
    except CheckpointError:
        return
    shutil.rmtree(directory.parent, ignore_errors=True)


class FileJobCheckpoints(JobCheckpoints):
    """The core's ``JobCheckpoints`` port for one job, on these files
    (ADR-0016, step 4)."""

    def __init__(
        self, job_id: str, options: Mapping[str, Mapping[str, Any]] | None = None
    ) -> None:
        self.job_id = job_id
        #: The service's own processing options, by stage (#549).
        self.options = dict(options or {})

    def load(self, phase: str) -> dict[str, Any] | None:
        return load(self.job_id, phase)

    def save(self, phase: str, payload: dict[str, Any]) -> None:
        save(self.job_id, phase, payload)

    def remove(self, phase: str) -> None:
        remove(self.job_id, phase)


def expire(max_age_seconds: float, now: float | None = None) -> int:
    """Remove job checkpoint directories untouched for longer than ``max_age_seconds``."""
    root = settings.data_dir / "jobs"
    if not root.is_dir():
        return 0
    current = now if now is not None else time.time()
    removed = 0
    for job_dir in root.iterdir():
        if not job_dir.is_dir():
            continue
        try:
            newest = max(
                (path.stat().st_mtime for path in job_dir.rglob("*") if path.is_file()),
                default=job_dir.stat().st_mtime,
            )
        except OSError:
            continue
        if current - newest <= max_age_seconds:
            continue
        shutil.rmtree(job_dir, ignore_errors=True)
        removed += 1
    return removed


__all__ = [
    "CHECKPOINT_VERSION",
    "PHASES",
    "CheckpointError",
    "FileJobCheckpoints",
    "clear",
    "expire",
    "load",
    "remove",
    "resumable",
    "save",
]
