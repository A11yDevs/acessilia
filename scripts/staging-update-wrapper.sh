#!/usr/bin/env bash
# staging-update-wrapper.sh — Carrega credenciais e executa o staging-update.sh
#
# Este wrapper é usado pelo systemd (staging-update.service) e também serve
# para execução manual sem precisar exportar variáveis.
#
# Instalação (feita automaticamente pelo setup-homologacao.sh):
#   sudo cp scripts/staging-update-wrapper.sh /opt/acessilia/scripts/
#   sudo chmod +x /opt/acessilia/scripts/staging-update-wrapper.sh
#
# Pré-requisitos:
#   - scripts/staging-update.sh instalado em /opt/acessilia/scripts/
#   - .env com GHCR_TOKEN em $STAGING_DIR (ou /opt/acessilia/scripts/.env legado)

set -euo pipefail

# Diretório do staging (onde ficam .env e docker-compose.staging.yml)
export STAGING_DIR="${STAGING_DIR:-/opt/acessilia/staging}"

# Carrega GHCR_TOKEN se ainda não estiver definido no ambiente.
# Fontes possiveis, em ordem:
#   1. Variavel de ambiente GHCR_TOKEN
#   2. Arquivo $STAGING_DIR/.env (layout atual do servidor)
#   3. Arquivo /opt/acessilia/scripts/.env (layout legado)
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

exec /opt/acessilia/scripts/staging-update.sh