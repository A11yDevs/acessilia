#!/usr/bin/env bash
# finish_bhs_cycle.sh — Closes the BHS cycle (release/x.y.z -> main + develop)
#
# Usage:
#   ./scripts/finish_bhs_cycle.sh 0.2.0            # opens (or updates) the closing PRs
#   ./scripts/finish_bhs_cycle.sh 0.2.0 --cleanup   # once both PRs are merged, tags
#                                                     # v0.2.0 on the main merge and
#                                                     # deletes the branches
#
# The release replaces main: the release/x.y.z -> main PR must be merged with
# "Create a merge commit" (squash or rebase discard the release history).
#
# The fixes reach develop through a branch of their own,
# chore/sync-release-x.y.z, forked from the release: conflicts with develop are
# resolved there, without bringing develop (new features) into the release that
# goes to main. Running the script again carries fixes merged into the release
# afterwards over to the sync branch.
#
# Close the Toolbox first: CI on main checks the capability contract published
# on the Toolbox's main.
#
# Prerequisites: GitHub CLI (`gh`) authenticated with access to the repository.

set -euo pipefail

VERSION="${1:-}"
MODE="${2:-open}"
if ! [[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || ! [[ "$MODE" =~ ^(open|--cleanup)$ ]]; then
  echo "Usage: $0 <x.y.z> [--cleanup]   (e.g. $0 0.2.0)"
  exit 1
fi

BRANCH="release/${VERSION}"
SYNC_BRANCH="chore/sync-release-${VERSION}"
TAG="v${VERSION}"
REPO="A11yDevs/acessilia"

cd "$(dirname "$0")/.."

if ! command -v gh &>/dev/null; then
  echo "[finish-bhs] ❌ GitHub CLI (gh) not found."
  exit 1
fi

git fetch origin --quiet --prune

_pr_field() {
  # $1 = head, $2 = base, $3 = jq expression over the most recent PR
  gh pr list -R "$REPO" --head "$1" --base "$2" --state all \
    --json number,state,mergeCommit --jq ".[0] | $3"
}

if [ "$MODE" = "--cleanup" ]; then
  echo "[finish-bhs] Checking the PRs of ${BRANCH}..."
  MAIN_STATE=$(_pr_field "$BRANCH" main '.state // "NONE"')
  DEVELOP_STATE=$(_pr_field "$SYNC_BRANCH" develop '.state // "NONE"')

  echo "  main:    ${MAIN_STATE}"
  echo "  develop: ${DEVELOP_STATE}"

  if [ "$MAIN_STATE" != "MERGED" ] || [ "$DEVELOP_STATE" != "MERGED" ]; then
    echo "[finish-bhs] ⏳ PR(s) still pending. Wait for approval/merge before cleaning up."
    exit 1
  fi

  MERGE_SHA=$(_pr_field "$BRANCH" main '.mergeCommit.oid')
  PARENTS=$(gh api "repos/$REPO/commits/$MERGE_SHA" --jq '.parents | length')
  if [ "$PARENTS" != "2" ]; then
    echo "[finish-bhs] ❌ ${BRANCH} reached main without a merge commit (squash/rebase)."
    echo "             Tag and delete the branch yourself after checking main."
    exit 1
  fi

  if git ls-remote --exit-code --tags origin "$TAG" >/dev/null; then
    echo "[finish-bhs] Tag ${TAG} already exists on origin."
  else
    echo "[finish-bhs] Tagging ${TAG} at ${MERGE_SHA:0:7} (merge of the release into main)..."
    git fetch origin --quiet main
    git tag "$TAG" "$MERGE_SHA"
    git push origin "$TAG"
  fi

  echo "[finish-bhs] ✅ Both PRs merged. Deleting ${BRANCH} and ${SYNC_BRANCH}..."
  git push origin --delete "$BRANCH" || echo "  (remote branch ${BRANCH} already deleted)"
  git push origin --delete "$SYNC_BRANCH" || echo "  (remote branch ${SYNC_BRANCH} already deleted)"
  git branch -D "$BRANCH" 2>/dev/null || true

  echo ""
  echo "Last manual steps:"
  echo "  1. Remove TRACK_BRANCH from the staging server's .env to track develop again."
  echo "  2. Promote production as described in docs/producao-systemd.md (the ${TAG} tag triggers the Release workflow)."
  exit 0
fi

if ! git ls-remote --exit-code --heads origin "$BRANCH" >/dev/null; then
  echo "[finish-bhs] ❌ Branch ${BRANCH} does not exist on origin."
  exit 1
fi

echo "[finish-bhs] Opening the BHS closing PRs for ${BRANCH}..."

if [ "$(_pr_field "$BRANCH" main '.state // "NONE"')" = "OPEN" ]; then
  echo "  PR ${BRANCH} -> main already open."
else
  gh pr create -R "$REPO" \
    --head "$BRANCH" --base main \
    --title "release: ${VERSION}" \
    --body "Closes the BHS cycle of \`${BRANCH}\`: the release replaces \`main\`.

Merge with **Create a merge commit** (not squash/rebase). After the merge, \`./scripts/finish_bhs_cycle.sh ${VERSION} --cleanup\` creates the \`${TAG}\` tag (see CONTRIBUTING.md section 6)."
fi

# Moves the sync branch up to the release by fast-forward only: when it already
# holds conflict resolutions, they are not overwritten.
if ! git push --quiet origin "refs/remotes/origin/${BRANCH}:refs/heads/${SYNC_BRANCH}"; then
  echo "  ⚠️  ${SYNC_BRANCH} diverged from the release (conflicts resolved on it?)."
  echo "     Bring the new fixes with: git checkout ${SYNC_BRANCH} && git merge origin/${BRANCH}"
fi

if [ "$(_pr_field "$SYNC_BRANCH" develop '.state // "NONE"')" = "OPEN" ]; then
  echo "  PR ${SYNC_BRANCH} -> develop already open."
else
  gh pr create -R "$REPO" \
    --head "$SYNC_BRANCH" --base develop \
    --title "chore(release): carry ${BRANCH} fixes over to develop" \
    --body "Carries the fixes accumulated during the \`${BRANCH}\` BHS over to \`develop\`.

Resolve conflicts on this branch (\`${SYNC_BRANCH}\`), never on \`${BRANCH}\`: the release goes to \`main\` and must not take in \`develop\`."
fi

echo ""
echo "[finish-bhs] PRs opened. Once both are reviewed and merged, run:"
echo "  ./scripts/finish_bhs_cycle.sh ${VERSION} --cleanup"
