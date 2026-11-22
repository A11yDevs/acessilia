"""Characterization of the shared frontend startup and process lock.

Both ``python -m frontend.run`` and the console-script entry point must start
the same interfaces and use the same lock. These tests pin that behaviour
before the duplicate entry point is reduced to a delegation (#656, groups 8–10).
"""

from __future__ import annotations

import asyncio
import os
import sys
from types import ModuleType, SimpleNamespace

import pytest

from frontend import run as runtime
from frontend.cli import run as console


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


def test_the_lock_records_the_process_and_is_released(tmp_path, monkeypatch) -> None:
    lock_file = tmp_path / "bot.lock"
    monkeypatch.setattr(runtime, "LOCK_FILE", str(lock_file))
    monkeypatch.setattr(runtime, "logger", RecordingLogger())

    runtime.acquire_lock()
    assert lock_file.read_text(encoding="utf-8") == str(os.getpid())

    runtime.release_lock()
    assert not lock_file.exists()


def test_a_live_lock_is_refused(tmp_path, monkeypatch) -> None:
    lock_file = tmp_path / "bot.lock"
    lock_file.write_text("1234", encoding="utf-8")
    monkeypatch.setattr(runtime, "LOCK_FILE", str(lock_file))
    monkeypatch.setattr(runtime, "logger", RecordingLogger())
    monkeypatch.setattr(runtime, "_is_process_running", lambda pid: True)

    with pytest.raises(SystemExit) as raised:
        runtime.acquire_lock()

    assert raised.value.code == 1
    assert lock_file.read_text(encoding="utf-8") == "1234"


def test_a_stale_lock_is_replaced(tmp_path, monkeypatch) -> None:
    lock_file = tmp_path / "bot.lock"
    lock_file.write_text("1234", encoding="utf-8")
    monkeypatch.setattr(runtime, "LOCK_FILE", str(lock_file))
    monkeypatch.setattr(runtime, "logger", RecordingLogger())
    monkeypatch.setattr(runtime, "_is_process_running", lambda pid: False)

    runtime.acquire_lock()

    assert lock_file.read_text(encoding="utf-8") == str(os.getpid())


def test_a_malformed_lock_is_replaced(tmp_path, monkeypatch) -> None:
    lock_file = tmp_path / "bot.lock"
    lock_file.write_text("not a pid", encoding="utf-8")
    monkeypatch.setattr(runtime, "LOCK_FILE", str(lock_file))
    monkeypatch.setattr(runtime, "logger", RecordingLogger())

    runtime.acquire_lock()

    assert lock_file.read_text(encoding="utf-8") == str(os.getpid())


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


@pytest.mark.parametrize("error", [ProcessLookupError, PermissionError])
def test_posix_pid_probe_treats_missing_or_denied_processes_as_stale(
    monkeypatch,
    error,
) -> None:
    def fail(pid: int, signal: int) -> None:
        raise error()

    monkeypatch.setattr(runtime.sys, "platform", "linux")
    monkeypatch.setattr(runtime.os, "kill", fail)

    assert runtime._is_process_running(4321) is False


@pytest.mark.parametrize(
    ("stdout", "expected"),
    [('"python.exe","4321","Console","1","10 K"', True), ("", False)],
)
def test_windows_pid_probe_reads_tasklist(monkeypatch, stdout, expected) -> None:
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(stdout=stdout)

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
