#!/usr/bin/env bash
# production-update.sh — Atualiza o container de producao rastreando a main
#
# Reusa o mecanismo de update validado para homologacao, mas com defaults de
# producao: /opt/acessilia/production, docker-compose.production.yml,
# container acessilia-production e branch main.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

export DEPLOY_DIR="${PRODUCTION_DIR:-${DEPLOY_DIR:-/opt/acessilia/production}}"
export COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.production.yml}"
export CONTAINER_NAME="${CONTAINER_NAME:-acessilia-production}"
export DEPLOY_ENV="${DEPLOY_ENV:-production}"
export DEFAULT_TRACK_BRANCH="${DEFAULT_TRACK_BRANCH:-main}"
export STAGING_UPDATE_CACHE="${STAGING_UPDATE_CACHE:-$DEPLOY_DIR/var/data/.last_production_sha}"

exec "$SCRIPT_DIR/staging-update.sh"