"""Concurrent cache writers must publish complete, independent JSON files."""

import asyncio
import json
import os
import time
from contextlib import asynccontextmanager

import pytest

from backend.services import cache


@pytest.mark.asyncio
async def test_concurrent_writes_to_same_key_publish_complete_payload(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    original_open = cache.aiofiles.open
    original_replace = cache.aiofiles.os.replace
    both_open = asyncio.Event()
    first_written = asyncio.Event()
    second_written = asyncio.Event()
    both_closed = asyncio.Event()
    opened = closed = 0
    paths = []
    long_payload = {"answer": "long answer " * 2000}
    short_payload = {"answer": "short"}

    class CoordinatedFile:
        def __init__(self, stream):
            self.stream = stream

        async def write(self, text):
            if json.loads(text)["payload"] == long_payload:
                await self.stream.write(text)
                await self.stream.flush()
                first_written.set()
                await second_written.wait()
            else:
                await first_written.wait()
                await self.stream.write(text)
                await self.stream.flush()
                second_written.set()

    @asynccontextmanager
    async def coordinated_open(path, *args, **kwargs):
        nonlocal opened, closed
        async with original_open(path, *args, **kwargs) as stream:
            paths.append(path)
            opened += 1
            if opened == 2:
                both_open.set()
            await both_open.wait()
            yield CoordinatedFile(stream)
        closed += 1
        if closed == 2:
            both_closed.set()

    async def coordinated_replace(*args):
        await both_closed.wait()
        return await original_replace(*args)

    with monkeypatch.context() as writes:
        writes.setattr(cache.aiofiles, "open", coordinated_open)
        writes.setattr(cache.aiofiles.os, "replace", coordinated_replace)
        await asyncio.wait_for(
            asyncio.gather(
                cache.set_cache_bytes(b"same image", long_payload),
                cache.set_cache_bytes(b"same image", short_payload),
            ),
            timeout=10,
        )

    assert await cache.get_cached_bytes(b"same image") in (long_payload, short_payload)
    assert len(set(paths)) == 2
    assert len(list(tmp_path.glob("*.json"))) == 1
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.asyncio
async def test_clear_cache_removes_stale_temporaries_but_keeps_recent_ones(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    await cache.set_cache_bytes(b"image", {"answer": "cached"})
    for name in ("old.json.tmp", ".cache-orphan.tmp"):
        path = tmp_path / name
        path.write_text("partial", encoding="utf-8")
        old = time.time() - cache.CACHE_TEMP_MAX_AGE_SECONDS - 60
        os.utime(path, (old, old))
    recent = tmp_path / ".cache-recent.tmp"
    recent.write_text("in progress elsewhere", encoding="utf-8")

    assert await cache.clear_cache() == 3
    assert list(tmp_path.iterdir()) == [recent]


@pytest.mark.asyncio
async def test_clear_cache_preserves_even_an_old_active_temporary(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    original_open = cache.aiofiles.open
    writing = asyncio.Event()
    release = asyncio.Event()

    class PausedFile:
        def __init__(self, stream):
            self.stream = stream

        async def write(self, text):
            await self.stream.write(text)
            await self.stream.flush()
            writing.set()
            await release.wait()

    @asynccontextmanager
    async def paused_open(*args, **kwargs):
        async with original_open(*args, **kwargs) as stream:
            yield PausedFile(stream)

    with monkeypatch.context() as writes:
        writes.setattr(cache.aiofiles, "open", paused_open)
        task = asyncio.create_task(cache.set_cache_bytes(b"image", {"answer": "complete"}))
        try:
            await asyncio.wait_for(writing.wait(), timeout=10)
            temporary = next(tmp_path.glob("*.tmp"))
            old = time.time() - cache.CACHE_TEMP_MAX_AGE_SECONDS - 60
            os.utime(temporary, (old, old))
            assert await cache.clear_cache() == 0
            assert temporary.exists()
        finally:
            release.set()
            await asyncio.wait_for(task, timeout=10)

    assert await cache.get_cached_bytes(b"image") == {"answer": "complete"}
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.asyncio
async def test_failed_replace_preserves_previous_cache_and_removes_temporary(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    await cache.set_cache_bytes(b"image", {"answer": "previous"})

    async def fail_replace(*args):
        raise OSError("replacement unavailable")

    monkeypatch.setattr(cache.aiofiles.os, "replace", fail_replace)
    await cache.set_cache_bytes(b"image", {"answer": "new"})

    assert await cache.get_cached_bytes(b"image") == {"answer": "previous"}
    assert not list(tmp_path.glob("*.tmp"))
