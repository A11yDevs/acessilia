# Staging environment with a systemd timer

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](homologacao-systemd.pt-br.md)

The staging (homologation) server runs from a **clone of this repository**. The clone holds
the scripts, `docker-compose.staging.yml`, `.env` and `var/`; the containers run the images
CI publishes on GHCR. A **systemd user timer** checks the tracked branch every 5 minutes via
the GitHub API and updates the container once the image of a new commit is published.

Everything goes through `scripts/ops.sh`:

| Command | What it does |
|---------|--------------|
| `./scripts/ops.sh auto-update setup` | Starts the stack and installs the timer |
| `./scripts/ops.sh auto-update status` | Clone branch, tracked branch, timer, last check, health, recent runs |
| `./scripts/ops.sh auto-update start` | Updates now (what the timer runs) |
| `./scripts/ops.sh track [<branch>]` | Follows a branch: `git pull` of the clone and `TRACK_BRANCH` in `.env`, then updates; without a branch, pulls the tracked one |
| `./scripts/ops.sh auto-update migrate <dir>` | Moves an install made by the former `setup-homologacao.sh` into the clone |

## Overview

```
Every 5 minutes → acessilia-staging-update.timer (user)
                    ↓
<clone>/scripts/ops.sh auto-update start
                    ↓
staging-update.sh: GitHub API → SHA of the last commit on the tracked branch
                    ↓
SHA changed and sha-<7> image on GHCR? → docker compose pull + up -d
                    ↓
container restarted 🚀
```

The tracked branch is `develop`, or `TRACK_BRANCH` from `.env` during the BHS cycle
(`release/x.y.z`). The clone's branch and `TRACK_BRANCH` always move together through
`ops.sh track`: the scripts and the compose file come from the clone, the image from
`TRACK_BRANCH`. `auto-update status` warns when they differ.

## Prerequisites

- Docker and Docker Compose, `git`, `curl` and `jq` (`sudo apt install jq`)
- `docker login ghcr.io` with a token with the `read:packages` scope (create it at
  https://github.com/settings/tokens/new?scopes=read:packages)
- `setup` enables, with `sudo`, **linger** for the user (the timer survives logout) and
  membership in the **`docker` group** (the timer reaches the Docker daemon without `sudo`;
  log out and back in once it is added)

## First install

```bash
git clone https://github.com/A11yDevs/acessilia.git
cd acessilia
cp .env.example .env              # fill in the credentials (AI, Telegram, SMTP...)
./scripts/ops.sh auto-update setup
```

`setup` sets `COMPOSE_PROJECT_NAME=acessilia-staging` in `.env`, so the containers belong
to the same compose project whatever the clone's directory is called, then starts the stack
and enables `acessilia-staging-update.timer`.

## Migrating from `/opt/acessilia/staging`

Installs made by the former `setup-homologacao.sh` copied the scripts to
`/opt/acessilia/scripts` and kept `.env` and `var/` in `/opt/acessilia/staging`. To move
one into a clone:

```bash
git clone -b release/0.2.0 https://github.com/A11yDevs/acessilia.git ~/acessilia
cd ~/acessilia
./scripts/ops.sh auto-update migrate /opt/acessilia/staging
```

`migrate` copies `.env` (refusing to overwrite a different `.env` in the clone) and `var/`
(stopping the container meanwhile), keeps the compose project name of the running container
so compose takes it over instead of clashing with it, removes the old `staging-update` timer,
checks out the branch in `TRACK_BRANCH` and runs `setup`. `/opt/acessilia/staging` is left
untouched; remove it once staging works.

## Updating the scripts

`ops.sh track` without a branch runs `git pull` on the branch already tracked and updates:

```bash
./scripts/ops.sh track
```

`track` refuses to run when tracked files in the clone have local changes, so the server
never drifts from the repository.

## Management

```bash
./scripts/ops.sh auto-update status          # overview
./scripts/ops.sh auto-update start           # update now
journalctl --user -u acessilia-staging-update.service -n 50 --no-pager
systemctl --user stop acessilia-staging-update.timer     # pause updates
systemctl --user start acessilia-staging-update.timer    # resume them
```

To test a locally built image, stop the timer first: otherwise the next update pulls the
GHCR image over it.

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `pull access denied` | GHCR token expired | `echo <token> \| docker login ghcr.io -u <user> --password-stdin` |
| `jq: command not found` | `jq` is not installed | `sudo apt install jq` |
| Docker gives `permission denied` | User is outside the `docker` group | log out and back in after `setup` |
| Timer doesn't run after logout | Linger is disabled | `sudo loginctl enable-linger $USER` |
| `image sha-xxxxxxx not yet published` | CI is still building the commit | wait for the next check |
| API fails (fallback enabled) | GitHub API unavailable | the script falls back to a direct `docker pull` |
| `Container name already in use` | Another compose project owns the container | set `COMPOSE_PROJECT_NAME` in `.env` to that project (`docker inspect acessilia-staging --format '{{ index .Config.Labels "com.docker.compose.project" }}'`) or use `auto-update migrate` |
