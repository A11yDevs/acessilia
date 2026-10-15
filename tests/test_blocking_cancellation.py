import asyncio
import threading

import pytest

from backend.services.blocking import run_blocking


@pytest.mark.asyncio
async def test_repeated_cancellation_waits_for_thread_before_cleanup():
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def operation():
        started.set()
        release.wait(timeout=5)
        finished.set()

    task = asyncio.create_task(run_blocking(operation))
    try:
        while not started.is_set():
            await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not task.done(), "cancellation abandoned a thread still using files"
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert finished.is_set()
