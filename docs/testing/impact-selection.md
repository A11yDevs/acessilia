# Architecture-aware test selection (shadow mode)

> A Brazilian Portuguese translation is available in
> [impact-selection.pt-br.md](impact-selection.pt-br.md).

This is the next step of [issue #644](https://github.com/A11yDevs/acessilia/issues/644):
a selector that maps changed files to the component suites they can affect.
It runs in **shadow mode** on pull requests: it records what an impact-aware CI
would run, while the full suite remains the merge gate.

- **Script:** [`scripts/tests/select_suites.py`](../../scripts/tests/select_suites.py).
- **CI job:** `detect changed components (shadow)`, artifact
  `test-selection-shadow`.
- **Machine-readable output:** `var/selection.json`.

## Dependency model

The selection follows the dependency direction in
[dependencies.md](../architecture/dependencies.md) for the service/SDK/docstruct
edges and ADR-0016 for `libs/core`. In this document, **core** means
`libs/core` (`acessilia_core`), not the `backend/`/`frontend/` service:

| Changed component | docstruct | SDK | core | application |
|---|---:|---:|---:|---:|
| docstruct | required | required | required | required |
| SDK | — | required | required | required |
| core | — | — | required | required |
| backend/frontend/tests | — | — | — | required |
| schemas/contracts | required | required | required | required |
| shared CI/config | required | required | required | required |

A change in a consumer never forces the unit suite of its dependencies; a
change in a base library always selects its consumers.

## Rules

- `libs/docstruct/**` → docstruct, SDK, core, app.
- `libs/sdk/**` → SDK, core, app.
- `libs/core/**` → core, app.
- `backend/**`, `frontend/**`, `tests/**` → app.
- `docs/**` and `*.md` → app (the documentation/link/Portuguese guards live in
  the application suite).
- `.github/**`, `infra/**`, `schemas/**`, `scripts/**`, `deploy/**`, `Makefile`,
  `pyproject.toml`, `uv.lock`, `.python-version`, Docker Compose files → every
  suite. Nested `libs/*` files are not transversal unless they match a library
  rule.
- A path under top-level `schemas/` or a filename containing
  `toolbox-contract`/`capability_contract` sets `contracts_required` in addition
  to the suite selection.
- `integration_required` is set for `backend/**`, `frontend/**`,
  `libs/core/**`, `libs/sdk/**`, `libs/docstruct/**`, the focused
  `tests/test_provider_choice_methods.py` and its shared support
  (`conftest.py`, `judge_support.py`, `core_config_support.py`,
  `toolbox_render_fake.py`, `pyproject.toml`, `uv.lock`, the CI workflow).
  This mirrors the `app integration` trigger for pull-request path events; the
  selector is case-insensitive and its fallbacks are supersets. The globs live
  in `INTEGRATION_GLOBS`, and a workflow test compares them with the CI filter.
- Unknown paths, an empty diff or a failed `git diff` → every suite, the
  conservative flag and `integration_required`. Unknown paths set
  `unclassified_changed` rather than pretending to be infrastructure.

The script reports separate indicators
(`docstruct_changed`, `sdk_changed`, `core_changed`, `app_changed`,
`contracts_changed`, `infrastructure_changed`, `unclassified_changed`,
`integration_changed`) so the rules can be audited without reading the path
list.

## Shadow mode

The workflow job runs only on `pull_request`:

```bash
python scripts/tests/select_suites.py \
  --base-ref origin/develop --head-ref HEAD \
  --output var/selection.json \
  --summary "$GITHUB_STEP_SUMMARY"
```

The job requires `fetch-depth: 0` and fetches the base branch before the
three-dot diff. No job depends on it; the delivery gate does not include it. The
fetch/select steps are `continue-on-error` so unavailable evidence cannot turn a
pull request red.

Locally:

```bash
python scripts/tests/select_suites.py \
  --changed-file libs/core/src/acessilia_core/config.py

python scripts/tests/select_suites.py \
  --changed-file backend/api/app.py --changed-file libs/sdk/README.md
```

## Adoption criteria

The selector becomes a gate only after the observations show, over a
representative set of pull requests:

- no regression that the full suite would have caught was skipped;
- contract and architecture guards remain mandatory;
- transversal changes consistently select every suite;
- the wall-clock and runner-minute savings justify the extra job;
- the matrix is updated when a new component or dependency edge appears.

Until then, the full suite is mandatory and this job is evidence only.

## Limitations

- The matrix is a static model, not a runtime dependency graph. A new import
  that crosses a component boundary must be reflected here and in
  `dependencies.md`.
- A path-only selector cannot see generated files that are not committed.
- Deletions and renames are expanded (`--no-renames`, `ACMRDT`) so both sides
  are classified.
- Documentation changes are conservatively sent to the application suite.
- `git diff` is three-dot: a stale base ref or a shallow checkout triggers the
  conservative fallback.
