#!/usr/bin/env bash
# staging-update.sh — Atualiza o container de homologação via GitHub API
#
# Checa o SHA do último commit na branch develop via GitHub API e
# confirma que a imagem correspondente (tag sha-<7>) JÁ FOI PUBLICADA
# no GHCR antes de atualizar. Evita atualizar para um commit cujo build
# ainda está rodando ou falhou.
#
# Uso:
#   ./scripts/staging-update.sh                     # Executa uma vez
#   systemctl start staging-update.service           # Executa via systemd
#
# Instalação como user timer systemd (a cada 5 min):
#   1. sudo cp scripts/staging-update.sh /opt/acessilia/scripts/
#   2. Criar ~/.config/systemd/user/staging-update.service
#   3. Criar ~/.config/systemd/user/staging-update.timer
#   4. systemctl --user daemon-reload
#   5. systemctl --user enable --now staging-update.timer
#
# Pré-requisitos:
#   - Docker + Docker Compose instalados
#   - jq instalado (sudo apt install jq)
#   - docker login ghcr.io configurado
#   - Variável GHCR_TOKEN definida (token com escopo read:packages)
#   - Executar do diretório raiz do projeto
#
# Branch rastreada (Bug Hunting/Squashing):
#   Por padrao rastreia "develop". Durante o ciclo de BHS, defina TRACK_BRANCH
#   no .env (ex: TRACK_BRANCH=release/0.0.1) para apontar o staging para a
#   branch de release efemera; ao encerrar o BHS, remova a variavel (ou volte
#   para "develop") para retomar o rastreio normal.

set -euo pipefail

# ──────────────────────────────────────────────
# Detectar o diretório do staging (onde ficam .env e docker-compose.staging.yml)
# ──────────────────────────────────────────────
# Layouts suportados:
#   A) Servidor de homologacao: /opt/acessilia/staging/  (STAGING_DIR ou deteccao)
#   B) Repositorio clonado: <repo>/scripts/staging-update.sh -> <repo>/
# Prioridade: 1. STAGING_DIR (env)  2. /opt/acessilia/staging  3. pai do script
if [ -n "${STAGING_DIR:-}" ]; then
  STAGING_DIR="$STAGING_DIR"
elif [ -d /opt/acessilia/staging ]; then
  STAGING_DIR="/opt/acessilia/staging"
else
  STAGING_DIR="$(cd "$(dirname "$0")/.." && pwd)"
fi
cd "$STAGING_DIR"

COMPOSE_FILE="docker-compose.staging.yml"
CONTAINER_NAME="acessilia-staging"
GITHUB_REPO="A11yDevs/acessilia"
# Cache e status ficam dentro do volume ./var (visivel ao container via /app/var)
CACHE_FILE="${STAGING_UPDATE_CACHE:-$STAGING_DIR/var/data/.last_sha}"
STATUS_FILE="${STAGING_STATUS_FILE:-$STAGING_DIR/var/data/staging-status.json}"

# ──────────────────────────────────────────────
# Helpers de status
# ──────────────────────────────────────────────
_write_status() {
  # $1 = latest_sha, $2 = running_sha, $3 = last_update (ISO) ou vazio
  local latest_sha="$1" running_sha="$2" last_update="$3"
  local now
  now=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  mkdir -p "$(dirname "$STATUS_FILE")"
  jq -n \
    --arg latest "$latest_sha" \
    --arg running "$running_sha" \
    --arg check "$now" \
    --arg update "$last_update" \
    '{latest_sha: $latest, running_sha: $running, last_check: $check, last_update: $update}' \
    > "$STATUS_FILE"
}

# ──────────────────────────────────────────────
# 0. Carregar GHCR_TOKEN (se nao definido no ambiente)
# ──────────────────────────────────────────────
# Fontes possiveis, em ordem:
#   1. Variavel de ambiente GHCR_TOKEN
#   2. Arquivo <STAGING_DIR>/.env (GHCR_TOKEN=...)
#   3. Arquivo /opt/acessilia/scripts/.env (layout antigo)
if [ -z "${GHCR_TOKEN:-}" ]; then
  for env_file in "$STAGING_DIR/.env" /opt/acessilia/scripts/.env; do
    if [ -f "$env_file" ]; then
      set -a
      # shellcheck disable=SC1090
      source "$env_file"
      set +a
      break
    fi
  done
fi

# Branch/tag rastreada: "develop" por padrao, ou TRACK_BRANCH (env ou .env)
# durante o ciclo de BHS (ex: release/0.0.1)
GITHUB_BRANCH="${TRACK_BRANCH:-develop}"
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

LATEST_SHA=$(curl -fsS \
  "${AUTH_HEADER[@]}" \
  "https://api.github.com/repos/$GITHUB_REPO/commits/$GITHUB_BRANCH" \
  | jq -r '.sha')

# Se não conseguiu obter o SHA, faz pull direto (fallback seguro)
if [ -z "$LATEST_SHA" ] || [ "$LATEST_SHA" = "null" ]; then
  echo "[staging-update] ⚠️  Falha ao consultar GitHub API. Fazendo pull direto..."
  docker pull "$IMAGE_TAG" 2>/dev/null || {
    echo "[staging-update] ❌ Falha ao puxar $IMAGE_TAG"
    exit 1
  }
  docker compose -f "$COMPOSE_FILE" up -d --no-deps acessilia
  docker image prune -f
  _write_status "" "" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "[staging-update] Container atualizado (fallback)."
  exit 0
fi

# Compara com o SHA da última execução
if [ -f "$CACHE_FILE" ]; then
  CACHED_SHA=$(cat "$CACHE_FILE")
  if [ "$CACHED_SHA" = "$LATEST_SHA" ]; then
    _write_status "$LATEST_SHA" "" ""
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
  _write_status "$LATEST_SHA" "" ""
  echo "[staging-update] ⏳ Imagem sha-$SHA7 ainda não publicada no GHCR (build em andamento?). Aguardando próxima checagem."
  exit 0
fi

# ──────────────────────────────────────────────
# 3. SHA mudou e imagem publicada → atualizar
# ──────────────────────────────────────────────
echo "[staging-update] 🔄 Novo commit detectado: $SHA7. Atualizando..."

docker pull "$IMAGE_TAG" 2>/dev/null || {
  echo "[staging-update] ❌ Falha ao puxar $IMAGE_TAG"
  exit 1
}

echo "[staging-update] 🚀 Reiniciando container..."
docker compose -f "$COMPOSE_FILE" up -d --no-deps acessilia

# so grava o cache apos o restart ter sucesso (set -e aborta antes em caso de falha)
echo "$LATEST_SHA" > "$CACHE_FILE"

docker image prune -f

_write_status "$LATEST_SHA" "$LATEST_SHA" "$(date -u +%Y-%m-%dT%H:%M:%SZ)"

echo "[staging-update] ✅ Container $CONTAINER_NAME atualizado com sucesso."