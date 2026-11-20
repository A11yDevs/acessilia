"""Enforce Ruff linting against a shrinking per-file baseline (#366).

Runs ``ruff check`` using the repository configuration in ``pyproject.toml``
and compares per-file, per-rule violation counts against
``tests/fixtures/ruff_baseline.json``:

- Any new violation (count above the recorded baseline, or in a clean file)
  fails the check with full diagnostic details.
- Any stale baseline entry (count below the recorded baseline, or a file that
  is now clean) also fails the check so the baseline can only shrink.
- ``--update`` rewrites the baseline with lower counts only (refusing any
  increase unless ``--allow-increase`` is passed explicitly).
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

#: Repository root derived from this script's location.
REPO_ROOT = Path(__file__).resolve().parents[1]

#: Default baseline fixture tracking pre-existing Ruff violations.
DEFAULT_BASELINE = REPO_ROOT / "tests" / "fixtures" / "ruff_baseline.json"

#: Top-level directories checked by Ruff in local runs and CI.
DEFAULT_PATHS: tuple[str, ...] = ("backend", "frontend", "libs", "scripts", "tests")

Baseline = dict[str, dict[str, int]]


@dataclass(frozen=True)
class Comparison:
    """Result of comparing current Ruff counts against a recorded baseline."""

    regressions: list[tuple[str, str, int, int]]
    stale: list[tuple[str, str, int, int]]

    @property
    def ok(self) -> bool:
        return not self.regressions and not self.stale


def run_ruff(
    paths: Sequence[str] = DEFAULT_PATHS,
    *,
    root: Path = REPO_ROOT,
) -> list[dict[str, Any]]:
    """Run ``ruff check --output-format=json`` and return parsed diagnostics."""
    cmd = [
        sys.executable,
        "-m",
        "ruff",
        "check",
        "--no-cache",
        "--output-format=json",
        *paths,
    ]
    completed = subprocess.run(
        cmd,
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    # Ruff exits 0 (no violations) or 1 (violations found); 2 indicates a CLI/config error.
    if completed.returncode not in (0, 1):
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"ruff check failed (exit {completed.returncode}): {detail}")
    raw = completed.stdout.strip()
    if not raw:
        if completed.returncode == 0:
            return []
        detail = completed.stderr.strip() or "no output"
        raise RuntimeError(
            f"ruff check failed without JSON output (exit {completed.returncode}): {detail}"
        )
    parsed = json.loads(raw)
    if not isinstance(parsed, list):
        raise RuntimeError(f"Unexpected ruff JSON output: {type(parsed).__name__}")
    return parsed


def _rel_posix(filename: str, root: Path) -> str:
    path = Path(filename)
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def summarize_diagnostics(
    diagnostics: Sequence[dict[str, Any]],
    *,
    root: Path = REPO_ROOT,
) -> Baseline:
    """Aggregate Ruff diagnostics into ``{relative_path: {rule_code: count}}``."""
    per_file: dict[str, Counter[str]] = defaultdict(Counter)
    for item in diagnostics:
        rel = _rel_posix(str(item["filename"]), root)
        code = str(item.get("code") or "UNKNOWN")
        per_file[rel][code] += 1
    return {
        rel: dict(sorted(counts.items()))
        for rel, counts in sorted(per_file.items())
    }


def load_baseline(path: Path) -> Baseline:
    """Load a baseline JSON file into ``{relative_path: {rule_code: count}}``."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    files = payload.get("files", {})
    result: Baseline = {}
    for rel, codes in sorted(files.items()):
        result[str(rel)] = {str(code): int(count) for code, count in sorted(codes.items())}
    return result


def write_baseline(path: Path, counts: Baseline) -> None:
    """Write a deterministic baseline JSON file."""
    payload = {
        "_comment": (
            "Pre-existing Ruff violations (rules F, E excluding E501; #366), "
            "counted per file and rule code. Counts may only go down: when you "
            "fix violations, run `uv run python scripts/check_ruff_baseline.py --update`."
        ),
        "files": {
            rel: dict(sorted(codes.items()))
            for rel, codes in sorted(counts.items())
            if codes
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def _filter_baseline_for_paths(
    allowed: Baseline,
    paths: Sequence[str],
    *,
    root: Path,
) -> Baseline:
    """Restrict ``allowed`` to entries matching any target in ``paths``."""
    resolved_root = root.resolve()
    targets: list[Path] = []
    for raw in paths:
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = resolved_root / candidate
        targets.append(candidate.resolve())

    filtered: Baseline = {}
    for rel, codes in allowed.items():
        entry_path = (resolved_root / rel).resolve()
        if any(entry_path == target or entry_path.is_relative_to(target) for target in targets):
            filtered[rel] = codes
    return filtered


def _display_path(path: Path, *, root: Path) -> str:
    """Format ``path`` relative to ``root`` when inside it, otherwise as given."""
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def compare_baselines(current: Baseline, allowed: Baseline) -> Comparison:
    """Return regressions (current > allowed) and stale entries (current < allowed)."""
    regressions: list[tuple[str, str, int, int]] = []
    stale: list[tuple[str, str, int, int]] = []

    all_files = sorted(set(current) | set(allowed))
    for rel in all_files:
        cur_codes = current.get(rel, {})
        allow_codes = allowed.get(rel, {})
        for code in sorted(set(cur_codes) | set(allow_codes)):
            cur = cur_codes.get(code, 0)
            allow = allow_codes.get(code, 0)
            if cur > allow:
                regressions.append((rel, code, allow, cur))
            elif cur < allow:
                stale.append((rel, code, allow, cur))
    return Comparison(regressions=regressions, stale=stale)


def _format_diagnostics_for(
    diagnostics: Sequence[dict[str, Any]],
    targets: set[tuple[str, str]],
    *,
    root: Path,
) -> list[str]:
    lines: list[str] = []
    for item in diagnostics:
        rel = _rel_posix(str(item["filename"]), root)
        code = str(item.get("code") or "UNKNOWN")
        if (rel, code) not in targets:
            continue
        loc = item.get("location") or {}
        row = loc.get("row", 0)
        col = loc.get("column", 0)
        message = item.get("message", "")
        lines.append(f"  {rel}:{row}:{col}: {code} {message}")
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--baseline",
        type=Path,
        default=DEFAULT_BASELINE,
        help="Path to the Ruff baseline JSON file.",
    )
    parser.add_argument(
        "--update",
        action="store_true",
        help="Shrink the baseline file to match current counts (refuses increases).",
    )
    parser.add_argument(
        "--allow-increase",
        action="store_true",
        help="Permit --update to record higher counts (e.g. when initializing or adding a rule).",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        default=None,
        help="Directories or files to lint (default: all repository source/test trees).",
    )
    args = parser.parse_args(argv)

    custom_paths = args.paths is not None and len(args.paths) > 0
    if args.update and custom_paths:
        parser.error(
            "--update rewrites the full baseline and cannot be combined with positional paths."
        )
    target_paths = list(args.paths) if custom_paths else list(DEFAULT_PATHS)

    diagnostics = run_ruff(target_paths, root=REPO_ROOT)
    current = summarize_diagnostics(diagnostics, root=REPO_ROOT)

    if args.update:
        if args.baseline.exists() and not args.allow_increase:
            allowed = load_baseline(args.baseline)
            comparison = compare_baselines(current, allowed)
            if comparison.regressions:
                print("Refusing to increase the Ruff baseline:", file=sys.stderr)
                for rel, code, allow, cur in comparison.regressions:
                    print(f"  {rel} [{code}]: {allow} -> {cur}", file=sys.stderr)
                return 1
        write_baseline(args.baseline, current)
        total = sum(sum(codes.values()) for codes in current.values())
        shown = _display_path(args.baseline, root=REPO_ROOT)
        print(f"Updated {shown}: {total} violation(s) across {len(current)} file(s).")
        return 0

    if not args.baseline.exists():
        print(
            f"Baseline file not found: {args.baseline}. "
            "Run with --update --allow-increase to create it.",
            file=sys.stderr,
        )
        return 1

    allowed = load_baseline(args.baseline)
    if custom_paths:
        allowed = _filter_baseline_for_paths(allowed, target_paths, root=REPO_ROOT)
    comparison = compare_baselines(current, allowed)

    if comparison.regressions:
        print("New Ruff violation(s) above baseline:", file=sys.stderr)
        regression_keys = set()
        for rel, code, allow, cur in comparison.regressions:
            regression_keys.add((rel, code))
            print(f"  {rel} [{code}]: {cur} found, {allow} allowed", file=sys.stderr)
        detail_lines = _format_diagnostics_for(diagnostics, regression_keys, root=REPO_ROOT)
        if detail_lines:
            print("Diagnostics:", file=sys.stderr)
            for line in detail_lines:
                print(line, file=sys.stderr)

    if comparison.stale:
        print(
            "Ruff baseline can shrink — run "
            "`uv run python scripts/check_ruff_baseline.py --update`:",
            file=sys.stderr,
        )
        for rel, code, allow, cur in comparison.stale:
            print(f"  {rel} [{code}]: {allow} -> {cur}", file=sys.stderr)

    if not comparison.ok:
        return 1

    total = sum(sum(codes.values()) for codes in current.values())
    print(f"Ruff baseline check passed: 0 new violations ({total} tracked across {len(current)} file(s)).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
