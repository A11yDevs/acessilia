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
| `./scripts/ops.sh auto-update check` | Verifies the timer (installed for this clone, enabled, old timer gone), its recent runs (last one succeeded, last check recent, latest commit deployed) and the deployment (branch, container, image, health); exit status 1 on a problem |
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
- The user that runs the timer needs, granted once by an administrator:
  - membership in the **`docker` group** (`usermod -aG docker <user>`, then log in again):
    `setup` and `migrate` refuse to run without access to the Docker daemon;
  - **linger** (`loginctl enable-linger <user>`), so the timer keeps running after logout:
    `setup` warns when it is off.

  `ops.sh` never calls `sudo`; if something must run as root, run that command (or
  `ops.sh` itself) as root.

  A session opened with `su` has no `XDG_RUNTIME_DIR`; `ops.sh` then uses
  `/run/user/<uid>` by itself. When that does not exist either (no linger, no login),
  `setup` and `migrate` stop and say so.

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

`migrate` first checks everything it needs: that it can read the old `.env` and all of
`var/` (it lists what it cannot read), that the clone has no different `.env`, that the
branch in `TRACK_BRANCH` can be checked out, and that Docker and the user's systemd instance
are reachable. Any failure stops it before anything changes, and a run interrupted later can
simply be repeated. It then disables the old `staging-update` timer (stopping if it cannot),
copies `.env` and `var/` (stopping the container meanwhile), moves staging to its own compose
project `acessilia-staging` — replacing the old container, whose data is now in `./var` —
checks out the branch in `TRACK_BRANCH` and runs `setup`. The old installs kept Acessilia
and the Toolbox in one project named `staging`; leaving it means a `--remove-orphans` here
can no longer delete the Toolbox's containers. `/opt/acessilia/staging` is left
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
./scripts/ops.sh auto-update check           # pass/fail verdict on the timer and its runs
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
| `acessilia-staging belongs to compose project '…' (dir)` | Another install owns the container | `./scripts/ops.sh auto-update migrate <dir>` |
