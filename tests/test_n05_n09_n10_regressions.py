"""Regressions for observability auth, periodic cache cleanup and artifact IDs."""

import asyncio
import json
import multiprocessing
import os
import time
from pathlib import Path
from threading import Event, Thread

import httpx
import pytest
from fastapi import Depends, FastAPI

from acessilia_sdk.toolbox.artifacts import ArtifactRef
from acessilia_sdk.toolbox.errors import ToolboxContractViolation
from backend.api.observability_auth import require_observability_token
from backend.config.settings import settings
from backend.services import cache, cleanup_service


@pytest.mark.parametrize("prefix", ["", "sha256:"])
@pytest.mark.parametrize("suffix", ["\n", "\r\n", " ", "\t", "\x00"])
def test_artifact_id_rejects_trailing_characters(prefix, suffix):
    with pytest.raises(ToolboxContractViolation):
        ArtifactRef.parse(prefix + "a" * 64 + suffix)


@pytest.mark.parametrize("prefix", ["", "sha256:"])
def test_artifact_id_accepts_exact_digest(prefix):
    ref = ArtifactRef.parse(prefix + "a" * 64)
    assert ref.digest == "a" * 64
    assert ref.artifact_id == prefix + "a" * 64


def _publish_in_process(directory, attempting, finished):
    cache.CACHE_DIR = Path(directory)
    original = cache._publish_cache

    def publish(*args):
        attempting.set()
        original(*args)

    cache._publish_cache = publish
    asyncio.run(cache._write_cached("entry", "fresh"))
    finished.set()


def test_periodic_sweep_serializes_with_writer_in_another_process(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    entry = tmp_path / "entry.json"
    entry.write_text('{"payload": "old"}')
    old = time.time() - cleanup_service.CACHE_MAX_AGE - 60
    os.utime(entry, (old, old))
    inspected, release = Event(), Event()
    original_stat = Path.stat
    captured = False

    def paused_stat(path, *args, **kwargs):
        nonlocal captured
        snapshot = original_stat(path, *args, **kwargs)
        if path == entry and not captured:
            captured = True
            inspected.set()
            assert release.wait(20)
        return snapshot

    monkeypatch.setattr(Path, "stat", paused_stat)
    context = multiprocessing.get_context("spawn")
    attempting, finished = context.Event(), context.Event()
    process = context.Process(
        target=_publish_in_process, args=(str(tmp_path), attempting, finished)
    )
    errors = []

    def sweep():
        try:
            cleanup_service._clean_cache_directory()
        except BaseException as exc:
            errors.append(exc)

    thread = Thread(target=sweep)
    thread.start()
    try:
        assert inspected.wait(10)
        process.start()
        assert attempting.wait(20)
        assert not finished.wait(0.3), (
            "writer published while sweep held an old snapshot"
        )
    finally:
        release.set()
        thread.join(10)
        if process.pid is not None:
            process.join(20)
            if process.is_alive():
                process.terminate()
                process.join(5)
    assert not thread.is_alive()
    assert not errors
    assert process.exitcode == 0
    assert finished.is_set()
    assert json.loads(entry.read_text())["payload"] == "fresh"
    # A later sweep observes and preserves the new version.
    cleanup_service._clean_cache_directory()
    assert entry.exists()
