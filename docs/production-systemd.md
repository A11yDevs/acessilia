# Production preparation, activation and updater

Brazilian Portuguese: [production-systemd.pt-br.md](production-systemd.pt-br.md).

Production configuration and data must be reviewed before the 0.1.0 → 0.2.0
migration. Passing `docker compose config` validates configuration, not model
availability, data migration, document conversion or rollback.

## Why preparation and activation are separate

The old installer started `main` even with `--no-timer`, created `var` before
migration and could copy registry credentials into the application environment.
Production Compose also inherited the old AI client and used a bind that could
silently create an empty runtime directory. The revised installer only prepares
files, refuses overwrites, uses no sudo and never starts containers or timers.
`--no-timer` is now a preparation-only alias; calling setup without an explicit
preparation flag fails. Registry login and timer installation are separate.

## Prepare as the deployment user

An administrator first provisions the `acessilia` account, its writable home
`/opt/acessilia`, Docker access and linger. The deployment user does not need
sudo. From a reviewed release checkout, as that user:

```bash
bash scripts/setup-producao.sh --prepare-only --production-dir /opt/acessilia/core
```

The script creates private `.env`, `.deploy.env`, Compose and `ops/` files.
It creates no `var`. Existing destination files cause failure before copying.
The templates are `deploy/production.runtime.env.example` and
`deploy/production.deploy.env.example`.

Edit both files privately. `.env` contains only application settings: preserve
the real production bot, SMTP, public API/download URLs and observability
settings from the old environment, using `.env.example` as the full reference.
Review endpoints that still use `host.docker.internal` when transferring settings;
the production Compose preserves its `host-gateway` mapping for compatibility.
Set `TOOLBOX_API_KEY` to the new production Toolbox's key. Its defaults enable
dual Docling/MinerU fusion, PDDL execution and 3000-second model timeout.

`.deploy.env` contains the approved `PRODUCTION_IMAGE=ghcr.io/a11ydevs/acessilia@sha256:...`,
Toolbox endpoint/network and optional updater GitHub API token. Never copy that
token into runtime `.env`. Keep `.deploy.env` shell-compatible for the updater.
Use `docker login ghcr.io` as the deployment user for registry authentication.
The setup script no longer accepts token arguments or stores registry tokens.

## Toolbox and gateway prerequisites

Configure the separate production Toolbox project to join external network
`acessilia-production-backplane` with alias `toolbox-production`. Create the
network once before starting it. Core reaches `http://toolbox-production:8002`;
Toolbox, sidecars, MinIO and Valkey need no published host ports for this path.
`PRODUCTION_TOOLBOX_NETWORK` and `PRODUCTION_TOOLBOX_BASE_URL` configure another
approved topology. Existing core ports 8000/8001 remain published for compatibility
with the current proxy; validate public routes before changing their bindings.

Keep the gateway native on MV2 under `vlm-gateway`. Production Toolbox uses
`VLM_SERVE_URL=http://172.16.109.33:8002/v1/vlm` and the gateway's API key as
`VLM_API_KEY`; this differs from the core-to-Toolbox key. Environment Toolboxes
use concurrency 4, timeout 2700 s and local slot wait 120 s. Final gateway state:
one server process, global concurrency 2, model `--parallel 2`, model listening
only on loopback. Coordinate that change with staging and validate authenticated
model health and inference. This core PR does not modify MV2 or Toolbox deployment.

## Validate, migrate, then activate

Before downtime, run:

```bash
python3 /opt/acessilia/core/ops/production_deploy.py check
```

This resolves Compose without printing credentials and rejects mutable images,
deployment variables in runtime, missing keys, dry-run execution, incompatible
paths/ports or short gateway timeouts. `MODEL_CALL_TIMEOUT_SECONDS`,
`DATA_AGENT_TIMEOUT_SECONDS` and `TOOLBOX_TIMEOUT_SECONDS` must each be at least
3000 s, covering the environment Toolbox's 120 s wait plus 2700 s gateway call.
Measure peak memory/CPU with representative
dual-fusion documents before choosing resource caps. Core has bounded Docker
logs, a 60-second stop grace and an init process; none implements job draining.
Test shutdown/restart in staging. Preserve image/configuration/automation backups
and validate a working gateway route for rollback before the maintenance window.

Follow [the versioned migration guide](data-migration-0.1.0-to-0.2.0.md): block
every ingress including Telegram, drain queued and active jobs, stop the old core,
back up all data offline, dry-run/apply/verify migration and check UID permissions.
Do not manually create new `core/var` before migration. The bind refuses to create
it automatically. Directory existence alone does not verify migration.

After migration verification, as the deployment user:

```bash
cd /opt/acessilia/core
set -a
. ./.deploy.env
set +a
python3 ops/production_deploy.py check --require-data
docker compose -p production --env-file .deploy.env -f docker-compose.production.yml pull acessilia
docker compose -p production --env-file .deploy.env -f docker-compose.production.yml up -d --no-deps --wait --wait-timeout 120 acessilia
python3 ops/production_deploy.py verify-running --image "$PRODUCTION_IMAGE"
```

Verification checks actual image identity, `/api/v1/ready` for both structural
providers in dual mode, and `model_reachable=true` from `/api/v1/health` inside
the container. HTTP 200 alone does not prove model readiness. Finish with a real
document, all interfaces/exports, valid retained downloads and expired-token
rejection. Avoid printing tokens or full resolved Compose output.

These are **post-start checks, not a gate before traffic switches**. `up -d`
replaces the old container before dependency verification. If `--wait` or
`verify-running` fails, the new image may remain running and serving traffic.
Keep ingress blocked during migration acceptance; stop the production timer,
inspect the actual container and perform the manual rollback below when needed.
The updater reports the previous image ID on activation/verification failure.
It does not automatically restore that image or any data: reverting an image
alone may be incompatible with database changes or new writes.

## Existing timer and future automatic tracking

Keep the existing user timer disabled during migration, acceptance and manual
digest pinning. When recording the new layout, update its drop-in as `acessilia`:

```ini
[Service]
WorkingDirectory=/opt/acessilia/core
ExecStart=
ExecStart=/opt/acessilia/core/ops/production-update.sh
Environment=PRODUCTION_DIR=/opt/acessilia/core
Environment=STAGING_UPDATE_CACHE=/opt/acessilia/core/var/data/.last_production_sha
Environment=STAGING_STATUS_FILE=/opt/acessilia/core/var/data/production-status.json
```

Run `systemctl --user daemon-reload`; do not enable the timer yet. Production
updates now require separate `.deploy.env`, refuse manual/literal image pins,
fail closed if the GitHub commit cannot be resolved, pull its SHA artifact,
check its OCI revision and select its digest. They verify image/dependencies
before recording cache/status success and preserve rollback images. Staging's
existing branch selection and fallback behavior remain unchanged.

When the cached branch/commit still matches GitHub, production checks that the
container is running the digest recorded by the last accepted deployment. If it
matches, the updater only refreshes `last_check`, preserves `last_update`, and
does not pull, run Compose `up` or probe dependencies. A transient VLM outage
therefore does not fail an unchanged deployment check; dependency monitoring
remains separate. A missing/inconsistent status, stopped container or different
running digest takes the full deployment path. The GitHub commit lookup still
runs each tick to detect changes.

Future automatic tracking requires explicitly clearing `PRODUCTION_IMAGE`,
keeping reviewed `TRACK_BRANCH=main`, valid runtime settings and the shared
network, and an operational drain/maintenance policy. The updater does not drain
jobs or coordinate database migrations. Do not re-enable it merely because this
PR merges or BHS ends; production promotion and staging branch switching are
separate operations.

The `Production deployment validation` workflow runs the complete core,
docstruct and SDK suites inside the runtime image when its deployment-related
path filters match, or via manual dispatch. It does not run on every PR. The
regular CI workflow continues to run the suites on all supported PRs.

## Rollback

Stop the new core and restore the saved 0.1.0 image, original Compose/environment
and original data directory under project `production`. Never run 0.1.0 against
the migrated database or use the 0.2.0 Toolbox-specific Compose unchanged.
The old MV1 endpoint on port 80 already failed; validate a compatible authenticated
OpenRouter-style route through the gateway before cutover. Preserve exclusive
gateway access to the model during rollback. New 0.2.0 writes require explicit
reconciliation if rolling back; restoring an earlier dataset cannot retain them.
