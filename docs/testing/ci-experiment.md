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
| B2 — #787 after shared setup | [45251360702](https://github.com/A11yDevs/acessilia/actions/runs/45251360702) | 2m11s | 0.20m (aggregator) | 8.37 |

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
- After the shared setup action and the working setup-uv cache (#788), run B2
  was **2m11s / 8.37 job-minutes** (app leg 1.87m, image scan 1.80m). The
  maintainability change did not reduce aggregate runner-minutes; the image
  scan is still the critical path.
- The **container image scan (2.28m)** is now the critical path in mode B. A
  further gain requires attacking that job, not only the test suites.
- The shadow selection ran successfully in mode B (PR #771). Its changed
  `scripts/tests/**` paths selected all suites because `scripts/**` is
  transversal; PR #763's own run behaved the same for `.github/**` and
  `scripts/**`. No false negative was observable because mode C is not used to
  skip anything.

## Shadow selections observed

The `test-selection-shadow` artifact is produced for every follow-up PR. These
five merged PRs illustrate each rule; all five CI runs passed, so this does not
prove the selector would have caught a regression (mode C is not used to skip
anything).

| PR | Changed area | Selected | Not selected | Conservative |
|---|---|---|---|---|
| #766 | core | core, app | docstruct, SDK | no |
| #769 | `tests/**` only | app | docstruct, SDK, core | no |
| #771 | `scripts/**`, docs, tests | all | — | no |
| #772 | docs | app | docstruct, SDK, core | no |
| #776 | docstruct | all | — | no |

This matches the documented rules: `tests/**` and docs keep the application
suite, a core change selects core+app, docstruct selects all consumers, and
`scripts/**` is transversal. The sample still contains only green PRs.

### Integration dimension and CI-only changes

The follow-up PRs after #802 exercised the `app integration` dimension and
changes that were mostly CI/security files. Replaying the current selector over
their file lists:

| PR | Changed area | Selected | `integration_required` | Conservative |
|---|---|---|---|---|
| #788 | shared setup action, workflows, tests | all | yes | no |
| #793 | CI workflow, docs, `pyproject.toml`, tests | all | yes | no |
| #795 | security workflow, docs, tests | all | no | no |
| #800 | release workflow, `SECURITY.md`, tests | all | no | no |
| #802 | CI workflow, selector, docs, tests | all | yes | no |
| #807 | CodeQL/security workflows, tests | all | no | no |
| #808 | selector, docs, tests | all | no | no |

`.github/**` and `scripts/**` are transversal, so CI-only changes still select
every suite. The integration flag follows the focused list: only the PRs that
touched `.github/workflows/ci.yml` or its integration support selected it.

### Historical failure replay

To test the risk direction — a failure the full suite catches but the selected
set would skip — the current selector was replayed against pull requests with
known failures:

| PR | Run | Failing job | Selector result | False negative? |
|---|---|---|---|---|
| #732 | [45001010971](https://github.com/A11yDevs/acessilia/actions/runs/45001010971) | `quality` / Ruff | all | no (quality is always run) |
| #726 | [44994569632](https://github.com/A11yDevs/acessilia/actions/runs/44994569632) | core tests | all | no |
| #713 | [44977779847](https://github.com/A11yDevs/acessilia/actions/runs/44977779847) | app tests | all | no |
| #711 | [44976566900](https://github.com/A11yDevs/acessilia/actions/runs/44976566900) | app tests | sdk, core, app | no |
| #709 | [44972669665](https://github.com/A11yDevs/acessilia/actions/runs/44972669665) | app tests | all | no |
| #621 | [44683419408](https://github.com/A11yDevs/acessilia/actions/runs/44683419408) | app tests | all (conservative) | no |
| #781 | [45254071576](https://github.com/A11yDevs/acessilia/actions/runs/45254071576) | core tests | all (shadow artifact) | no |

The selected set contained the failing suite in every replayed run, so this
sample produced **zero false negatives**. The replays use the current selector
over each PR's file list; only #781 has an artifact from the original run, and
that artifact uses schema v1. This is evidence, not a proof of completeness.

## Decision

No selective gate is adopted. The full suite remains mandatory. The failure
replay adds real regressions to the observation, but the sample is still small,
most replays are retrospective, and no repeated controlled run separates the
code change from machine load. Provider setup duplication and the image-scan
critical path are tracked in
[#778](https://github.com/A11yDevs/acessilia/issues/778). A gate decision still
needs a larger representative set and a controlled comparison.

## Limitations

- One run per mode, with different PR content; the wall-clock delta is not a
  controlled measurement.
- Job-minutes are derived from GitHub start/completion timestamps and include
  download/setup overhead.
- Most failure replays use the current selector over a historical PR file
  list, not the shadow artifact produced at the time; #781 is the exception.
  The replay cannot detect a path that was missing from the diff or a failure
  caused by an environment not represented in the file list.
- The experiment must be repeated after the security/image jobs change; the
  critical path may move back to the tests.
- On pull requests the container image scan is now conditional on image inputs
  (`infra/**`, `pyproject.toml`, `uv.lock`, library manifests and locks,
  `.dockerignore`, `.python-version`, `.trivyignore`, the security workflow);
  pushes, `workflow_dispatch` and the weekly schedule still scan
  unconditionally. The dependency audit remains unconditional.
- `docs/testing.md` still records the #448-era 1m59s / 59s–1m26s figures. The
  job absorbed Ruff/Mypy on 2026-11-20 and the suite grew; the numbers here are
  the comparable 2026-11-23 sample, not a contradiction of the historical
  record.

Part of #767 and #644.
