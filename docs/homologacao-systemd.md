# Homologação com systemd timer

O ambiente de homologação usa um **timer systemd** para verificar periodicamente
se há uma nova imagem no GHCR e reiniciar o container automaticamente.

## Visão geral

```
A cada 60 segundos → staging-update.timer
                         ↓
                    staging-update.service
                         ↓
                    docker pull ghcr.io/a11ydevs/acessilia:develop
                         ↓
                    digest mudou? → docker compose up -d
                                      ↓
                                 container reiniciado 🚀
```

## Instalação

### Automática (recomendada)

```bash
./scripts/setup-homologacao.sh
```

O script já configura o timer como parte do setup.

### Manual

```bash
# 1. Copiar o script de update
sudo mkdir -p /opt/acessilia/scripts
sudo cp scripts/staging-update.sh /opt/acessilia/scripts/
sudo chmod +x /opt/acessilia/scripts/staging-update.sh

# 2. Criar o service unit
sudo tee /etc/systemd/system/staging-update.service << 'SERVICE'
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

# 3. Criar o timer unit
sudo tee /etc/systemd/system/staging-update.timer << 'TIMER'
[Unit]
Description=Check acessilia staging updates every 60 seconds

[Timer]
OnBootSec=30s
OnUnitActiveSec=60s

[Install]
WantedBy=timers.target
TIMER

# 4. Ativar
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

# Acompanhar logs em tempo real
journalctl -u staging-update.service -f

# Executar manualmente (forçar update)
sudo systemctl start staging-update.service

# Alterar intervalo (ex: a cada 30s)
sudo systemctl edit staging-update.timer
# Adicionar:
# [Timer]
# OnUnitActiveSec=30s
sudo systemctl daemon-reload

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
| `pull access denied` | Token GHCR expirado | `./scripts/setup-homologacao.sh` novamente |
| `Container name already in use` | Container com nome diferente | Verificar com `docker ps -a` |
| Nada acontece, mas pull funciona | Digest é o mesmo | Aguarde o próximo build na develop |