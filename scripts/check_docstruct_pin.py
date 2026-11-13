"""Check that the Toolbox pins the docstruct release the core's branch calls for.

The Toolbox installs docstruct as a wheel published here, on a
``docstruct-vX.Y.Z`` GitHub Release, pinned by URL and ``#sha256=`` in its
``pyproject.toml``. Until #470 nothing checked that the pin follows the core:
the paired branches agreed by convention only (#470's P8 risk).

The pin is read from the Toolbox ref paired with the core branch, the same
pairing as the capability contract (``scripts/toolbox_contract_ref.py``). It
must:

1. point at a ``docstruct-v*`` release of this repository, with the wheel of
   the same version;
2. carry the SHA-256 of the wheel that release published;
3. not be newer than the docstruct version of the core branch;
4. be the newest release that is not newer than that version. A version bumped
   but not released yet asks nothing; a release the Toolbox did not adopt is
   reported as the Toolbox being behind.

A ``docstruct-vX.Y.Z`` tag counts as a release only once its wheel can be
downloaded: the tag is pushed before the release workflow publishes the wheel,
and a draft release has no public asset, so a tag alone never makes the
Toolbox "behind" (review of #498).

Only the Toolbox can fix any of these, so a pull request's CI runs this with
``--report-only`` (findings become warnings and the step passes), and the
scheduled monitoring runs it strictly, so a finding fails that run and reaches
its tracking issue.

Usage:
    python scripts/check_docstruct_pin.py develop [--report-only]
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import tomllib
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.toolbox_contract_ref import _remote_refs, select_ref

CORE_REPOSITORY = "https://github.com/A11yDevs/acessilia.git"
TOOLBOX_REPOSITORY = "https://github.com/A11yDevs/acessilia-toolbox.git"
TOOLBOX_PYPROJECT = (
    "https://raw.githubusercontent.com/A11yDevs/acessilia-toolbox/{ref}/pyproject.toml"
)
RELEASE_PREFIX = "https://github.com/A11yDevs/acessilia/releases/download/"
PIN = re.compile(
    r"acessilia-docstruct\s*@\s*"
    r"(?P<url>https://github\.com/(?P<repository>[^/]+/[^/]+)/releases/download/"
    r"docstruct-v(?P<tag_version>[^/]+)/"
    r"acessilia_docstruct-(?P<file_version>[^-]+)-py3-none-any\.whl)"
    r"#sha256=(?P<sha256>[0-9a-f]{64})"
)


@dataclass(frozen=True)
class Pin:
    url: str
    repository: str
    tag_version: str
    file_version: str
    sha256: str


def version_key(version: str) -> tuple[int, ...]:
    return tuple(int(part) for part in version.split("."))


def parse_pin(pyproject: str) -> Pin | None:
    """The docstruct pin of a Toolbox ``pyproject.toml``, or ``None`` without one."""
    for dependency in tomllib.loads(pyproject).get("project", {}).get("dependencies", []):
        match = PIN.fullmatch(dependency.strip())
        if match:
            return Pin(**{key: match[key] for key in Pin.__dataclass_fields__})
        if dependency.strip().startswith("acessilia-docstruct"):
            raise ValueError(f"unrecognized acessilia-docstruct pin: {dependency!r}")
    return None


def wheel_url(version: str) -> str:
    """Where the release of ``version`` publishes its wheel."""
    return (
        f"{RELEASE_PREFIX}docstruct-v{version}/acessilia_docstruct-{version}-py3-none-any.whl"
    )


def tagged_versions(tags: set[str]) -> list[str]:
    """Versions with a ``docstruct-vX.Y.Z`` tag, oldest first."""
    versions = [
        tag.removeprefix("docstruct-v")
        for tag in tags
        if re.fullmatch(r"docstruct-v\d+\.\d+\.\d+", tag)
    ]
    return sorted(versions, key=version_key)


def evaluate(
    core_version: str,
    pin: Pin | None,
    releases: list[str],
    published_sha256: str | None,
) -> list[str]:
    """Findings for a Toolbox pin against the core's docstruct version; empty when it agrees.

    ``releases`` are the versions whose wheel was found published (see
    ``published_releases``), and ``published_sha256`` is the pinned version's
    wheel hash when it is one of them.
    """
    if pin is None:
        return ["the Toolbox does not pin acessilia-docstruct"]
    findings = []
    if pin.repository != "A11yDevs/acessilia":
        findings.append(f"the pin points at {pin.repository}, not at this repository's releases")
    if pin.tag_version != pin.file_version:
        findings.append(
            f"the pin's release (docstruct-v{pin.tag_version}) and wheel "
            f"({pin.file_version}) differ"
        )
    if pin.tag_version not in releases:
        findings.append(f"docstruct-v{pin.tag_version} is not a published release")
    elif published_sha256 is not None and published_sha256 != pin.sha256:
        findings.append(
            f"the pin's sha256 ({pin.sha256[:12]}…) is not the published wheel's "
            f"({published_sha256[:12]}…)"
        )
    if version_key(pin.tag_version) > version_key(core_version):
        findings.append(
            f"the Toolbox pins {pin.tag_version}, newer than the core branch's "
            f"docstruct {core_version}"
        )
    candidates = [v for v in releases if version_key(v) <= version_key(core_version)]
    if candidates and version_key(pin.tag_version) < version_key(candidates[-1]):
        findings.append(
            f"the Toolbox is behind: it pins {pin.tag_version}, and "
            f"docstruct-v{candidates[-1]} is released for the core branch's "
            f"docstruct {core_version}"
        )
    return findings


def _fetch(url: str) -> bytes:
    # Only the fixed https URLs above are fetched.
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read()


def _published_sha256(version: str) -> str | None:
    """The SHA-256 of the wheel ``version``'s release published, ``None`` when it has none.

    Only a missing asset (404) means "not published"; any other failure is
    raised, so the check reports that it could not run instead of a verdict.
    """
    try:
        return hashlib.sha256(_fetch(wheel_url(version))).hexdigest()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def published_releases(
    tags: list[str], core_version: str, pinned: str | None
) -> tuple[dict[str, str], list[str]]:
    """Published wheels to judge the pin by, and the tags found without one.

    Returns ``{version: sha256}`` for the pinned version and for the newest
    tagged version not newer than ``core_version`` that has a wheel, walking
    the tags down from the newest, and the tags passed over for lacking one.
    """
    published: dict[str, str] = {}
    unpublished: list[str] = []
    if pinned is not None and pinned in tags:
        sha = _published_sha256(pinned)
        if sha is not None:
            published[pinned] = sha
        else:
            unpublished.append(pinned)
    for version in reversed([v for v in tags if version_key(v) <= version_key(core_version)]):
        if version in published:
            break
        if version in unpublished:
            continue
        sha = _published_sha256(version)
        if sha is not None:
            published[version] = sha
            break
        unpublished.append(version)
    return published, unpublished


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("target_branch", help="core branch being tested or merged into")
    parser.add_argument(
        "--core-version",
        help="the core branch's docstruct version (default: libs/docstruct of this checkout)",
    )
    parser.add_argument(
        "--report-only", action="store_true",
        help="print findings as warnings and exit 0 (pull request CI)",
    )
    args = parser.parse_args(argv)
    level = "warning" if args.report_only else "error"
    try:
        toolbox_branches, toolbox_tags = (
            _remote_refs(TOOLBOX_REPOSITORY)
            if args.target_branch.startswith("release/")
            else (set(), set())
        )
        toolbox_ref = select_ref(args.target_branch, toolbox_branches, toolbox_tags)
        core_version = args.core_version or tomllib.loads(
            (ROOT / "libs/docstruct/pyproject.toml").read_text(encoding="utf-8")
        )["project"]["version"]
        pin = parse_pin(_fetch(TOOLBOX_PYPROJECT.format(ref=toolbox_ref)).decode("utf-8"))
        _, core_tags = _remote_refs(CORE_REPOSITORY)
        tags = tagged_versions(core_tags)
        # Another repository's URL is never fetched; the pin is reported instead.
        ours = pin is not None and pin.url == wheel_url(pin.tag_version)
        published, unpublished = published_releases(
            tags, core_version, pin.tag_version if ours else None
        )
        releases = sorted(published, key=version_key)
        findings = evaluate(
            core_version, pin, releases, published.get(pin.tag_version) if pin else None
        )
    except Exception as exc:  # noqa: BLE001 - reported with its level, never swallowed
        print(f"::{level}::cannot check the Toolbox's docstruct pin: {type(exc).__name__}: {exc}")
        return 0 if args.report_only else 1
    pinned = pin.tag_version if pin else "nothing"
    print(
        f"core {args.target_branch}: docstruct {core_version}; "
        f"Toolbox {toolbox_ref}: pins {pinned}; tags: {', '.join(tags)}; "
        f"published wheels checked: {', '.join(releases) or 'none'}"
    )
    if unpublished:
        print(f"tags without a published wheel yet: {', '.join(unpublished)}")
    for finding in findings:
        print(f"::{level}::{finding}")
    if not findings:
        print("The Toolbox's docstruct pin follows the core.")
    return 0 if (args.report_only or not findings) else 1


if __name__ == "__main__":
    sys.exit(main())
