# Staging × code consistency report

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](staging_consistency.pt-br.md)
Date of capture: 2026-10-14. Host: `proj028-vm3@200.137.215.135`
(homologation). All staging probes in this report were read-only.

## What was compared

| Artifact | Source |
|---|---|
| `develop` HEAD | `A11yDevs/acessilia` @ local checkout |
| Running core image | `/api/v1/health` on `localhost:8000` (inside the host) |
| Running Toolbox image | `/v1/health`, `/v1/capabilities`, `/v1/providers` on `localhost:8002` |
| Staging configuration | `/opt/acessilia/staging/.env` (keys only, values redacted) |
| Update bookkeeping | `/opt/acessilia/staging/var/data/staging-status.json` |

## Findings

### S1 — The running core reports no build identity (high)

```json
{"status":"ok", ..., "git_commit":"", "image_tag":"", "image_digest":"",
 "container_id":"110b236abfc3", "ghcr_latest_sha":"", "last_check":"2026-10-14T11:47:21Z",
 "last_update":"", "update_available":false, "up_to_date":false}
```

`git_commit`, `image_tag` and `image_digest` are all empty, so there is **no way to
prove which commit is running** in homologation. The whole purpose of
`/api/v1/health`'s build fields and of the `fix/health-ghcr-digest` work is
defeated in practice.

Cause: the staging image is built by the tag-triggered path, which never passes the
build args that `infra/Dockerfile` declares:

- `infra/Dockerfile` (lines 74-80) declares `ARG GIT_COMMIT`, `ARG IMAGE_TAG` and
  `ARG IMAGE_DIGEST`, exported as `ENV`.
- `.github/workflows/delivery.yml` passes `GIT_COMMIT` and `IMAGE_TAG` **only** to the
  verification build; the *publish* step (the one that produces the tags staging
  pulls) passes no `build-args` at all.
- `.github/workflows/release.yml` passes no `build-args` either, so release images
  are identical in this respect.

### S2 — `update_available` / `up_to_date` can never become true (medium)

`staging-status.json` on the host shows `running_digest` and `latest_digest` as empty
strings:

```json
{"latest_sha": "e08e2b4e...", "running_sha": "", "last_check": "2026-10-14T11:47:21Z",
 "last_update": "", "latest_digest": "", "running_digest": ""}
```

`backend/api/routes/health.py` computes
`update_available = bool(ghcr_latest and running_digest and ghcr_latest != running_digest)`.
With `ghcr_latest` empty the expression is always false, so `up_to_date` is always
false too.

Cause: `scripts/staging-update.sh` only computes the digests in the *update* path,
after detecting a new commit. On the "no new commit" path (line ~162) it writes the
status with empty digests. Since the digest comparison cannot work without the GHCR
side being fetched, the check is structurally unable to report "up to date".

### S3 — The Toolbox image reports no build identity (medium)

```json
{"status":"healthy","version":"0.1.0"}
```

`/v1/health` returns only the static `__version__` from
`src/acessilia_toolbox/__init__.py`. `GIT_COMMIT` and `IMAGE_TAG` **are** passed as
`ENV` by that repository's `Dockerfile` (lines 13-15), but nothing reads them. The
core can prove its commit once S1 is fixed; the Toolbox cannot.

### S4 — The capability contract is broken between the deployed pair (high)

Against the running Toolbox (26 capabilities, 25 providers):

```
7 contract violation(s):
  - core consumes capability 'document.adjudicate.page'  but the Toolbox does not expose it
  - core consumes capability 'document.adjudicate.region' but the Toolbox does not expose it
  - core consumes capability 'document.ocr.page'          but the Toolbox does not expose it
  - core consumes capability 'document.orientation.detect' but the Toolbox does not expose it
  - core default TOOLBOX_ADJUDICATE_PROVIDER   -> provider 'qwen3-vl-judge'      not registered
  - core default TOOLBOX_PAGE_OCR_PROVIDER     -> provider 'qwen3-vl-page'       not registered
  - core default TOOLBOX_ORIENTATION_PROVIDER  -> provider 'rapidocr-orientation' not registered
```

Reproduce with:

```bash
python scripts/check_capability_contract.py --snapshot tests/fixtures/toolbox-contract.json
```

The four missing capabilities are the PR #125 clients (`toolbox_page_ocr_client.py`,
`toolbox_adjudicate_client.py`, `toolbox_orientation_client.py`), which have no
production caller. The VLM provider profile that would serve them exists only as
`scripts/drbench/experiments/slurm/providers-config-vlm.yaml` inside the *core*
repository, never in the Toolbox catalogue the image is built from.

### S5 — Staging tracks `develop` but its `.env` carries per-host divergence (informational)

Non-secret values from `/opt/acessilia/staging/.env`:

```
TRACK_BRANCH=develop
SCRIPT_UPDATE_BRANCH=fix/health-ghcr-digest
PIPELINE_ENGINE=pddl
TOOLBOX_PROVIDER=docling
TOOLBOX_BASE_URL=https://www.acessilia3.inf.ufg.br/toolbox
STRUCTURER=toolbox        # declared twice in the same file; the second wins
AI_CLIENT=openrouter
OPENROUTER_MODEL=qwen3-vl-8b
LOCALE=pt_BR
LOG_LEVEL=DEBUG
```

Two notes:

- `STRUCTURER` appears twice. The effective value is `toolbox`, which is right for the
  PDDL pipeline, but the duplicate is a latent trap for whoever edits the file next.
- `TOOLBOX_BASE_URL` points at the public reverse-proxy URL
  `https://www.acessilia3.inf.ufg.br/toolbox`. With `PIPELINE_ENGINE=pddl` and
  `STRUCTURER=toolbox`, **every** document processed in homologation delegates its
  structural extraction back out through the public proxy instead of using the
  Toolbox container on the same host. This is worth confirming as intentional; a
  loopback URL would remove an unnecessary external dependency from the critical path.

## What is consistent

- `PIPELINE_ENGINE=pddl`, matching the compose file's forced value.
- `TOOLBOX_PROVIDER=docling` is a registered Toolbox provider.
- The Toolbox capabilities that the core *does* reach through the supported paths
  (`document.structure.extract`, `document.layout.analyze`, `document.ocr`,
  `math.recognize`, `math.convert`, `math.verbalize`, `pdf.split`, `pdf.render`,
  `media.inspect`, `artifact.store`, `artifact.retrieve`, `dataset.*`) all exist.
- The seven Toolbox capabilities with no core client are a product decision, not a
  deployment fault; they are tracked in
  `docs/toolbox_capability_matrix.md`.

## Follow-up

S1, S2 and S3 are reproduced and fixed by the homologation consistency work
(`fix/health-build-info`, `fix/staging-digest-status`,
`fix/toolbox-health-build-info`). S4 is the integration review's subject and is
pinned by `tests/test_toolbox_contract_drift.py`. S5 is documented here and needs a
product decision on the Toolbox URL.
