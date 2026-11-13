# Automated Test Suite (tests)

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](README.pt-br.md)

The project's unit test suite covers the canonical pipeline, PDDL engine, API and exporters. Everything is fast and isolated: files go to temporary directories; network and LLM calls are mocked, and async flows run with `pytest-asyncio`.

The merge gate is CI, which runs the non-E2E core, docstruct and SDK suites natively. The constitution still names a container gate; [#190](https://github.com/A11yDevs/acessilia/issues/190) tracks that wording, and the image has no `test` stage today.

Issue #342 regressions cover list continuations across paragraphs and tables with explicit consecutive numbering. The math scorecard separates runs at changes of source parent without matching continuation numbering, explicit restarts, style changes, numbering gaps, headings, page boundaries, and blocks other than paragraphs, tables or formulas. Legacy adjacent blocks without parent metadata retain their grouping. TXT/MP3 continue to use enriched speech under ADR-0011; use the current dataset expectations, which accept the spoken negative sign.

## Running

The supported local loop is described in [docs/testing.md](../docs/testing.md):

```bash
# Everything CI runs, non-E2E (core, docstruct and SDK)
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
- [PDDL + Agno pipeline](../docs/pmv_agno_pddl.md)
- [Internationalization (i18n)](../docs/i18n.md) — see the internationalization test suite in [test_i18n.py](test_i18n.py)
