# Homologação com systemd timer

O ambiente de homologação usa um **timer systemd** para verificar periodicamente
se há novos commits na branch `develop` (via GitHub API) e, quando detectados,
atualizar o container automaticamente com a imagem mais recente.

**Vantagem:** zero requisições desnecessárias ao GHCR. A API do GitHub (com token
autenticado, 5.000 req/h) é consultada a cada 5 min. O `docker pull` só acontece
quando há um commit novo.

## Visão geral

O timer roda no **escopo do usuário** (`systemctl --user`), com units em
`~/.config/systemd/user/`. Isso evita depender de `sudo` para o agendamento e
permite que o usuário gerencie o timer sem privilégios.

```
A cada 5 minutos → staging-update.timer (user)
                       ↓
                  staging-update-wrapper.sh
                       ↓
                  carrega GHCR_TOKEN de $STAGING_DIR/.env
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
- **Linger habilitado** para o usuário (`sudo loginctl enable-linger $USER`) —
  sem isso, o user timer morre quando o usuário faz logout
- **Usuário no grupo `docker`** (`sudo usermod -aG docker $USER`) — o user timer
  roda sem `sudo` e precisa do grupo para acessar o daemon

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
5. Instala o **user timer** (`systemctl --user`), habilita linger e o grupo
   `docker`, e persiste o token em `$STAGING_DIR/.env` (ex.: `/opt/acessilia/staging/.env`)

### Manual

```bash
# 1. Criar diretório para os scripts
sudo mkdir -p /opt/acessilia/scripts

# 2. Copiar o script de update e o wrapper (versionados no repositório)
sudo cp scripts/staging-update.sh /opt/acessilia/scripts/
sudo cp scripts/staging-update-wrapper.sh /opt/acessilia/scripts/
sudo chmod +x /opt/acessilia/scripts/staging-update.sh /opt/acessilia/scripts/staging-update-wrapper.sh

# 3. Persistir o token GHCR no .env do staging
#    (o wrapper e o staging-update.sh carregam de $STAGING_DIR/.env)
sudo tee /opt/acessilia/staging/.env > /dev/null << 'ENV'
GHCR_TOKEN=seu_token_aqui
ENV
sudo chmod 600 /opt/acessilia/staging/.env

# 4. Pré-requisitos do user timer
sudo loginctl enable-linger "$USER"          # timer sobrevive ao logout
sudo usermod -aG docker "$USER"              # user timer acessa o docker
# relogue (logout/login) para o grupo docker valer

# 5. Criar o service unit (user)
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/staging-update.service << 'SERVICE'
[Unit]
Description=Update acessilia staging container

[Service]
Type=oneshot
ExecStart=/opt/acessilia/scripts/staging-update-wrapper.sh
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
SERVICE

# 6. Criar o timer unit (user, a cada 5 minutos)
cat > ~/.config/systemd/user/staging-update.timer << 'TIMER'
[Unit]
Description=Check acessilia staging updates every 5 minutes

[Timer]
OnBootSec=30s
OnUnitActiveSec=300s

[Install]
WantedBy=timers.target
TIMER

# 7. Ativar
systemctl --user daemon-reload
systemctl --user enable --now staging-update.timer
```

## Gerenciamento

> Todos os comandos usam `systemctl --user` (o timer roda no escopo do usuário).

```bash
# Verificar status do timer
systemctl --user status staging-update.timer

# Verificar última execução
systemctl --user status staging-update.service

# Ver logs da última execução
journalctl --user -u staging-update.service -n 50 --no-pager

# Executar manualmente (forçar update)
systemctl --user start staging-update.service

# Desabilitar temporariamente
systemctl --user stop staging-update.timer

# Remover completamente
systemctl --user disable --now staging-update.timer
rm ~/.config/systemd/user/staging-update.{service,timer}
systemctl --user daemon-reload
```

## Troubleshooting

### O container não reiniciou

Verifique o log do serviço:

```bash
journalctl --user -u staging-update.service -n 50 --no-pager
```

Causas comuns:

| Sintoma | Causa | Solução |
|---------|-------|---------|
| `pull access denied` | Token GHCR expirado | Rodar `setup-homologacao.sh` novamente |
| `jq: command not found` | `jq` não instalado | `sudo apt install jq` |
| `GHCR_TOKEN: parameter not set` | Token não persistido | Verificar `$STAGING_DIR/.env` (ex.: `/opt/acessilia/staging/.env`) |
| `permission denied` no docker | Usuário fora do grupo `docker` | `sudo usermod -aG docker $USER` + relogar |
| Timer não roda após logout | Linger desabilitado | `sudo loginctl enable-linger $USER` |
| Nada acontece, SHA não muda | Sem commits novos na develop | Aguarde o próximo build |
| Falha na API (fallback ativado) | GitHub API indisponível | Script faz `docker pull` direto |
| `Container name already in use` | Container com nome diferente | `docker ps -a` e `docker rm` |