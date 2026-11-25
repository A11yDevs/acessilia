# Automated Test Suite (tests)

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](README.pt-br.md)

The project's unit test suite covers the canonical pipeline, PDDL engine, API and exporters. Everything is fast and isolated: files go to temporary directories; network and LLM calls are mocked, and async flows run with `pytest-asyncio`.

The merge gate is CI, which runs the non-E2E main, docstruct, SDK and core
library suites on Python 3.12 in the root `uv.lock` environment. Additional jobs test the libraries
in isolation from their own locks. The production image carries runtime
dependencies and passes build, startup and API health smoke checks before
publication. See the [constitution's testing strategy](../docs/constitution.md#3-architectural-quality-rules).

Issue #342 regressions cover list continuations across paragraphs and tables with explicit consecutive numbering. The math scorecard separates runs at changes of source parent without matching continuation numbering, explicit restarts, style changes, numbering gaps, headings, page boundaries, and blocks other than paragraphs, tables or formulas. Legacy adjacent blocks without parent metadata retain their grouping. TXT/MP3 continue to use enriched speech under ADR-0011; use the current dataset expectations, which accept the spoken negative sign.

## Running

The supported local loop is described in [docs/testing.md](../docs/testing.md):

```bash
# Everything CI runs, non-E2E (main suite, docstruct, SDK and libs/core)
make test-all

# One file or one node id
make test-file F=tests/test_pddl_planning.py

# Rerun the tests that failed last time
make test-failed
```

The equivalent pytest commands:

```bash
# Native
uv run pytest

# A single file only
uv run pytest tests/test_pddl_planning.py
```

## Fixtures

`fixtures/` holds sample PDFs and images, used both by the tests and by the load scenarios and benchmarks in `scripts/`. `fixtures/failures/` holds inert corrupt documents used by `test_job_failure_e2e.py` to reproduce a pipeline failure and the failure e-mail; see its [README](fixtures/failures/README.md). No debug switch is involved: the files live only in the test tree.

## Legacy canonical type compatibility

E1.3 compatibility is covered by
`libs/docstruct/tests/test_legacy_canonical_types.py`: deprecated metadata, root
reexport identity, constructor/field compatibility, defaults, serialized state,
loading a pre-deprecation 0.5.2 pickle, and cold imports/construction with
warnings treated as errors. These tests run against the installed wheel too.
The existing type and export characterization suites retain their coverage.
See [ADR 0024](../docs/adr/0024-legacy-canonical-type-deprecation.md).

## Canonical schema contract

The canonical schema contract is checked separately:
`libs/docstruct/tests/test_schema_validation.py` covers the bundled draft,
injected validator, failure propagation and builder output including children;
`libs/core/tests/test_canonical_schema_contract.py` checks the root copy, core builder and
continued export acceptance of custom block types. CI also validates the schema
from the installed wheel outside the checkout. `jsonschema` is dev-only in
docstruct; the standard-library runtime and infrastructure guards still run,
with the fixed package-resource exception recorded in ADR 0023.

Regenerate/check the historical root schema after editing the package source:

```bash
uv run python scripts/sync_accessible_document_schema.py
uv run python scripts/sync_accessible_document_schema.py --check
```

Core 0.2.0 applies schema validation after normalization/audit and before profile
selection. `libs/core/tests/test_export_schema_gate.py` exercises 68 old/new format outcomes,
normalization, nested/filtered cases, no renderer side effects in direct Core
calls and localized diagnostics. The worker regression observes job-directory
creation before export, schema rejection and removal afterward, plus error
history and no download registration.
See the [compatibility corpus](fixtures/export_schema_gate/README.md) and the
[schema API](../libs/docstruct/README.md#canonical-schema-docstructschemas-docstructvalidation).

## Export characterization

The export parity baseline for #371 lives in
[`fixtures/export_snapshots/`](fixtures/export_snapshots/README.md).
`libs/docstruct/tests/test_export_characterization.py` freezes the four pure
export APIs, their current omission/filter policies and both Pandoc targets.
It runs natively, against the isolated wheel and in a locked CI container.
Keep its golden files unchanged during the walker extraction/migration.

`test_export_walk.py` checks the E1.6 traversal, per-type dispatch, fallback,
selection and context metadata. For E1.7, `test_export_walk_parity.py` observes
all 30 characterized calls using the production walker and checks that rendering
goes through the eleven callbacks and explicit fallback. It replaces the former
test-only traversal substitutions. It also preserves the existing rejection of
unhashable block kinds in TXT/HTML/Pandoc, acceptance in Markdown, and filtering
before rejection. The unchanged golden gate still checks exact output and the
distinct title/child-label policies. These tests run in the same locked container.
See the [walker API](../libs/docstruct/README.md#export-walker-docstructexportwalk).

## End-to-end tests

Tests marked with `-m e2e` are excluded from CI and need a live environment:

```bash
# Toolbox only (existing suite)
TOOLBOX_BASE_URL=https://toolbox.example/toolbox \
TOOLBOX_API_KEY="$TOOLBOX_API_KEY" \
uv run pytest -m e2e -v --timeout=900

# Deployed core API as well (tests/test_core_api_e2e.py)
CORE_BASE_URL=https://core.example/api/v1 \
CORE_EXPECT_BUILD_INFO=1 \
uv run pytest -m e2e -v --timeout=900
```

`--timeout=900` overrides the suite-wide 180-second limit: E2E operations can
take up to 300 seconds and a core job wait up to 600. The scheduled E2E job uses
the same value. The full-deck slide case is the exception: it uses
`CORE_SLIDE_TIMEOUT` (default 10800 s) and marks itself for that wait plus 600 s.

The `Scheduled test monitoring` workflow runs the E2E suite weekly when the
repository variables `TOOLBOX_BASE_URL` or `CORE_BASE_URL` are configured. It
uses the optional `TOOLBOX_API_KEY` secret and the `CORE_EXPECT_BUILD_INFO`
variable; the optional dataset corpus is not cloned there, so those cases skip.
E2E is a scheduled validation, not a merge gate.

`tests/test_core_api_e2e.py` skips only while `CORE_BASE_URL` is unset. Once it
is set, an unreachable core or an unhealthy `/health` fails the run: a skipped
suite must not pass during a real outage. A job left without a terminal state
is cancelled at the end of the wait.

Some E2E tests need the optional corpus from
[A11yDevs/acessilia-dataset](https://github.com/A11yDevs/acessilia-dataset).
It is a separate clone, ignored by Git, placed at `tests/dataset/`; point
`ACESSILIA_TEST_DATASET_DIR` elsewhere instead of copying it into the checkout.

- `test_compare_pipelines_e2e.py` reads `input/00{1,4,5,7,8}.*` and
  `intermediate/canonical-document/*.json`; without the clone, its 25
  reference-based cases are skipped.
- `test_math_case_e2e.py` reads `input/math-reference/` from the dataset branch
  `feat/036-velocidade-instantanea`; it is not on the dataset's `main`.
- `test_slide_case_e2e.py` reads `input/presentation-reference/` (the 006
  deck, issue #615) from the dataset's `main` and uploads the byte-identical
  copy in `fixtures/presentations/`. It makes one full-deck job, so
  `CORE_SLIDE_TIMEOUT` (default 10800 s) bounds the wait; its scorecards and
  outputs go to `var/bench/slides/e2e/`.

To run those cases against a clone kept in the main checkout:

```bash
git clone https://github.com/A11yDevs/acessilia-dataset.git tests/dataset
git -C tests/dataset archive origin/feat/036-velocidade-instantanea \
    input/math-reference | tar -x -C tests/dataset

ACESSILIA_TEST_DATASET_DIR="$PWD/tests/dataset" uv run pytest -m e2e -v
```

## Related documentation
- [Local test workflow](../docs/testing.md) — `make` commands, baseline timings and timeouts
- [Architecture](../docs/architecture.md)
- [PDDL + Agno pipeline](../docs/pddl_pipeline.md)
- [Internationalization (i18n)](../docs/i18n.md) — see the internationalization test suite in [test_i18n.py](test_i18n.py)

## Format catalogue compatibility

`test_export_catalog.py` freezes the E1.9 download identities, wire labels, MIME
types, filenames, distinct delivery roles, SDK references and worker plan.
`test_download_token_service.py` checks existing files, including legacy PDF,
in both locales. `test_web_panel.py` excludes internal and experimental entries
from the offered formats. Worker regressions cover mandatory TXT/HTML/ZIP
failures, optional benchmark/remote/audio failures, flags, completed format
order and archive entry order. `libs/docstruct/tests/test_format_spec.py` runs
against the standalone wheel too. Existing E1.0 goldens remain unchanged. See
[ADR 0025](../docs/adr/0025-format-catalogue-ownership.md).
