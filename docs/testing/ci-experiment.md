# CI experiment: baseline, parallel and shadow selection

> A Brazilian Portuguese translation is available in
> [ci-experiment.pt-br.md](ci-experiment.pt-br.md).

This is the first observation record for [issue #767](https://github.com/A11yDevs/acessilia/issues/767),
the experiment required by the [#644](https://github.com/A11yDevs/acessilia/issues/644)
CI proposal. The full suite remains the gate; this document compares execution
modes before any selective gate is considered.

## Modes

| Mode | Configuration |
|---|---|
| A — baseline | one `tests (Python 3.12)` job runs the application, docstruct, SDK and core suites sequentially, plus the Ruff/Mypy/contract steps |
| B — parallel | `quality` plus four `component-tests` legs run in parallel; `tests (Python 3.12)` is a fail-closed aggregator |
| C — selective | shadow `detect-changes` recommendation; not a gate |

## Sample

Two successful pull-request runs of the same workflow, before and after the
parallel change. They are not identical codebases, so the comparison is
indicative, not a controlled benchmark.

| Mode | Run | Wall-clock | `tests` job | Job-minutes |
|---|---|---:|---:|---:|
| A — #748 branch | [45174924436](https://github.com/A11yDevs/acessilia/actions/runs/45174924436) | 3m07s | 3.05m | 7.47 |
| B — #771 | [45193011145](https://github.com/A11yDevs/acessilia/actions/runs/45193011145) | 2m21s | 0.20m (aggregator) | 8.47 |

Job-minutes include the isolation and security jobs; skipped jobs are excluded
because they consume no runner minutes. The figures measure aggregate
consumption, not only the test suites.

## First observations

- The `tests` job dropped from **3.05m to 1.22m** (the `app tests` leg); the
  end-to-end test chain (legs start to aggregator finish) is about **1.47m**,
  not 1.22 + 0.20. The `tests (Python 3.12)` check itself is no longer the
  slowest test job.
- Mode A also ran Ruff/Mypy/Mypy 3.11 (~39s) inside the job; those now run in
  `quality`. The pure suite portion was ~131s sequential in A versus the 73s
  longest leg in B.
- End-to-end wall-clock dropped from **3m07s to 2m21s** in this pair.
- Aggregate job-minutes rose from **7.47 to 8.47** because five provider jobs
  repeat checkout/install. Parallelism reduced latency but not consumption.
- The **container image scan (2.28m)** is now the critical path in mode B. A
  further gain requires attacking that job, not only the test suites.
- The shadow selection ran successfully in mode B (PR #771). Its changed
  `scripts/tests/**` paths selected all suites because `scripts/**` is
  transversal; PR #763's own run behaved the same for `.github/**` and
  `scripts/**`. No false negative was observable because mode C is not used to
  skip anything.

## Shadow selections observed

The `test-selection-shadow` artifact was available for three follow-up PRs. All
three CI runs passed; this does not prove the selector would have caught a
regression, because mode C is not used to skip anything.

| PR | Changed area | Selected | Skipped | Conservative |
|---|---|---|---|---|
| #769 | `tests/**` only | app | docstruct, SDK, core | no |
| #771 | `scripts/**`, docs, tests | all | — | no |
| #772 | docs | app | docstruct, SDK, core | no |

This matches the documented rules: `tests/**` and docs keep the application
suite, while `scripts/**` is transversal and selects everything. No false
negative was observable, but the sample contains only green PRs.

## Decision

No selective gate is adopted. The full suite remains mandatory while the
shadow artifacts accumulate. A gate decision needs a representative set of PRs,
observed false negatives, and repeated runs that separate the code change from
machine load.

## Limitations

- One run per mode, with different PR content; the wall-clock delta is not a
  controlled measurement.
- Job-minutes are derived from GitHub start/completion timestamps and include
  download/setup overhead.
- Selective false negatives cannot be measured until the recommendation is
  replayed against PRs with known failures.
- The experiment must be repeated after the security/image jobs change; the
  critical path may move back to the tests.
- `docs/testing.md` still records the #448-era 1m59s / 59s–1m26s figures. The
  job absorbed Ruff/Mypy on 2026-11-20 and the suite grew; the numbers here are
  the comparable 2026-11-23 sample, not a contradiction of the historical
  record.

Part of #767 and #644.
