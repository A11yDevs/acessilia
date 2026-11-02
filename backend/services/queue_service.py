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
        self._active_items: dict[str, QueueItem] = {}
        self._active_tasks: dict[str, asyncio.Task] = {}
        self._started_items: set[str] = set()
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

    def cancel(self, task_id: str) -> bool:
        for item in list(self._queue):
            if item.task_id == task_id:
                self._queue.remove(item)
                try:
                    item.file_path.unlink(missing_ok=True)
                except OSError as exc:
                    logger.warning("Could not remove cancelled upload {}: {}", item.file_path, exc)
                logger.info("Fila Unificada: tarefa {} cancelada antes do processamento", task_id)
                return True
        task = self._active_tasks.get(task_id)
        if task is not None and not task.done():
            if task_id not in self._started_items:
                try:
                    self._active_items[task_id].file_path.unlink(missing_ok=True)
                except OSError as exc:
                    logger.warning("Could not remove cancelled upload {}: {}", task_id, exc)
            if not task.cancelling():
                task.cancel()
            return True
        return False

    def _finish_item(self, task_id: str) -> None:
        if self._active_items.pop(task_id, None) is not None:
            self._processing_count -= 1
        self._active_tasks.pop(task_id, None)
        self._started_items.discard(task_id)

    async def _process_item(self, item: QueueItem):
        self._started_items.add(item.task_id)
        try:
            logger.info(t(LOG_WORKER_TASK_STARTING).format(filename=item.filename, source=item.source))
            await item.callback(**item.callback_args)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error(t(LOG_WORKER_TASK_ERROR).format(filename=item.filename, error=exc))
        finally:
            self._finish_item(item.task_id)
            logger.info(t(LOG_WORKER_TASK_COMPLETED).format(filename=item.filename))

    def _can_start_item(self) -> bool:
        # Retain cancelling tasks (and their protected files) until they join
        # blocking work, but allow one replacement to run in the meantime.
        # The total cap prevents repeated cancellations spawning unbounded work.
        cancelling = sum(
            bool(task.cancelling())
            for task in self._active_tasks.values() if not task.done()
        )
        return (
            self._processing_count < self._max_concurrent + 1
            and self._processing_count - cancelling < self._max_concurrent
        )

    async def _worker(self):
        try:
            while True:
                async with self._lock:
                    while self._queue and self._can_start_item():
                        item = self._queue.popleft()
                        self._processing_count += 1
                        self._active_items[item.task_id] = item
                        task = asyncio.create_task(self._process_item(item))
                        self._active_tasks[item.task_id] = task
                        task.add_done_callback(lambda _task, key=item.task_id: self._finish_item(key))
                await asyncio.sleep(0.05)
        finally:
            tasks = list(self._active_tasks.values())
            for task in tasks:
                if not task.cancelling():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    def get_position(self, task_id: str) -> int:
        for i, item in enumerate(self._queue):
            if item.task_id == task_id:
                return i + 1
        return 0

    def qsize(self) -> int:
        return len(self._queue)

    def protected_file_paths(self) -> set[Path]:
        return {
            item.file_path.resolve()
            for item in [*self._queue, *self._active_items.values()]
        }


unified_queue = UnifiedQueue(max_concurrent=1)
