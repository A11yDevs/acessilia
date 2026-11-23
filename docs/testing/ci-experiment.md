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
| A — baseline | one `tests (Python 3.12)` job runs the application, docstruct, SDK and core suites sequentially |
| B — parallel | `quality` plus four `component-tests` legs run in parallel; `tests (Python 3.12)` is a fail-closed aggregator |
| C — selective | shadow `detect-changes` recommendation; not a gate |

## Sample

Two successful pull-request runs of the same workflow, before and after the
parallel change. They are not identical codebases, so the comparison is
indicative, not a controlled benchmark.

| Mode | Run | Wall-clock | `tests` job | Job-minutes |
|---|---|---:|---:|---:|
| A | [45174924436](https://github.com/A11yDevs/acessilia/actions/runs/45174924436) | 3m07s | 3.05m | 7.43 |
| B | [45193011145](https://github.com/A11yDevs/acessilia/actions/runs/45193011145) | 2m21s | 0.20m (aggregator) | 8.45 |

Job-minutes include the isolation and security jobs; they measure aggregate
runner consumption, not only the test suites.

## First observations

- The tests critical path dropped from **3.05m to 1.22m** (the `app tests` leg);
  the aggregator adds **0.20m**. The `tests (Python 3.12)` check itself is no
  longer the slowest test job.
- End-to-end wall-clock dropped from **3m07s to 2m21s** in this pair.
- Aggregate job-minutes rose from **7.43 to 8.45** because five provider jobs
  repeat checkout/install. Parallelism reduced latency but not consumption.
- The **container image scan (2.28m)** is now the critical path in mode B. A
  further gain requires attacking that job, not only the test suites.
- The shadow selection ran successfully in mode B. For the #763 PR, the changed
  workflow/scripts paths correctly selected all suites; no false negative was
  observable because mode C is not used to skip anything.

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

Part of #767 and #644.
