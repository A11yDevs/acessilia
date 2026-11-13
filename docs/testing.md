# Testing workflow: fast feedback and the full gate

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](testing.pt-br.md).

The project has about 4,700 tests: roughly 3,000 non-E2E tests in the core,
1,272 in `libs/docstruct` and 450 in `libs/sdk`. Running all of them after every
small edit is expensive, both locally and in CI. This guide explains how the
suite is organized, which commands to use in each part of the edit–test–fix
loop, and which techniques make the loop faster without weakening the full
regression gate. The changes came from issue
[#448](https://github.com/A11yDevs/acessilia/issues/448).

## The problem: a large suite, a short loop

A full serial run of the core takes about 2m23s on the reference machine; the
CI `tests` job used to take 1m59s. Most of that time is unrelated to a one-line
edit. Waiting minutes for every change breaks concentration and encourages
skipping tests.

The answer is not to run fewer tests in the merge gate. It is to run the
*right* tests during development, run the full suite before integration, and
make the full suite itself faster.

## Which command should I use?

| Situation | Command | What happens |
|---|---|---|
| I changed one file or one test | `make test-file F=tests/test_example.py` | Runs only that path, non-E2E |
| I fixed a failure and want to confirm it | `make test-failed` | Reruns the failures recorded in the core, docstruct and SDK caches |
| I want the full local confidence check | `make test-all` | Core with four workers, then docstruct and SDK |
| I want the core only, in parallel | `uv run pytest -m "not e2e" -n 4 --dist worksteal` | Runs the non-E2E core with four workers |
| I need the exact commands `make` uses | `make -n test-all` | Prints the commands without running them |

`make` with no target prints the short command list.

> **Important:** `uv run pytest` without `-n` is **serial**. It also does not run
> the `libs/docstruct` and `libs/sdk` suites. The speed-up comes from
> `make test-all` or from passing `-n 4 --dist worksteal` explicitly.

## What runs by default

### In CI

Every pull request and push to `develop`, `main` or a release branch runs the
GitHub Actions workflow `CI`:

- **`tests (Python 3.11)`** installs the project, checks the Toolbox capability
  contract, runs the non-E2E core suite with **four workers**, runs the
  docstruct and SDK suites, rejects unexpected skipped tests and uploads JUnit
  reports.
- **`SDK alone (Python 3.11)`** installs only the SDK and proves that it works
  without the core or docstruct.
- Both jobs are required checks in the live rulesets for `main` and `develop`.
- Image delivery waits for both jobs.

The core check does not have a separate collection step: the test run collects
the suite itself. The job name is intentionally kept as `tests (Python 3.11)` so
branch protection and existing links keep working.

### Locally

The supported full local command is:

```bash
make test-all
```

It runs the non-E2E core with four workers, then the docstruct and SDK suites
sequentially. The libraries are fast and have separate package environments, so
they stay simple. `make test-all` executes all three suites even if one fails,
and returns a non-zero status if any of them failed.

Running plain `uv run pytest` from the repository root is a different thing: it
uses pytest's defaults, includes E2E tests that need a live environment, and
runs serially.

## The techniques, in plain language

### 1. Run only what you are changing

A pytest **node id** identifies one test, for example
`tests/test_api.py::test_health`. Running one file or one node is much faster
than running the whole suite, and it is the normal first step of the local loop.

```bash
make test-file F=tests/test_api.py::test_health
make test-file F=tests/test_pddl_planning.py
```

`make test-file` adds `-m "not e2e"` and `--durations=25`, so E2E tests are
excluded and the slowest tests in that file are printed. For a single file,
starting four workers usually adds more overhead than it saves; targeted runs
stay serial.

### 2. Rerun only the failures

After a failed run, `pytest --lf` would be the obvious next command, but it has
two traps in this repository: it can fall back to the whole suite when the cache
is empty, and it knows nothing about the separate library caches.

`make test-failed` is the supported wrapper. It:

- reads the `lastfailed` cache for the core, docstruct and SDK;
- checks that the recorded files still exist and collects only those files;
- reruns the explicit node ids that still exist;
- reports removed or renamed tests instead of falling back to a full run;
- reruns a file recorded with a collection error as a file;
- exits successfully with a message when there is nothing to rerun.

That makes the "fix one failure, confirm it, move on" loop fast and predictable.

### 3. Run the core suite in parallel

The core suite is the large one. `pytest-xdist` starts several worker processes
and distributes tests across them. The Makefile and CI use
`-n 4 --dist worksteal`:

- **`-n 4`** starts four workers, matching the four-vCPU GitHub runner and
  keeping memory use bounded.
- **`--dist worksteal`** gives a worker a new test as soon as it finishes one.
  This matters because a few tests are much slower than the rest; a fixed
  module-based distribution leaves workers idle while one worker finishes a
  long tail.

The result is roughly **1.9x** for the core suite on the reference 12-core
machine: **143s serial → 74s with four workers** in a quiet run. `-n 2` is
slower (124s), `--dist load` is slower (178s), and `-n auto` (12 workers) was
slower (96s) because the long test cannot be split and the extra processes
compete for the same cores. Four is the supported bound, not a universal
optimum.

### 4. Isolation is what makes parallelism safe

Parallelism only works if tests do not fight over the same files, databases or
locks. The suite had two real conflicts:

- `tests/test_api.py` used to start every worker against the shared `var/data`
  directory. The second worker failed in `runtime_lease()` because only one API
  worker may own that directory. The session client now receives the worker's
  `tmp_path_factory` tree (`temp_dir`, `data_dir`, `logs_dir`) before the app
  starts.
- The optional-export test used a shared output directory, so an `audio.docx`
  from one parametrization could leak into the next. It now writes input and
  output under `tmp_path`.

The testmon experiment also exposed an order dependency in the history
database. `test_history_empty` and `test_stats_empty` now use a per-test
`fresh_history_db`, so an empty-history assertion does not depend on what ran
before it.

No test currently needs to be marked as serial. If one does, the `serial`
marker will be introduced together with the mechanism that makes it run alone.

### 5. Put the same wins in CI

CI uses the same bounded parallel core run as `make test-all`. Removing the
standalone `--collect-only` step and parallelizing the core took the `tests` job
from **1m59s** to **59s–1m26s** in the validation runs; one validation run on
develop took **1m11s**, with the core step at **32s**. The other jobs stay unchanged:
docstruct and SDK are still tested, skips are still rejected, the contract
check still runs and the JUnit artifacts are still uploaded even on failure.

### 6. Monitor order-dependent and flaky behaviour

Parallelism and different orders can reveal a test that depends on another
test's leftovers. The `Scheduled test monitoring` workflow runs weekly (and on
demand) for `main` and `develop`. For each branch it runs the core suite
serially and again with four workers, compares the JUnit outcomes, fails on a
difference, failure, error or unexpected skip, and writes a summary with p50/p95
test durations and the slowest tests. A scheduled failure opens or updates the
issue `Scheduled test monitoring failed`.

The workflow only starts firing after its file reaches the default branch. E2E
is a separate, conditional job: it runs only when `TOOLBOX_BASE_URL` or
`CORE_BASE_URL` is configured, and it is not a merge gate.

### 7. Automatic test selection was evaluated and rejected

`pytest-testmon` selects tests affected by a change by tracking coverage. The
experiment found that it cannot see static files such as docs, schemas and
fixtures, and that the root command does not run the library suites. A README
change selected zero tests even though a mandatory static gate failed; a
central change selected 246 tests; rebuilding the dependency database took
221s in the quiet measurement (+55% over the serial core baseline). It also
added a stateful `.testmondata` database and showed unstable selection between
runs. The full details and measurements are in the experiment record from
[#448](https://github.com/A11yDevs/acessilia/issues/448).

`pytest-testmon` is **not** a project dependency and `make test-fast` is not
part of the workflow. The supported shortcuts remain `test-file`, `test-failed`
and parallel `test-all`.

## Measured gains

Reference machine: macOS, 12 logical cores, 16 GB RAM, Python 3.11.15, pytest
9.1.1. These numbers vary with the machine, load and dependency cache.

| Scenario | Before | After |
|---|---:|---:|
| Core suite, serial vs four workers | 143s | 74s (~1.9x) |
| CI core step | 60s + 10s collection | 26–43s |
| CI `tests` job | 1m59s | 59s–1m26s (one run: 1m11s) |

`--durations=25` prints the slowest tests of any run, so you can refresh the
baseline on your own machine with:

```bash
make test-all
# or only the core:
time uv run pytest -m "not e2e" --durations=25
time uv run pytest -m "not e2e" -n 4 --dist worksteal --durations=25
```

## Command reference

### Make targets

```bash
make help
make test-file F=tests/test_example.py
make test-file F=tests/test_api.py::test_health
make test-failed
make test-all
```

`make -n test-all` prints the exact commands without running them.

Useful variables:

| Variable | Default | Effect |
|---|---|---|
| `CORE_JOBS` | `4` | Number of xdist workers for the core |
| `CORE_DIST` | `worksteal` | xdist distribution strategy |
| `DURATIONS` | `25` | Number of slow tests printed |
| `PYTEST` | `uv run pytest` | Pytest command used by the Makefile |
| `PYTEST_FLAGS` | `-m "not e2e"` | Selection flags for the core |

Examples:

```bash
make test-all CORE_JOBS=2
make test-all CORE_DIST=load
```

### Direct pytest

```bash
# One node id
uv run pytest -m "not e2e" tests/test_api.py::test_health

# One file, serial
uv run pytest -m "not e2e" tests/test_pddl_planning.py

# Core, four workers
uv run pytest -m "not e2e" -n 4 --dist worksteal --durations=25

# Only the library suites
(cd libs/docstruct && uv run --extra dev pytest)
(cd libs/sdk && uv run --extra dev pytest)
```

`uv run pytest` without `-n` is serial. `uv run pytest` also includes E2E
selection unless you pass `-m "not e2e"`; use the make targets for the normal
loop.

### Timeouts and markers

`pytest-timeout` gives the core suite a 180-second per-test limit. The CPU-heavy
VLM judge test raises its own limit to 300 seconds because four workers can
stretch it on a busy machine. To debug a hang:

```bash
uv run pytest --timeout=0 ...
```

`-p no:timeout` does **not** work with this project's `--strict-config`, because
disabling the plugin also removes its `timeout` option. An explicit
`@pytest.mark.timeout(...)` still takes precedence over `--timeout=0`, so remove
the marker while debugging that test.

The `slow` marker identifies the known expensive VLM test. `-m slow` repeats it;
`-m "not slow"` is a faster local loop. `make test-all` still runs it, because
the full gate must not skip tests. No test currently needs serial execution.

## Recipes

### I changed one file

```bash
make test-file F=tests/test_the_file.py
```

### A test failed and I fixed it

```bash
make test-failed
```

If the cache has no real failure, the command exits successfully with a message;
it does not silently run the whole suite.

### I want full local confidence before pushing

```bash
make test-all
```

This is the local equivalent of the CI gate: core with four workers, then
docstruct and SDK.

### I need to investigate a slow or hanging test

```bash
# make test-file already adds --durations=25
make test-file F=tests/test_the_file.py

# Disable the timeout only while debugging one node id
uv run pytest -m "not e2e" tests/test_the_file.py::test_name --timeout=0 -s
```

### I need E2E

E2E tests need a live environment and are excluded from the normal loop:

```bash
TOOLBOX_BASE_URL=https://toolbox.example/toolbox \
TOOLBOX_API_KEY="$TOOLBOX_API_KEY" \
uv run pytest -m e2e -v
```

See [tests/README.md](../tests/README.md#end-to-end-tests) for the Core API
variables and the optional dataset corpus. E2E is also a scheduled validation,
not a merge gate.

## Troubleshooting

**Why is `uv run pytest` still slow?**
Because it is serial by default. Use `make test-all` or add
`-n 4 --dist worksteal` to the core command.

**Why four workers and not `-n auto`?**
Four matches the CI runner and was faster here: the slowest test cannot be
split, and extra processes compete for the same cores. Use `CORE_JOBS` if your
machine has a different shape.

**Why did we not adopt `pytest-testmon`?**
It does not track static files (docs, schemas, fixtures), does not run the
library suites, has a costly baseline and showed false negatives. The evidence
is in the [#448](https://github.com/A11yDevs/acessilia/issues/448) experiment.

**What happened to the collection step in CI?**
The test run collects the suite itself, so the separate `--collect-only` step
was redundant.

**Where are the slow-test reports?**
`make` and CI pass `--durations=25`. CI also uploads JUnit reports as
`test-reports` and `sdk-isolated-report`, with 7-day retention.

**Where do I see the scheduled comparison?**
After the workflow reaches the default branch, open Actions →
`Scheduled test monitoring`. Each `main`/`develop` run uploads
`scheduled-test-reports-<ref>` and writes p50/p95 and the slowest tests to the
job summary.

**Why is my parallel run failing with a data-directory error?**
The suite is now isolated per worker; if this appears again, it means a new test
is sharing a runtime path. Check `tests/test_api.py`'s worker paths and use
`tmp_path`/`tmp_path_factory` for new mutable state.

## Where to see the results

- **CI:** GitHub Actions → workflow `CI` → job `tests (Python 3.11)` → step
  `Run complete test suite`. The log shows `created: 4/4 workers` and
  `--durations=25`.
- **Artifacts:** `test-reports` (core, docstruct, SDK) and
  `sdk-isolated-report`.
- **Scheduled:** workflow `Scheduled test monitoring`, with artifacts retained
  for 30 days and a tracking issue on scheduled failures.
- **Rulesets:** both `main` and `develop` require `tests (Python 3.11)` and
  `SDK alone (Python 3.11)`.
- **Locally:** run `time make test-all` and compare it with the serial core
  command above on the same idle machine.

## Supported environments

- **macOS and Linux.** `make` ships with the Xcode command-line tools on macOS
  and is present on common Linux distributions.
- **`uv`** is required ([docs](https://docs.astral.sh/uv/)). Run the commands
  from the repository root. The libraries are separate packages and are invoked
  with `uv run --extra dev pytest` from their own directories.
- `uv sync --extra dev` installs `pytest-xdist` and the dependencies used by
  the Make targets and CI.

## Scope and related work

- The constitution still names the Docker container as the primary gate;
  [#190](https://github.com/A11yDevs/acessilia/issues/190) tracks rewording that
  rule. The [tests README](../tests/README.md#running) states that CI is the
  enforced gate and the image has no `test` stage.
- Dependency installation and caching remain under
  [#405](https://github.com/A11yDevs/acessilia/issues/405).
- The local commands, isolation fixes, CI parallelization, testmon decision and
  scheduled monitoring were delivered through the five PRs of
  [#448](https://github.com/A11yDevs/acessilia/issues/448).
