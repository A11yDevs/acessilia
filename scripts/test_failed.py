#!/usr/bin/env python3
"""Rerun the tests that failed in the previous pytest session.

The core, docstruct and SDK suites keep separate pytest caches, so this wrapper
reads all three and reruns each suite's failures from its own project directory.
It passes the still-collected node ids explicitly instead of ``--lf``: with a
recorded id that no longer exists, ``--lf`` falls back to the whole suite and
runs unrelated tests.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CACHE_RELATIVE = Path(".pytest_cache") / "v" / "cache" / "lastfailed"
CACHE = REPO_ROOT / CACHE_RELATIVE
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")


@dataclass(frozen=True)
class Suite:
    """One pytest project, with its own cache, directory and configuration."""

    name: str
    directory: Path
    cache: Path
    pytest_args: tuple[str, ...] = ()
    runner: tuple[str, ...] = ()
    # Path from the repository root, used to route a cache entry that was
    # recorded while pytest ran from another directory into this project.
    prefix: str | None = None

    def command(self, *args: str) -> list[str]:
        runner = self.runner or (sys.executable, "-m", "pytest")
        return [*runner, *self.pytest_args, *args]


def default_suites() -> list[Suite]:
    return [
        Suite(
            "core",
            REPO_ROOT,
            REPO_ROOT / CACHE_RELATIVE,
            pytest_args=("-m", "not e2e"),
        ),
        Suite(
            "docstruct",
            REPO_ROOT / "libs" / "docstruct",
            REPO_ROOT / "libs" / "docstruct" / CACHE_RELATIVE,
            runner=("uv", "run", "--extra", "dev", "pytest"),
            prefix="libs/docstruct",
        ),
        Suite(
            "sdk",
            REPO_ROOT / "libs" / "sdk",
            REPO_ROOT / "libs" / "sdk" / CACHE_RELATIVE,
            runner=("uv", "run", "--extra", "dev", "pytest"),
            prefix="libs/sdk",
        ),
    ]


def failed_tests(cache_path: Path | None = None) -> list[str]:
    """Node ids recorded in a pytest ``lastfailed`` cache, sorted."""
    path = CACHE if cache_path is None else cache_path
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    return sorted(str(nodeid) for nodeid in data)


def _key(directory: Path, path: str) -> Path:
    try:
        return (directory / path).resolve()
    except OSError:
        return Path(path)


def _route(suites: list[Suite], entry: str) -> tuple[Suite | None, str]:
    """Find the project that owns a cache entry recorded from another directory."""
    for suite in suites:
        if not suite.prefix:
            continue
        prefix = suite.prefix.rstrip("/")
        if entry.startswith(prefix + "/"):
            return suite, entry.removeprefix(prefix).lstrip("/")
    return None, entry


def _collectable(
    suite: Suite, nodeids: list[str]
) -> tuple[set[str], list[str], str | None]:
    """Collect the recorded files.

    Returns the ids that still exist, the files that still fail to collect and
    an error message when collection itself failed for an unknown reason.
    """
    files = sorted(
        {
            file
            for nodeid in nodeids
            if (file := nodeid.split("::", 1)[0])
            and (suite.directory / file).is_file()
        }
    )
    if not files:
        return set(), [], None

    command = suite.command(
        "--collect-only",
        "-q",
        "--disable-warnings",
        "--continue-on-collection-errors",
        *files,
    )
    try:
        result = subprocess.run(
            command, cwd=suite.directory, check=False, capture_output=True, text=True
        )
    except OSError as error:
        return set(), [], str(error)

    lines = [
        ANSI_ESCAPE.sub("", line).strip() for line in result.stdout.splitlines()
    ]
    collected = {
        line for line in lines if "::" in line and not line.startswith("ERROR")
    }
    problem_files = sorted(
        {
            line.removeprefix("ERROR ").strip()
            for line in lines
            if line.startswith("ERROR ") and not line.startswith("ERROR: ")
        }
    )
    fatal = None
    if result.returncode not in (0, 5) and not problem_files:
        fatal = (result.stdout + result.stderr).strip() or (
            f"pytest exited {result.returncode} while collecting the recorded failures"
        )
    return collected & set(nodeids), problem_files, fatal


def rerun(suites: list[Suite] | None = None) -> int:
    suites = default_suites() if suites is None else suites
    recorded: dict[str, list[str]] = {suite.name: [] for suite in suites}
    seen: set[tuple[str, str]] = set()
    for owner in suites:
        for entry in failed_tests(owner.cache):
            target, relative = _route(suites, entry)
            target = owner if target is None else target
            if not relative:
                continue
            key = (target.name, relative)
            if key in seen:
                continue
            seen.add(key)
            recorded[target.name].append(relative)

    if not any(recorded.values()):
        print(
            "No previously failed tests in the core, docstruct or SDK cache; "
            "nothing to rerun.",
            flush=True,
        )
        return 0

    status = 0
    for suite in suites:
        entries = sorted(recorded[suite.name])
        if not entries:
            continue

        nodeids = [entry for entry in entries if "::" in entry]
        file_entries = [entry for entry in entries if "::" not in entry]
        valid, problem_files, fatal = _collectable(suite, nodeids)

        problem_keys = {_key(suite.directory, path) for path in problem_files}
        stale = [
            nodeid
            for nodeid in nodeids
            if nodeid not in valid
            and _key(suite.directory, nodeid.split("::", 1)[0]) not in problem_keys
        ]
        missing_files = [
            path
            for path in file_entries
            if not (suite.directory / path).is_file()
        ]
        if stale or missing_files:
            count = len(stale) + len(missing_files)
            print(
                f"[{suite.name}] {count} recorded failure(s) are not selected "
                "in this run and will not run:",
                flush=True,
            )
            for nodeid in stale:
                print(f"  {nodeid}", flush=True)
            for path in missing_files:
                print(f"  {path} (file no longer exists)", flush=True)

        if fatal:
            print(f"[{suite.name}] could not collect the recorded failures:", flush=True)
            print(fatal, flush=True)
            status = status or 2

        run_args = sorted(valid)
        seen_files = set()
        for path in [*problem_files, *file_entries]:
            key = _key(suite.directory, path)
            if key in seen_files or not (suite.directory / path).is_file():
                continue
            seen_files.add(key)
            run_args.append(path)

        if not run_args:
            if not fatal:
                print(
                    f"[{suite.name}] Nothing to rerun from the recorded failures.",
                    flush=True,
                )
            continue

        print(
            f"[{suite.name}] Rerunning {len(valid) + len(seen_files)} "
            "recorded failure(s).",
            flush=True,
        )
        try:
            result = subprocess.run(
                suite.command("--durations=25", *run_args),
                cwd=suite.directory,
                check=False,
            )
        except OSError as error:
            print(f"[{suite.name}] could not start pytest: {error}", flush=True)
            status = status or 2
            continue
        if result.returncode not in (0, 5):
            status = result.returncode
        elif result.returncode == 5:
            print(f"[{suite.name}] No test ran from the recorded failures.", flush=True)

    return status


def main() -> int:
    return rerun()


if __name__ == "__main__":
    raise SystemExit(main())
