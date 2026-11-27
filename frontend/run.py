#!/usr/bin/env python3
import asyncio
import csv
import os
import subprocess
import sys
from typing import BinaryIO

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

from acessilia_core.i18n import t
from acessilia_core.i18n.log_messages import (
    LOG_API_INTERFACE_ENABLED,
    LOG_BOT_ALREADY_RUNNING,
    LOG_BOT_INTERRUPTED_BY_USER,
    LOG_FATAL_ERROR_IN_BOT,
    LOG_LOCK_ACQUIRED,
    LOG_LOCK_ALREADY_HELD,
    LOG_LOCK_FILE_STALE,
    LOG_LOCK_OWNER_UNKNOWN,
    LOG_LOCK_RELEASED,
    LOG_LOCK_UNUSABLE,
    LOG_NO_INTERFACE_ENABLED,
    LOG_STARTING_INTERFACES,
    LOG_TELEGRAM_INTERFACE_ENABLED,
    LOG_TELEGRAM_INTERFACE_NO_TOKEN,
    LOG_WEB_INTERFACE_ENABLED,
)
from acessilia_core.logger import logger
from backend.config.process_setup import setup_process
from backend.config.settings import settings

LOCK_FILE = os.path.join(os.path.dirname(__file__), "bot.lock")
# The console entry point used a separate lock before both entry points shared
# this runtime. Keep recognizing it during an in-place upgrade.
LEGACY_LOCK_FILE = os.path.join(os.path.dirname(__file__), "cli", "bot.lock")

#: The open handle that holds the OS lock for this process. The lock lives as
#: long as the handle is open, so it must stay referenced until release_lock.
_LOCK_HANDLE: BinaryIO | None = None


class _ProcessCheckError(RuntimeError):
    """The liveness of the process named by a lock file could not be checked."""


def _windows_process_running(pid: int) -> bool:
    """Whether ``tasklist`` reports exactly ``pid``, never a longer number."""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
            capture_output=True,
            text=True,
        )
    except OSError as error:
        raise _ProcessCheckError(str(error)) from error
    if result.returncode != 0:
        raise _ProcessCheckError(
            result.stderr.strip() or f"tasklist exited with {result.returncode}"
        )
    # Match the PID column of the CSV output, not a substring: 4321 must not
    # match 14321 or 43210 (#742).
    return any(
        len(row) > 1 and row[1].strip() == str(pid)
        for row in csv.reader(result.stdout.splitlines())
    )


def _is_process_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if sys.platform == "win32":
        return _windows_process_running(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError as error:
        # Another user (or a PID namespace) owns the process. Its liveness is
        # unknown, so the caller must not treat the lock as stale (#742).
        raise _ProcessCheckError(str(error)) from error
    except OSError as error:
        # Any other failure to probe is also unknown, never "stale".
        raise _ProcessCheckError(str(error)) from error
    return True


def _read_lock_pid(handle: BinaryIO) -> int | None:
    handle.seek(0)
    try:
        pid = int(handle.read().strip())
    except ValueError:
        return None
    return pid if pid > 0 else None


def _open_lock_file(path: str) -> BinaryIO:
    """Open the lock file for the process lifetime, without truncating it."""
    try:
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    except OSError as error:
        logger.critical(t(LOG_LOCK_UNUSABLE).format(path=path, error=error))
        sys.exit(1)
    handle = os.fdopen(descriptor, "r+b")
    if sys.platform == "win32":
        # msvcrt.locking() needs a byte to lock; an empty file is normal
        # before the first start.
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
    return handle


def _acquire_os_lock(handle: BinaryIO) -> bool:
    """Take the exclusive OS lock without waiting; False when another holder has it."""
    try:
        if sys.platform == "win32":
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _release_os_lock(handle: BinaryIO) -> None:
    try:
        if sys.platform == "win32":
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


def _abandon_lock(handle: BinaryIO) -> None:
    _release_os_lock(handle)
    try:
        handle.close()
    except OSError:
        pass


def _write_lock_pid(handle: BinaryIO) -> None:
    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()).encode("ascii"))
    handle.flush()
    os.fsync(handle.fileno())


def _check_previous_owner(handle: BinaryIO, path: str) -> None:
    """Refuse a live PID left by a runtime that predates the OS lock.

    The OS lock already excludes another holder of this lock. An in-place
    upgrade can still find a PID written by the old implementation, which did
    not hold the OS lock: if that process is alive, starting a second instance
    would be wrong, and if its liveness cannot be checked the lock is kept.
    """
    pid = _read_lock_pid(handle)
    if pid is None or pid == os.getpid():
        return
    try:
        running = _is_process_running(pid)
    except _ProcessCheckError as error:
        logger.critical(
            t(LOG_LOCK_OWNER_UNKNOWN).format(path=path, pid=pid, error=error)
        )
        _abandon_lock(handle)
        sys.exit(1)
    if running:
        logger.critical(t(LOG_BOT_ALREADY_RUNNING).format(pid=pid))
        _abandon_lock(handle)
        sys.exit(1)
    logger.warning(t(LOG_LOCK_FILE_STALE).format(pid=pid))


def _check_legacy_lock(path: str) -> None:
    """Refuse a live legacy lock, and remove a stale or malformed one."""
    if not os.path.exists(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as file:
            pid = int(file.read().strip())
    except FileNotFoundError:
        return
    except ValueError:
        pass
    except OSError as error:
        logger.critical(t(LOG_LOCK_UNUSABLE).format(path=path, error=error))
        sys.exit(1)
    else:
        if pid <= 0:
            pass
        else:
            try:
                running = _is_process_running(pid)
            except _ProcessCheckError as error:
                logger.critical(
                    t(LOG_LOCK_OWNER_UNKNOWN).format(path=path, pid=pid, error=error)
                )
                sys.exit(1)
            if running:
                logger.critical(t(LOG_BOT_ALREADY_RUNNING).format(pid=pid))
                sys.exit(1)
            logger.warning(t(LOG_LOCK_FILE_STALE).format(pid=pid))
    try:
        os.remove(path)
    except FileNotFoundError:
        return
    except OSError as error:
        logger.critical(t(LOG_LOCK_UNUSABLE).format(path=path, error=error))
        sys.exit(1)


def acquire_lock() -> None:
    """Take the single-instance lock, refusing a live holder and replacing a stale one.

    The lock is an exclusive OS lock on ``LOCK_FILE`` (``fcntl.flock`` on
    POSIX, ``msvcrt.locking`` on Windows), held by an open handle for the
    process lifetime. The PID written to the file is for diagnostics and for
    recognizing a lock left by an older runtime; the OS lock, not the file's
    existence or content, decides whether two starts may run (#742).
    """
    global _LOCK_HANDLE
    _check_legacy_lock(LEGACY_LOCK_FILE)
    handle = _open_lock_file(LOCK_FILE)
    if not _acquire_os_lock(handle):
        pid = _read_lock_pid(handle)
        if pid is None:
            logger.critical(t(LOG_LOCK_ALREADY_HELD).format(path=LOCK_FILE))
        else:
            logger.critical(t(LOG_BOT_ALREADY_RUNNING).format(pid=pid))
        handle.close()
        sys.exit(1)
    _check_previous_owner(handle, LOCK_FILE)
    try:
        _write_lock_pid(handle)
    except OSError as error:
        logger.critical(t(LOG_LOCK_UNUSABLE).format(path=LOCK_FILE, error=error))
        _abandon_lock(handle)
        sys.exit(1)
    _LOCK_HANDLE = handle
    logger.info(t(LOG_LOCK_ACQUIRED).format(pid=os.getpid()))


def release_lock() -> None:
    """Release the OS lock and clear the diagnostic PID from the lock file.

    The file is kept in place instead of removed: unlinking a lock file lets a
    second process lock the old inode while a third creates and locks a new
    one, which would defeat the mutual exclusion (#742).
    """
    global _LOCK_HANDLE
    handle = _LOCK_HANDLE
    if handle is None:
        return
    _LOCK_HANDLE = None
    try:
        handle.seek(0)
        handle.truncate()
        handle.flush()
        os.fsync(handle.fileno())
    except OSError:
        pass
    _release_os_lock(handle)
    try:
        handle.close()
    except OSError:
        pass
    logger.info(t(LOG_LOCK_RELEASED))

async def startup():
    enabled = [i.strip() for i in settings.enabled_interfaces.split(",")]
    tasks = []

    if "api" in enabled:
        import uvicorn

        from backend.api.app import app as api_app

        api_config = uvicorn.Config(
            api_app,
            host=settings.api_host,
            port=settings.api_port,
            log_level=settings.log_level.lower(),
        )
        api_server = uvicorn.Server(api_config)
        tasks.append(api_server.serve())
        logger.info(
            t(LOG_API_INTERFACE_ENABLED).format(port=settings.api_port)
        )

    if "telegram" in enabled and settings.bot_token_valid:
        from frontend.telegram.bot import start_polling

        tasks.append(start_polling())
        logger.info(t(LOG_TELEGRAM_INTERFACE_ENABLED))
    elif "telegram" in enabled and not settings.bot_token_valid:
        logger.warning(t(LOG_TELEGRAM_INTERFACE_NO_TOKEN))

    if "web" in enabled:
        import uvicorn

        from frontend.web.app import app

        config = uvicorn.Config(
            app, host="0.0.0.0", port=settings.web_port, log_level=settings.log_level.lower()
        )
        server = uvicorn.Server(config)
        tasks.append(server.serve())
        logger.info(
            t(LOG_WEB_INTERFACE_ENABLED).format(port=settings.web_port)
        )

    if not tasks:
        logger.critical(t(LOG_NO_INTERFACE_ENABLED))
        sys.exit(1)

    logger.info(t(LOG_STARTING_INTERFACES).format(interfaces=settings.enabled_interfaces))
    try:
        await asyncio.gather(*tasks)
    finally:
        from backend.services.model_calls import shutdown_model_calls
        shutdown_model_calls()


def main() -> None:
    # Before the lock: its messages are already translated (review of #568).
    setup_process()
    acquire_lock()
    try:
        asyncio.run(startup())
    except KeyboardInterrupt:
        logger.info(t(LOG_BOT_INTERRUPTED_BY_USER))
    except Exception:
        logger.exception(t(LOG_FATAL_ERROR_IN_BOT))
        sys.exit(1)
    finally:
        release_lock()


if __name__ == "__main__":
    main()
