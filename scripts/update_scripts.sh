#!/usr/bin/env bash
# update_scripts.sh — Atualiza os scripts de homologação a partir do GitHub (sem git clone)
#
# Uso (rodar no servidor de homologação):
#   ./update_scripts.sh                 # usa a branch rastreada (TRACK_BRANCH ou develop)
#   ./update_scripts.sh release/0.1.0   # forca uma branch/tag especifica
#
# O que este script faz:
#   1. Baixa staging-update.sh, staging-update-wrapper.sh e docker-compose.staging.yml
#      direto do GitHub (raw.githubusercontent.com), sem precisar clonar o repositorio
#   2. Faz backup (.bak) dos arquivos existentes
#   3. Instala em /opt/acessilia/scripts e no STAGING_DIR (ex: /opt/acessilia/staging)
#
# Pré-requisitos: curl. Repositório público (não requer token).

set -euo pipefail

REPO="A11yDevs/acessilia"
SCRIPTS_DIR="${SCRIPTS_DIR:-/opt/acessilia/scripts}"

if [ -n "${STAGING_DIR:-}" ]; then
  STAGING_DIR="$STAGING_DIR"
elif [ -d /opt/acessilia/staging ]; then
  STAGING_DIR="/opt/acessilia/staging"
else
  STAGING_DIR="$(cd "$(dirname "$0")/.." && pwd)"
fi

# Branch/tag a baixar: argumento > TRACK_BRANCH do .env > develop
REF="${1:-}"
if [ -z "$REF" ] && [ -f "$STAGING_DIR/.env" ]; then
  REF=$(grep -E '^TRACK_BRANCH=' "$STAGING_DIR/.env" | tail -1 | cut -d= -f2-)
fi
REF="${REF:-develop}"

echo "[update-scripts] Baixando arquivos da branch/tag '${REF}'..."

_download() {
  # $1 = caminho no repo, $2 = destino local
  local src="$1" dest="$2"
  local url="https://raw.githubusercontent.com/${REPO}/${REF}/${src}"
  if [ -f "$dest" ]; then
    cp "$dest" "${dest}.bak"
  fi
  curl -fsSL "$url" -o "$dest.tmp"
  mv "$dest.tmp" "$dest"
  echo "  ✅ ${dest}"
}

# so usa sudo se o diretorio ainda nao existir/nao for gravavel pelo usuario atual
mkdir -p "$SCRIPTS_DIR" 2>/dev/null || sudo mkdir -p "$SCRIPTS_DIR"
_download "scripts/staging-update.sh" "$SCRIPTS_DIR/staging-update.sh"
_download "scripts/staging-update-wrapper.sh" "$SCRIPTS_DIR/staging-update-wrapper.sh"
chmod +x "$SCRIPTS_DIR/staging-update.sh" "$SCRIPTS_DIR/staging-update-wrapper.sh"

_download "docker-compose.staging.yml" "$STAGING_DIR/docker-compose.staging.yml"

echo ""
echo "[update-scripts] ✅ Scripts atualizados. Para aplicar agora:"
echo "  systemctl --user start staging-update.service"
