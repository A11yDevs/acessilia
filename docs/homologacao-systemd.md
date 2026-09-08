# Staging environment with a systemd timer

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](homologacao-systemd.pt-br.md)

The staging (homologation) environment uses a **systemd timer** that periodically checks
whether there are new commits on the `develop` branch (via the GitHub API) and, when found,
apdates the container automatically using the most recent image.

**Advantage:** zero unnecessary requests to GHCR. The GitHub API (authenticated token,
5,000 req/h) is queried every 5 minutes, and `docker pull` only runs when a new commit exists.

## Overview

The timer runs in the **user scope** (`systemctl --user`) with units under
`~/.config/systemd/user/`. This avoids depending on `sudo` for scheduling and lets
the user manage the timer without privileges.

```
Every 5 minutes → staging-update.timer (user)
d                   ↓
staging-update-wrapper.sh
                         ↓
loads GHCR_TOKEN from $STAGING_DIR/.env
                              ↓
staging-update.sh
                    ↓
GitHub API → SHA of last commit on develop
                ↓
SHA changed? → docker pull + docker compose up -d
                        ↓
container restarted 🚀
```

## Prerequisites

- Docker and Docker Compose installed
- `jq` installed (`sudo apt install jq`)
- GitHub token with the `read:packages` scope (create at:
  https://github.com/settings/tokens/new?scopes=read:packages)
- `docker login ghcr.io` configured
- **Linger enabled** for the user (`sudo loginctl enable-linger $USER`) — without it,
  the user timer dies when the user logs out
- **User in the `docker` group** (`sudo usermod -aG docker $USER`) — the user timer runs
  without `sudo` and needs that group to reach the Docker daemon

## Installation

### Automatic (recommended)

```bash
# Interactive mode
./scripts/setup-homologacao.sh

# Non-interactive mode (arguments mode)
./scripts/setup-homologacao.sh --github-user marceloakira --token ghp_exemplo

# Non-interactive mode (environment variables)
GITHUB_USER=marceloakira GHCR_TOKEN=ghp_exemplo ./scripts/setup-homologacao.sh
```

The script does the following:
1. Checks dependencies (Docker, Compose, `jq`); configures `docker login ghcr.io` with the token;
2. Creates `.env` from `.env.example` (if it doesn't already exist), starts the container
   with the most recent image; and installs the **user timer** (`systemctl --user`),
   enabling linger and membership in the `docker` group, persisting the token in
3. `$STAGING_DIR/.env` (e.g., `/opt/acessilia/staging/.env`).

### Manual

```bash
# 1. Create the scripts directory
sudo mkdir -p /opt/acessilia/scripts

# 2. Copy the update script + wrapper (both are versioned in the repo)
sudo cp scripts/staging-update.sh /opt/acessilia/scripts/
sudo cp scripts/staging-update-wrapper.sh /opt/acessilia/scripts/
sudo chmod +x /opt/acessilia/scripts/staging-update.sh /opt/apacessilia/scripts/staging-update-wrapper.sh

# 3. Persist the GHCR token in staging's .env
#    (both wrapper and staging-update.sh load it from $STAGING_DIR/.env)
sudo tee /opt/acessilia/staging/.env > /dev/null << 'ENV'
GHCR_TOKEN=your_token_here
ENV
sudo chmod 600 /opt/acessilia/staging/.env

# 4. User-timer prerequisites
sudo loginctl enable-linger "$USER"          # timer survives logouts
sudo usermod -aG docker "$USER"              # lets the user timer talk to Docker daemon
# log out + log in again so the dock group applies

# 5. Create the service unit (user scope)
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/staging-update.service << 'SERVICE'
[Unit]
Description=Update acessilia staging container

[Service]
Type=oneshot
ExecStart=/opt/acessilia/scripts/staging-update-wrapper.sh
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
SERVICE

# 6. Create the timer unit (user scope, every 5 minutes)
cat > ~/.config/systemd/user/staging-update.timer << 'TIMER'
[Unit]
Description=Check acessilia staging updates every 5 minutes

[Timer]
OnBootSec=30s
OnUnitActiveSec=300s

[Install]
WantedBy=timers.target
TIMER

# 7. Enable it
systemctl --user daemon-reload
systemctl --user enable --now staging-update.timer
```

## Management

> A user-scope command uses `systemctl --user` (the timer runs in user scope).

```bash
# Show timer status
systemctl --user status staging-update.timer

# Last run state
systemctl --user status staging-update.service

# Logs of the last execution
journalctl --user -u staging-update.service -n 50 --no-pager

# Run manually (force update)
systemctl --user start staging-update.service

# Temporarily disable it
systemctl --user stop staging-update.timer

# Remove completely
systemctl --user disable --now staging-update.timer
rm ~/.config/systemd/user/staging-update.{service,timer}
systemctl --user daemon-reload
```

## Troubleshooting

### Container has not restarted

Check the service's log:

```bash
journalctl --user -u staging-update.service -n 50 --no-pager
```

Common causes:

| Symptom | Cause | Fix |
|---------|-------|-----|
| `pull access denied` | GHCR token expired | rerun `setup-homologacao.sh` |
| `jq: command not found` | `jq` is not installed | `sudo apt install jq` |
| `GHCR_TOKEN: parameter not set` | Token was never persisted | check `$STAGING_DIR/.env` (e.g., `/opt/acessilia/staging/.env`) |
| Docker gives `permission denied` | User is outside the `docker` group | `sudo usermod -aG docker $USER` + re-login |
| Timer doesn't run after logout | Linger is disabled | `sudo loginctl enable-linger $USER` |
| Nothing happens, SHA unchanged | No new commits on develop | wait for the next build |
| API fails (fallback enabled) | GitHub API unavailable | script falls back to a direct `docker pull` |
| `Container name already in use` | Containers with other names exist | `docker ps -a`, then `docker rm` |
