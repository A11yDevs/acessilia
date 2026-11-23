# Test suite optimization: baseline and method

> A Brazilian Portuguese translation is available in
> [optimization.pt-br.md](optimization.pt-br.md).

This is PR 1 of [issue #644](https://github.com/A11yDevs/acessilia/issues/644):
instrumentation and a reproducible baseline of the four test suites. It changes
no test or production code. The baseline is the reference for the overlap
analysis (PR 2), the mutation/subsusumption experiment (PR 3) and the
optimizations (PR 4).

- **Snapshot:** `develop` at `cd7003d2` (2026-11-23), Python 3.12.13.
- **Tool:** [`scripts/tests/collect_timings.py`](../../scripts/tests/collect_timings.py),
  standard library plus the packages the project already installs.
- **Machine-readable baseline:** [`baseline.json`](baseline.json).
- **Serial application baseline:** [`baseline-serial-app.json`](baseline-serial-app.json).
- **Scope:** the application (`tests/`), docstruct (`libs/docstruct/tests`), SDK
  (`libs/sdk/tests`) and core (`libs/core/tests`).

## Method

`collect_timings.py collect --run` executes each suite from the root
environment, with the same coverage configuration the CI gate uses, and keeps:

| Measure | Source |
|---|---|
| Test count, failures, errors, skips | JUnit `testcase` elements |
| Per-test duration, p50/p95, slowest tests | JUnit `testcase@time` |
| Suite JUnit time | Sum of `testsuite@time` |
| Suite wall-clock time | `time.monotonic()` around the pytest process |
| Branch coverage | pytest-cov's `coverage.json` (lines and branches) |
| Environment | revision, Python, platform, pytest, xdist and Coverage versions |

A second mode reads reports produced by CI, so a baseline can be refreshed
without repeating the suites:

```bash
uv run --extra dev python scripts/tests/collect_timings.py collect \
  --report app=var/test-results/app.xml \
  --report docstruct=var/test-results/docstruct.xml \
  --report sdk=var/test-results/sdk.xml \
  --report core=var/test-results/core.xml \
  --coverage-dir var/coverage \
  --output var/timings/baseline.json
```

The CI `tests` job writes the same summary to the job summary and uploads
`timing-baseline-py*`. It is report-only: `continue-on-error` keeps a missing
report from changing the gate.

### Reproducing the baseline

```bash
# All four suites, application with four workers
make test-baseline

# Compare a new run with the committed baseline
make test-baseline-compare BASELINE=var/timings/baseline.json

# The application suite serially, for the parallelism comparison
uv run --extra dev python scripts/tests/collect_timings.py collect --run --only app \
  --xdist 0 --work-dir var/timings-serial \
  --output var/timings-serial/baseline.json
```

The committed numbers come from one quiet run on a macOS reference machine
(12 logical cores, 16 GB RAM). They are indicators, not hard limits: run the
same command on the same machine before treating a difference as a regression.

## Baseline

### Per component

| Suite | Tests | JUnit (s) | Wall (s) | p50 (s) | p95 (s) | Coverage (branch) |
|---|---:|---:|---:|---:|---:|---:|
| Application (`tests/`) | 3,181 | 151.76 | 157.23 | 0.014 | 0.216 | 87.9% |
| docstruct | 1,859 | 93.09 | 96.48 | 0.006 | 0.076 | 87.0% |
| SDK | 702 | 28.34 | 31.20 | 0.027 | 0.072 | 97.3% |
| core | 1,379 | 37.13 | 41.25 | 0.003 | 0.122 | 82.7% |
| **Total** | **7,121** | **310.32** | **326.17** | — | — | — |

The application suite is 49% of the JUnit time; docstruct is 30%, even though
it is a pure library. The four suites run sequentially and each imports the
project again, so the wall-clock total is slightly larger than the sum of the
JUnit times.

### Parallelism

The application suite is the only one the project parallelizes. The same
revision, same coverage flags, one serial run and one four-worker run:

| Run | Tests | JUnit (s) | Wall (s) | Slowest test (s) |
|---|---:|---:|---:|---:|
| serial | 3,181 | 884.30 | 890.15 | 88.56 |
| `-n 4 --dist worksteal` | 3,181 | 151.76 | 157.23 | 52.19 |

The four-worker run is **5.7× faster in wall-clock time** on this machine. The
slowest test is a long VLM-judge case that cannot be split, so it alone sets a
floor of about 52 seconds on the application job. `--dist worksteal` matters:
the distribution gives a free worker the next test instead of waiting for a
fixed module batch.

The libraries stay serial: docstruct is 96 seconds, the SDK 31 seconds and the
core 41 seconds, all below the cost of starting four workers and repeating
their fixtures. This is the same choice the Makefile and CI already make.

### Bottlenecks

| Suite | Test | Seconds | Share of the suite |
|---|---|---:|---:|
| Application | `TestVlmPairwiseJudge::test_long_page_is_flagged_as_truncated` | 52.19 | 33% of wall time |
| Application | `test_it_counts_test_functions` | 8.18 | 5% |
| Application | `test_every_exception_is_still_needed` | 8.14 | 5% |
| docstruct | `test_long_parent_chains_are_acyclic` | 23.59 | 24% of wall time |
| docstruct | `test_imports_outside_the_standard_library_are_guarded_accelerators` | 4.25 | 4% |
| core | `test_boundary.py` static scans (14 tests) | 8.72 | 21% of wall time |

Two patterns dominate the tail:

1. **Deliberately expensive cases.** The VLM judge and the 2,000-element parent
   chain exercise real scale. They are candidates for evidence-based review,
   not automatic removal.
2. **Repository-wide static scans.** The architecture, purity and Portuguese
   guards walk the tracked tree in several tests. They are cheap individually
   but add up, and they cannot be replaced by a narrower unit check without
   losing the guard.

The per-test list is in [`baseline.json`](baseline.json). The next PRs use it to
prioritize: overlap without duration is only half of the cost question.

## Limitations

- **One run per suite.** JUnit time varies with machine load; the slowest test
  in the serial run took 88.56s versus 52.19s in the parallel run. The serial
  run is a single process with a much larger resident set and no worker
  isolation, so GC and memory pressure are plausible causes; this measurement
  does not establish which one. Compare runs made under the same conditions,
  ideally more than once.
- **Collection time is not in JUnit.** pytest reports test call, setup and
  teardown durations, not collection. The wall-clock time includes it.
- **Fixture attribution is indirect.** A slow setup appears in the `testcase`
  time, but JUnit does not say which fixture caused it. PR 2 combines durations
  with coverage overlap to find repeated fixture work.
- **Coverage is per suite, not per test.** The per-test contexts used by PR 2
  come from a separate `--cov-context=test` run; they are not part of this
  baseline.

## What this baseline does not decide

No test is removed, merged or marked slower/faster by this PR. A test with high
coverage overlap can still be the only one that checks a contract, and a slow
test can be the only one that exercises a real scale. The baseline records the
cost; PR 2 and PR 3 record the evidence before PR 4 changes anything.
