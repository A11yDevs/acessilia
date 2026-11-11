# Local test workflow

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](testing.pt-br.md).

This page describes the supported local edit–test–fix loop. The commands are
thin wrappers around pytest; CI keeps running the complete suites before a
merge. Issue [#448](https://github.com/A11yDevs/acessilia/issues/448) tracks the
remaining work: bounded parallel execution (PR 2), the optional test-impact
experiment (PR 3), CI optimization (PR 4) and monitoring (PR 5).

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

## Commands

| Command | What it runs |
|---|---|
| `make test-file F=tests/test_example.py` | One file or one node id (`tests/test_api.py::test_health`), non-E2E |
| `make test-failed` | The tests recorded as failed by the previous pytest session |
| `make test-all` | The non-E2E core, docstruct and SDK suites, sequentially |

`make` with no target prints the same list.

`test-failed` reads `.pytest_cache/v/cache/lastfailed`. When there is no
recorded failure it prints a message and exits successfully instead of letting
`pytest --lf` fall back to the whole suite. A run whose only recorded failures
are E2E tests is also treated as "nothing to rerun", because this command
excludes E2E.

`test-all` stops at no suite: it runs all three and returns the last non-zero
exit status, so a failing library does not hide the core result. It is
sequential today; PR 2 of #448 adds bounded parallelism (`-n 4 --dist
worksteal`) after the isolation fixes.

The wrappers pass `-m "not e2e"`; use `uv run pytest -m e2e` directly to reach a
live environment, as described in [tests/README.md](../tests/README.md).

## Timeouts

`pytest-timeout` fails a hung test with its name instead of letting it consume
the 30-minute CI job timeout. The core suite uses a 180-second limit, far above
the slowest current test (about 11s). A test that legitimately needs longer
overrides the limit locally:

```python
import pytest

@pytest.mark.timeout(300)
def test_a_long_but_bounded_operation():
    ...
```

To debug without the timeout, disable the plugin for one run with
`uv run pytest -p no:timeout ...`.

## CI artifacts

CI runs the same suites with `--durations=25` and uploads the JUnit XML reports
even when a step fails: `test-reports` for the core, docstruct and SDK suites,
and `sdk-isolated-report` for the SDK-only job.

## Supported environments

- **macOS and Linux.** `make` ships with the Xcode command line tools on macOS
  and is present on common Linux distributions.
- **`uv`** must be installed ([docs](https://docs.astral.sh/uv/)). The commands
  run from the repository root; the libraries are separate packages and are
  invoked with `uv run --extra dev pytest` from their own directories.

## Scope and related work

- The constitution and [tests/README.md](../tests/README.md#running) still name
  the Docker container as the primary gate, but the image has no `test` stage;
  [#190](https://github.com/A11yDevs/acessilia/issues/190) tracks rewording that
  rule. Until then CI runs the three suites natively and is the check enforced
  before a merge.
- Dependency installation and caching stay under
  [#405](https://github.com/A11yDevs/acessilia/issues/405).
- E2E policy, scheduled runs and flaky-test monitoring are PR 5 of #448.
