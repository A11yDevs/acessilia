# Coverage overlap and redundancy candidates

> A Brazilian Portuguese translation is available in
> [overlap.pt-br.md](overlap.pt-br.md).

This is PR 2 of [issue #644](https://github.com/A11yDevs/acessilia/issues/644):
the automated overlap analysis and the first candidate list. It changes no test
or production code. The baseline method and timings are PR 1; this report is
about which tests exercise the same code.

- **Snapshot:** `develop` at `cd7003d2` (2026-11-23), Python 3.12.13.
- **Tool:** [`scripts/tests/coverage_overlap.py`](../../scripts/tests/coverage_overlap.py)
  and [`scripts/tests/redundancy_report.py`](../../scripts/tests/redundancy_report.py).
- **Machine-readable report:** [`overlap-app.json`](overlap-app.json).
- **Review sheet:** [`redundancy-app.json`](redundancy-app.json) (Markdown:
  [`redundancy-app.md`](redundancy-app.md)).
- **Scope:** the application suite (`tests/`) against `backend/` and `frontend/`.
  The library suites can be analysed with the same command and a different
  `--include`.

## Method

Coverage.py can attach a dynamic context to every measured line. pytest-cov
sets that context to the test node id with `--cov-context=test`, so the
`.coverage` database knows which test executed each `file:line`:

```bash
COVERAGE_FILE="$PWD/var/context/app/.coverage" \
uv run pytest -m "not e2e" -n 4 --dist worksteal \
  --cov=backend --cov=frontend --cov-branch --cov-context=test \
  --cov-config="$PWD/pyproject.toml" --cov-report= \
  --junitxml=var/context/app/results.xml

uv run python scripts/tests/coverage_overlap.py \
  --coverage-file var/context/app/.coverage \
  --include backend --include frontend \
  --output docs/testing/overlap-app.json \
  --summary docs/testing/overlap-app.md

uv run python scripts/tests/redundancy_report.py \
  docs/testing/overlap-app.json \
  --junit app=var/context/app/results.xml \
  --output docs/testing/redundancy-app.json \
  --summary docs/testing/redundancy-app.md
```

The first script computes the Jaccard similarity
`|A ∩ B| / |A ∪ B|` for every pair that shares at least five lines, and flags
pairs at or above `0.8`. A line covered by more than 50 tests is ignored as
shared infrastructure: every test imports the application, so those lines would
make unrelated tests look identical. The threshold and the cap are configurable.

The second script adds durations, identifies whether one test covers no line
the other does not, and separates parametrized variants. It never edits,
deletes or skips a test.

## Results

The application suite ran 3,192 tests over 3,559 measured lines.

| Measure | Value |
|---|---:|
| Pairs at Jaccard >= 0.8 with >= 5 shared lines | 83 |
| Exact pairs (Jaccard = 1.0) | 0 |
| Mean similarity of the reported pairs | 0.815 |
| Parametrized families analysed | 288 |
| Families with identical line coverage | 246 |
| Tests with no exclusive production line | 3,080 of 3,192 |

At a looser threshold of 0.6 and three shared lines, the report has 234 pairs
and still **no pair where one test's measured lines are a subset of the
other's**. That is the central result of this PR: the suite has large overlap,
but it does not have a demonstrable pairwise elimination candidate.

### Where the overlap is

| Cluster | Example | Jaccard | Shared | Only A | Only B |
|---|---|---:|---:|---:|---:|
| Telegram document flow | `test_document_does_not_consume_another_senders_preferences` ↔ `test_document_submits_with_mode_and_source` | 0.849 | 269 | 24 | 24 |
| Telegram locale variants | `test_pdf_ua_warning_survives_worker_and_user_locales_differing[en_US-pt_BR]` ↔ `[pt_BR-en_US]` | 0.853 | 279 | 24 | 24 |
| Web panel receipts | `test_receipt_close_info_only_while_the_email_promise_holds[done-failed-False-False]` ↔ `test_receipt_recovers_result_after_refresh[failed]` | 0.826 | 171 | 18 | 18 |
| Benchmark client matrix | `test_the_harness_configures_clients_like_the_core[...]` variants | — | 273 | — | — |

These clusters share the request/response plumbing of one scenario. Each test
still covers between 18 and 30 lines that its neighbour does not, usually the
branch for the state, locale or client it asserts. Removing one would lose
coverage of that branch, so none is a candidate on coverage evidence alone.

### Parametrized families

246 of the 288 analysed families have **identical line coverage** across their
variants. The strongest examples are the benchmark client matrix, the web panel
receipt states and the Telegram locale permutations. This is expected: a
parametrization usually varies inputs and expected assertions, not the
production path. Equal line coverage is not duplicate behaviour; the variants
can fail for different reasons.

The review sheet lists the families and the pairs. It classifies
`identical-parameterization` separately and never proposes one of its variants
as subsumed.

### Tests without an exclusive production line

3,080 of 3,192 tests cover no line that no other test covers. This number is
not a defect: coverage omits the test files themselves, so assertions,
parametrized expected values and error messages are invisible to it. Almost
every test that exercises the same service entry point will share all its
production lines with another test.

That is exactly why this PR does **not** remove tests. It narrows the question
for PR 3: equal production coverage can hide different detection, and mutation
testing is the experiment that can tell them apart.

## Answers to the PR 2 questions

| Question from #644 | Result |
|---|---|
| Matrix relating tests and covered code | `.coverage` contexts, summarised as `file:line` sets per test |
| Coverage similarity between tests | Jaccard per pair, 83 pairs at 0.8 |
| Sets with high overlap | Telegram, web panel, benchmark client and receipt clusters |
| Exclusive contribution of each test | Per pair and per suite; 3,080 tests have none on production lines |
| Parametrized cases possibly equivalent | 246 families with identical line coverage; none auto-removed |
| Duplication across unit, integration and contract tests | No pairwise subset at 0.8 or 0.6; PR 3 compares detection |
| Expensive fixtures shared by similar tests | Duration is added from JUnit; the report ranks candidates by seconds |
| Candidate classification and risk | No automatic candidate; the review sheet requires contract review |

## Limitations

- **Line coverage, not branch coverage, per test.** Coverage.py exposes
  contexts per line, not per arc. Branch coverage is still collected for the
  totals, but the per-test sets are line-based.
- **Tests are omitted from coverage.** Assertion-only branches do not appear;
  this is why "no exclusive line" is weak evidence and why PR 3 is necessary.
- **Common lines are capped.** Lines covered by more than 50 tests are ignored
  to keep the analysis meaningful and fast; raising the cap adds noise and
  quadratic work.
- **One revision and one run.** Contexts come from a passing run at the commit
  in the snapshot; a later refactor can change which helper a test reaches.
- **No semantic analysis.** Two tests can cover the same lines and assert
  different values. The report says so explicitly.

## Commands for the library suites

```bash
# docstruct
COVERAGE_FILE="$PWD/var/context/docstruct/.coverage" \
  uv run --project "$PWD" python -m pytest libs/docstruct/tests \
  --cov=docstruct --cov-branch --cov-context=test \
  --cov-config="$PWD/pyproject.toml" --cov-report=
uv run python scripts/tests/coverage_overlap.py \
  --coverage-file var/context/docstruct/.coverage \
  --include libs/docstruct/src/docstruct \
  --output var/overlap/docstruct.json
```

The same pattern works for `acessilia_sdk` and `acessilia_core`. The committed
reports are the application run, the largest and most diverse suite.
