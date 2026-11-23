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
make test-overlap

# The target writes var/overlap/app.json, app.md, redundancy.json and
# redundancy.md; the committed snapshot is those files copied here.
cp var/overlap/app.json docs/testing/overlap-app.json
cp var/overlap/app.md docs/testing/overlap-app.md
cp var/overlap/redundancy.json docs/testing/redundancy-app.json
cp var/overlap/redundancy.md docs/testing/redundancy-app.md
```

The target runs the application suite with
`--cov-context=test`, writes `var/overlap/context/.coverage` and
`var/overlap/app-results.xml`, then invokes both analysis scripts with
`--extra dev`.

The first script computes the Jaccard similarity
`|A ∩ B| / |A ∪ B|` for every pair that shares at least five lines, and flags
pairs at or above `0.8`. A line covered by more than 50 tests is used only to
*propose* candidate pairs; every reported intersection, union, `only_a`,
`only_b` and Jaccard value is recomputed from the complete test sets. The cap
therefore bounds the search, not the metric.

Coverage subsumption is computed separately from the complete sets and does not
depend on the Jaccard threshold: a small test can be contained in a much larger
one with low similarity. Tests with the same coverage signature are grouped, so
the report shows signature relations and their group sizes instead of millions
of pairwise duplicates.

The second script adds durations, ranks the coverage-subset candidates,
separates parametrized variants and states how many examples of each table are
shown. `--junit` reads complete JUnit reports; `--baseline` is the optional PR 1
baseline and is only used for its slowest-test lists. It never edits, deletes or
skips a test.

## Results

The application suite ran 3,197 tests over 3,559 measured lines.

| Measure | Value |
|---|---:|
| Pairs at Jaccard >= 0.8 with >= 5 shared lines | 1,995 |
| Exact pairs (Jaccard = 1.0) | 735 |
| Mean similarity of the reported pairs | 0.951 |
| Parametrized families analysed | 288 |
| Families with identical line coverage | 247 |
| Coverage-subset signature relations | 1,250 |
| · strict subsets | 1,151 |
| · identical-coverage groups | 99 |
| Tests sharing an identical coverage signature | 2,914 |
| Tests with no exclusive production line | 3,085 of 3,197 |

The suite has substantial overlap, but the conclusion is not an automatic
deletion list. The subset analysis finds **1,250 coverage relations between
unique signatures**, including 1,151 strict subsets. That contradicts the
earlier framing that no subset exists: a small test can be contained in a much
larger one with low Jaccard, which is why subsumption must be computed without
the similarity threshold. The review sheet ranks the examples by measured
seconds; it does not remove any test.

### Where the overlap is

| Cluster | Example | Jaccard | Shared | Only A | Only B |
|---|---|---:|---:|---:|---:|
| Long output names | `test_long_filename_can_be_exported_and_downloaded[long-ascii]` ↔ `[long-cjk]` | 1.000 | 605 | 0 | 0 |
| Pending fixes | `test_email_delivery_status_does_not_lose_download[False]` ↔ `[None]` | 0.993 | 455 | 3 | 0 |
| Model-call executor | `test_pending_calls_are_removed_and_never_start_late[False]` ↔ `test_running_deadline_retains_capacity_and_default_executor_stays_available` | 0.924 | 98 | 8 | 0 |
| Benchmark client matrix | `test_the_harness_configures_clients_like_the_core[...]` variants | — | 273 | — | — |

These clusters share the request/response plumbing of one scenario. Some pairs
are strict coverage subsets; others still cover lines that their neighbour does
not. Coverage alone cannot show whether the assertions, contracts or failure
modes are duplicated, so the review sheet is the input for PR 3's mutation
experiment.

### Parametrized families

246 of the 288 analysed families have **identical line coverage** across their
variants. The strongest examples are the benchmark client matrix, the web panel
receipt states and the Telegram locale permutations. This is expected: a
parametrization usually varies inputs and expected assertions, not the
production path. Equal line coverage is not duplicate behaviour; the variants
can fail for different reasons.

The overlap report lists the families and their signature groups; the review
sheet lists the candidate tests and pairs. It classifies
`identical-parameterization` separately and never proposes one of its variants
as a removal.

### Tests without an exclusive production line

3,085 of 3,197 tests cover no line that no other test covers. This number is
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
| Coverage similarity between tests | Jaccard per pair, 1,995 pairs at 0.8 |
| Sets with high overlap | Long-output, pending-fix, model-call and benchmark clusters |
| Exclusive contribution of each test | Per pair and per suite; 3,085 tests have none on production lines |
| Coverage subsumption | 1,250 signature relations (1,151 strict, 99 identical), independent of Jaccard |
| Parametrized cases possibly equivalent | 246 families with identical line coverage; none auto-removed |
| Duplication across unit, integration and contract tests | 1,250 coverage-subset signatures; PR 3 compares detection |
| Expensive fixtures shared by similar tests | Duration is added from JUnit; the report ranks candidates by seconds |
| Candidate classification and risk | No automatic candidate; the review sheet requires contract review |

## Limitations

- **Line coverage, not branch coverage, per test.** Coverage.py exposes
  contexts per line, not per arc. Branch coverage is still collected for the
  totals, but the per-test sets are line-based.
- **Tests are omitted from coverage.** Assertion-only branches do not appear;
  this is why "no exclusive line" is weak evidence and why PR 3 is necessary.
- **Common lines only prune the pair search.** Lines covered by more than 50
  tests are not used to propose pairs; the reported metrics and the subset
  analysis use the complete sets. The candidate set can still miss a pair whose
  every line is shared infrastructure, which is documented by the totals.
- **One revision and one run.** Contexts come from a passing run at the commit
  in the snapshot; a later refactor can change which helper a test reaches.
- **No semantic analysis.** Two tests can cover the same lines and assert
  different values. The report says so explicitly.

## Commands for the library suites

```bash
# docstruct
COVERAGE_FILE="$PWD/var/context/docstruct/.coverage" \
  uv run --extra dev --project "$PWD" python -m pytest libs/docstruct/tests \
  --cov=docstruct --cov-branch --cov-context=test \
  --cov-config="$PWD/pyproject.toml" --cov-report=
uv run --extra dev python scripts/tests/coverage_overlap.py \
  --coverage-file var/context/docstruct/.coverage \
  --include libs/docstruct/src/docstruct \
  --output var/overlap/docstruct.json
```

The same pattern works for `acessilia_sdk` and `acessilia_core`. The committed
reports are the application run, the largest and most diverse suite.
