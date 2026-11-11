"""The ``make test-failed`` wrapper (scripts/test_failed.py).

``pytest --lf`` falls back to the whole suite when it has no recorded failure;
the wrapper must exit successfully instead of running everything.
"""

from __future__ import annotations

from pathlib import Path

from scripts import test_failed


class _Completed:
    def __init__(self, returncode: int) -> None:
        self.returncode = returncode


def test_failed_tests_is_empty_without_a_cache(tmp_path: Path) -> None:
    assert test_failed.failed_tests(tmp_path / "missing") == []


def test_failed_tests_ignores_malformed_json(tmp_path: Path) -> None:
    cache = tmp_path / "lastfailed"
    cache.write_text("not json", encoding="utf-8")
    assert test_failed.failed_tests(cache) == []


def test_failed_tests_ignores_a_non_object_cache(tmp_path: Path) -> None:
    cache = tmp_path / "lastfailed"
    cache.write_text('["tests/test_a.py::test_a"]', encoding="utf-8")
    assert test_failed.failed_tests(cache) == []


def test_failed_tests_lists_node_ids_in_order(tmp_path: Path) -> None:
    cache = tmp_path / "lastfailed"
    cache.write_text(
        '{"tests/test_b.py::test_z": true, "tests/test_a.py::test_a": true}',
        encoding="utf-8",
    )
    assert test_failed.failed_tests(cache) == [
        "tests/test_a.py::test_a",
        "tests/test_b.py::test_z",
    ]


def test_main_without_failures_does_not_run_pytest(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(test_failed, "CACHE", tmp_path / "lastfailed")
    calls: list[tuple] = []
    monkeypatch.setattr(
        test_failed.subprocess, "run", lambda *args, **kwargs: calls.append(args)
    )

    assert test_failed.main([]) == 0
    assert calls == []
    assert "nothing to rerun" in capsys.readouterr().out


def test_main_reruns_the_cached_tests_with_lf(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    cache = tmp_path / "lastfailed"
    cache.write_text('{"tests/test_a.py::test_a": true}', encoding="utf-8")
    monkeypatch.setattr(test_failed, "CACHE", cache)
    captured: dict = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return _Completed(1)

    monkeypatch.setattr(test_failed.subprocess, "run", fake_run)

    assert test_failed.main([]) == 1
    command = captured["command"]
    assert command[0] == test_failed.sys.executable
    assert command[1:3] == ["-m", "pytest"]
    assert "--lf" in command
    assert "not e2e" in command
    assert captured["kwargs"]["cwd"] == test_failed.REPO_ROOT
    assert "Rerunning 1" in capsys.readouterr().out


def test_main_treats_no_selected_tests_as_nothing_to_rerun(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    cache = tmp_path / "lastfailed"
    cache.write_text('{"tests/test_e2e.py::test_live": true}', encoding="utf-8")
    monkeypatch.setattr(test_failed, "CACHE", cache)
    monkeypatch.setattr(
        test_failed.subprocess, "run", lambda *args, **kwargs: _Completed(5)
    )

    assert test_failed.main([]) == 0
    assert "No previously failed non-E2E tests" in capsys.readouterr().out
