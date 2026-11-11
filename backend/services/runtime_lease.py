"""Coordinate exclusive access to a file-backed runtime."""

from contextlib import contextmanager
from pathlib import Path

from backend.config.settings import settings


def runtime_lease():
    """Prevent two API processes from recovering/executing the same queue."""
    return file_lease(
        settings.data_dir / "api-worker.lock",
        "Only one API worker may use a data directory",
    )


@contextmanager
def file_lease(path: Path, busy_message: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as lock:
        try:
            import fcntl

            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except ImportError:
            import msvcrt

            lock.seek(0)
            if not lock.read(1):
                lock.write(b"0")
                lock.flush()
            lock.seek(0)
            try:
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError(busy_message) from exc
        except BlockingIOError as exc:
            raise RuntimeError(busy_message) from exc
        # Closing the handle releases the OS lease, including on crashes.
        yield
