# Producao com systemd timer

Este procedimento promove a Acessilia para producao usando as imagens publicadas
no GHCR a partir da branch `main`. Ele complementa o fluxo de release: o merge em
`main` publica as tags `main`, `latest` e `sha-<commit>`; a tag semantica `v*`
publica as imagens versionadas e cria a GitHub Release.

## Politica de imagem

Para atualizacao automatica, o ambiente de producao rastreia `main` e executa a
tag `ghcr.io/a11ydevs/acessilia:main`. Para releases reguladas, registre tambem
o digest imutavel mostrado no workflow antes de promover a versao.

Use `latest` apenas se a operacao de producao ja adotou essa convencao. Para
rollback, prefira voltar para o digest anterior registrado antes do deploy.

## Pre-requisitos

- Docker + Docker Compose instalados
- `jq` instalado (`sudo apt install jq`)
- Token GitHub com escopo `read:packages`
- `docker login ghcr.io` configurado
- Linger habilitado para o usuario (`sudo loginctl enable-linger $USER`)
- Usuario no grupo `docker` (`sudo usermod -aG docker $USER`)

## Instalacao automatica

```bash
# Modo interativo
./scripts/setup-producao.sh

# Modo nao interativo
./scripts/setup-producao.sh --github-user marceloakira --token ghp_exemplo

# Diretorio customizado
./scripts/setup-producao.sh --production-dir /opt/acessilia/production

# Primeiro deploy sem ativar update automatico imediatamente
./scripts/setup-producao.sh --no-timer
```

O script instala `docker-compose.production.yml`, `staging-update.sh` e
`production-update.sh`, cria o `.env` se necessario, sobe o container e habilita
o timer `acessilia-production-update.timer`. Use `--no-timer` para instalar o
timer desabilitado e ativar manualmente depois da validacao inicial.

## Instalacao manual

```bash
# 1. Criar diretorios
sudo mkdir -p /opt/acessilia/production /opt/acessilia/scripts

# 2. Copiar compose, exemplo de ambiente e scripts
sudo cp docker-compose.production.yml /opt/acessilia/production/
sudo cp .env.example /opt/acessilia/production/.env
sudo cp scripts/staging-update.sh /opt/acessilia/scripts/
sudo cp scripts/production-update.sh /opt/acessilia/scripts/
sudo chmod +x /opt/acessilia/scripts/staging-update.sh /opt/acessilia/scripts/production-update.sh

# 3. Ajustar segredos e configuracoes reais de producao
sudo editor /opt/acessilia/production/.env
sudo chmod 600 /opt/acessilia/production/.env

# 4. Login no GHCR
echo "$GHCR_TOKEN" | docker login ghcr.io -u "$GITHUB_USER" --password-stdin

# 5. Subir a imagem atual da main
cd /opt/acessilia/production
sudo mkdir -p var/temp var/data var/logs
sudo chown -R "$USER":"$(id -gn)" /opt/acessilia/production
docker compose -f docker-compose.production.yml pull acessilia
docker compose -f docker-compose.production.yml up -d
```

## Timer systemd de usuario

Crie o servico:

```bash
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/acessilia-production-update.service << 'SERVICE'
[Unit]
Description=Update acessilia production container

[Service]
Type=oneshot
ExecStart=/opt/acessilia/scripts/production-update.sh
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
SERVICE
```

Crie o timer:

```bash
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
systemctl --user enable --now acessilia-production-update.timer
```

## Promocao de release

Depois que o PR `release/x.y.z` for mesclado em `main`, aguarde o workflow de CI
e Delivery publicar a imagem `main`. Em seguida, execute uma atualizacao manual
ou aguarde o timer:

```bash
systemctl --user start acessilia-production-update.service
journalctl --user -u acessilia-production-update.service -n 50 --no-pager
```

Valide:

```bash
curl --fail http://localhost:8000/api/v1/health
docker inspect acessilia-production --format '{{.Config.Image}}'
docker compose -f /opt/acessilia/production/docker-compose.production.yml logs --tail=100 acessilia
```

## Rollback manual minimo

Antes de promover, registre a imagem ou digest atual:

```bash
docker inspect acessilia-production --format '{{.Config.Image}}'
```

Se precisar voltar, edite temporariamente `docker-compose.production.yml` para a
imagem/digest anterior e aplique:

```bash
cd /opt/acessilia/production
docker compose -f docker-compose.production.yml pull acessilia
docker compose -f docker-compose.production.yml up -d --no-deps acessilia
curl --fail http://localhost:8000/api/v1/health
```

Depois do rollback, pare o timer ate decidir a proxima promocao:

```bash
systemctl --user stop acessilia-production-update.timer
```