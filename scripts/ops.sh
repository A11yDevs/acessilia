#!/usr/bin/env bash
# ops.sh — Operations for the BHS cycle and the staging server
#
# The staging server runs from a clone of this repository: .env, var/ and
# docker-compose.staging.yml live in the clone, `git pull` (done by `track`)
# updates the scripts, and the containers run the images CI publishes on GHCR.
#
# Usage:
#   BHS, on a maintainer's machine (push access and an authenticated `gh`):
#     ./scripts/ops.sh bhs start <x.y.z>              cut release/x.y.z from develop
#     ./scripts/ops.sh bhs finish <x.y.z> [--cleanup] open the closing PRs / tag and clean up
#     ./scripts/ops.sh bhs status [<x.y.z>]           CI, image and PRs of the open releases
#
#   Staging server, in the clone:
#     ./scripts/ops.sh track [<branch>]               follow a branch (release/x.y.z or develop);
#                                                     without one, pull the tracked branch
#     ./scripts/ops.sh auto-update setup              start the stack and install the timer
#     ./scripts/ops.sh auto-update status             clone, timer, deployed image and health
#     ./scripts/ops.sh auto-update start              update now (what the timer runs)
#     ./scripts/ops.sh auto-update migrate <old dir>  move an /opt/.../staging install here
#
# First install on the server:
#   git clone https://github.com/A11yDevs/acessilia.git && cd acessilia
#   cp .env.example .env    # fill in the credentials
#   ./scripts/ops.sh auto-update setup

set -euo pipefail

REPO="A11yDevs/acessilia"
PACKAGE="acessilia"
IMAGE="ghcr.io/a11ydevs/acessilia"
TOOLBOX_REPO="${OPS_TOOLBOX_REPO:-https://github.com/A11yDevs/acessilia-toolbox.git}"
DEFAULT_BRANCH="develop"
COMPOSE_FILE="docker-compose.staging.yml"
COMPOSE_PROJECT="acessilia-staging"
CONTAINER_NAME="acessilia-staging"
HEALTH_URL="http://localhost:8000/api/v1/health"
UNIT="acessilia-staging-update"
# Unit installed by the former setup-homologacao.sh, replaced by $UNIT.
LEGACY_UNIT="staging-update"
LEGACY_DESCRIPTION="Update acessilia staging container"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT/.env"
STATUS_FILE="$ROOT/var/data/staging-status.json"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

cd "$ROOT"

_usage() {
  sed -n '8,21p' "$0" | sed 's/^# \{0,1\}//'
}

_die() {
  echo "[ops] ❌ $*" >&2
  exit 1
}

_info() {
  echo "[ops] $*"
}

_need() {
  local cmd
  for cmd in "$@"; do
    command -v "$cmd" >/dev/null 2>&1 || _die "$cmd not found."
  done
}

_check_version() {
  [[ "${1:-}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || _die "expected a version x.y.z (e.g. 0.2.0), got '${1:-}'."
}

# ──────────────────────────────────────────────
# .env helpers
# ──────────────────────────────────────────────
_env_get() {
  # $1 = key; prints the value of its last assignment in .env (unquoted)
  [ -f "$ENV_FILE" ] || return 0
  { grep -E "^$1=" "$ENV_FILE" || true; } | tail -1 | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//'
}

_env_set() {
  # $1 = key, $2 = value; an empty value removes the key. The file is
  # rewritten in place so its owner and mode are kept.
  local tmp
  tmp="$(mktemp)"
  { grep -vE "^$1=" "$ENV_FILE" || true; } > "$tmp"
  if [ -n "$2" ]; then
    echo "$1=$2" >> "$tmp"
  fi
  cat "$tmp" > "$ENV_FILE"
  rm -f "$tmp"
}

_require_env_file() {
  [ -f "$ENV_FILE" ] || _die "$ENV_FILE not found: create it with 'cp .env.example .env' and fill in the credentials."
}

_tracked_branch() {
  local branch
  branch="$(_env_get TRACK_BRANCH)"
  echo "${branch:-$DEFAULT_BRANCH}"
}

_pr_field() {
  # $1 = head, $2 = base, $3 = jq expression over the most recent PR
  gh pr list -R "$REPO" --head "$1" --base "$2" --state all \
    --json number,state,mergeCommit --jq ".[0] | $3"
}

# ──────────────────────────────────────────────
# bhs start
# ──────────────────────────────────────────────
# Forks release/<version> from origin/develop and commits the version bump on
# it in a temporary worktree, so the current checkout is left untouched. Cut
# the Toolbox first: CI checks a release branch against the capability
# contract of the Toolbox release of the same version.
_bhs_start() {
  local version="${1:-}" branch worktree
  _check_version "$version"
  _need git python3
  branch="release/${version}"

  _info "Fetching origin..."
  git fetch origin --quiet

  if git ls-remote --exit-code --heads origin "$branch" >/dev/null; then
    _die "branch ${branch} already exists on origin."
  fi
  if git ls-remote --exit-code --tags origin "v${version}" >/dev/null; then
    _die "tag v${version} already exists: ${version} has been released."
  fi
  if ! git ls-remote --exit-code --heads "$TOOLBOX_REPO" "$branch" >/dev/null; then
    _info "⚠️  The Toolbox has no ${branch} yet: the release CI fails its contract"
    _info "    check until the Toolbox is cut too."
  fi

  worktree="$(mktemp -d "${TMPDIR:-/tmp}/bhs-worktree.XXXXXX")"
  # rm -rf covers a failed `git worktree add`: git does not know the directory
  # then, and `worktree remove` leaves it behind; prune drops the registration.
  # shellcheck disable=SC2064
  trap "git worktree remove --force '$worktree' >/dev/null 2>&1 || true; rm -rf '$worktree'; git worktree prune" EXIT
  git worktree add --quiet --detach "$worktree" origin/develop

  _info "Bumping ${PACKAGE} to ${version}..."
  python3 - "$worktree" "$PACKAGE" "$version" <<'EOF'
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

  if ! git -C "$worktree" diff --quiet; then
    git -C "$worktree" commit --quiet -am "chore(release): bump to ${version}"
  fi

  _info "Publishing ${branch} (forked from origin/develop)..."
  git -C "$worktree" push --quiet origin "HEAD:refs/heads/${branch}"

  echo ""
  _info "✅ BHS cycle started: ${branch}"
  echo ""
  echo "Next steps:"
  echo "  1. On the staging server, in the clone: ./scripts/ops.sh track ${branch}"
  echo "  2. fix/* PRs that fix bugs found in staging target ${branch}."
  echo "  3. feat/*, refactor/* and other PRs keep targeting develop."
  echo "  4. When the cycle ends: ./scripts/ops.sh bhs finish ${version}"
}

# ──────────────────────────────────────────────
# bhs finish
# ──────────────────────────────────────────────
# The release replaces main: release/x.y.z -> main must be merged with "Create
# a merge commit". Fixes reach develop through chore/sync-release-x.y.z, forked
# from the release, so conflicts are resolved there without bringing develop
# into the release. Running it again carries later fixes over to the sync
# branch. Close the Toolbox first: CI on main checks the contract published on
# the Toolbox's main.
_bhs_finish() {
  local version="${1:-}" mode="${2:-open}" branch sync_branch tag merge_sha parents
  _check_version "$version"
  [[ "$mode" =~ ^(open|--cleanup)$ ]] || _die "unknown option '$mode' (expected --cleanup)."
  _need git gh
  branch="release/${version}"
  sync_branch="chore/sync-release-${version}"
  tag="v${version}"

  git fetch origin --quiet --prune

  if [ "$mode" = "--cleanup" ]; then
    _info "Checking the PRs of ${branch}..."
    local main_state develop_state
    main_state=$(_pr_field "$branch" main '.state // "NONE"')
    develop_state=$(_pr_field "$sync_branch" develop '.state // "NONE"')
    echo "  main:    ${main_state}"
    echo "  develop: ${develop_state}"

    if [ "$main_state" != "MERGED" ] || [ "$develop_state" != "MERGED" ]; then
      _die "PR(s) still pending. Wait for approval/merge before cleaning up."
    fi

    merge_sha=$(_pr_field "$branch" main '.mergeCommit.oid')
    parents=$(gh api "repos/$REPO/commits/$merge_sha" --jq '.parents | length')
    if [ "$parents" != "2" ]; then
      _die "${branch} reached main without a merge commit (squash/rebase); tag and delete the branch yourself after checking main."
    fi

    if git ls-remote --exit-code --tags origin "$tag" >/dev/null; then
      _info "Tag ${tag} already exists on origin."
    else
      _info "Tagging ${tag} at ${merge_sha:0:7} (merge of the release into main)..."
      git fetch origin --quiet main
      git tag "$tag" "$merge_sha"
      git push origin "$tag"
    fi

    _info "✅ Both PRs merged. Deleting ${branch} and ${sync_branch}..."
    git push origin --delete "$branch" || echo "  (remote branch ${branch} already deleted)"
    git push origin --delete "$sync_branch" || echo "  (remote branch ${sync_branch} already deleted)"
    git branch -D "$branch" 2>/dev/null || true

    echo ""
    echo "Last manual steps:"
    echo "  1. On the staging server, in the clone: ./scripts/ops.sh track ${DEFAULT_BRANCH}"
    echo "  2. Promote production as described in docs/producao-systemd.md (the ${tag} tag triggers the Release workflow)."
    return 0
  fi

  if ! git ls-remote --exit-code --heads origin "$branch" >/dev/null; then
    _die "branch ${branch} does not exist on origin."
  fi

  _info "Opening the BHS closing PRs for ${branch}..."

  if [ "$(_pr_field "$branch" main '.state // "NONE"')" = "OPEN" ]; then
    echo "  PR ${branch} -> main already open."
  else
    gh pr create -R "$REPO" \
      --head "$branch" --base main \
      --title "release: ${version}" \
      --body "Closes the BHS cycle of \`${branch}\`: the release replaces \`main\`.

Merge with **Create a merge commit** (not squash/rebase). After the merge, \`./scripts/ops.sh bhs finish ${version} --cleanup\` creates the \`${tag}\` tag (see CONTRIBUTING.md section 6)."
  fi

  # Moves the sync branch up to the release by fast-forward only: when it
  # already holds conflict resolutions, they are not overwritten.
  if ! git push --quiet origin "refs/remotes/origin/${branch}:refs/heads/${sync_branch}"; then
    echo "  ⚠️  ${sync_branch} diverged from the release (conflicts resolved on it?)."
    echo "     Bring the new fixes with: git checkout ${sync_branch} && git merge origin/${branch}"
  fi

  if [ "$(_pr_field "$sync_branch" develop '.state // "NONE"')" = "OPEN" ]; then
    echo "  PR ${sync_branch} -> develop already open."
  else
    gh pr create -R "$REPO" \
      --head "$sync_branch" --base develop \
      --title "chore(release): carry ${branch} fixes over to develop" \
      --body "Carries the fixes accumulated during the \`${branch}\` BHS over to \`develop\`.

Resolve conflicts on this branch (\`${sync_branch}\`), never on \`${branch}\`: the release goes to \`main\` and must not take in \`develop\`."
  fi

  echo ""
  _info "PRs opened. Once both are reviewed and merged, run:"
  echo "  ./scripts/ops.sh bhs finish ${version} --cleanup"
}

# ──────────────────────────────────────────────
# bhs status
# ──────────────────────────────────────────────
_bhs_status() {
  local branches branch sha version
  _need git gh
  git fetch origin --quiet --prune

  if [ -n "${1:-}" ]; then
    _check_version "$1"
    branches="release/$1"
  else
    branches=$(git ls-remote --heads origin 'release/*' | sed 's|.*refs/heads/||')
  fi
  if [ -z "$branches" ]; then
    _info "No open release branch."
    return 0
  fi

  for branch in $branches; do
    sha=$(git ls-remote --heads origin "$branch" | cut -f1)
    if [ -z "$sha" ]; then
      echo "## ${branch}: does not exist on origin"
      continue
    fi
    version="${branch#release/}"
    echo "## ${branch} @ ${sha:0:7}"
    echo "  Workflows on this commit:"
    gh run list -R "$REPO" --branch "$branch" --commit "$sha" \
      --json workflowName,status,conclusion \
      --jq 'if length == 0 then "    (none yet)" else .[] | "    \(.workflowName): \(.status) \(.conclusion)" end'
    if command -v docker >/dev/null 2>&1; then
      if docker manifest inspect "${IMAGE}:sha-${sha:0:7}" >/dev/null 2>&1; then
        echo "  Image: ${IMAGE}:sha-${sha:0:7} published"
      else
        echo "  Image: ${IMAGE}:sha-${sha:0:7} not published yet"
      fi
    fi
    echo "  Open PRs into ${branch}:"
    gh pr list -R "$REPO" --base "$branch" --state open \
      --json number,title,headRefName \
      --jq 'if length == 0 then "    (none)" else .[] | "    #\(.number) \(.headRefName): \(.title)" end'
    echo "  Closing PRs: main $(_pr_field "$branch" main '.state // "NONE"'), develop $(_pr_field "chore/sync-release-${version}" develop '.state // "NONE"')"
  done
}

# ──────────────────────────────────────────────
# track
# ──────────────────────────────────────────────
# The clone's branch and TRACK_BRANCH must move together: the scripts and the
# compose file come from the clone, the image from TRACK_BRANCH. TRACK_TAG is
# written too, so a plain `docker compose` in the clone uses the same image.
_track_checkout() {
  local branch="$1"
  _require_env_file
  if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    _die "the clone has local changes to tracked files; commit, stash or discard them first."
  fi
  git fetch origin --quiet --prune
  git ls-remote --exit-code --heads origin "$branch" >/dev/null \
    || _die "branch ${branch} does not exist on origin."
  # The timer runs scripts/ops.sh from the clone; a branch without it (develop
  # before the release is carried over) would leave the timer broken.
  git cat-file -e "origin/${branch}:scripts/ops.sh" 2>/dev/null \
    || _die "origin/${branch} has no scripts/ops.sh yet (merge the release's sync PR into it first)."
  git checkout --quiet "$branch"
  git pull --quiet --ff-only

  if [ "$branch" = "$DEFAULT_BRANCH" ]; then
    _env_set TRACK_BRANCH ""
    _env_set TRACK_TAG ""
  else
    _env_set TRACK_BRANCH "$branch"
    _env_set TRACK_TAG "${branch//\//-}"
  fi
  _info "Clone on ${branch} ($(git rev-parse --short HEAD)); staging tracks ${branch}."
}

_track() {
  # Without a branch, pulls the one already tracked (updates the scripts).
  local branch="${1:-}"
  _require_env_file
  _track_checkout "${branch:-$(_tracked_branch)}"
  # A new process: the pull above may have updated this script.
  "$ROOT/scripts/ops.sh" auto-update start
}

# ──────────────────────────────────────────────
# auto-update
# ──────────────────────────────────────────────
_auto_update_start() {
  local head tracked
  _require_env_file
  head="$(git rev-parse --abbrev-ref HEAD)"
  tracked="$(_tracked_branch)"
  if [ "$head" != "$tracked" ]; then
    _info "⚠️  The clone is on ${head} but staging tracks ${tracked}: run ./scripts/ops.sh track ${tracked}"
  fi
  unset DEPLOY_DIR
  export STAGING_DIR="$ROOT"
  exec "$ROOT/scripts/staging-update.sh"
}

_disable_legacy_unit() {
  local service="$UNIT_DIR/${LEGACY_UNIT}.service"
  [ -f "$service" ] && grep -qx "Description=${LEGACY_DESCRIPTION}" "$service" || return 0
  _info "Removing the ${LEGACY_UNIT} timer installed by the former setup-homologacao.sh..."
  systemctl --user disable --now "${LEGACY_UNIT}.timer" >/dev/null 2>&1 || true
  rm -f "$service" "$UNIT_DIR/${LEGACY_UNIT}.timer"
}

_auto_update_setup() {
  local tracked
  _need docker jq git curl systemctl
  docker compose version >/dev/null 2>&1 || _die "Docker Compose not found."
  _require_env_file

  # A fixed project name keeps the containers and volumes independent of the
  # clone's directory name.
  if [ -z "$(_env_get COMPOSE_PROJECT_NAME)" ]; then
    _env_set COMPOSE_PROJECT_NAME "$COMPOSE_PROJECT"
  fi
  chmod 600 "$ENV_FILE"

  if ! grep -q 'ghcr.io' ~/.docker/config.json 2>/dev/null; then
    _info "⚠️  Not logged in to ghcr.io; if pulls fail, run:"
    echo "     echo <token> | docker login ghcr.io -u <github-user> --password-stdin"
  fi

  # User timer prerequisites: linger (the timer survives logout) and the
  # docker group (the timer reaches the daemon).
  if ! loginctl show-user "$USER" 2>/dev/null | grep -q 'Linger=yes'; then
    _info "Enabling linger for $USER..."
    sudo loginctl enable-linger "$USER"
  fi
  if ! id -nG | tr ' ' '\n' | grep -qx docker; then
    _info "Adding $USER to the docker group (log out and back in for it to apply)..."
    sudo usermod -aG docker "$USER"
  fi

  _disable_legacy_unit

  tracked="$(_tracked_branch)"
  _info "Starting the stack (${tracked})..."
  export TRACK_TAG="${tracked//\//-}"
  docker compose -f "$COMPOSE_FILE" pull
  docker compose -f "$COMPOSE_FILE" up -d

  mkdir -p "$UNIT_DIR"
  cat > "$UNIT_DIR/${UNIT}.service" <<SERVICE
[Unit]
Description=Update ${COMPOSE_PROJECT} from GHCR

[Service]
Type=oneshot
ExecStart=${ROOT}/scripts/ops.sh auto-update start
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
SERVICE

  cat > "$UNIT_DIR/${UNIT}.timer" <<TIMER
[Unit]
Description=Check ${COMPOSE_PROJECT} updates every 5 minutes

[Timer]
OnBootSec=30s
OnUnitActiveSec=300s

[Install]
WantedBy=timers.target
TIMER

  systemctl --user daemon-reload
  systemctl --user enable --now "${UNIT}.timer"

  echo ""
  _info "✅ Auto-update installed: ${UNIT}.timer checks ${tracked} every 5 minutes."
  echo "  Status: ./scripts/ops.sh auto-update status"
}

_auto_update_status() {
  local head tracked behind
  head="$(git rev-parse --abbrev-ref HEAD)"
  tracked="$(_tracked_branch)"

  echo "Clone:     ${ROOT}"
  echo "Branch:    ${head} @ $(git rev-parse --short HEAD)"
  if git fetch origin --quiet "$head" 2>/dev/null; then
    behind="$(git rev-list --count "HEAD..origin/${head}")"
    if [ "$behind" != "0" ]; then
      echo "           ${behind} commit(s) behind origin/${head}: run ./scripts/ops.sh track ${tracked}"
    fi
  fi
  echo "Tracks:    ${tracked}"
  if [ "$head" != "$tracked" ]; then
    echo "           ⚠️  differs from the clone's branch: run ./scripts/ops.sh track ${tracked}"
  fi

  echo ""
  echo "Timer:     $(systemctl --user is-active "${UNIT}.timer" 2>/dev/null || true)"
  systemctl --user show "${UNIT}.service" -p Result -p ExecMainExitTimestamp 2>/dev/null \
    | sed 's/^/           /' || true

  echo ""
  echo "Last check (${STATUS_FILE#"$ROOT"/}):"
  if [ -f "$STATUS_FILE" ]; then
    jq . "$STATUS_FILE" | sed 's/^/  /'
  else
    echo "  (none yet)"
  fi

  echo ""
  echo "Health (${HEALTH_URL}):"
  curl -fsS --max-time 5 "$HEALTH_URL" 2>/dev/null \
    | jq 'with_entries(select(.key | IN("status", "image_tag", "git_commit", "up_to_date", "update_available")))' 2>/dev/null \
    | sed 's/^/  /' || echo "  (unreachable)"

  echo ""
  echo "Recent runs:"
  journalctl --user -u "${UNIT}.service" -n 10 --no-pager -o cat 2>/dev/null | sed 's/^/  /' || true
}

_read_old_env() {
  # $1 = old staging dir; its .env is often root-owned with mode 600
  if [ -r "$1/.env" ]; then
    cat "$1/.env"
  else
    sudo cat "$1/.env"
  fi
}

# Moves an install made by the former setup-homologacao.sh (scripts copied to
# /opt/.../scripts, .env and var/ in /opt/.../staging) into this clone. The
# old directory is left untouched.
_auto_update_migrate() {
  local old="${1:-}" project
  [ -n "$old" ] && [ -d "$old" ] || _die "usage: $0 auto-update migrate <old staging dir>   (e.g. /opt/acessilia/staging)"
  old="$(cd "$old" && pwd)"
  [ "$old" != "$ROOT" ] || _die "$old is this clone."

  if [ -f "$ENV_FILE" ]; then
    if ! _read_old_env "$old" | cmp -s - "$ENV_FILE"; then
      _die "$ENV_FILE already exists and differs from $old/.env; keep the one you want and run again."
    fi
  else
    _info "Copying $old/.env..."
    _read_old_env "$old" > "$ENV_FILE" || { rm -f "$ENV_FILE"; _die "cannot read $old/.env"; }
    chmod 600 "$ENV_FILE"
  fi

  # Keeping the old compose project name lets compose take over the running
  # containers and their named volumes instead of creating new ones.
  project=$(docker inspect "$CONTAINER_NAME" \
    --format '{{ index .Config.Labels "com.docker.compose.project" }}' 2>/dev/null || true)
  if [ -n "$project" ] && [ -z "$(_env_get COMPOSE_PROJECT_NAME)" ]; then
    _info "Keeping the compose project name '${project}'."
    _env_set COMPOSE_PROJECT_NAME "$project"
  fi

  _disable_legacy_unit

  if [ -d "$old/var" ]; then
    _info "Copying $old/var (the container is stopped meanwhile)..."
    docker stop "$CONTAINER_NAME" >/dev/null 2>&1 || true
    mkdir -p "$ROOT/var"
    cp -a "$old/var/." "$ROOT/var/" 2>/dev/null || sudo cp -a "$old/var/." "$ROOT/var/"
  fi

  _track_checkout "$(_tracked_branch)"
  _auto_update_setup

  echo ""
  _info "✅ Migrated from ${old}, which was left untouched. Remove it after checking staging."
}

case "${1:-help}" in
  bhs)
    case "${2:-}" in
      start) _bhs_start "${3:-}" ;;
      finish) _bhs_finish "${3:-}" "${4:-open}" ;;
      status) _bhs_status "${3:-}" ;;
      *) _usage; exit 1 ;;
    esac
    ;;
  track) _track "${2:-}" ;;
  auto-update)
    case "${2:-}" in
      setup) _auto_update_setup ;;
      status) _auto_update_status ;;
      start) _auto_update_start ;;
      migrate) _auto_update_migrate "${3:-}" ;;
      *) _usage; exit 1 ;;
    esac
    ;;
  help | -h | --help) _usage ;;
  *) _usage; exit 1 ;;
esac
