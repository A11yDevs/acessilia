#!/usr/bin/env python3
"""Rerun the tests that failed in the previous pytest session.

``pytest --lf`` runs the whole suite when the cache holds no failure ("last
failed" falls back to "all"), which is surprising in a command whose only job
is to retry failures. This wrapper reads pytest's cache first and exits
successfully with a message when there is nothing to rerun.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CACHE = REPO_ROOT / ".pytest_cache" / "v" / "cache" / "lastfailed"


def failed_tests(cache_path: Path | None = None) -> list[str]:
    """Node ids recorded in pytest's ``lastfailed`` cache, sorted."""
    path = CACHE if cache_path is None else cache_path
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    return sorted(str(nodeid) for nodeid in data)


def main(argv: list[str] | None = None) -> int:
    extra = list(sys.argv[1:] if argv is None else argv)
    tests = failed_tests()
    if not tests:
        print(
            "No previously failed tests in .pytest_cache; nothing to rerun.",
            flush=True,
        )
        return 0
    print(f"Rerunning {len(tests)} previously failed test(s).", flush=True)
    command = [
        sys.executable,
        "-m",
        "pytest",
        "--lf",
        "-m",
        "not e2e",
        "--durations=25",
        *extra,
    ]
    result = subprocess.run(command, check=False, cwd=REPO_ROOT)
    if result.returncode == 5:
        print("No previously failed non-E2E tests to rerun.", flush=True)
        return 0
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
