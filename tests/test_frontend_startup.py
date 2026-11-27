"""Characterization of the shared frontend startup and process lock.

Both ``python -m frontend.run`` and the console-script entry point must start
the same interfaces and use the same lock. These tests pin that behaviour for
the shared runtime and the delegated entry point (#656, groups 8–10).
"""

from __future__ import annotations

import asyncio
import errno
import os
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from frontend import run as runtime
from frontend.cli import run as console

_ROOT = Path(__file__).resolve().parents[1]


def _install_fake_fcntl(monkeypatch) -> None:
    """Give a Windows host the POSIX branch when a test forces ``linux``."""
    if hasattr(runtime, "fcntl"):
        return
    monkeypatch.setattr(
        runtime,
        "fcntl",
        SimpleNamespace(
            flock=lambda *args: None,
            LOCK_EX=0,
            LOCK_NB=0,
            LOCK_UN=0,
        ),
        raising=False,
    )


def _held_lock_text() -> str:
    """Read the diagnostic PID through the handle that owns the OS lock.

    On Windows a byte-range lock is mandatory, so a second handle cannot read
    the held byte; the owning handle can.
    """
    handle = runtime._LOCK_STATE.handle
    assert handle is not None
    handle.seek(0)
    return handle.read().decode("utf-8")


class RecordingLogger:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def _record(self, level: str):
        return lambda message: self.calls.append((level, message))

    def __getattr__(self, name: str):
        if name in {"info", "warning", "critical", "exception"}:
            return self._record(name)
        raise AttributeError(name)


class FakeConfig:
    def __init__(self, app, *, host: str, port: int, log_level: str) -> None:
        self.app = app
        self.host = host
        self.port = port
        self.log_level = log_level


class FakeServer:
    started: list[FakeConfig] = []

    def __init__(self, config: FakeConfig) -> None:
        self.config = config

    async def serve(self) -> None:
        type(self).started.append(self.config)


def _module(name: str, **attributes: object) -> ModuleType:
    module = ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    return module


def _settings(**overrides: object) -> SimpleNamespace:
    values = {
        "enabled_interfaces": "api,telegram,web",
        "api_host": "127.0.0.1",
        "api_port": 8000,
        "web_port": 8080,
        "log_level": "INFO",
        "bot_token_valid": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture
def lock_files(tmp_path, monkeypatch):
    current = tmp_path / "bot.lock.v2"
    compat = tmp_path / "bot.lock"
    legacy = tmp_path / "cli" / "bot.lock"
    legacy.parent.mkdir()
    monkeypatch.setattr(runtime, "LOCK_FILE", str(current))
    monkeypatch.setattr(runtime, "COMPAT_LOCK_FILE", str(compat))
    monkeypatch.setattr(runtime, "LEGACY_LOCK_FILE", str(legacy))
    monkeypatch.setattr(runtime, "logger", RecordingLogger())
    yield SimpleNamespace(current=current, compat=compat, legacy=legacy)
    runtime.release_lock()


@pytest.fixture
def startup_environment(monkeypatch):
    started: list[object] = []
    logger = RecordingLogger()
    shutdowns: list[str] = []

    async def start_polling() -> None:
        started.append("telegram")

    monkeypatch.setattr(FakeServer, "started", started)
    monkeypatch.setitem(
        sys.modules,
        "uvicorn",
        _module("uvicorn", Config=FakeConfig, Server=FakeServer),
    )
    monkeypatch.setitem(
        sys.modules,
        "backend.api.app",
        _module("backend.api.app", app=object()),
    )
    monkeypatch.setitem(
        sys.modules,
        "frontend.web.app",
        _module("frontend.web.app", app=object()),
    )
    monkeypatch.setitem(
        sys.modules,
        "frontend.telegram.bot",
        _module("frontend.telegram.bot", start_polling=start_polling),
    )
    monkeypatch.setitem(
        sys.modules,
        "backend.services.model_calls",
        _module(
            "backend.services.model_calls",
            shutdown_model_calls=lambda: shutdowns.append("shutdown"),
        ),
    )
    monkeypatch.setattr(runtime, "logger", logger)
    return SimpleNamespace(
        started=started,
        logger=logger,
        shutdowns=shutdowns,
        monkeypatch=monkeypatch,
    )


def test_startup_launches_every_enabled_interface(startup_environment) -> None:
    env = startup_environment
    env.monkeypatch.setattr(runtime, "settings", _settings())

    asyncio.run(runtime.startup())

    api, telegram, web = env.started
    assert api.app is sys.modules["backend.api.app"].app
    assert (api.host, api.port, api.log_level) == ("127.0.0.1", 8000, "info")
    assert telegram == "telegram"
    assert web.app is sys.modules["frontend.web.app"].app
    assert (web.host, web.port, web.log_level) == ("0.0.0.0", 8080, "info")
    assert env.shutdowns == ["shutdown"]
    assert {level for level, _ in env.logger.calls} == {"info"}


def test_startup_shuts_down_when_an_interface_fails(startup_environment) -> None:
    env = startup_environment

    class FailingServer:
        def __init__(self, config: FakeConfig) -> None:
            self.config = config

        async def serve(self) -> None:
            raise RuntimeError("boom")

    env.monkeypatch.setitem(
        sys.modules,
        "uvicorn",
        _module("uvicorn", Config=FakeConfig, Server=FailingServer),
    )
    env.monkeypatch.setattr(runtime, "settings", _settings(enabled_interfaces="api"))

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(runtime.startup())

    assert env.shutdowns == ["shutdown"]


def test_startup_without_a_valid_bot_token_does_not_poll(startup_environment) -> None:
    env = startup_environment
    env.monkeypatch.setattr(
        runtime,
        "settings",
        _settings(enabled_interfaces="telegram", bot_token_valid=False),
    )

    with pytest.raises(SystemExit) as raised:
        asyncio.run(runtime.startup())

    assert raised.value.code == 1
    assert env.started == []
    assert [level for level, _ in env.logger.calls] == ["warning", "critical"]


def test_startup_refuses_to_run_without_an_interface(startup_environment) -> None:
    env = startup_environment
    env.monkeypatch.setattr(runtime, "settings", _settings(enabled_interfaces=""))

    with pytest.raises(SystemExit) as raised:
        asyncio.run(runtime.startup())

    assert raised.value.code == 1
    assert env.started == []
    assert env.shutdowns == []
    assert [level for level, _ in env.logger.calls] == ["critical"]


def test_the_console_script_reuses_the_runtime_main() -> None:
    assert console.main is runtime.main


def _patch_main(monkeypatch, events, logger=None):
    async def fake_startup() -> None:
        events.append("startup")

    monkeypatch.setattr(runtime, "setup_process", lambda: events.append("setup"))
    monkeypatch.setattr(runtime, "acquire_lock", lambda: events.append("acquire"))
    monkeypatch.setattr(runtime, "release_lock", lambda: events.append("release"))
    monkeypatch.setattr(runtime, "startup", fake_startup)
    if logger is not None:
        monkeypatch.setattr(runtime, "logger", logger)


def test_main_sets_up_acquires_starts_and_releases(monkeypatch) -> None:
    events: list[str] = []
    _patch_main(monkeypatch, events)

    runtime.main()

    assert events == ["setup", "acquire", "startup", "release"]


def test_main_releases_the_lock_after_keyboard_interrupt(monkeypatch) -> None:
    events: list[str] = []
    logger = RecordingLogger()
    _patch_main(monkeypatch, events, logger)

    async def interrupted() -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(runtime, "startup", interrupted)
    runtime.main()

    assert events == ["setup", "acquire", "release"]
    assert [level for level, _ in logger.calls] == ["info"]


def test_main_releases_the_lock_and_exits_on_startup_failure(monkeypatch) -> None:
    events: list[str] = []
    logger = RecordingLogger()
    _patch_main(monkeypatch, events, logger)

    async def failed() -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(runtime, "startup", failed)
    with pytest.raises(SystemExit) as raised:
        runtime.main()

    assert raised.value.code == 1
    assert events == ["setup", "acquire", "release"]
    assert [level for level, _ in logger.calls] == ["exception"]


def test_the_lock_records_the_process_and_is_released(lock_files) -> None:
    runtime.acquire_lock()
    assert _held_lock_text() == str(os.getpid())

    runtime.release_lock()
    # The file stays in place: unlinking it would let a second process lock
    # the old inode while a third creates and locks a new one (#742).
    assert lock_files.current.exists()
    assert lock_files.current.read_text(encoding="utf-8") == ""


def test_a_released_lock_can_be_acquired_again(lock_files) -> None:
    runtime.acquire_lock()
    runtime.release_lock()
    runtime.acquire_lock()

    assert _held_lock_text() == str(os.getpid())


def test_a_live_lock_is_refused(lock_files, monkeypatch) -> None:
    lock_files.current.write_text("1234", encoding="utf-8")
    monkeypatch.setattr(runtime, "_is_process_running", lambda pid: True)

    with pytest.raises(SystemExit) as raised:
        runtime.acquire_lock()

    assert raised.value.code == 1
    assert lock_files.current.read_text(encoding="utf-8") == "1234"
    assert any(
        "1234" in message and str(lock_files.current) in message
        for level, message in runtime.logger.calls
        if level == "critical"
    )


def test_a_live_lock_that_cannot_be_inspected_is_not_removed(
    lock_files, monkeypatch
) -> None:
    """A process owned by another user is unknown, not stale (#742)."""
    lock_files.current.write_text("1234", encoding="utf-8")

    def denied(pid: int, signal: int) -> None:
        raise PermissionError("Operation not permitted")

    monkeypatch.setattr(runtime.sys, "platform", "linux")
    _install_fake_fcntl(monkeypatch)
    monkeypatch.setattr(runtime.os, "kill", denied)

    with pytest.raises(SystemExit) as raised:
        runtime.acquire_lock()

    assert raised.value.code == 1
    assert lock_files.current.read_text(encoding="utf-8") == "1234"
    assert any(
        "cannot determine" in message.lower()
        for level, message in runtime.logger.calls
        if level == "critical"
    )


def test_a_legacy_lock_that_cannot_be_inspected_is_not_removed(
    lock_files, monkeypatch
) -> None:
    lock_files.legacy.write_text("1234", encoding="utf-8")

    def denied(pid: int, signal: int) -> None:
        raise PermissionError("Operation not permitted")

    monkeypatch.setattr(runtime.sys, "platform", "linux")
    _install_fake_fcntl(monkeypatch)
    monkeypatch.setattr(runtime.os, "kill", denied)

    with pytest.raises(SystemExit) as raised:
        runtime.acquire_lock()

    assert raised.value.code == 1
    assert lock_files.legacy.read_text(encoding="utf-8") == "1234"
    assert not lock_files.current.exists()


def test_a_stale_lock_is_replaced(lock_files, monkeypatch) -> None:
    lock_files.current.write_text("1234", encoding="utf-8")
    monkeypatch.setattr(runtime, "_is_process_running", lambda pid: False)

    runtime.acquire_lock()

    assert _held_lock_text() == str(os.getpid())


def test_a_malformed_lock_is_replaced(lock_files) -> None:
    lock_files.current.write_text("not a pid", encoding="utf-8")

    runtime.acquire_lock()

    assert _held_lock_text() == str(os.getpid())


def test_a_held_lock_without_a_readable_pid_is_reported(
    lock_files, monkeypatch
) -> None:
    lock_files.current.write_text("not a pid", encoding="utf-8")
    # The OS lock is held but the file has no PID to show (e.g. on Windows
    # the mandatory byte lock makes the holder's PID unreadable).
    monkeypatch.setattr(runtime, "_acquire_os_lock", lambda handle: False)

    with pytest.raises(SystemExit) as raised:
        runtime.acquire_lock()

    assert raised.value.code == 1
    assert any(
        "Another instance holds the process lock" in message
        for level, message in runtime.logger.calls
        if level == "critical"
    )


def test_a_held_lock_whose_pid_cannot_be_read_is_reported(
    lock_files, monkeypatch
) -> None:
    """Windows mandatory byte locks make the holder's PID unreadable."""

    def unreadable(handle):
        raise PermissionError("The process cannot access the file")

    monkeypatch.setattr(runtime, "_acquire_os_lock", lambda handle: False)
    monkeypatch.setattr(runtime, "_read_lock_pid", unreadable)

    with pytest.raises(SystemExit) as raised:
        runtime.acquire_lock()

    assert raised.value.code == 1
    assert any(
        "Another instance holds the process lock" in message
        for level, message in runtime.logger.calls
        if level == "critical"
    )


def test_a_lock_file_that_cannot_be_opened_is_reported(
    lock_files, monkeypatch
) -> None:
    def denied(*args, **kwargs):
        raise PermissionError("Operation not permitted")

    monkeypatch.setattr(runtime.os, "open", denied)

    with pytest.raises(SystemExit) as raised:
        runtime.acquire_lock()

    assert raised.value.code == 1
    assert any(
        "Cannot use the process lock" in message
        for level, message in runtime.logger.calls
        if level == "critical"
    )


def test_a_lock_pid_that_cannot_be_written_is_reported(
    lock_files, monkeypatch
) -> None:
    def failed(handle):
        raise OSError("disk full")

    monkeypatch.setattr(runtime, "_write_lock_pid", failed)

    with pytest.raises(SystemExit) as raised:
        runtime.acquire_lock()

    assert raised.value.code == 1
    assert any(
        "Cannot use the process lock" in message
        for level, message in runtime.logger.calls
        if level == "critical"
    )


def test_a_lock_pid_that_cannot_be_read_after_acquisition_is_reported(
    lock_files, monkeypatch
) -> None:
    original = runtime._read_lock_pid

    def unreadable(handle):
        runtime._read_lock_pid = original
        raise OSError("read failed")

    monkeypatch.setattr(runtime, "_read_lock_pid", unreadable)

    with pytest.raises(SystemExit) as raised:
        runtime.acquire_lock()

    assert raised.value.code == 1
    assert runtime._LOCK_STATE.handle is None
    assert any(
        "Cannot use the process lock" in message
        for level, message in runtime.logger.calls
        if level == "critical"
    )

    # The failed acquisition released the handle, so a later attempt succeeds.
    runtime.acquire_lock()
    assert _held_lock_text() == str(os.getpid())


def test_an_os_lock_error_is_reported_as_unusable(
    lock_files, monkeypatch
) -> None:
    def failed(handle):
        raise OSError(errno.EIO, "I/O error")

    monkeypatch.setattr(runtime, "_acquire_os_lock", failed)

    with pytest.raises(SystemExit) as raised:
        runtime.acquire_lock()

    assert raised.value.code == 1
    assert runtime._LOCK_STATE.handle is None
    assert any(
        "Cannot use the process lock" in message
        for level, message in runtime.logger.calls
        if level == "critical"
    )


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (BlockingIOError(errno.EAGAIN, "busy"), True),
        (OSError(errno.EIO, "I/O error"), False),
    ],
)
def test_lock_contention_classification(monkeypatch, error, expected) -> None:
    monkeypatch.setattr(runtime.sys, "platform", "linux")

    assert runtime._is_lock_contention(error) is expected


def test_windows_lock_contention_classification(monkeypatch) -> None:
    monkeypatch.setattr(runtime.sys, "platform", "win32")

    assert runtime._is_lock_contention(OSError(errno.EACCES, "busy"))
    assert not runtime._is_lock_contention(OSError(errno.EINVAL, "bad"))


def test_a_huge_pid_is_unknown(monkeypatch) -> None:
    def overflow(pid, signal):
        raise OverflowError("pid out of range")

    monkeypatch.setattr(runtime.sys, "platform", "linux")
    monkeypatch.setattr(runtime.os, "kill", overflow)

    with pytest.raises(runtime._ProcessCheckError):
        runtime._is_process_running(2**40)


def test_a_huge_current_lock_pid_is_not_removed(
    lock_files, monkeypatch
) -> None:
    lock_files.current.write_text(str(2**40), encoding="utf-8")

    def overflow(pid, signal):
        raise OverflowError("pid out of range")

    monkeypatch.setattr(runtime.sys, "platform", "linux")
    _install_fake_fcntl(monkeypatch)
    monkeypatch.setattr(runtime.os, "kill", overflow)

    with pytest.raises(SystemExit) as raised:
        runtime.acquire_lock()

    assert raised.value.code == 1
    assert lock_files.current.read_text(encoding="utf-8") == str(2**40)
    assert any(
        "cannot determine" in message.lower()
        for level, message in runtime.logger.calls
        if level == "critical"
    )


def test_a_huge_legacy_lock_pid_is_not_removed(
    lock_files, monkeypatch
) -> None:
    lock_files.legacy.write_text(str(2**40), encoding="utf-8")

    def overflow(pid, signal):
        raise OverflowError("pid out of range")

    monkeypatch.setattr(runtime.sys, "platform", "linux")
    _install_fake_fcntl(monkeypatch)
    monkeypatch.setattr(runtime.os, "kill", overflow)

    with pytest.raises(SystemExit) as raised:
        runtime.acquire_lock()

    assert raised.value.code == 1
    assert lock_files.legacy.read_text(encoding="utf-8") == str(2**40)
    assert not lock_files.current.exists()


@pytest.mark.parametrize("pid_text", ["0", "-1"])
def test_a_non_positive_legacy_pid_is_replaced(lock_files, pid_text) -> None:
    lock_files.legacy.write_text(pid_text, encoding="utf-8")

    runtime.acquire_lock()

    assert lock_files.legacy.read_text(encoding="utf-8") == str(os.getpid())
    assert _held_lock_text() == str(os.getpid())


@pytest.mark.parametrize("raw", ["0", "-1", "not a pid", ""])
def test_read_lock_pid_returns_none_for_non_positive(raw, tmp_path) -> None:
    path = tmp_path / "lock"
    path.write_text(raw, encoding="utf-8")

    with path.open("r+b") as handle:
        assert runtime._read_lock_pid(handle) is None


def test_a_live_legacy_lock_is_refused(lock_files, monkeypatch) -> None:
    lock_files.legacy.write_text("1234", encoding="utf-8")
    monkeypatch.setattr(runtime, "_is_process_running", lambda pid: True)

    with pytest.raises(SystemExit) as raised:
        runtime.acquire_lock()

    assert raised.value.code == 1
    assert lock_files.legacy.read_text(encoding="utf-8") == "1234"
    assert not lock_files.current.exists()


def test_a_stale_legacy_lock_is_replaced(lock_files, monkeypatch) -> None:
    lock_files.legacy.write_text("1234", encoding="utf-8")
    monkeypatch.setattr(runtime, "_is_process_running", lambda pid: False)

    runtime.acquire_lock()

    assert lock_files.legacy.read_text(encoding="utf-8") == str(os.getpid())
    assert _held_lock_text() == str(os.getpid())
    assert any(
        "Legacy lock file stale" in message
        for _, message in runtime.logger.calls
    )


def test_a_malformed_legacy_lock_is_replaced(lock_files) -> None:
    lock_files.legacy.write_text("not a pid", encoding="utf-8")

    runtime.acquire_lock()

    assert lock_files.legacy.read_text(encoding="utf-8") == str(os.getpid())
    assert _held_lock_text() == str(os.getpid())


def test_the_compat_file_advertises_the_owner(lock_files) -> None:
    runtime.acquire_lock()

    assert lock_files.compat.read_text(encoding="utf-8") == str(os.getpid())


def test_a_release_clears_the_compat_pid(lock_files) -> None:
    runtime.acquire_lock()
    runtime.release_lock()

    assert lock_files.compat.exists()
    assert lock_files.compat.read_text(encoding="utf-8") == ""


def test_a_compat_file_naming_this_process_is_kept(lock_files) -> None:
    lock_files.compat.write_text(str(os.getpid()), encoding="utf-8")

    runtime._check_legacy_lock(
        str(lock_files.compat), keep_own_pid=True
    )

    assert lock_files.compat.read_text(encoding="utf-8") == str(os.getpid())


def test_the_legacy_cli_file_advertises_the_owner(lock_files) -> None:
    runtime.acquire_lock()

    assert lock_files.legacy.read_text(encoding="utf-8") == str(os.getpid())


def test_a_release_clears_the_legacy_cli_pid(lock_files) -> None:
    runtime.acquire_lock()
    runtime.release_lock()

    assert lock_files.legacy.exists()
    assert lock_files.legacy.read_text(encoding="utf-8") == ""


def test_a_legacy_file_naming_this_process_is_kept(lock_files) -> None:
    lock_files.legacy.write_text(str(os.getpid()), encoding="utf-8")

    runtime._check_legacy_lock(
        str(lock_files.legacy), keep_own_pid=True
    )

    assert lock_files.legacy.read_text(encoding="utf-8") == str(os.getpid())


def test_a_live_compat_lock_is_refused(lock_files, monkeypatch) -> None:
    lock_files.compat.write_text("1234", encoding="utf-8")
    monkeypatch.setattr(runtime, "_is_process_running", lambda pid: True)

    with pytest.raises(SystemExit) as raised:
        runtime.acquire_lock()

    assert raised.value.code == 1
    assert lock_files.compat.read_text(encoding="utf-8") == "1234"
    assert not lock_files.current.exists()


def test_a_stale_compat_lock_is_replaced(lock_files, monkeypatch) -> None:
    lock_files.compat.write_text("1234", encoding="utf-8")
    monkeypatch.setattr(runtime, "_is_process_running", lambda pid: False)

    runtime.acquire_lock()

    assert lock_files.compat.read_text(encoding="utf-8") == str(os.getpid())
    assert _held_lock_text() == str(os.getpid())


def test_a_malformed_compat_lock_is_removed(lock_files) -> None:
    lock_files.compat.write_text("not a pid", encoding="utf-8")

    runtime.acquire_lock()

    assert lock_files.compat.read_text(encoding="utf-8") == str(os.getpid())
    assert _held_lock_text() == str(os.getpid())


def test_a_compat_file_that_cannot_be_written_is_reported(lock_files) -> None:
    runtime._write_compat_pid(str(lock_files.compat.parent))

    assert any(
        "Could not write the legacy process lock" in message
        for level, message in runtime.logger.calls
        if level == "warning"
    )


def test_an_unwritable_compat_path_does_not_undo_the_lock(
    lock_files, monkeypatch
) -> None:
    real_open = runtime.os.open

    def denied(path, flags, mode=0o777):
        if str(path) in {str(lock_files.compat), str(lock_files.legacy)}:
            raise PermissionError("denied")
        return real_open(path, flags, mode)

    monkeypatch.setattr(runtime.os, "open", denied)

    runtime.acquire_lock()

    assert _held_lock_text() == str(os.getpid())
    assert any(
        "Could not write the legacy process lock" in message
        for level, message in runtime.logger.calls
        if level == "warning"
    )


def test_a_release_keeps_a_foreign_compat_pid(lock_files) -> None:
    runtime.acquire_lock()
    lock_files.compat.write_text("1234", encoding="utf-8")
    lock_files.legacy.write_text("5678", encoding="utf-8")

    runtime.release_lock()

    assert lock_files.compat.read_text(encoding="utf-8") == "1234"
    assert lock_files.legacy.read_text(encoding="utf-8") == "5678"


def test_a_corrupt_compat_file_does_not_break_release(lock_files) -> None:
    runtime.acquire_lock()
    lock_files.compat.write_bytes(b"\xff\xfe123")

    runtime.release_lock()

    assert runtime._LOCK_STATE.handle is None
    runtime.acquire_lock()
    assert _held_lock_text() == str(os.getpid())


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
def test_the_compat_file_is_owner_only(lock_files) -> None:
    lock_files.compat.write_text(str(os.getpid()), encoding="utf-8")
    lock_files.compat.chmod(0o644)

    runtime.acquire_lock()

    assert (lock_files.compat.stat().st_mode & 0o777) == 0o600


def test_a_legacy_lock_that_cannot_be_read_is_reported(lock_files) -> None:
    lock_files.legacy.mkdir()

    with pytest.raises(SystemExit) as raised:
        runtime.acquire_lock()

    assert raised.value.code == 1
    assert any(
        "Cannot use the process lock" in message
        for level, message in runtime.logger.calls
        if level == "critical"
    )


def test_a_legacy_lock_that_cannot_be_removed_is_reported(
    lock_files, monkeypatch
) -> None:
    lock_files.legacy.write_text("1234", encoding="utf-8")
    monkeypatch.setattr(runtime, "_is_process_running", lambda pid: False)

    def denied(*args, **kwargs):
        raise PermissionError("Operation not permitted")

    monkeypatch.setattr(runtime.os, "remove", denied)

    with pytest.raises(SystemExit) as raised:
        runtime.acquire_lock()

    assert raised.value.code == 1
    assert lock_files.legacy.read_text(encoding="utf-8") == "1234"
    assert any(
        "Cannot use the process lock" in message
        for level, message in runtime.logger.calls
        if level == "critical"
    )


def test_posix_pid_probe_treats_a_running_process_as_alive(monkeypatch) -> None:
    calls: list[tuple[int, int]] = []
    monkeypatch.setattr(runtime.sys, "platform", "linux")
    monkeypatch.setattr(
        runtime.os,
        "kill",
        lambda pid, signal: calls.append((pid, signal)),
    )

    assert runtime._is_process_running(4321) is True
    assert calls == [(4321, 0)]


def test_posix_pid_probe_treats_a_missing_process_as_stale(monkeypatch) -> None:
    def fail(pid: int, signal: int) -> None:
        raise ProcessLookupError()

    monkeypatch.setattr(runtime.sys, "platform", "linux")
    monkeypatch.setattr(runtime.os, "kill", fail)

    assert runtime._is_process_running(4321) is False


def test_posix_pid_probe_refuses_to_guess_when_permission_is_denied(
    monkeypatch,
) -> None:
    def fail(pid: int, signal: int) -> None:
        raise PermissionError("Operation not permitted")

    monkeypatch.setattr(runtime.sys, "platform", "linux")
    monkeypatch.setattr(runtime.os, "kill", fail)

    with pytest.raises(runtime._ProcessCheckError):
        runtime._is_process_running(4321)


@pytest.mark.parametrize(
    ("stdout", "expected"),
    [
        ('"python.exe","4321","Console","1","10 K"', True),
        ('"python.exe","14321","Console","1","10 K"', False),
        ('"python.exe","43210","Console","1","10 K"', False),
        ("", False),
        ("INFO: No tasks are running which match the specified criteria.", False),
    ],
)
def test_windows_pid_probe_matches_the_exact_csv_pid(
    monkeypatch, stdout, expected
) -> None:
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(stdout=stdout, stderr="", returncode=0)

    monkeypatch.setattr(runtime.sys, "platform", "win32")
    monkeypatch.setattr(runtime.subprocess, "run", fake_run)

    assert runtime._is_process_running(4321) is expected
    assert calls[0][0] == [
        "tasklist",
        "/FI",
        "PID eq 4321",
        "/NH",
        "/FO",
        "CSV",
    ]
    assert calls[0][1]["errors"] == "replace"


def test_windows_pid_probe_refuses_to_guess_when_tasklist_fails(
    monkeypatch,
) -> None:
    def fake_run(args, **kwargs):
        return SimpleNamespace(stdout="", stderr="Access denied", returncode=1)

    monkeypatch.setattr(runtime.sys, "platform", "win32")
    monkeypatch.setattr(runtime.subprocess, "run", fake_run)

    with pytest.raises(runtime._ProcessCheckError):
        runtime._is_process_running(4321)


def test_windows_pid_probe_refuses_to_guess_when_tasklist_cannot_start(
    monkeypatch,
) -> None:
    def fake_run(args, **kwargs):
        raise OSError("tasklist not found")

    monkeypatch.setattr(runtime.sys, "platform", "win32")
    monkeypatch.setattr(runtime.subprocess, "run", fake_run)

    with pytest.raises(runtime._ProcessCheckError):
        runtime._is_process_running(4321)


def test_windows_pid_probe_refuses_to_guess_when_tasklist_times_out(
    monkeypatch,
) -> None:
    def fake_run(args, **kwargs):
        raise subprocess.TimeoutExpired(args, runtime._TASKLIST_TIMEOUT_SECONDS)

    monkeypatch.setattr(runtime.sys, "platform", "win32")
    monkeypatch.setattr(runtime.subprocess, "run", fake_run)

    with pytest.raises(runtime._ProcessCheckError):
        runtime._is_process_running(4321)


#: A subprocess that holds the lock until the test lets it go.
_HOLDER_SCRIPT = """
import os
import sys
import time
from pathlib import Path

import frontend.run as runtime

lock_file, compat_file, legacy_file, ready_file, go_file = sys.argv[1:6]
runtime.LOCK_FILE = lock_file
runtime.COMPAT_LOCK_FILE = compat_file
runtime.LEGACY_LOCK_FILE = legacy_file


class SilentLogger:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


runtime.logger = SilentLogger()
runtime.acquire_lock()
Path(ready_file).write_text(str(os.getpid()), encoding="utf-8")
try:
    while not Path(go_file).exists():
        time.sleep(0.01)
finally:
    runtime.release_lock()
"""

#: A subprocess that must be refused while the holder owns the lock.
_CONTENDER_SCRIPT = """
import sys

import frontend.run as runtime

runtime.LOCK_FILE = sys.argv[1]
runtime.COMPAT_LOCK_FILE = sys.argv[2]
runtime.LEGACY_LOCK_FILE = sys.argv[3]


class SilentLogger:
    def __getattr__(self, name):
        return lambda *args, **kwargs: None


runtime.logger = SilentLogger()
# The OS lock must be the gate, not the holder's live PID: with this stub a
# broken flock would let the contender acquire and the test would fail.
runtime._is_process_running = lambda pid: False
try:
    runtime.acquire_lock()
except SystemExit:
    # A crash also exits 1; the marker lets the test tell refusal from a bug.
    print("REFUSED", flush=True)
    raise
runtime.release_lock()
"""


def _wait_for_ready(process, ready_file) -> None:
    """Wait for the holder to publish its PID, failing on an early exit."""
    deadline = time.monotonic() + 30
    while not ready_file.exists():
        if process.poll() is not None:
            pytest.fail(
                f"lock holder exited before acquiring (status {process.returncode})"
            )
        if time.monotonic() > deadline:
            pytest.fail("lock holder did not acquire the lock in time")
        time.sleep(0.02)


def test_two_concurrent_acquisitions_cannot_both_succeed(tmp_path) -> None:
    lock_file = tmp_path / "bot.lock.v2"
    compat_file = tmp_path / "bot.lock"
    legacy_file = tmp_path / "cli" / "bot.lock"
    ready_file = tmp_path / "ready"
    go_file = tmp_path / "go"

    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            _HOLDER_SCRIPT,
            str(lock_file),
            str(compat_file),
            str(legacy_file),
            str(ready_file),
            str(go_file),
        ],
        cwd=_ROOT,
        # The holder must not block on a full pipe; its status is all the test
        # needs.
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        _wait_for_ready(holder, ready_file)

        contender = subprocess.run(
            [
                sys.executable,
                "-c",
                _CONTENDER_SCRIPT,
                str(lock_file),
                str(compat_file),
                str(legacy_file),
            ],
            cwd=_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert contender.returncode == 1, contender.stderr
        assert "REFUSED" in contender.stdout, contender.stderr
    finally:
        go_file.touch(exist_ok=True)
        try:
            holder.wait(timeout=30)
        except subprocess.TimeoutExpired:
            holder.kill()
            holder.wait(timeout=30)

    assert holder.returncode == 0


def test_an_abruptly_terminated_owner_releases_the_lock(tmp_path) -> None:
    lock_file = tmp_path / "bot.lock.v2"
    compat_file = tmp_path / "bot.lock"
    legacy_file = tmp_path / "cli" / "bot.lock"
    ready_file = tmp_path / "ready"
    go_file = tmp_path / "go"

    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            _HOLDER_SCRIPT,
            str(lock_file),
            str(compat_file),
            str(legacy_file),
            str(ready_file),
            str(go_file),
        ],
        cwd=_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        _wait_for_ready(holder, ready_file)
        holder.kill()
        holder.wait(timeout=30)

        contender = subprocess.run(
            [
                sys.executable,
                "-c",
                _CONTENDER_SCRIPT,
                str(lock_file),
                str(compat_file),
                str(legacy_file),
            ],
            cwd=_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert contender.returncode == 0, contender.stderr
    finally:
        if holder.poll() is None:
            holder.kill()
            holder.wait(timeout=30)


def test_an_old_runtime_unlink_does_not_release_the_new_lock(tmp_path) -> None:
    lock_file = tmp_path / "bot.lock.v2"
    compat_file = tmp_path / "bot.lock"
    legacy_file = tmp_path / "cli" / "bot.lock"
    ready_file = tmp_path / "ready"
    go_file = tmp_path / "go"

    holder = subprocess.Popen(
        [
            sys.executable,
            "-c",
            _HOLDER_SCRIPT,
            str(lock_file),
            str(compat_file),
            str(legacy_file),
            str(ready_file),
            str(go_file),
        ],
        cwd=_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    try:
        _wait_for_ready(holder, ready_file)

        # A pre-#903 runtime unlinks the old path on exit. The authoritative
        # lock lives elsewhere, so this must not free it.
        unlinker = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys; from pathlib import Path; "
                    "[Path(p).unlink(missing_ok=True) for p in sys.argv[1:]]"
                ),
                str(compat_file),
                str(legacy_file),
            ],
            cwd=_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert unlinker.returncode == 0, unlinker.stderr

        contender = subprocess.run(
            [
                sys.executable,
                "-c",
                _CONTENDER_SCRIPT,
                str(lock_file),
                str(compat_file),
                str(legacy_file),
            ],
            cwd=_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert contender.returncode == 1, contender.stderr
        assert "REFUSED" in contender.stdout, contender.stderr
    finally:
        go_file.touch(exist_ok=True)
        try:
            holder.wait(timeout=30)
        except subprocess.TimeoutExpired:
            holder.kill()
            holder.wait(timeout=30)

    assert holder.returncode == 0
