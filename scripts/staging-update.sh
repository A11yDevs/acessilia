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
# Instalação como timer systemd (a cada 5 min):
#   1. sudo cp scripts/staging-update.sh /opt/acessilia/scripts/
#   2. Criar /etc/systemd/system/staging-update.service
#   3. Criar /etc/systemd/system/staging-update.timer
#   4. sudo systemctl daemon-reload
#   5. sudo systemctl enable --now staging-update.timer
#
# Pré-requisitos:
#   - Docker + Docker Compose instalados
#   - jq instalado (sudo apt install jq)
#   - docker login ghcr.io configurado
#   - Variável GHCR_TOKEN definida (token com escopo read:packages)
#   - Executar do diretório raiz do projeto

set -euo pipefail

cd "$(dirname "$0")/.."

COMPOSE_FILE="docker-compose.staging.yml"
CONTAINER_NAME="acessilia-staging"
IMAGE_TAG="ghcr.io/a11ydevs/acessilia:develop"
CACHE_FILE="/opt/acessilia/scripts/.last_sha"
GITHUB_REPO="A11yDevs/acessilia"
GITHUB_BRANCH="develop"

# ──────────────────────────────────────────────
# 1. Checar SHA do último commit via GitHub API
# ──────────────────────────────────────────────
LATEST_SHA=$(curl -fsS \
  -H "Authorization: token ${GHCR_TOKEN:?}" \
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
  echo "[staging-update] Container atualizado (fallback)."
  exit 0
fi

# Compara com o SHA da última execução
if [ -f "$CACHE_FILE" ]; then
  CACHED_SHA=$(cat "$CACHE_FILE")
  if [ "$CACHED_SHA" = "$LATEST_SHA" ]; then
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
  echo "[staging-update] ⏳ Imagem sha-$SHA7 ainda não publicada no GHCR (build em andamento?). Aguardando próxima checagem."
  exit 0
fi

# ──────────────────────────────────────────────
# 3. SHA mudou e imagem publicada → atualizar
# ──────────────────────────────────────────────
echo "[staging-update] 🔄 Novo commit detectado: $SHA7. Atualizando..."

echo "$LATEST_SHA" > "$CACHE_FILE"

docker pull "$IMAGE_TAG" 2>/dev/null || {
  echo "[staging-update] ❌ Falha ao puxar $IMAGE_TAG"
  exit 1
}

echo "[staging-update] 🚀 Reiniciando container..."
docker compose -f "$COMPOSE_FILE" up -d --no-deps acessilia

docker image prune -f

echo "[staging-update] ✅ Container $CONTAINER_NAME atualizado com sucesso."