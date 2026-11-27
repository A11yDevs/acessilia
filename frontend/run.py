#!/usr/bin/env python3
import asyncio
import csv
import errno
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
    LOG_LOCK_COMPAT_UNWRITABLE,
    LOG_LOCK_FILE_STALE,
    LOG_LOCK_LEGACY_FILE_STALE,
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

#: The authoritative lock. A pre-#903 runtime only knows the old path below,
#: and its release unlinks that file; giving the OS lock a path it never
#: touches keeps an old process from unlinking the inode the new runtime holds.
LOCK_FILE = os.path.join(os.path.dirname(__file__), "bot.lock.v2")
#: The pre-#903 lock path, kept as a compatibility advertisement: the new
#: runtime writes its PID here so an old runtime refuses to start, and checks
#: a live old PID here before taking the authoritative lock.
COMPAT_LOCK_FILE = os.path.join(os.path.dirname(__file__), "bot.lock")
# The console entry point used a separate lock before both entry points shared
# this runtime. Keep recognizing it during an in-place upgrade.
LEGACY_LOCK_FILE = os.path.join(os.path.dirname(__file__), "cli", "bot.lock")

#: Longest wait for the Windows process probe. A hung tasklist must not block
#: startup forever; the failure is treated as unknown, never as "not running".
_TASKLIST_TIMEOUT_SECONDS = 10


class _LockState:
    """The open handle that holds the OS lock for this process.

    The lock lives as long as the handle is open, so the state keeps it
    referenced until release_lock.
    """

    handle: BinaryIO | None = None


_LOCK_STATE = _LockState()


class _ProcessCheckError(RuntimeError):
    """The liveness of the process named by a lock file could not be checked."""


def _windows_process_running(pid: int) -> bool:
    """Whether ``tasklist`` reports exactly ``pid``, never a longer number."""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
            capture_output=True,
            text=True,
            # The tool emits the OEM code page; a process name outside the
            # ANSI page must not crash the lock probe (#742 review).
            errors="replace",
            timeout=_TASKLIST_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
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
    except (OverflowError, ValueError) as error:
        # A corrupt lock can name a PID outside the platform's pid_t range;
        # it is not a process we can verify, so keep the conservative policy.
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
        # Owner-only on POSIX. On Windows the mode is a no-op and the OS lock
        # is what protects the file.
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    except OSError as error:
        logger.critical(t(LOG_LOCK_UNUSABLE).format(path=path, error=error))
        sys.exit(1)
    fchmod = getattr(os, "fchmod", None)
    if sys.platform != "win32" and fchmod is not None:
        try:
            # os.open's mode applies only on creation: tighten a lock file
            # left by an older runtime as well.
            fchmod(descriptor, 0o600)
        except OSError:
            # The file holds only a PID; the OS lock still protects it.
            pass
    try:
        return os.fdopen(descriptor, "r+b")
    except OSError as error:
        try:
            os.close(descriptor)
        except OSError:
            # The descriptor is already unusable; report the original error.
            pass
        logger.critical(t(LOG_LOCK_UNUSABLE).format(path=path, error=error))
        sys.exit(1)


def _is_lock_contention(error: OSError) -> bool:
    """Whether ``error`` is the platform's normal "another holder" answer."""
    if sys.platform == "win32":
        # _locking reports EACCES for a held region; every other error is an
        # unusable lock, not a holder.
        return error.errno == errno.EACCES
    return isinstance(error, BlockingIOError) or error.errno in {
        errno.EAGAIN,
        errno.EWOULDBLOCK,
    }


def _acquire_os_lock(handle: BinaryIO) -> bool:
    """Take the exclusive OS lock without waiting; False when another holder has it.

    Contention is False; an OS error that is not contention is re-raised so the
    caller can report ``LOG_LOCK_UNUSABLE`` instead of claiming an instance is
    running when the lock itself could not be used.
    """
    try:
        if sys.platform == "win32":
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
        if _is_lock_contention(error):
            return False
        raise
    return True


def _release_os_lock(handle: BinaryIO) -> None:
    try:
        if sys.platform == "win32":
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        # Unlocking is best-effort: closing the handle releases the OS lock too.
        pass


def _abandon_lock(handle: BinaryIO) -> None:
    _release_os_lock(handle)
    try:
        handle.close()
    except OSError:
        # Closing is best-effort; the OS releases the lock with the descriptor.
        pass


def _write_lock_pid(handle: BinaryIO) -> None:
    handle.seek(0)
    handle.truncate()
    handle.write(str(os.getpid()).encode("ascii"))
    handle.flush()
    os.fsync(handle.fileno())


def _write_compat_pid(path: str) -> None:
    """Advertise this owner on the pre-#903 path, so an old runtime refuses.

    The authoritative lock is ``LOCK_FILE``; this file exists only for an
    in-place upgrade. A failure is logged but does not undo the new lock.
    """
    try:
        descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_TRUNC, 0o600)
    except OSError as error:
        logger.warning(t(LOG_LOCK_COMPAT_UNWRITABLE).format(path=path, error=error))
        return
    try:
        os.write(descriptor, str(os.getpid()).encode("ascii"))
    except OSError as error:
        logger.warning(t(LOG_LOCK_COMPAT_UNWRITABLE).format(path=path, error=error))
    finally:
        try:
            os.close(descriptor)
        except OSError:
            # The advertisement is best-effort; the descriptor is gone anyway.
            pass


def _clear_compat_pid(path: str) -> None:
    """Clear the compatibility PID only while it is still this process's."""
    try:
        with open(path, "r+", encoding="utf-8") as file:
            if file.read().strip() != str(os.getpid()):
                return
            file.seek(0)
            file.truncate()
    except FileNotFoundError:
        return
    except OSError:
        # The old path is advisory; the authoritative OS lock is unchanged.
        return


def _check_previous_owner(handle: BinaryIO, path: str) -> None:
    """Refuse a live PID left by a runtime that predates the OS lock.

    The OS lock already excludes another holder of this lock. An in-place
    upgrade can still find a PID written by the old implementation, which did
    not hold the OS lock: if that process is alive, starting a second instance
    would be wrong, and if its liveness cannot be checked the lock is kept.
    """
    try:
        pid = _read_lock_pid(handle)
    except OSError as error:
        logger.critical(t(LOG_LOCK_UNUSABLE).format(path=path, error=error))
        _abandon_lock(handle)
        sys.exit(1)
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
        logger.critical(
            t(LOG_BOT_ALREADY_RUNNING).format(pid=pid, path=path)
        )
        _abandon_lock(handle)
        sys.exit(1)
    logger.warning(t(LOG_LOCK_FILE_STALE).format(pid=pid))


def _check_legacy_lock(path: str, *, keep_own_pid: bool = False) -> None:
    """Refuse a live legacy lock, and remove a stale or malformed one.

    ``keep_own_pid`` keeps the pre-#903 compatibility advertisement when it
    already names this process: a re-entrant acquisition must not delete the
    file the running owner advertises.
    """
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
        elif pid == os.getpid():
            if keep_own_pid:
                return
        else:
            try:
                running = _is_process_running(pid)
            except _ProcessCheckError as error:
                logger.critical(
                    t(LOG_LOCK_OWNER_UNKNOWN).format(path=path, pid=pid, error=error)
                )
                sys.exit(1)
            if running:
                logger.critical(
                    t(LOG_BOT_ALREADY_RUNNING).format(pid=pid, path=path)
                )
                sys.exit(1)
            logger.warning(
                t(LOG_LOCK_LEGACY_FILE_STALE).format(pid=pid, path=path)
            )
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

    ``COMPAT_LOCK_FILE`` is the pre-#903 path, which that runtime unlinks on
    release. The new runtime only writes its PID there for an old runtime to
    see; the authoritative lock lives in the path the old runtime never
    touches (#906).
    """
    _check_legacy_lock(COMPAT_LOCK_FILE, keep_own_pid=True)
    _check_legacy_lock(LEGACY_LOCK_FILE)
    handle = _open_lock_file(LOCK_FILE)
    try:
        acquired = _acquire_os_lock(handle)
    except OSError as error:
        logger.critical(t(LOG_LOCK_UNUSABLE).format(path=LOCK_FILE, error=error))
        try:
            handle.close()
        except OSError:
            # This attempt never held the lock; closing is best-effort.
            pass
        sys.exit(1)
    if not acquired:
        try:
            pid = _read_lock_pid(handle)
        except OSError:
            # Windows byte-range locks are mandatory: a second handle cannot
            # read the holder's PID. Report the holder without it (#742).
            pid = None
        if pid is None:
            logger.critical(t(LOG_LOCK_ALREADY_HELD).format(path=LOCK_FILE))
        else:
            logger.critical(
                t(LOG_BOT_ALREADY_RUNNING).format(pid=pid, path=LOCK_FILE)
            )
        try:
            handle.close()
        except OSError:
            # This attempt never held the lock; closing is best-effort.
            pass
        sys.exit(1)
    _check_previous_owner(handle, LOCK_FILE)
    try:
        _write_lock_pid(handle)
    except OSError as error:
        logger.critical(t(LOG_LOCK_UNUSABLE).format(path=LOCK_FILE, error=error))
        _abandon_lock(handle)
        sys.exit(1)
    _write_compat_pid(COMPAT_LOCK_FILE)
    _LOCK_STATE.handle = handle
    logger.info(t(LOG_LOCK_ACQUIRED).format(pid=os.getpid()))


def release_lock() -> None:
    """Release the OS lock and clear the diagnostic PID from the lock file.

    The file is kept in place instead of removed: unlinking a lock file lets a
    second process lock the old inode while a third creates and locks a new
    one, which would defeat the mutual exclusion (#742).
    """
    handle = _LOCK_STATE.handle
    if handle is None:
        return
    _LOCK_STATE.handle = None
    try:
        handle.seek(0)
        handle.truncate()
        handle.flush()
        os.fsync(handle.fileno())
    except OSError:
        # The unlock and close below still release the lock; a PID left behind
        # is treated as stale by the next start.
        pass
    _clear_compat_pid(COMPAT_LOCK_FILE)
    _release_os_lock(handle)
    try:
        handle.close()
    except OSError:
        # The descriptor may already be closed; the OS lock is released anyway.
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
