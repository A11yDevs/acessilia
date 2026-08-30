#!/usr/bin/env bash
# setup-homologacao.sh — Prepara o servidor de homologação com systemd timer
#
# Uso:
#   ./scripts/setup-homologacao.sh          # Setup interativo
#
# Pré-requisitos:
#   - Docker + Docker Compose instalados
#   - gh (GitHub CLI) autenticado com escopo 'read:packages'
#
# Este script:
#   1. Cria um token GHCR para leitura de pacotes
#   2. Configura o Docker para autenticar no ghcr.io
#   3. Cria o .env a partir do .env.example se não existir
#   4. Sobe os containers com docker compose -f docker-compose.staging.yml
#   5. Instala o timer systemd para atualização automática

set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== Setup do Ambiente de Homologação ==="
echo ""

# ──────────────────────────────────────────────
# 1. Verificar dependências
# ──────────────────────────────────────────────
echo "[1/4] Verificando dependências..."

if ! command -v docker &>/dev/null; then
  echo "❌ Docker não encontrado. Instale em: https://docs.docker.com/engine/install/"
  exit 1
fi

if ! docker compose version &>/dev/null; then
  echo "❌ Docker Compose não encontrado."
  exit 1
fi

echo "  ✅ Docker $(docker --version)"
echo "  ✅ Compose $(docker compose version --short)"

# ──────────────────────────────────────────────
# 2. Autenticação no GHCR
# ──────────────────────────────────────────────
echo ""
echo "[2/4] Configurando autenticação no GitHub Container Registry..."

if [ ! -f ~/.docker/config.json ] || ! grep -q 'ghcr.io' ~/.docker/config.json 2>/dev/null; then
  echo "  Você precisa de um token do GitHub com escopo 'read:packages'."
  echo "  Crie em: https://github.com/settings/tokens/new?scopes=read:packages&description=GHCR+read+acessilia"
  echo ""
  read -rp "  Cole o token (ou deixe em branco para pular): " ghcr_token

  if [ -n "$ghcr_token" ]; then
    echo "$ghcr_token" | docker login ghcr.io -u "$(whoami)" --password-stdin
    echo "  ✅ Login GHCR configurado."
  else
    echo "  ⚠️  Token não informado. Execute manualmente:"
    echo "     echo <token> | docker login ghcr.io -u <user> --password-stdin"
  fi
else
  echo "  ✅ GHCR já configurado."
fi

# ──────────────────────────────────────────────
# 3. Arquivo .env
# ──────────────────────────────────────────────
echo ""
echo "[3/4] Verificando arquivo .env..."

if [ ! -f .env ]; then
  if [ -f .env.example ]; then
    cp .env.example .env
    echo "  ✅ .env criado a partir de .env.example"
    echo "  ⚠️  Edite .env com as credenciais necessárias (AI, Telegram, SMTP...)"
  else
    echo "  ⚠️  .env.example não encontrado. Crie .env manualmente."
  fi
else
  echo "  ✅ .env já existe."
fi

# ──────────────────────────────────────────────
# 4. Subir containers
# ──────────────────────────────────────────────
echo ""
echo "[4/4] Configurando update automático via systemd timer..."

docker compose -f docker-compose.staging.yml pull acessilia
docker compose -f docker-compose.staging.yml up -d

SCRIPTS_DIR="$(pwd)/scripts"

# Cria o diretório para os scripts se não existir
sudo mkdir -p /opt/acessilia/scripts
sudo cp "$SCRIPTS_DIR/staging-update.sh" /opt/acessilia/scripts/
sudo chmod +x /opt/acessilia/scripts/staging-update.sh

# Cria o service unit
sudo tee /etc/systemd/system/staging-update.service > /dev/null << 'SERVICE'
[Unit]
Description=Update acessilia staging container
After=network.target docker.service
Requires=docker.service

[Service]
Type=oneshot
ExecStart=/opt/acessilia/scripts/staging-update.sh
User=root
Group=root
SERVICE

# Cria o timer unit
sudo tee /etc/systemd/system/staging-update.timer > /dev/null << 'TIMER'
[Unit]
Description=Check acessilia staging updates every 60 seconds

[Timer]
OnBootSec=30s
OnUnitActiveSec=60s

[Install]
WantedBy=timers.target
TIMER

sudo systemctl daemon-reload
sudo systemctl enable --now staging-update.timer

echo "  ✅ Timer systemd instalado e ativo."
echo "  ⏱   Checa a cada 60s por novas imagens em ghcr.io/a11ydevs/acessilia:develop"
echo ""

echo ""
echo "=== Setup concluído! ==="
echo ""
echo "Acessos:"
echo "  API:  http://localhost:8000"
echo "  Web:  http://localhost:8001"
echo ""
echo "Para ver os logs:"
echo "  docker compose -f docker-compose.staging.yml logs -f"
echo ""
echo "Para parar:"
echo "  docker compose -f docker-compose.staging.yml down"