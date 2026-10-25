"""Concurrent cache writers must publish complete, independent JSON files."""

import asyncio
import json
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
async def test_failed_replace_preserves_previous_cache_and_removes_temporary(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    await cache.set_cache_bytes(b"image", {"answer": "previous"})

    async def fail_replace(*args):
        raise OSError("replacement unavailable")

    monkeypatch.setattr(cache.aiofiles.os, "replace", fail_replace)
    await cache.set_cache_bytes(b"image", {"answer": "new"})

    assert await cache.get_cached_bytes(b"image") == {"answer": "previous"}
    assert not list(tmp_path.glob("*.tmp"))
