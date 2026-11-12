# Local test workflow

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](testing.pt-br.md).

This page describes the supported local edit–test–fix loop. The commands are
thin wrappers around pytest; CI keeps running the complete suites before a
merge. Issue [#448](https://github.com/A11yDevs/acessilia/issues/448) tracks the
remaining work: the optional test-impact experiment (PR 3), CI optimization
(PR 4) and monitoring (PR 5). Bounded parallel execution (PR 2) is available in
`make test-all`.

## Baseline

Measured on 2026-11-11 at `c3ea6d5d`, before the local commands were added:

| Suite | Tests | Collection | Full run |
|---|---|---|---|
| Core (`-m "not e2e"`) | 2800 collected, 2740 selected | 10.2s | 132.0s |
| `libs/docstruct` | 1194 | 1.05s | — |
| `libs/sdk` | 427 | 0.46s | — |

Environment: macOS, 12 logical cores, 16 GB RAM, Python 3.11.15, pytest 9.1.1.
The CI `tests` job took 1m59s in
[run 43038402225](https://github.com/A11yDevs/acessilia/actions/runs/43038402225):
26s to install dependencies, 12s to collect, 65s for the core suite and 5s for
each library suite.

These numbers are a reference, not a guarantee: they vary with the machine, the
operating system and the dependency cache. `--durations=25` prints the slowest
tests on every run, so a fresh baseline is one command away:

```bash
uv run pytest -m "not e2e" --durations=25
```

### Parallel baseline

After the isolation fixes in PR 2, with about 2920 core tests on the same
machine (2026-11-12):

| Run | Wall time |
|---|---|
| Core serial | 143s |
| Core `-n 4 --dist worksteal` | 74s (1.9x) |
| Core `-n 2 --dist worksteal` | 124s |
| Core `-n auto --dist worksteal` | 96s |
| Core `-n 4 --dist load` | 178s |

`worksteal` wins because a few long tests dominate the tail; `load` assigns
whole modules and leaves workers idle. `-n auto` (12 workers here) was slower
than four: the slowest test cannot be split, and the extra processes contend
for the same cores. The slowest test alone takes roughly 20–80s depending on
load, so it caps the gain. These numbers are a reference, not a guarantee.

## Commands

| Command | What it runs |
|---|---|
| `make test-file F=tests/test_example.py` | One file or one node id (`tests/test_api.py::test_health`), non-E2E |
| `make test-failed` | The failures recorded in the core, docstruct and SDK caches |
| `make test-all` | The non-E2E core suite with four workers, then docstruct and SDK sequentially |

`make` with no target prints the same list.

`test-failed` reads the `lastfailed` cache of all three suites (`.pytest_cache`
at the repository root, `libs/docstruct` and `libs/sdk`) and reruns each
suite's failures from its own directory, with the same configuration and
relative node ids as `test-all`. Before running, it collects only the recorded
files and keeps the ids that still exist. A removed or renamed test is reported
and skipped instead of making `pytest --lf` fall back to the whole suite; a file
recorded with a collection error is rerun as a file. When there is no recorded
failure, or the only recorded failures are E2E tests, it prints a message and
exits successfully.

`test-all` stops at no suite: it runs all three and returns the last non-zero
exit status, so a failing library does not hide the core result. The core suite
uses `-n 4 --dist worksteal`; docstruct and SDK stay sequential.

The core suite runs with `-m "not e2e"`; use `uv run pytest -m e2e` directly to
reach a live environment, as described in
[tests/README.md](../tests/README.md).

## Parallel execution

`make test-all` passes `-n 4 --dist worksteal` to the core suite. Override the
bound or the distribution without editing the Makefile:

```bash
make test-all CORE_JOBS=2
make test-all CORE_DIST=load
```

The suite is parallel-safe because tests that used to share runtime paths now
use per-worker paths:

- `tests/test_api.py` points `settings.temp_dir`, `settings.data_dir` and
  `settings.logs_dir` at the worker's `tmp_path_factory` directory before the
  session `TestClient` starts the app. Without that, the second worker fails
  `runtime_lease()` with `RuntimeError: Only one API worker may use a data
  directory`.
- the optional-export test writes its input and output under `tmp_path`, so an
  `audio.docx` left by one parametrization cannot leak into the next.

`-n auto` is not enabled. It passed in the validation run but was slower (96s)
than four workers (74s) and uses more memory. Keep it as an experimental local
option; CI and `make test-all` stay bounded.

## Timeouts

`pytest-timeout` fails a hung test with its name instead of letting it consume
the 30-minute CI job timeout. The core suite uses a 180-second limit. The
CPU-heavy VLM judge test raises its own limit to 300 seconds because four
workers can stretch it to 60–80s on a busy machine. A test that legitimately
needs longer overrides the limit locally:

```python
import pytest

@pytest.mark.timeout(300)
def test_a_long_but_bounded_operation():
    ...
```

To debug without the default timeout, pass `--timeout=0`:
`uv run pytest --timeout=0 ...`. `-p no:timeout` does not work with this
project's `--strict-config`, because disabling the plugin also removes its
`timeout` option. An explicit `@pytest.mark.timeout(...)` still takes precedence
over `--timeout=0`, so remove the marker while debugging that test.

## CI artifacts

CI runs the same suites with `--durations=25` and uploads the JUnit XML reports
even when a step fails: `test-reports` for the core, docstruct and SDK suites,
and `sdk-isolated-report` for the SDK-only job.

## Supported environments

- **macOS and Linux.** `make` ships with the Xcode command line tools on macOS
  and is present on common Linux distributions.
- **`uv`** must be installed ([docs](https://docs.astral.sh/uv/)). The commands
  run from the repository root; the libraries are separate packages and are
  invoked with `uv run --extra dev pytest` from their own directories. The dev
  extra includes `pytest-xdist`, so `uv sync --extra dev` is enough for
  `make test-all`.

## Scope and related work

- The constitution and [tests/README.md](../tests/README.md#running) still name
  the Docker container as the primary gate, but the image has no `test` stage;
  [#190](https://github.com/A11yDevs/acessilia/issues/190) tracks rewording that
  rule. Until then CI runs the three suites natively and is the check enforced
  before a merge.
- Dependency installation and caching stay under
  [#405](https://github.com/A11yDevs/acessilia/issues/405).
- E2E policy, scheduled runs and flaky-test monitoring are PR 5 of #448.
