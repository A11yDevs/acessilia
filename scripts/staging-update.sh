#!/usr/bin/env bash
# staging-update.sh — Atualiza o container de homologação com a última imagem
#
# Uso:
#   ./scripts/staging-update.sh                     # Executa uma vez
#   systemctl start staging-update.service           # Executa via systemd
#
# Instalação como timer systemd (atualiza a cada 60s):
#   1. sudo cp scripts/staging-update.sh /opt/acessilia/scripts/
#   2. Criar /etc/systemd/system/staging-update.service
#   3. Criar /etc/systemd/system/staging-update.timer
#   4. sudo systemctl daemon-reload
#   5. sudo systemctl enable --now staging-update.timer
#
# Pré-requisitos:
#   - Docker + Docker Compose instalados
#   - docker login ghcr.io configurado (ver scripts/setup-homologacao.sh)
#   - Executar do diretório raiz do projeto

set -euo pipefail

cd "$(dirname "$0")/.."

COMPOSE_FILE="docker-compose.staging.yml"
CONTAINER_NAME="acessilia-staging"
IMAGE_TAG="ghcr.io/a11ydevs/acessilia:develop"

# Puxa a imagem mais recente (silencioso se já está atualizada)
docker pull "$IMAGE_TAG" 2>/dev/null || {
  echo "[staging-update] Falha ao puxar $IMAGE_TAG"
  exit 1
}

# Compara a imagem em uso com a mais recente
CURRENT_IMAGE=$(docker inspect --format '{{.Config.Image}}' "$CONTAINER_NAME" 2>/dev/null || echo "")

if [ "$CURRENT_IMAGE" = "$IMAGE_TAG" ]; then
  # Mesma tag, verifica se o digest mudou (imagem foi atualizada)
  CURRENT_DIGEST=$(docker image inspect "$IMAGE_TAG" --format '{{.Id}}' 2>/dev/null || echo "")
  RUNNING_DIGEST=$(docker inspect "$CONTAINER_NAME" --format '{{.Image}}' 2>/dev/null || echo "")
  if [ "$CURRENT_DIGEST" = "$RUNNING_DIGEST" ]; then
    echo "[staging-update] Imagem já está atualizada. Nada a fazer."
    exit 0
  fi
fi

echo "[staging-update] Nova imagem detectada! Reiniciando container..."
docker compose -f "$COMPOSE_FILE" up -d --no-deps acessilia

# Remove imagens antigas não utilizadas
docker image prune -f

echo "[staging-update] Container $CONTAINER_NAME atualizado com sucesso."