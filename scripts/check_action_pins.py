"""Verify that pinned GitHub Action SHAs resolve to commits (#812).

GitHub Actions accepts a 40-character object ID, but an annotated tag object
also has one. A tag-object pin can look pinned and then fail when the runner
tries to resolve a commit. The #807 static test keeps the CodeQL pins on one
shared value; this check asks the GitHub API whether each pinned action SHA is
actually a commit.

``--report-only`` is used in pull requests: findings are warnings and the step
passes. The scheduled monitoring runs it strictly, so a bad pin fails the run.
To fix a finding, dereference the tag to its commit SHA (for example
``git ls-remote --tags <repository> <tag>`` plus ``git rev-parse``), update the
pin, and update the shared CodeQL constant when the action is CodeQL.

Usage:
    python scripts/check_action_pins.py [--report-only] [--root PATH]
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

ROOT = Path(__file__).resolve().parents[1]
GITHUB_API = "https://api.github.com/repos/{repository}/git/commits/{ref}"
COMMIT_SHA = re.compile(r"[0-9a-f]{40}")
USES = re.compile(r"^\s*(?:-\s*)?uses:\s*[\"']?(?P<uses>[^\"'\s#]+)")
USER_AGENT = "acessilia-action-pin-check"


@dataclass(frozen=True)
class ActionPin:
    path: Path
    line: int
    repository: str
    ref: str


def iter_uses(root: Path) -> Iterator[tuple[Path, int, str]]:
    """Yield external ``uses`` references from workflows and composite actions."""
    base = root / ".github"
    for path in sorted(base.rglob("*")):
        if not path.is_file() or path.suffix not in {".yml", ".yaml"}:
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = USES.search(line)
            if not match:
                continue
            reference = match.group("uses")
            if reference.startswith("./") or reference.startswith("docker://"):
                continue
            yield path, number, reference


def parse_action_pin(
    reference: str, *, path: Path, line: int
) -> ActionPin:
    """Split ``owner/repository[/subpath]@ref`` into a repository and ref."""
    if "@" not in reference:
        raise ValueError(f"action is not pinned to a SHA: {reference}")
    target, ref = reference.rsplit("@", 1)
    parts = target.split("/")
    if len(parts) < 2 or not parts[0] or not parts[1]:
        raise ValueError(f"action is not an owner/repository reference: {reference}")
    return ActionPin(path, line, "/".join(parts[:2]), ref)


def _request_commit(
    repository: str,
    ref: str,
    *,
    token: str | None,
    timeout: float,
    opener: Callable[..., object],
) -> bool:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        GITHUB_API.format(repository=repository, ref=ref), headers=headers
    )
    try:
        with opener(request, timeout=timeout):
            return True
    except urllib.error.HTTPError as exc:
        if exc.code in {404, 422}:
            return False
        raise


def is_commit(
    repository: str,
    ref: str,
    *,
    token: str | None = None,
    timeout: float = 30,
    opener: Callable[..., object] = urllib.request.urlopen,
) -> bool:
    """Whether ``ref`` is a commit in ``repository``; tag objects are not commits."""
    if token and _request_commit(
        repository,
        ref,
        token=token,
        timeout=timeout,
        opener=opener,
    ):
        return True
    # An installation token may not resolve a different public repository.
    # Retry without it when the authenticated request did not find a commit;
    # a tag object is also missing there, so it remains invalid.
    return _request_commit(
        repository,
        ref,
        token=None,
        timeout=timeout,
        opener=opener,
    )


def pin_problem(
    pin: ActionPin,
    *,
    token: str | None,
    timeout: float = 30,
    opener: Callable[..., object] = urllib.request.urlopen,
) -> str | None:
    """A finding for one pin, or ``None`` when it is a pinned commit."""
    if not COMMIT_SHA.fullmatch(pin.ref):
        return f"is not pinned to a 40-character commit SHA: {pin.ref}"
    if not is_commit(pin.repository, pin.ref, token=token, timeout=timeout, opener=opener):
        return f"does not resolve to a commit object: {pin.ref}"
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="print findings as warnings and exit 0 (pull request CI)",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"),
        help="GitHub token; defaults to GITHUB_TOKEN or GH_TOKEN",
    )
    parser.add_argument("--timeout", type=float, default=30)
    args = parser.parse_args(argv)
    level = "warning" if args.report_only else "error"
    root = args.root.resolve()

    references = list(iter_uses(root))
    if not references:
        print(f"::{level}::no GitHub Action references found under {root / '.github'}")
        return 0 if args.report_only else 1

    cached: dict[tuple[str, str], str | None] = {}
    findings = 0
    for path, line, reference in references:
        try:
            pin = parse_action_pin(reference, path=path, line=line)
        except ValueError as exc:
            findings += 1
            print(f"::{level} file={path.relative_to(root)},line={line}::{exc}")
            continue
        key = (pin.repository, pin.ref)
        if key not in cached:
            try:
                cached[key] = pin_problem(
                    pin, token=args.token, timeout=args.timeout
                )
            except Exception as exc:  # noqa: BLE001 - reported with its level
                cached[key] = f"could not verify: {type(exc).__name__}: {exc}"
        problem = cached[key]
        if problem:
            findings += 1
            print(f"::{level} file={path.relative_to(root)},line={line}::{problem}")

    print(
        f"Checked {len(references)} action references in {root / '.github'}: "
        f"{findings} finding(s)."
    )
    return 0 if args.report_only or findings == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
