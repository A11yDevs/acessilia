import asyncio
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Coroutine, Any

from backend.i18n import t
from backend.log_messages import (
    LOG_QUEUE_ITEM_ENQUEUED,
    LOG_WORKER_STARTED,
    LOG_WORKER_TASK_COMPLETED,
    LOG_WORKER_TASK_ERROR,
    LOG_WORKER_TASK_STARTING,
)
from backend.tools.logger import logger


@dataclass
class QueueItem:
    file_path: Path
    filename: str
    source: str
    callback: Callable[..., Coroutine]
    callback_args: dict[str, Any] = field(default_factory=dict)
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    added_at: float = field(default_factory=time.time)


class UnifiedQueue:
    def __init__(self, max_concurrent: int = 1):
        self._queue: deque[QueueItem] = deque()
        self._processing_count = 0
        self._max_concurrent = max_concurrent
        self._lock = asyncio.Lock()
        self._worker_task: asyncio.Task | None = None

    def start_worker(self):
        if self._worker_task is None or self._worker_task.done():
            self._worker_task = asyncio.create_task(self._worker())
            logger.info(t(LOG_WORKER_STARTED))

    async def enqueue(self, item: QueueItem) -> int:
        async with self._lock:
            self._queue.append(item)
            pos = len(self._queue)
            logger.info(
                t(LOG_QUEUE_ITEM_ENQUEUED).format(
                    filename=item.filename, source=item.source, position=pos
                )
            )
            return pos

    async def _worker(self):
        while True:
            item = None
            async with self._lock:
                if self._queue and self._processing_count < self._max_concurrent:
                    item = self._queue.popleft()
                    self._processing_count += 1

            if item:
                try:
                    logger.info(
                        t(LOG_WORKER_TASK_STARTING).format(
                            filename=item.filename, source=item.source
                        )
                    )
                    await item.callback(**item.callback_args)
                except Exception as e:
                    logger.error(
                        t(LOG_WORKER_TASK_ERROR).format(
                            filename=item.filename, error=e
                        )
                    )
                finally:
                    async with self._lock:
                        self._processing_count -= 1
                    logger.info(
                        t(LOG_WORKER_TASK_COMPLETED).format(filename=item.filename)
                    )

            await asyncio.sleep(0.5)

    def get_position(self, task_id: str) -> int:
        for i, item in enumerate(self._queue):
            if item.task_id == task_id:
                return i + 1
        return 0

    def qsize(self) -> int:
        return len(self._queue)


unified_queue = UnifiedQueue(max_concurrent=1)
