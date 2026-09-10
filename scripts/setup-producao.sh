#!/usr/bin/env bash
# setup-producao.sh — Prepara o servidor de producao com systemd timer
#
# Uso:
#   ./scripts/setup-producao.sh
#   ./scripts/setup-producao.sh --github-user <user> --token <token>
#   ./scripts/setup-producao.sh --production-dir /opt/acessilia/production
#
# Variaveis de ambiente:
#   GITHUB_USER=<user> GHCR_TOKEN=<token> ./scripts/setup-producao.sh

set -euo pipefail
cd "$(dirname "$0")/.."

GITHUB_USER="${GITHUB_USER:-}"
GHCR_TOKEN="${GHCR_TOKEN:-}"
PRODUCTION_DIR="${PRODUCTION_DIR:-/opt/acessilia/production}"
ENABLE_TIMER="true"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --github-user) GITHUB_USER="$2"; shift 2 ;;
    --token) GHCR_TOKEN="$2"; shift 2 ;;
    --production-dir) PRODUCTION_DIR="$2"; shift 2 ;;
    --no-timer) ENABLE_TIMER="false"; shift ;;
    --help|-h)
      echo "Uso: $0 [--github-user <user>] [--token <token>] [--production-dir <dir>] [--no-timer]"
      echo ""
      echo "Variaveis de ambiente: GITHUB_USER, GHCR_TOKEN, PRODUCTION_DIR"
      exit 0 ;;
    *) echo "Argumento desconhecido: $1"; exit 1 ;;
  esac
done

echo "=== Setup do Ambiente de Producao ==="
echo ""

echo "[1/5] Verificando dependencias..."

if ! command -v docker &>/dev/null; then
  echo "Docker nao encontrado. Instale em: https://docs.docker.com/engine/install/"
  exit 1
fi

if ! docker compose version &>/dev/null; then
  echo "Docker Compose nao encontrado."
  exit 1
fi

if ! command -v jq &>/dev/null; then
  echo "jq nao encontrado. Instale com: sudo apt install jq"
  exit 1
fi

echo "  Docker $(docker --version)"
echo "  Compose $(docker compose version --short)"
echo "  jq $(jq --version)"

echo ""
echo "[2/5] Configurando autenticacao no GitHub Container Registry..."

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
    echo "  Login GHCR configurado."
  else
    echo "  Token ou username nao informado. Execute manualmente:"
    echo "     echo <token> | docker login ghcr.io -u <seu-user> --password-stdin"
  fi
else
  echo "  GHCR ja configurado."
fi

echo ""
echo "[3/5] Instalando arquivos de producao em $PRODUCTION_DIR..."

sudo mkdir -p "$PRODUCTION_DIR" /opt/acessilia/scripts
sudo cp docker-compose.production.yml "$PRODUCTION_DIR/"

if [ ! -f "$PRODUCTION_DIR/.env" ]; then
  sudo cp .env.example "$PRODUCTION_DIR/.env"
  echo "  .env criado a partir de .env.example"
  echo "  Edite $PRODUCTION_DIR/.env com as credenciais reais de producao."
else
  echo "  .env ja existe em $PRODUCTION_DIR/.env"
fi

sudo mkdir -p "$PRODUCTION_DIR/var/temp" "$PRODUCTION_DIR/var/data" "$PRODUCTION_DIR/var/logs"
sudo chown -R "$USER":"$(id -gn)" "$PRODUCTION_DIR"
sudo cp scripts/staging-update.sh /opt/acessilia/scripts/
sudo cp scripts/production-update.sh /opt/acessilia/scripts/
sudo chmod +x /opt/acessilia/scripts/staging-update.sh /opt/acessilia/scripts/production-update.sh

if [ -n "$GHCR_TOKEN" ]; then
  if sudo grep -q '^GHCR_TOKEN=' "$PRODUCTION_DIR/.env" 2>/dev/null; then
    sudo sed -i "s|^GHCR_TOKEN=.*|GHCR_TOKEN=$GHCR_TOKEN|" "$PRODUCTION_DIR/.env"
  else
    echo "GHCR_TOKEN=$GHCR_TOKEN" | sudo tee -a "$PRODUCTION_DIR/.env" > /dev/null
  fi
fi
sudo chmod 600 "$PRODUCTION_DIR/.env"

echo ""
echo "[4/5] Subindo container de producao com a imagem main..."

(
  cd "$PRODUCTION_DIR"
  docker compose -f docker-compose.production.yml pull acessilia
  docker compose -f docker-compose.production.yml up -d
)

echo ""
echo "[5/5] Configurando update automatico via systemd user timer..."

if ! loginctl show-user "$USER" 2>/dev/null | grep -q 'Linger=yes'; then
  echo "  Habilitando linger para $USER (user timer sobrevive ao logout)..."
  sudo loginctl enable-linger "$USER"
fi

if ! id -nG | tr ' ' '\n' | grep -qx docker; then
  echo "  Adicionando $USER ao grupo docker (user timer acessa o daemon)..."
  sudo usermod -aG docker "$USER"
  echo "  Relogue (logout/login) para o grupo docker ter efeito."
fi

mkdir -p ~/.config/systemd/user

cat > ~/.config/systemd/user/acessilia-production-update.service << SERVICE
[Unit]
Description=Update acessilia production container

[Service]
Type=oneshot
ExecStart=/opt/acessilia/scripts/production-update.sh
Environment=PRODUCTION_DIR=$PRODUCTION_DIR
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
SERVICE

cat > ~/.config/systemd/user/acessilia-production-update.timer << 'TIMER'
[Unit]
Description=Check acessilia production updates every 5 minutes

[Timer]
OnBootSec=30s
OnUnitActiveSec=300s

[Install]
WantedBy=timers.target
TIMER

systemctl --user daemon-reload
if [ "$ENABLE_TIMER" = "true" ]; then
  systemctl --user enable --now acessilia-production-update.timer
  echo "  User timer systemd instalado e ativo."
else
  systemctl --user disable --now acessilia-production-update.timer >/dev/null 2>&1 || true
  echo "  User timer systemd instalado, mas desabilitado (--no-timer)."
fi

echo ""
echo "=== Setup concluido! ==="
echo ""
echo "Acessos:"
echo "  API:  http://localhost:8000"
echo "  Web:  http://localhost:8001"
echo ""
echo "Para validar:"
echo "  curl --fail http://localhost:8000/api/v1/health"
echo ""
echo "Para ver logs:"
echo "  docker compose -f $PRODUCTION_DIR/docker-compose.production.yml logs -f"