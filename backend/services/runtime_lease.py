"""Prevent two API processes from recovering/executing the same local queue."""

from contextlib import contextmanager

from backend.config.settings import settings


@contextmanager
def runtime_lease():
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    path = settings.data_dir / "api-worker.lock"
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
                raise RuntimeError(
                    "Only one API worker may use a data directory"
                ) from exc
        except BlockingIOError as exc:
            raise RuntimeError("Only one API worker may use a data directory") from exc
        try:
            yield
        finally:
            # Closing the handle releases the OS lease, including on crashes.
            lock.close()
