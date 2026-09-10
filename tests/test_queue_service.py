import asyncio
from pathlib import Path

import pytest

from backend.services.queue_service import QueueItem, UnifiedQueue


@pytest.mark.asyncio
async def test_cancelled_queued_item_is_not_processed():
    calls = []
    queue = UnifiedQueue(max_concurrent=1)

    async def callback():
        calls.append("processed")

    item = QueueItem(
        file_path=Path("documento.pdf"),
        filename="documento.pdf",
        source="pytest",
        task_id="queued1",
        callback=callback,
    )

    await queue.enqueue(item)
    assert queue.cancel("queued1") is True

    queue.start_worker()
    await asyncio.sleep(0.6)
    queue._worker_task.cancel()

    assert calls == []
    assert queue.qsize() == 0
