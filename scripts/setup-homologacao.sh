#!/usr/bin/env bash
# setup-homologacao.sh — Prepara o servidor de homologação com systemd timer
#
# Uso:
#   ./scripts/setup-homologacao.sh                                          # Modo interativo
#   ./scripts/setup-homologacao.sh --github-user <user> --token <token>     # Modo não interativo
#
# Variáveis de ambiente (alternativa aos argumentos):
#   GITHUB_USER=<user> GHCR_TOKEN=<token> ./scripts/setup-homologacao.sh
#
# Pré-requisitos:
#   - Docker + Docker Compose instalados
#   - jq instalado (sudo apt install jq)
#
# Este script:
#   1. Configura autenticação no GHCR
#   2. Cria o .env a partir do .env.example se não existir
#   3. Sobe os containers com docker compose -f docker-compose.staging.yml
#   4. Instala o timer systemd para atualização automática via GitHub API

set -euo pipefail
cd "$(dirname "$0")/.."

# ──────────────────────────────────────────────
# Parse CLI arguments
# ──────────────────────────────────────────────
GITHUB_USER="${GITHUB_USER:-}"
GHCR_TOKEN="${GHCR_TOKEN:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --github-user) GITHUB_USER="$2"; shift 2 ;;
    --token)       GHCR_TOKEN="$2"; shift 2 ;;
    --help|-h)
      echo "Uso: $0 [--github-user <user>] [--token <token>]"
      echo ""
      echo "Variáveis de ambiente: GITHUB_USER, GHCR_TOKEN"
      exit 0 ;;
    *) echo "❌ Argumento desconhecido: $1"; exit 1 ;;
  esac
done

echo "=== Setup do Ambiente de Homologação ==="
echo ""

# ──────────────────────────────────────────────
# 1. Verificar dependências
# ──────────────────────────────────────────────
echo "[1/5] Verificando dependências..."

if ! command -v docker &>/dev/null; then
  echo "❌ Docker não encontrado. Instale em: https://docs.docker.com/engine/install/"
  exit 1
fi

if ! docker compose version &>/dev/null; then
  echo "❌ Docker Compose não encontrado."
  exit 1
fi

if ! command -v jq &>/dev/null; then
  echo "❌ jq não encontrado. Instale com: sudo apt install jq"
  exit 1
fi

echo "  ✅ Docker $(docker --version)"
echo "  ✅ Compose $(docker compose version --short)"
echo "  ✅ jq $(jq --version)"

# ──────────────────────────────────────────────
# 2. Autenticação no GHCR
# ──────────────────────────────────────────────
echo ""
echo "[2/5] Configurando autenticação no GitHub Container Registry..."

if [ ! -f ~/.docker/config.json ] || ! grep -q 'ghcr.io' ~/.docker/config.json 2>/dev/null; then
  if [ -z "$GITHUB_USER" ]; then
    read -rp "  Seu username do GitHub: " GITHUB_USER
  fi
  if [ -z "$GHCR_TOKEN" ]; then
    echo "  Crie em: https://github.com/settings/tokens/new?scopes=read:packages"
    read -rp "  Cole o token (ou deixe em branco para pular): " GHCR_TOKEN
  fi

  if [ -n "$GHCR_TOKEN" ] && [ -n "$GITHUB_USER" ]; then
    echo "$GHCR_TOKEN" | docker login ghcr.io -u "$GITHUB_USER" --password-stdin
    echo "  ✅ Login GHCR configurado."
  else
    echo "  ⚠️  Token ou username não informado. Execute manualmente:"
    echo "     echo <token> | docker login ghcr.io -u <seu-user> --password-stdin"
  fi
else
  echo "  ✅ GHCR já configurado."
fi

# ──────────────────────────────────────────────
# 3. Arquivo .env
# ──────────────────────────────────────────────
echo ""
echo "[3/5] Verificando arquivo .env..."

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
echo "[4/5] Subindo containers com a imagem mais recente..."

docker compose -f docker-compose.staging.yml pull acessilia
docker compose -f docker-compose.staging.yml up -d

# ──────────────────────────────────────────────
# 5. Configurar update automático via systemd timer
# ──────────────────────────────────────────────
echo ""
echo "[5/5] Configurando update automático via systemd timer..."

SCRIPTS_DIR="$(pwd)/scripts"

# Cria o diretório para os scripts se não existir
sudo mkdir -p /opt/acessilia/scripts
sudo cp "$SCRIPTS_DIR/staging-update.sh" /opt/acessilia/scripts/
sudo chmod +x /opt/acessilia/scripts/staging-update.sh

# Detecta o diretório do staging (onde ficam .env e docker-compose.staging.yml)
STAGING_DIR="${STAGING_DIR:-}"
if [ -z "$STAGING_DIR" ] && [ -d /opt/acessilia/staging ]; then
  STAGING_DIR="/opt/acessilia/staging"
fi
if [ -z "$STAGING_DIR" ]; then
  STAGING_DIR="$(pwd)"
fi

# Persiste o token no .env do staging (usado pelo compose e pelo staging-update.sh)
if [ -n "$GHCR_TOKEN" ]; then
  if [ -f "$STAGING_DIR/.env" ]; then
    if grep -q '^GHCR_TOKEN=' "$STAGING_DIR/.env"; then
      sudo sed -i "s|^GHCR_TOKEN=.*|GHCR_TOKEN=$GHCR_TOKEN|" "$STAGING_DIR/.env"
    else
      echo "GHCR_TOKEN=$GHCR_TOKEN" | sudo tee -a "$STAGING_DIR/.env" > /dev/null
    fi
  else
    echo "GHCR_TOKEN=$GHCR_TOKEN" | sudo tee "$STAGING_DIR/.env" > /dev/null
  fi
  sudo chmod 600 "$STAGING_DIR/.env"
fi

# Cria um wrapper que carrega o token e exporta STAGING_DIR antes do staging-update.sh
sudo tee /opt/acessilia/scripts/staging-update-wrapper.sh > /dev/null << 'WRAPPER'
#!/usr/bin/env bash
# staging-update-wrapper.sh — Carrega credenciais e executa o staging-update.sh
set -euo pipefail

# Diretório do staging (onde ficam .env e docker-compose.staging.yml)
export STAGING_DIR="${STAGING_DIR:-/opt/acessilia/staging}"

# Carrega GHCR_TOKEN se ainda não estiver definido
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
WRAPPER
sudo chmod +x /opt/acessilia/scripts/staging-update-wrapper.sh

# Cria o service unit
sudo tee /etc/systemd/system/staging-update.service > /dev/null << 'SERVICE'
[Unit]
Description=Update acessilia staging container
After=network.target docker.service
Requires=docker.service

[Service]
Type=oneshot
ExecStart=/opt/acessilia/scripts/staging-update-wrapper.sh
User=root
Group=root
SERVICE

# Cria o timer unit (a cada 5 minutos)
sudo tee /etc/systemd/system/staging-update.timer > /dev/null << 'TIMER'
[Unit]
Description=Check acessilia staging updates every 5 minutes

[Timer]
OnBootSec=30s
OnUnitActiveSec=300s

[Install]
WantedBy=timers.target
TIMER

sudo systemctl daemon-reload
sudo systemctl enable --now staging-update.timer

echo "  ✅ Timer systemd instalado e ativo."
echo "  ⏱   Checa a cada 5 minutos via GitHub API se há novos commits em develop"
echo "  🔑  Token GHCR salvo em $STAGING_DIR/.env (modo 600)"
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