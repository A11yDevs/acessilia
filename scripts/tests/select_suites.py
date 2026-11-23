"""Select test suites from the files changed in a pull request (#644).

This is the architecture-aware selector for the #644 CI experiment. It maps
changed paths to the component document in ``docs/architecture/dependencies.md``:

* docstruct is the base library, consumed by the SDK, the core and the service;
* the SDK is consumed by the core and the service;
* the core is consumed by the service;
* the service (backend/frontend) does not force the libraries' unit suites.

The default mode is **shadow**: the script writes its recommendation, but the CI
gate still runs every suite. A conservative fallback selects everything when a
transversal or unknown path is touched, or when the diff cannot be read.

Example::

    python scripts/tests/select_suites.py \
      --base-ref origin/develop --head-ref HEAD \
      --output var/selection.json --summary "$GITHUB_STEP_SUMMARY"
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA_VERSION = 2
SUITES = ("docstruct", "sdk", "core", "app")
INDICATORS = (
    "docstruct_changed",
    "sdk_changed",
    "core_changed",
    "app_changed",
    "contracts_changed",
    "infrastructure_changed",
    "unclassified_changed",
    "integration_changed",
)

#: Paths that make every suite mandatory: shared configuration, schemas,
#: contracts and the test infrastructure itself.
TRANSVERSAL_PREFIXES = (
    ".github/",
    "infra/",
    "schemas/",
    "scripts/",
    "deploy/",
)
TRANSVERSAL_FILES = {
    "Makefile",
    "pyproject.toml",
    "uv.lock",
    ".python-version",
    "docker-compose.yml",
    "docker-compose.staging.yml",
    "docker-compose.production.yml",
}
CONTRACT_MARKERS = (
    "toolbox-contract",
    "capability_contract",
)

#: The exact path globs used by the real ``changes`` filter in ci.yml.
INTEGRATION_GLOBS = (
    "backend/**",
    "frontend/**",
    "libs/core/**",
    "libs/sdk/**",
    "libs/docstruct/**",
    "tests/test_provider_choice_methods.py",
    "tests/conftest.py",
    "tests/judge_support.py",
    "tests/core_config_support.py",
    "tests/toolbox_render_fake.py",
    "pyproject.toml",
    "uv.lock",
    ".github/workflows/ci.yml",
)


def matches_integration(path: str) -> bool:
    """Whether a repository-relative path matches one of the CI globs.

    Matching is case-insensitive. A trailing ``/**`` also matches the bare
    directory path, mirroring ``dorny/paths-filter`` for directory entries.
    """
    normalized = path.replace("\\", "/").strip().lower()
    return any(
        fnmatchcase(normalized, pattern)
        or (pattern.endswith("/**") and normalized == pattern[:-3])
        for pattern in INTEGRATION_GLOBS
    )


@dataclass(frozen=True)
class Selection:
    paths: tuple[str, ...]
    suites: tuple[str, ...]
    indicators: dict[str, bool]
    contracts_required: bool
    infrastructure_changed: bool
    integration_required: bool
    conservative: bool
    reasons: dict[str, list[str]]


def _suites(*names: str) -> tuple[str, ...]:
    return tuple(name for name in SUITES if name in names)


def _all_suites() -> tuple[str, ...]:
    return SUITES


def classify_paths(paths: Sequence[str]) -> Selection:
    """Map changed paths to suites, indicators and human-readable reasons."""
    selected: set[str] = set()
    indicators = {name: False for name in INDICATORS}
    reasons: dict[str, list[str]] = {name: [] for name in SUITES}
    contracts = False
    infrastructure = False
    integration = False
    conservative = False

    normalized = [
        raw_path.replace("\\", "/").strip()
        for raw_path in paths
        if raw_path.replace("\\", "/").strip()
    ]
    for path in normalized:
        lowered = path.lower()
        if (
            lowered in {name.lower() for name in TRANSVERSAL_FILES}
            or lowered.startswith(TRANSVERSAL_PREFIXES)
        ):
            infrastructure = True
            selected.update(_all_suites())
            indicators["infrastructure_changed"] = True
            for suite in SUITES:
                reasons[suite].append(f"transversal path: {path}")
        elif lowered.startswith("libs/docstruct/"):
            selected.update(_suites("docstruct", "sdk", "core", "app"))
            indicators["docstruct_changed"] = True
            for suite in _suites("docstruct", "sdk", "core", "app"):
                reasons[suite].append(f"docstruct dependency: {path}")
        elif lowered.startswith("libs/sdk/"):
            selected.update(_suites("sdk", "core", "app"))
            indicators["sdk_changed"] = True
            for suite in _suites("sdk", "core", "app"):
                reasons[suite].append(f"SDK dependency: {path}")
        elif lowered.startswith("libs/core/"):
            selected.update(_suites("core", "app"))
            indicators["core_changed"] = True
            for suite in _suites("core", "app"):
                reasons[suite].append(f"core dependency: {path}")
        elif lowered.startswith(("backend/", "frontend/", "tests/")):
            selected.add("app")
            indicators["app_changed"] = True
            reasons["app"].append(f"application/test path: {path}")
        elif lowered.startswith("docs/") or lowered.endswith(".md"):
            # Documentation checks (links, Portuguese allowlist, contract
            # snippets) live in the application suite; keep them covered.
            selected.add("app")
            indicators["app_changed"] = True
            reasons["app"].append(f"documentation path checked by the app suite: {path}")
        else:
            # Unknown paths are treated conservatively: the selector should
            # never hide a regression because it did not recognize a path.
            conservative = True
            integration = True
            selected.update(_all_suites())
            indicators["unclassified_changed"] = True
            indicators["integration_changed"] = True
            for suite in SUITES:
                reasons[suite].append(f"unknown path, conservative fallback: {path}")

        if lowered.startswith("schemas/") or any(
            marker in lowered for marker in CONTRACT_MARKERS
        ):
            contracts = True
            indicators["contracts_changed"] = True
            for suite in SUITES:
                reasons[suite].append(f"contract path: {path}")

        if matches_integration(lowered):
            integration = True
            indicators["integration_changed"] = True
            reasons["app"].append(f"integration trigger: {path}")

    ordered = _suites(*sorted(selected, key=SUITES.index))
    if not normalized or not ordered:
        conservative = True
        ordered = _all_suites()
        infrastructure = True
        integration = True
        indicators["infrastructure_changed"] = True
        indicators["integration_changed"] = True
        for suite in SUITES:
            reasons[suite].append("no changed paths: conservative fallback")

    return Selection(
        paths=tuple(normalized),
        suites=ordered,
        indicators=indicators,
        contracts_required=contracts,
        infrastructure_changed=infrastructure,
        integration_required=integration,
        conservative=conservative,
        reasons={suite: reasons[suite] for suite in SUITES},
    )


def changed_files(base_ref: str, head_ref: str, *, root: Path = ROOT) -> list[str]:
    """Paths changed between ``base_ref`` and ``head_ref`` (three-dot diff)."""
    completed = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            "--diff-filter=ACMRDT",
            "--no-renames",
            f"{base_ref}...{head_ref}",
        ],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    )
    return [line for line in completed.stdout.splitlines() if line.strip()]


def build_report(selection: Selection, *, base_ref: str, head_ref: str) -> dict:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "impact-selection",
        "mode": "shadow",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "base_ref": base_ref,
        "head_ref": head_ref,
        "changed_files": list(selection.paths),
        "indicators": selection.indicators,
        "selected_suites": list(selection.suites),
        "skipped_suites": [suite for suite in SUITES if suite not in selection.suites],
        "contracts_required": selection.contracts_required,
        "infrastructure_changed": selection.infrastructure_changed,
        "integration_required": selection.integration_required,
        "conservative_fallback": selection.conservative,
        "reasons": selection.reasons,
    }


def render_summary(report: dict) -> str:
    selected = report["selected_suites"]
    skipped = report["skipped_suites"]
    lines = [
        "## Changed-component selection (shadow mode)",
        "",
        (
            "This report **does not skip anything** yet: the full suite remains "
            "the merge gate. It records what an impact-aware CI would run."
        ),
        "",
        f"- Base: `{report['base_ref']}`",
        f"- Head: `{report['head_ref']}`",
        f"- Changed files: {len(report['changed_files'])}",
        f"- Selected suites: {', '.join(selected) if selected else '—'}",
        f"- Not selected: {', '.join(skipped) if skipped else '—'}",
        f"- Contracts required: {'yes' if report['contracts_required'] else 'no'}",
        f"- Integration required: {'yes' if report['integration_required'] else 'no'}",
        (
            "- Conservative fallback: "
            f"{'yes' if report['conservative_fallback'] else 'no'}"
        ),
        "",
        "| Indicator | Value |",
        "|---|---|",
    ]
    for name, value in report["indicators"].items():
        lines.append(f"| `{name}` | {'yes' if value else 'no'} |")
    lines += ["", "### Changed files", ""]
    if report["changed_files"]:
        lines += [f"- `{path}`" for path in report["changed_files"]]
    else:
        lines.append("- —")
    return "\n".join(lines) + "\n"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-ref", default="origin/develop")
    parser.add_argument("--head-ref", default="HEAD")
    parser.add_argument(
        "--changed-file",
        action="append",
        default=[],
        help="explicit changed path; repeatable (skips git diff)",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args(argv)

    paths = list(args.changed_file)
    fallback_reason = ""
    if not paths:
        try:
            paths = changed_files(args.base_ref, args.head_ref, root=args.root)
        except (OSError, subprocess.CalledProcessError) as exc:
            fallback_reason = f"git diff failed: {exc}"
            paths = []
    selection = classify_paths(paths)
    report = build_report(selection, base_ref=args.base_ref, head_ref=args.head_ref)
    if fallback_reason:
        report["conservative_fallback"] = True
        report["reasons"] = {
            suite: [fallback_reason] for suite in SUITES
        }
        report["selected_suites"] = list(SUITES)
        report["skipped_suites"] = []
    summary = render_summary(report)
    print(summary)
    if args.output:
        _write(args.output, json.dumps(report, indent=2) + "\n")
    if args.summary:
        _write(args.summary, summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
