#!/usr/bin/env bash
# start_bhs_cycle.sh — Cuts release/x.y.z from develop (start of BHS)
#
# Usage:
#   ./scripts/start_bhs_cycle.sh 0.2.0
#
# What this script does:
#   1. Checks that neither release/<version> nor the v<version> tag exist yet
#   2. Forks release/<version> from origin/develop and bumps the version in
#      pyproject.toml and uv.lock on it, in a temporary worktree: the current
#      checkout (branch, uncommitted changes) is left untouched
#   3. Publishes the branch; CI and Delivery then publish the
#      release-<version> image
#   4. Prints the next steps (point staging + route fix/*)
#
# Cut the Toolbox first: CI checks a release branch against the capability
# contract of the Toolbox release of the same version.
#
# Prerequisites: git with push access to the repository, python3.

set -euo pipefail

VERSION="${1:-}"
if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Usage: $0 <x.y.z>   (e.g. $0 0.2.0)"
  exit 1
fi

BRANCH="release/${VERSION}"
PACKAGE="acessilia"
TOOLBOX_REPO="https://github.com/A11yDevs/acessilia-toolbox.git"

cd "$(dirname "$0")/.."

echo "[start-bhs] Fetching origin..."
git fetch origin --quiet

if git ls-remote --exit-code --heads origin "$BRANCH" >/dev/null; then
  echo "[start-bhs] ❌ Branch ${BRANCH} already exists on origin."
  exit 1
fi
if git ls-remote --exit-code --tags origin "v${VERSION}" >/dev/null; then
  echo "[start-bhs] ❌ Tag v${VERSION} already exists: ${VERSION} has been released."
  exit 1
fi
if ! git ls-remote --exit-code --heads "$TOOLBOX_REPO" "$BRANCH" >/dev/null; then
  echo "[start-bhs] ⚠️  The Toolbox has no ${BRANCH} yet: the release CI fails its"
  echo "             contract check until the Toolbox is cut too."
fi

WORKTREE="$(mktemp -d)"
trap 'git worktree remove --force "$WORKTREE" >/dev/null 2>&1 || true' EXIT
git worktree add --quiet --detach "$WORKTREE" origin/develop

echo "[start-bhs] Bumping ${PACKAGE} to ${VERSION}..."
python3 - "$WORKTREE" "$PACKAGE" "$VERSION" <<'EOF'
import re
import sys
from pathlib import Path

root, package, version = sys.argv[1:]
edits = [
    (Path(root, "pyproject.toml"), r'(?m)^(version = ")[^"]*(")'),
    (
        Path(root, "uv.lock"),
        rf'(\[\[package\]\]\nname = "{re.escape(package)}"\nversion = ")[^"]*(")',
    ),
]
for path, pattern in edits:
    text, count = re.subn(pattern, rf"\g<1>{version}\g<2>", path.read_text(), count=1)
    if count != 1:
        sys.exit(f"version of {package} not found in {path.name}")
    path.write_text(text)
EOF

if ! git -C "$WORKTREE" diff --quiet; then
  git -C "$WORKTREE" commit --quiet -am "chore(release): bump to ${VERSION}"
fi

echo "[start-bhs] Publishing ${BRANCH} (forked from origin/develop)..."
git -C "$WORKTREE" push --quiet origin "HEAD:refs/heads/${BRANCH}"

echo ""
echo "[start-bhs] ✅ BHS cycle started: ${BRANCH}"
echo ""
echo "Next steps:"
echo "  1. On the staging server, set TRACK_BRANCH=${BRANCH} in /opt/acessilia/staging/.env"
echo "     and run update_scripts.sh (the timer then switches to the release-${VERSION} image)."
echo "  2. fix/* PRs that fix bugs found in staging target ${BRANCH}."
echo "  3. feat/*, refactor/* and other PRs keep targeting develop."
echo "  4. When the cycle ends, run: ./scripts/finish_bhs_cycle.sh ${VERSION}"
