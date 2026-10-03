"""Shared startup preserves both entry points and lock cleanup."""
import os

import pytest

from frontend import run as runtime
from frontend.cli import run as cli


@pytest.mark.parametrize("entrypoint", [runtime, cli])
@pytest.mark.parametrize("failure", [None, KeyboardInterrupt, RuntimeError])
def test_entrypoint_releases_its_lock(entrypoint, failure, monkeypatch, tmp_path):
    lock = tmp_path / f"{entrypoint.__name__}.lock"
    monkeypatch.setattr(entrypoint, "LOCK_FILE", str(lock))

    async def startup():
        assert lock.read_text() == str(os.getpid())
        if failure:
            raise failure()

    monkeypatch.setattr(runtime, "startup", startup)
    if failure is RuntimeError:
        with pytest.raises(SystemExit) as error:
            entrypoint.main()
        assert error.value.code == 1
    else:
        entrypoint.main()
    assert not lock.exists()


def test_existing_process_is_not_unlocked(monkeypatch, tmp_path):
    lock = tmp_path / "bot.lock"
    lock.write_text(str(os.getpid()))
    with pytest.raises(SystemExit) as error:
        runtime.main(lock_file=str(lock))
    assert error.value.code == 1
    assert lock.read_text() == str(os.getpid())


@pytest.mark.parametrize("contents", ["invalid-pid", "123"])
def test_stale_lock_is_replaced(contents, monkeypatch, tmp_path):
    lock = tmp_path / "bot.lock"
    lock.write_text(contents)
    monkeypatch.setattr(runtime, "_is_process_running", lambda _pid: False)
    runtime.acquire_lock(str(lock))
    assert lock.read_text() == str(os.getpid())
    runtime.release_lock(str(lock))
    assert not lock.exists()
