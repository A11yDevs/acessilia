"""The ``make test-failed`` wrapper (scripts/test_failed.py).

``pytest --lf`` falls back to the whole suite when it has no recorded failure
and runs unrelated tests when a recorded node id no longer exists. The wrapper
must handle both cases, for the core and for each library cache.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import test_failed


@pytest.fixture(autouse=True)
def _disable_plugin_autoload(monkeypatch) -> None:
    """The spawned pytest processes only need pytest's core."""
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")


def _cache(root: Path, entries: list[str]) -> Path:
    cache = root / test_failed.CACHE_RELATIVE
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(
        json.dumps({entry: True for entry in entries}), encoding="utf-8"
    )
    return cache


def _suite(
    root: Path, name: str = "core", pytest_args: tuple[str, ...] = ()
) -> test_failed.Suite:
    return test_failed.Suite(
        name=name,
        directory=root,
        cache=root / test_failed.CACHE_RELATIVE,
        pytest_args=pytest_args,
    )


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


def test_default_suites_read_each_project_cache() -> None:
    core, docstruct, sdk = test_failed.default_suites()

    assert core.directory == test_failed.REPO_ROOT
    assert core.cache == core.directory / test_failed.CACHE_RELATIVE
    assert core.pytest_args == ("-m", "not e2e")

    assert docstruct.directory == test_failed.REPO_ROOT / "libs" / "docstruct"
    assert docstruct.cache == docstruct.directory / test_failed.CACHE_RELATIVE
    assert docstruct.pytest_args == ()
    assert docstruct.runner[:1] == ("uv",)
    assert docstruct.prefix == "libs/docstruct"

    assert sdk.directory == test_failed.REPO_ROOT / "libs" / "sdk"
    assert sdk.cache == sdk.directory / test_failed.CACHE_RELATIVE
    assert sdk.pytest_args == ()
    assert sdk.runner[:1] == ("uv",)
    assert sdk.prefix == "libs/sdk"


def test_rerun_without_any_cache_does_not_run_pytest(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(
        test_failed.subprocess, "run", lambda *args, **kwargs: calls.append(args)
    )

    assert test_failed.rerun([_suite(tmp_path)]) == 0
    assert calls == []
    assert "nothing to rerun" in capsys.readouterr().out


def test_collectable_ignores_a_deleted_file(tmp_path: Path) -> None:
    valid, problems, fatal = test_failed._collectable(
        _suite(tmp_path), ["tests/test_gone.py::test_a"]
    )

    assert valid == set()
    assert problems == []
    assert fatal is None


def test_stale_node_id_does_not_run_unrelated_tests(
    tmp_path: Path, capsys
) -> None:
    (tmp_path / "test_sample.py").write_text(
        "def test_unrelated():\n"
        "    raise AssertionError('must not run')\n",
        encoding="utf-8",
    )
    _cache(tmp_path, ["test_sample.py::test_removed"])

    assert test_failed.rerun([_suite(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert "not selected in this run" in output
    assert "Nothing to rerun" in output


def test_only_the_recorded_failure_is_rerun(tmp_path: Path, capsys) -> None:
    (tmp_path / "test_sample.py").write_text(
        "def test_ok():\n"
        "    assert True\n"
        "\n"
        "def test_unrelated():\n"
        "    raise AssertionError('must not run')\n",
        encoding="utf-8",
    )
    _cache(tmp_path, ["test_sample.py::test_ok"])

    assert test_failed.rerun([_suite(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert "Rerunning 1" in output


def test_a_passing_core_does_not_hide_the_library_failure(
    tmp_path: Path, capfd
) -> None:
    core = tmp_path / "core"
    sdk = tmp_path / "libs" / "sdk"
    core.mkdir()
    sdk.mkdir(parents=True)
    (core / "test_core.py").write_text(
        "def test_core():\n    assert True\n", encoding="utf-8"
    )
    (sdk / "test_sdk.py").write_text(
        "def test_sdk():\n    assert False\n", encoding="utf-8"
    )
    _cache(core, [])
    _cache(sdk, ["test_sdk.py::test_sdk"])

    status = test_failed.rerun([_suite(core, "core"), _suite(sdk, "sdk")])

    assert status == 1
    output = capfd.readouterr().out
    assert "[sdk] Rerunning 1" in output
    assert "[core]" not in output


def test_an_entry_in_another_cache_runs_from_its_own_project(
    tmp_path: Path, capfd
) -> None:
    core = tmp_path / "core"
    sdk = tmp_path / "libs" / "sdk"
    core.mkdir()
    (sdk / "tests").mkdir(parents=True)
    (sdk / "tests" / "test_sdk.py").write_text(
        "def test_sdk():\n    assert True\n", encoding="utf-8"
    )
    _cache(core, ["libs/sdk/tests/test_sdk.py::test_sdk"])
    core_suite = _suite(core, "core")
    sdk_suite = test_failed.Suite(
        name="sdk",
        directory=sdk,
        cache=sdk / test_failed.CACHE_RELATIVE,
        prefix="libs/sdk",
    )

    assert test_failed.rerun([core_suite, sdk_suite]) == 0
    output = capfd.readouterr().out
    assert "[sdk] Rerunning 1" in output
    assert "[core] Rerunning" not in output


def test_only_e2e_failures_are_not_rerun(tmp_path: Path, capsys) -> None:
    (tmp_path / "pytest.ini").write_text(
        "[pytest]\nmarkers =\n    e2e: live\n", encoding="utf-8"
    )
    (tmp_path / "test_live.py").write_text(
        "import pytest\n"
        "\n"
        "@pytest.mark.e2e\n"
        "def test_live():\n"
        "    raise AssertionError('must not run')\n",
        encoding="utf-8",
    )
    _cache(tmp_path, ["test_live.py::test_live"])

    status = test_failed.rerun(
        [_suite(tmp_path, pytest_args=("-m", "not e2e"))]
    )

    assert status == 0
    output = capsys.readouterr().out
    assert "not selected in this run" in output
    assert "Nothing to rerun" in output


def test_a_file_level_collection_failure_is_rerun(tmp_path: Path, capfd) -> None:
    (tmp_path / "test_bad.py").write_text("def test_broken(:\n", encoding="utf-8")
    _cache(tmp_path, ["test_bad.py"])

    status = test_failed.rerun([_suite(tmp_path)])

    assert status != 0
    output = capfd.readouterr().out
    assert "Rerunning 1" in output
    assert "SyntaxError" in output
