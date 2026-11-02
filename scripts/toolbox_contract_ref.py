"""Print the Toolbox ref whose published contract a core branch is checked against.

CI checks the SDK registry against the contract the Toolbox publishes on the
branch this code is deployed with (#186):

- ``main`` runs against the Toolbox's ``main``;
- ``release/x.y.z`` runs against the Toolbox's ``release/x.y.z`` while that
  BHS is open (both are cut together, the Toolbox first), and against its
  ``vx.y.z`` tag once the Toolbox has closed the cycle and deleted the branch;
- everything else runs against the Toolbox's ``develop``.

The choice comes from the refs the Toolbox repository lists, never from a
failed download: a release with neither ref is an error, not a fallback to
another branch's contract.

Usage:
    python scripts/toolbox_contract_ref.py release/0.2.0
"""

from __future__ import annotations

import argparse
import subprocess
import sys

TOOLBOX_REPOSITORY = "https://github.com/A11yDevs/acessilia-toolbox.git"


def select_ref(target_branch: str, branches: set[str], tags: set[str]) -> str:
    """Pick the Toolbox ref for ``target_branch`` from its branches and tags."""
    if target_branch == "main":
        return "main"
    if not target_branch.startswith("release/"):
        return "develop"
    if target_branch in branches:
        return target_branch
    tag = "v" + target_branch.removeprefix("release/")
    if tag in tags:
        return tag
    raise ValueError(
        f"the Toolbox has neither {target_branch} nor {tag}; "
        "cut its release first (or tag it when closing the cycle)"
    )


def _remote_refs(repository: str) -> tuple[set[str], set[str]]:
    output = subprocess.run(
        ["git", "ls-remote", "--heads", "--tags", repository],
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    ).stdout
    branches: set[str] = set()
    tags: set[str] = set()
    for line in output.splitlines():
        ref = line.split("\t", 1)[-1]
        if ref.startswith("refs/heads/"):
            branches.add(ref.removeprefix("refs/heads/"))
        elif ref.startswith("refs/tags/"):
            tags.add(ref.removeprefix("refs/tags/").removesuffix("^{}"))
    return branches, tags


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("target_branch", help="core branch being tested or merged into")
    parser.add_argument("--repository", default=TOOLBOX_REPOSITORY)
    args = parser.parse_args(argv)
    try:
        # Only a release needs to know which refs exist.
        branches, tags = (
            _remote_refs(args.repository)
            if args.target_branch.startswith("release/")
            else (set(), set())
        )
        print(select_ref(args.target_branch, branches, tags))
    except (subprocess.SubprocessError, OSError, ValueError) as exc:
        print(f"cannot select the Toolbox contract ref: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
