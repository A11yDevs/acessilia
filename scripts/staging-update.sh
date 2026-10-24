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
PULL_ATTEMPTS=3
PULL_RETRY_DELAY="${PULL_RETRY_DELAY:-5}"

_pull_image() {
  # $1 = image reference. The Docker error goes to the journal, where the
  # systemd failure is read; suppressing it left only "Falha ao puxar" and no
  # cause.
  local ref="$1" attempt output
  for ((attempt = 1; attempt <= PULL_ATTEMPTS; attempt++)); do
    if output=$(docker pull "$ref" 2>&1); then
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

for env_file in "$STAGING_DIR/.env" /opt/acessilia/scripts/.env; do
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

# Branch/tag rastreada: DEFAULT_TRACK_BRANCH por padrao, ou TRACK_BRANCH
# (env ou .env) durante o ciclo de BHS (ex: release/0.0.1)
DEFAULT_TRACK_BRANCH="${DEFAULT_TRACK_BRANCH:-develop}"
GITHUB_BRANCH="${TRACK_BRANCH:-$DEFAULT_TRACK_BRANCH}"
# Docker tags nao aceitam "/" (ex: release/0.0.1 -> release-0.0.1)
TRACK_TAG="${GITHUB_BRANCH//\//-}"
IMAGE_TAG="ghcr.io/a11ydevs/acessilia:${TRACK_TAG}"
export TRACK_TAG

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
  echo "[staging-update] ⚠️  Falha ao consultar GitHub API. Fazendo pull direto..."
  _pull_image "$IMAGE_TAG" || {
    echo "[staging-update] ❌ Falha ao puxar $IMAGE_TAG"
    exit 1
  }
  docker compose -f "$COMPOSE_FILE" up -d --no-deps acessilia
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
  if [ "$CACHED_KEY" = "$CACHE_KEY" ]; then
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
RUNNING_DIGEST="$LATEST_DIGEST"

echo "[staging-update] 🚀 Reiniciando container..."
docker compose -f "$COMPOSE_FILE" up -d --no-deps acessilia

# so grava o cache apos o restart ter sucesso (set -e aborta antes em caso de falha)
echo "$CACHE_KEY" > "$CACHE_FILE"

docker image prune -f

_write_status "$LATEST_SHA" "$LATEST_SHA" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$LATEST_DIGEST" "$RUNNING_DIGEST"

echo "[staging-update] ✅ Container $CONTAINER_NAME atualizado com sucesso."
