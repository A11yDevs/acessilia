#!/usr/bin/env bash
# staging-update.sh — Updates the staging container from GHCR via the GitHub API
#
# Reads the SHA of the latest commit on the tracked branch from the GitHub API
# and updates only once the matching image (sha-<7> tag) HAS BEEN PUBLISHED on
# GHCR, so staging never moves to a commit whose build is running or failed.
#
# On the staging server it runs from the clone through scripts/ops.sh
# (`auto-update start`, which the timer installed by `auto-update setup`
# calls); production-update.sh reuses it with production defaults.
#
# Prerequisites: Docker + Docker Compose, jq, and a .env in the deployment
# directory (GHCR_TOKEN raises the GitHub API rate limit).
#
# Tracked branch (Bug Hunting/Squashing):
#   "develop" by default. During BHS `ops.sh track release/x.y.z` sets
#   TRACK_BRANCH in .env; `ops.sh track develop` removes it again.
#
# Parameters for other environments:
#   DEPLOY_DIR=/opt/acessilia/production
#   COMPOSE_FILE=docker-compose.production.yml
#   CONTAINER_NAME=acessilia-production
#   DEPLOY_ENV=production
#   DEFAULT_TRACK_BRANCH=main

set -euo pipefail

# ──────────────────────────────────────────────
# Detectar o diretório do staging (onde ficam .env e docker-compose.staging.yml)
# ──────────────────────────────────────────────
# Layouts suportados:
#   A) Servidor de homologacao: /opt/acessilia/staging/  (STAGING_DIR ou deteccao)
#   B) Repositorio clonado: <repo>/scripts/staging-update.sh -> <repo>/
# Prioridade: 1. STAGING_DIR (env)  2. /opt/acessilia/staging  3. pai do script
if [ -n "${DEPLOY_DIR:-}" ]; then
  STAGING_DIR="$DEPLOY_DIR"
elif [ -n "${STAGING_DIR:-}" ]; then
  STAGING_DIR="$STAGING_DIR"
elif [ -d /opt/acessilia/staging ]; then
  STAGING_DIR="/opt/acessilia/staging"
else
  STAGING_DIR="$(cd "$(dirname "$0")/.." && pwd)"
fi
cd "$STAGING_DIR"

DEPLOY_ENV="${DEPLOY_ENV:-staging}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.staging.yml}"
CONTAINER_NAME="${CONTAINER_NAME:-acessilia-staging}"
COMPOSE_ARGS=(-f "$COMPOSE_FILE")
if [ "$DEPLOY_ENV" = production ]; then
  if [ ! -f "$STAGING_DIR/.deploy.env" ]; then
    echo "Production requires .deploy.env separate from runtime .env; keep the timer disabled." >&2
    exit 1
  fi
  COMPOSE_ARGS=(-p production --env-file "$STAGING_DIR/.deploy.env" -f "$COMPOSE_FILE")
fi
GITHUB_REPO="A11yDevs/acessilia"
# Cache e status ficam dentro do volume ./var (visivel ao container via /app/var)
CACHE_FILE="${STAGING_UPDATE_CACHE:-$STAGING_DIR/var/data/.last_sha}"
STATUS_FILE="${STAGING_STATUS_FILE:-$STAGING_DIR/var/data/$DEPLOY_ENV-status.json}"

# ──────────────────────────────────────────────
# Helpers de status
# ──────────────────────────────────────────────
_write_status() {
  # $1 = latest_sha, $2 = running_sha, $3 = last_update (ISO) ou vazio
  # $4 = latest_digest, $5 = running_digest
  local latest_sha="$1" running_sha="$2" last_update="$3"
  local latest_digest="${4:-}" running_digest="${5:-}"
  local now
  now=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  mkdir -p "$(dirname "$STATUS_FILE")"
  jq -n \
    --arg latest "$latest_sha" \
    --arg running "$running_sha" \
    --arg check "$now" \
    --arg update "$last_update" \
    --arg latest_digest "$latest_digest" \
    --arg running_digest "$running_digest" \
    '{latest_sha: $latest, running_sha: $running, last_check: $check, last_update: $update, latest_digest: $latest_digest, running_digest: $running_digest}' \
    > "$STATUS_FILE"
}

_image_digest() {
  # Manifest digest of a locally cached image reference (empty when absent).
  docker image inspect "$1" --format '{{.RepoDigests}}' 2>/dev/null \
    | grep -oE 'sha256:[a-f0-9]{64}' | head -1 || true
}

_registry_digest() {
  # Manifest digest published for a tag, resolved without pulling so the
  # comparison also works when there is nothing to update.
  docker manifest inspect --verbose "$1" 2>/dev/null \
    | jq -r 'if type == "array" then .[0].Descriptor.digest else .Descriptor.digest end' 2>/dev/null \
    || true
}

#: Attempts per pull. GHCR can answer the manifest request and still fail the
#: tag pull with a transient 5xx, a rate limit or a token refresh; retrying
#: keeps one bad response from leaving staging behind for a whole interval.
PULL_ATTEMPTS="${PULL_ATTEMPTS:-3}"
PULL_RETRY_DELAY="${PULL_RETRY_DELAY:-5}"

_pull_image() {
  # $1 = image reference. The Docker error goes to the journal, where the
  # systemd failure is read; suppressing it left only "Falha ao puxar" and no
  # cause. A successful pull keeps its progress on stdout, as before.
  local ref="$1" attempt output
  for ((attempt = 1; attempt <= PULL_ATTEMPTS; attempt++)); do
    if output=$(docker pull "$ref" 2>&1); then
      printf '%s\n' "$output"
      return 0
    fi
    echo "[staging-update] ⚠️  Falha ao puxar $ref (tentativa $attempt/$PULL_ATTEMPTS)." >&2
    printf '%s\n' "$output" >&2
    if [ "$attempt" -lt "$PULL_ATTEMPTS" ]; then
      sleep "$PULL_RETRY_DELAY"
    fi
  done
  return 1
}

_start_container() {
  if [ "$DEPLOY_ENV" = production ]; then
    local helper
    helper="$(cd "$(dirname "$0")" && pwd)/production_deploy.py"
    python3 "$helper" check --directory "$STAGING_DIR" --require-data
    PREVIOUS_PRODUCTION_IMAGE=$(docker inspect "$CONTAINER_NAME" --format '{{.Image}}' 2>/dev/null || true)
    if ! docker compose "${COMPOSE_ARGS[@]}" up -d --no-deps --wait \
      --wait-timeout "${PRODUCTION_WAIT_TIMEOUT:-120}" acessilia; then
      _production_activation_failed
      return 1
    fi
    if ! python3 "$helper" verify-running --image "$PRODUCTION_IMAGE" --container "$CONTAINER_NAME"; then
      _production_activation_failed
      return 1
    fi
  else
    docker compose "${COMPOSE_ARGS[@]}" up -d --no-deps acessilia
  fi
}

_production_activation_failed() {
  echo "Production activation/verification failed; the new image may already be serving traffic." >&2
  echo "Stop the production timer, inspect the running container and perform manual rollback if required." >&2
  echo "Previous image ID: ${PREVIOUS_PRODUCTION_IMAGE:-unavailable}. No automatic rollback was performed." >&2
}

_production_already_current() {
  # A cached commit alone cannot detect a manual image change or stopped container.
  local accepted_digest running_id running_digest last_update
  accepted_digest=$(jq -er --arg sha "$LATEST_SHA" \
    'select(.running_sha == $sha) | .running_digest // empty' "$STATUS_FILE" 2>/dev/null) || return 1
  [[ "$accepted_digest" =~ ^sha256:[a-f0-9]{64}$ ]] || return 1
  [ "$(docker inspect "$CONTAINER_NAME" --format '{{.State.Running}}' 2>/dev/null)" = true ] || return 1
  running_id=$(docker inspect "$CONTAINER_NAME" --format '{{.Image}}' 2>/dev/null) || return 1
  [ -n "$running_id" ] || return 1
  running_digest=$(_image_digest "$running_id")
  [ "$running_digest" = "$accepted_digest" ] || return 1
  last_update=$(jq -r '.last_update // ""' "$STATUS_FILE" 2>/dev/null) || return 1
  _write_status "$LATEST_SHA" "$LATEST_SHA" "$last_update" "$accepted_digest" "$running_digest" || exit 1
  echo "Production already runs the accepted commit/digest; no deployment or dependency probe needed."
}

# Digests for the status file. /api/v1/health compares the published digest
# against the running one to decide `update_available`/`up_to_date`, so both
# have to be written on every check, not only when an update happens.
_collect_digests() {
  # $1 = tag published for the tracked branch, $2 = sha-tagged reference
  local track_ref="$1" sha_ref="$2"
  # Prefer the local images: `docker image inspect` reports the manifest-list
  # digest compose runs, while `docker manifest inspect --verbose` reports the
  # platform manifest digest. Mixing the two made /health believe the published
  # and running images differed and report `update_available` forever.
  LATEST_DIGEST=$(_image_digest "$sha_ref")
  if [ -z "$LATEST_DIGEST" ]; then
    LATEST_DIGEST=$(_image_digest "$track_ref")
  fi
  RUNNING_DIGEST=$(_image_digest "$track_ref")
  if [ -z "$RUNNING_DIGEST" ]; then
    RUNNING_DIGEST=$(_image_digest "$sha_ref")
  fi
  if [ -z "$LATEST_DIGEST" ]; then
    # No local copy: the registry digest is the only evidence left, and the
    # health check will stay "unknown" until a pull records the local one.
    LATEST_DIGEST=$(_registry_digest "$sha_ref")
  fi
}

# ──────────────────────────────────────────────
# 0. Carregar configuracoes do .env
# ──────────────────────────────────────────────
# Fontes possiveis, em ordem:
#   1. Variaveis de ambiente ja exportadas
#   2. Arquivo <STAGING_DIR>/.env
#   3. Arquivo /opt/acessilia/scripts/.env (layout antigo)
ENV_GHCR_TOKEN="${GHCR_TOKEN:-}"
ENV_TRACK_BRANCH="${TRACK_BRANCH:-}"
ENV_PRODUCTION_IMAGE="${PRODUCTION_IMAGE:-}"

ENV_FILES=("$STAGING_DIR/.env" /opt/acessilia/scripts/.env)
if [ "$DEPLOY_ENV" = production ]; then
  ENV_FILES=("$STAGING_DIR/.deploy.env")
fi
for env_file in "${ENV_FILES[@]}"; do
  if [ -f "$env_file" ]; then
    set -a
    # shellcheck disable=SC1090
    source "$env_file"
    set +a
    break
  fi
done

if [ -n "$ENV_GHCR_TOKEN" ]; then
  GHCR_TOKEN="$ENV_GHCR_TOKEN"
fi

if [ -n "$ENV_TRACK_BRANCH" ]; then
  TRACK_BRANCH="$ENV_TRACK_BRANCH"
fi
if [ -n "$ENV_PRODUCTION_IMAGE" ]; then
  PRODUCTION_IMAGE="$ENV_PRODUCTION_IMAGE"
fi

# Branch/tag rastreada: DEFAULT_TRACK_BRANCH por padrao, ou TRACK_BRANCH
# (env ou .env) durante o ciclo de BHS (ex: release/0.0.1)
DEFAULT_TRACK_BRANCH="${DEFAULT_TRACK_BRANCH:-develop}"
GITHUB_BRANCH="${TRACK_BRANCH:-$DEFAULT_TRACK_BRANCH}"
# Docker tags nao aceitam "/" (ex: release/0.0.1 -> release-0.0.1)
TRACK_TAG="${GITHUB_BRANCH//\//-}"
IMAGE_TAG="ghcr.io/a11ydevs/acessilia:${TRACK_TAG}"
export TRACK_TAG

if [ "$DEPLOY_ENV" = production ]; then
  if [ -n "${PRODUCTION_IMAGE:-}" ]; then
    echo "Production image is pinned for manual promotion; keep the updater disabled." >&2
    exit 1
  fi
  CONFIGURED_IMAGE=$(docker compose "${COMPOSE_ARGS[@]}" config --format json | jq -r '.services.acessilia.image')
  if [ "$CONFIGURED_IMAGE" != "$IMAGE_TAG" ]; then
    echo "Compose selects a custom production image; refusing a branch-tag update." >&2
    exit 1
  fi
fi

# ──────────────────────────────────────────────
# 1. Checar SHA do último commit via GitHub API
# ──────────────────────────────────────────────
# O repositorio e publico: a API funciona sem token (rate limit 60/h).
# Com token, o limite sobe para 5000/h.
AUTH_HEADER=()
if [ -n "${GHCR_TOKEN:-}" ]; then
  AUTH_HEADER=(-H "Authorization: token $GHCR_TOKEN")
fi

if ! LATEST_SHA=$(curl -fsS \
  "${AUTH_HEADER[@]}" \
  "https://api.github.com/repos/$GITHUB_REPO/commits/$GITHUB_BRANCH" \
  | jq -r '.sha'); then
  LATEST_SHA=""
fi
LATEST_DIGEST=""

# Se não conseguiu obter o SHA, faz pull direto (fallback seguro)
if [ -z "$LATEST_SHA" ] || [ "$LATEST_SHA" = "null" ]; then
  if [ "$DEPLOY_ENV" = production ]; then
    echo "Cannot resolve the production commit; refusing an unverified tag fallback." >&2
    exit 1
  fi
  echo "[staging-update] ⚠️  Falha ao consultar GitHub API. Fazendo pull direto..."
  _pull_image "$IMAGE_TAG" || {
    echo "[staging-update] ❌ Falha ao puxar $IMAGE_TAG"
    exit 1
  }
  _start_container
  docker image prune -f
  _write_status "" "" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "" ""
  echo "[staging-update] Container atualizado (fallback)."
  exit 0
fi

# Compare with the branch and SHA of the last execution. The branch is part of
# the key because a newly tracked branch (e.g. the BHS cut) can point at the
# same commit: comparing only the SHA kept the container on the previous
# branch's image until the next commit.
CACHE_KEY="$GITHUB_BRANCH $LATEST_SHA"
if [ -f "$CACHE_FILE" ]; then
  CACHED_KEY=$(cat "$CACHE_FILE")
  if [ "$CACHED_KEY" = "$CACHE_KEY" ] && [ "$DEPLOY_ENV" = production ] && _production_already_current; then
    exit 0
  fi
  if [ "$CACHED_KEY" = "$CACHE_KEY" ] && [ "$DEPLOY_ENV" != production ]; then
    # Record the running and published digests even when there is nothing to
    # update: /api/v1/health derives `up_to_date` from them, and leaving them
    # empty made the check structurally unable to report "up to date".
    _collect_digests "$IMAGE_TAG" "ghcr.io/a11ydevs/acessilia:sha-${LATEST_SHA:0:7}"
    _write_status "$LATEST_SHA" "$LATEST_SHA" "" "$LATEST_DIGEST" "$RUNNING_DIGEST"
    echo "[staging-update] ✅ Nenhum commit novo em $GITHUB_REPO/$GITHUB_BRANCH. Pulando."
    exit 0
  fi
fi

# ──────────────────────────────────────────────
# 2. Confirmar que a imagem do commit já está no GHCR
# ──────────────────────────────────────────────
SHA7="${LATEST_SHA:0:7}"
SHA_TAG="ghcr.io/a11ydevs/acessilia:sha-$SHA7"

if docker manifest inspect "$SHA_TAG" >/dev/null 2>&1; then
  echo "[staging-update] ✅ Imagem sha-$SHA7 já publicada no GHCR."
else
  _write_status "$LATEST_SHA" "" "" "" ""
  echo "[staging-update] ⏳ Imagem sha-$SHA7 ainda não publicada no GHCR (build em andamento?). Aguardando próxima checagem."
  exit 0
fi

# ──────────────────────────────────────────────
# 3. SHA mudou e imagem publicada → atualizar
# ──────────────────────────────────────────────
echo "[staging-update] 🔄 Novo commit detectado: $SHA7. Atualizando..."

# Production pulls the verified commit artifact, not a branch tag that can move.
if [ "$DEPLOY_ENV" = production ]; then
  IMAGE_TAG="$SHA_TAG"
fi

# One pull is enough: the sha tag above only proves the build for this commit
# finished, and the delivery workflow publishes it together with the branch tag
# that compose uses. Pulling both sent the same manifest to the registry twice;
# when the second pull failed, the script aborted even though the image it
# needed was already local.
_pull_image "$IMAGE_TAG" || {
  echo "[staging-update] ❌ Falha ao puxar $IMAGE_TAG"
  exit 1
}

# The pulled branch image is the one compose starts, so its digest is both the
# published and the running digest. The registry lookup is a fallback for a
# Docker that does not record RepoDigests.
LATEST_DIGEST=$(_image_digest "$IMAGE_TAG")
if [ -z "$LATEST_DIGEST" ]; then
  LATEST_DIGEST=$(_registry_digest "$SHA_TAG")
fi
if [ "$DEPLOY_ENV" = production ]; then
  IMAGE_REVISION=$(docker image inspect "$IMAGE_TAG" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')
  if [ "$IMAGE_REVISION" != "$LATEST_SHA" ] || [[ ! "$LATEST_DIGEST" =~ ^sha256:[a-f0-9]{64}$ ]]; then
    echo "Published production image does not identify the requested commit/digest." >&2
    exit 1
  fi
  export PRODUCTION_IMAGE="ghcr.io/a11ydevs/acessilia@$LATEST_DIGEST"
fi

echo "[staging-update] 🚀 Reiniciando container..."
_start_container
if [ "$DEPLOY_ENV" = production ]; then
  RUNNING_ID=$(docker inspect "$CONTAINER_NAME" --format '{{.Image}}')
  RUNNING_DIGEST=$(_image_digest "$RUNNING_ID")
  if [ "$RUNNING_DIGEST" != "$LATEST_DIGEST" ]; then
    echo "Running production digest differs; deployment was not accepted." >&2
    _production_activation_failed
    exit 1
  fi
else
  RUNNING_DIGEST="$LATEST_DIGEST"
fi

# so grava o cache apos o restart ter sucesso (set -e aborta antes em caso de falha)
echo "$CACHE_KEY" > "$CACHE_FILE"

if [ "$DEPLOY_ENV" != production ]; then
  docker image prune -f
fi

_write_status "$LATEST_SHA" "$LATEST_SHA" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$LATEST_DIGEST" "$RUNNING_DIGEST"

echo "[staging-update] ✅ Container $CONTAINER_NAME atualizado com sucesso."
