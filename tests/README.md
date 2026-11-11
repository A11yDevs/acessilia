# Automated Test Suite (tests)

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](README.pt-br.md)

The project's unit test suite covers the canonical pipeline, PDDL engine, API and exporters. Everything is fast and isolated: files go to temporary directories; network and LLM calls are mocked, and async flows run with `pytest-asyncio`.

By constitution, the gate is the container: tests must pass inside Docker (production equivalent) before a merge. The native run is secondary verification.

Issue #342 regressions cover list continuations across paragraphs and tables with explicit consecutive numbering. The math scorecard separates runs at changes of source parent without matching continuation numbering, explicit restarts, style changes, numbering gaps, headings, page boundaries, and blocks other than paragraphs, tables or formulas. Legacy adjacent blocks without parent metadata retain their grouping. TXT/MP3 continue to use enriched speech under ADR-0011; use the current dataset expectations, which accept the spoken negative sign.

## Running

```bash
# Native
uv run pytest

# A single file only
uv run pytest tests/test_pddl_planning.py

# Container (the gate — the `test` stage of infra/Dockerfile)
docker build -f infra/Dockerfile --target test -t acessilia:test-docling .
docker run --rm -v "$PWD:/app" -w /app acessilia:test-docling pytest tests/
```

## Fixtures

`fixtures/` holds sample PDFs and images, used both by the tests and by the load scenarios and benchmarks in `scripts/`. `fixtures/failures/` holds inert corrupt documents used by `test_job_failure_e2e.py` to reproduce a pipeline failure and the failure e-mail; see its [README](fixtures/failures/README.md). No debug switch is involved: the files live only in the test tree.

## End-to-end tests

Tests marked with `-m e2e` are excluded from CI and need a live environment:

```bash
# Toolbox only (existing suite)
TOOLBOX_BASE_URL=https://toolbox.example/toolbox \
TOOLBOX_API_KEY="$TOOLBOX_API_KEY" \
uv run pytest -m e2e -v

# Deployed core API as well (tests/test_core_api_e2e.py)
CORE_BASE_URL=https://core.example/api/v1 \
CORE_EXPECT_BUILD_INFO=1 \
uv run pytest -m e2e -v
```

`tests/test_core_api_e2e.py` skips only while `CORE_BASE_URL` is unset. Once it
is set, an unreachable core or an unhealthy `/health` fails the run: a skipped
suite must not pass during a real outage. A job left without a terminal state
is cancelled at the end of the wait.

The Core owns five historical canonicals (`001`, `004`, `005`, `007`, `008`)
in `tests/fixtures/pipeline-comparison/`, from Dataset revision
`9ed07b28aeddb69721228f2dd66de6f9794c0001`, schema `1.0.0`. The offline
integrity test checks the canonicals without Toolbox. The pinned Dataset smoke
test and pipeline comparison E2E verify the hashes of the corresponding
inputs in the Dataset checkout.

The math and presentation readers use the Dataset `references/manifest.csv`
contract (schema `1.2.0`). CI checks out the pinned consumer revision
`c436966d4fd051a2287273e471b4a3565d64a27a` and runs a smoke test that validates
the manifest, selectors, schemas, row counts, and both cases without a Toolbox.
The expected revision and reference digest live in
[`scripts/bench/dataset.lock.json`](../scripts/bench/dataset.lock.json).

For local reader runs, `--dataset` and `ACESSILIA_TEST_DATASET_DIR` still accept
any compatible directory, including an exported tree without `.git`. A valid
new `references/manifest.csv` takes precedence over the legacy case layout; an
invalid new manifest or missing required reference is an error and does not
fall back to legacy files. To run the pinned math E2E case, clone the Dataset
revision into `tests/dataset` or point the environment variable at that
revision:

```bash
git clone https://github.com/A11yDevs/acessilia-dataset.git tests/dataset
git -C tests/dataset checkout c436966d4fd051a2287273e471b4a3565d64a27a

ACESSILIA_TEST_DATASET_DIR="$PWD/tests/dataset" uv run pytest -m e2e -v
```

The historical pipeline comparator is a heuristic over canonical schema
`1.0.0`, not a structural or content-fidelity proof. Its current protocol
does not count canonical `math` blocks as formulas, does not read `table_ast`
cells when extracting text, and uses word-set similarity plus block-count
tolerances. Changes to this protocol need their own version and regression
cases; moving the fixtures must not regenerate them.

Generated evaluation artifacts stay together under the per-run directory in
`var/bench/`. They include the input/output snapshots available to that run,
scorecards, effective Dataset revision and digest, selection, protocol, and
configuration. Retention is operator-managed: there is no automatic pruning
or observability export. Artifacts may contain source documents and model
responses, so retain them according to the storage policy for that data.

## Related documentation
- [Architecture](../docs/architecture.md)
- [Benchmark evaluation contracts](../docs/benchmark-evaluations.md)
- [PDDL + Agno pipeline](../docs/pmv_agno_pddl.md)
- [Internationalization (i18n)](../docs/i18n.md) — see the internationalization test suite in [test_i18n.py](test_i18n.py)
