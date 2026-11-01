# Core data migration: 0.1.0 to 0.2.0

Brazilian Portuguese: [português brasileiro](data-migration-0.1.0-to-0.2.0.pt-br.md).

## Contract

`scripts/migrations/v0_1_0_to_v0_2_0.py` and its adjacent versioned SQL schema
export a new runtime dataset. They use only Python 3.11+ standard-library modules,
so they can run on an administrator's host without installing either application.
Copy both files together when transferring them to a platform.

The migration unit is a **published download and its supporting records**:

- Keep download tokens issued within the last seven days (168 hours in UTC),
  including the exact cutoff to match the existing download service. Preserve
  tokens, owner, task ID, filename, formats and the original issuance instant.
  Migration does **not** grant another seven days; the normal 0.2.0 download
  expiry remains in effect after startup.
- Copy only files published by live tokens, including legacy plain PDF and ZIP.
  A file's modification time never overrides its token's validity. When an
  expired token and a live token share a directory, expired-only files are omitted.
  A shared file still needed by a live token is retained.
- Keep history from the same seven-day window, plus older history referenced by
  a live download. Keep OCR records belonging to those tasks. Supporting records
  inherit their asset's retention; this avoids dangling references when a job
  started earlier than its download was issued.
- Recent unfinished history without a live download is exported as `error`,
  with `Stale: process interrupted` and the migration time as completion time.
  Only the destination is repaired; neither simulation nor application changes
  the rollback source or resumes jobs. `rows.conversoes.interrupted` reports
  these rows, even in dry run. Creation times and the seven-day cutoff stay unchanged.
- Exclude expired tokens, unrelated old history/OCR, unreferenced outputs, caches,
  logs, uploads and temporary work files. Rebuild caches under the new version.
  Do not invent durable job credentials or resume 0.1.0 in-memory jobs.

The source adapter recognizes the core schema in production commit
`535b22e9b07a99b3090e2fcfc6862299de2b5c69`, also supporting older token tables
without `formats`, `task_id` or `owner`. Unknown tables or columns are refused
instead of silently dropped. New storage changes require another versioned
adapter; do not edit an already deployed migration to reinterpret old datasets.

## Preconditions

1. Disable the deployment updater and keep it disabled throughout migration.
2. Preserve the old image, Compose, environment and automation configuration.
3. Stop accepting submissions through **all** interfaces, including Telegram;
   drain queued and running jobs, then stop the old container. A zero health
   queue size alone does not establish that no job is executing.
4. Take a consistent, full rollback backup of `var` while the application is
   stopped. The selective migration does not replace that backup.
5. Run simulation and application against the stopped source or an offline,
   consistent copy. SQLite is read through its backup API, including committed
   WAL transactions; copying just a live `.db` file is insufficient.

Nonterminal history referenced by a live download, future timestamps, missing
published files, unsafe paths or symlinks block migration. Resolve inconsistent
retained data on a separate working copy, preserving the original for rollback.
Database and file changes detected during copying also abort publication.
These checks do not replace quiescing all writers: row age cannot prove a job
has stopped, so even recent interrupted rows require the offline precondition.

Unparseable timestamps are counted under `rows.<table>.invalid_timestamps` and
excluded when they cannot support a live download. For tokens this uses the same
SQLite comparison as the application: NULL, empty or old invalid values that
fail that predicate are dropped. Malformed text such as `not-a-date` can pass
SQLite's textual comparison; it remains a blocker to avoid silently discarding
an accessible link. Unreferenced history with invalid dates is excluded; invalid
history supporting a retained token must be investigated on a working copy.

## MV1 procedure

All commands below run as root on MV1. Store the two migration files at
`/opt/acessilia/migrations/`. The existing dataset stays at
`/opt/acessilia/production/var`; the new one will be `/opt/acessilia/core/var`.
Create only the parent directory: the destination `var` must **not** exist.

```bash
install -d -m 700 /opt/acessilia/core
chown --reference=/opt/acessilia/production /opt/acessilia/core

python3 /opt/acessilia/migrations/v0_1_0_to_v0_2_0.py \
  --source-var /opt/acessilia/production/var \
  --destination-var /opt/acessilia/core/var \
  --dry-run
```

Review the JSON counts of retained/excluded rows, file count and bytes to copy.
The summary omits bearer tokens, owners and document filenames. Dry run neither
creates the destination nor changes source records. Each run computes its cutoff
once; simulation is informational and does not freeze validity for later runs.

Apply only after the preconditions above have been met:

```bash
python3 /opt/acessilia/migrations/v0_1_0_to_v0_2_0.py \
  --source-var /opt/acessilia/production/var \
  --destination-var /opt/acessilia/core/var \
  --apply

python3 /opt/acessilia/migrations/v0_1_0_to_v0_2_0.py \
  --destination-var /opt/acessilia/core/var \
  --verify

chown -R --reference=/opt/acessilia/production/var /opt/acessilia/core/var
```

Ownership is inherited from the existing deployment, without assuming a user or
group named `acessilia`. Confirm that the container's effective UID/GID can read
and write the new bind mount; if changing its runtime user, adapt ownership to
that planned UID/GID before startup.

Both versions mount host `var` at `/app/var`, the default runtime root. Therefore,
changing the host installation directory preserves runtime paths. For a different
runtime layout, set `--source-runtime-var` and `--destination-runtime-var`; these
are paths **inside the application runtime**, not necessarily host paths. Relative
`var/...` references and absolute source-host references are adapted as well.

Application builds a fresh database and files in a private sibling staging
directory, checks hashes, then publishes by directory rename. It never overwrites
an existing destination; a repeated invocation fails safely. Failed staging is
removed on ordinary errors; after a forced kill, an unexposed
`.var.migration-*` directory may require administrator cleanup. Do not activate it.

The new database records the migration ID, UTC reference instant and cutoff.
`migration-0.1.0-to-0.2.0.json` records file/database checksums. It is private
(0600, directories 0700), and includes internal file paths; do not publish it.
`--verify` is a **pre-startup** audit: application writes can legitimately change
the database checksum afterward. It verifies local consistency, not proxy routing.

## Switch Compose and the updater to the new directory

Prepare the reviewed configuration **before** the offline migration, following
[production preparation and activation](production-systemd.md). The setup script
only prepares files, uses a separate `.deploy.env`, and never creates `core/var`.
Preserve the real production runtime credentials and public routes; do not copy
staging credentials or inject registry/update secrets into the application.

After applying and verifying migration and UID permissions, follow that guide's
activation commands with `--env-file .deploy.env`, the approved image digest and
project `production`. It also describes the new updater drop-in and readiness/
model checks. Keep the timer disabled. Do not use the old installer to start
`main` or manually create a runtime directory before migration.

## Acceptance and rollback

Mount `/opt/acessilia/core/var` at `/app/var` in the 0.2.0 core and configure its
own environment separately from the Toolbox. Preserve the public hostname and
download routes used by existing links. Validate several existing download pages
and actual file downloads, including a plain PDF if one exists, then confirm an
expired token is rejected. Test download access without exposing tokens in logs.

The tests exercise the legacy schema, expiration boundary, path changes, failures,
shared directories and actual 0.2.0 API downloads:

```bash
python -m pytest -q tests/test_data_migration.py \
  tests/test_download_token_service.py tests/test_cleanup_service.py
```

Run these in the project's test container before merging, per the constitution.

For rollback, stop 0.2.0 and restore the preserved 0.1.0 image, configuration and
its original dataset. Do not point 0.1.0 at the migrated database. New 0.2.0 writes
are not reverse-migrated by this script; preserve them separately before rollback.
Restore the original updater configuration/scripts (including replacing or
removing `migrated-core.conf`) and reload the user's systemd manager before any
timer is resumed, so rollback automation points back to `production/var`.
Old installation and full backups remain untouched for recovery, so total host
disk usage only decreases after administrators retire them under their backup
policy. This migration performs no destructive source or backup cleanup.
