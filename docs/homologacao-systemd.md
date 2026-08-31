# Homologação com systemd timer

O ambiente de homologação usa um **timer systemd** para verificar periodicamente
se há novos commits na branch `develop` (via GitHub API) e, quando detectados,
atualizar o container automaticamente com a imagem mais recente.

**Vantagem:** zero requisições desnecessárias ao GHCR. A API do GitHub (com token
autenticado, 5.000 req/h) é consultada a cada 5 min. O `docker pull` só acontece
quando há um commit novo.

## Visão geral

```
A cada 5 minutos → staging-update.timer
                       ↓
                  staging-update-wrapper.sh
                       ↓
                  carrega GHCR_TOKEN de .env
                       ↓
                  staging-update.sh
                       ↓
                  GitHub API → SHA do último commit em develop
                       ↓
                  SHA mudou? → docker pull + docker compose up -d
                                    ↓
                               container reiniciado 🚀
```

## Pré-requisitos

- Docker + Docker Compose instalados
- `jq` instalado (`sudo apt install jq`)
- Token GitHub com escopo `read:packages`
  (criar em: https://github.com/settings/tokens/new?scopes=read:packages)
- `docker login ghcr.io` configurado

## Instalação

### Automática (recomendada)

```bash
# Modo interativo
./scripts/setup-homologacao.sh

# Modo não interativo (via argumentos)
./scripts/setup-homologacao.sh --github-user marceloakira --token ghp_exemplo

# Modo não interativo (via variáveis de ambiente)
GITHUB_USER=marceloakira GHCR_TOKEN=ghp_exemplo ./scripts/setup-homologacao.sh
```

O script:
1. Verifica dependências (Docker, Compose, `jq`)
2. Configura `docker login ghcr.io` com o token
3. Cria `.env` a partir de `.env.example` (se não existir)
4. Sobe o container com a imagem mais recente
5. Instala o timer systemd e persiste o token em `/opt/acessilia/scripts/.env`

### Manual

```bash
# 1. Criar diretório para os scripts
sudo mkdir -p /opt/acessilia/scripts

# 2. Copiar o script de update
sudo cp scripts/staging-update.sh /opt/acessilia/scripts/
sudo chmod +x /opt/acessilia/scripts/staging-update.sh

# 3. Persistir o token GHCR
sudo tee /opt/acessilia/scripts/.env > /dev/null << 'ENV'
GHCR_TOKEN=seu_token_aqui
ENV
sudo chmod 600 /opt/acessilia/scripts/.env

# 4. Criar o wrapper (carrega o token antes do script)
sudo tee /opt/acessilia/scripts/staging-update-wrapper.sh > /dev/null << 'WRAPPER'
#!/usr/bin/env bash
set -a
source /opt/acessilia/scripts/.env
set +a
exec /opt/acessilia/scripts/staging-update.sh
WRAPPER
sudo chmod +x /opt/acessilia/scripts/staging-update-wrapper.sh

# 5. Criar o service unit
sudo tee /etc/systemd/system/staging-update.service << 'SERVICE'
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

# 6. Criar o timer unit (a cada 5 minutos)
sudo tee /etc/systemd/system/staging-update.timer << 'TIMER'
[Unit]
Description=Check acessilia staging updates every 5 minutes

[Timer]
OnBootSec=30s
OnUnitActiveSec=300s

[Install]
WantedBy=timers.target
TIMER

# 7. Ativar
sudo systemctl daemon-reload
sudo systemctl enable --now staging-update.timer
```

## Gerenciamento

```bash
# Verificar status do timer
systemctl status staging-update.timer

# Verificar última execução
systemctl status staging-update.service

# Ver logs da última execução
journalctl -u staging-update.service -n 50 --no-pager

# Executar manualmente (forçar update)
sudo systemctl start staging-update.service

# Desabilitar temporariamente
sudo systemctl stop staging-update.timer

# Remover completamente
sudo systemctl disable --now staging-update.timer
sudo rm /etc/systemd/system/staging-update.{service,timer}
sudo systemctl daemon-reload
```

## Troubleshooting

### O container não reiniciou

Verifique o log do serviço:

```bash
journalctl -u staging-update.service -n 50 --no-pager
```

Causas comuns:

| Sintoma | Causa | Solução |
|---------|-------|---------|
| `pull access denied` | Token GHCR expirado | Rodar `setup-homologacao.sh` novamente |
| `jq: command not found` | `jq` não instalado | `sudo apt install jq` |
| `GHCR_TOKEN: parameter not set` | Token não persistido | Verificar `/opt/acessilia/scripts/.env` |
| Nada acontece, SHA não muda | Sem commits novos na develop | Aguarde o próximo build |
| Falha na API (fallback ativado) | GitHub API indisponível | Script faz `docker pull` direto |
| `Container name already in use` | Container com nome diferente | `docker ps -a` e `docker rm` |