# Baseline variability and exhaustive overlap

> A Brazilian Portuguese translation is available in
> [variability.pt-br.md](variability.pt-br.md).

This is the follow-up to [issue #644](https://github.com/A11yDevs/acessilia/issues/644)
tracked in #756. It replaces single-run claims with a repeatable measurement and
states exactly what the coverage-overlap pair search does and does not prove.

- **Tool:** [`scripts/tests/collect_timings.py`](../../scripts/tests/collect_timings.py)
  with `--repeat`.
- **Committed run:** [`variability.json`](variability.json) and
  [`variability.md`](variability.md).
- **Environment:** `develop` at `6b586fe9`, Python 3.12.13, four xdist workers,
  macOS reference machine under normal desktop load.

## Method

```bash
uv run --extra dev python scripts/tests/collect_timings.py collect \
  --run --repeat 3 \
  --output docs/testing/variability.json \
  --summary docs/testing/variability.md
```

Each suite runs three times in the same invocation. The suite record keeps:

- the three raw runs (`runs`);
- the median `junit_seconds`, `wall_seconds`, p50 and p95;
- `wall_seconds_min` and `wall_seconds_max`;
- `runs_count` and the last run's coverage totals.

`compare` still works on the medians. A single run is no longer presented as a
stable measurement.

## Three-run result

| Suite | Tests | Wall median (s) | Range (s) | JUnit median (s) |
|---|---:|---:|---:|---:|
| Application | 3,298 | 247.39 | 193.14–247.74 | 234.83 |
| docstruct | 1,863 | 47.54 | 30.79–48.78 | 37.80 |
| SDK | 702 | 41.88 | 31.91–44.11 | 40.10 |
| core | 1,397 | 59.50 | 53.74–60.02 | 57.67 |
| **Total** | **7,260** | **396.31** | — | **370.39** |

The ranges are the point: the docstruct suite moved between 30.8s and 48.8s and
the application between 193.1s and 247.7s in the same session. Delays observed
in one run should not be attributed to a code change without repeated
measurements and comparable machine conditions.

This table is **not** a before/after comparison. It includes tests and load
conditions different from earlier baselines; the docstruct cache effect remains
the stable observation (the slowest test stays around 2–3s instead of 23s, not
the aggregate suite time).

## Exhaustive coverage subsumption vs. pair search

The overlap report now exposes both:

- `summary.coverage_subsets` / `coverage_subsets` — complete coverage-subset
  relations between **unique signatures**, independent of Jaccard and of the
  pair-display cap. This is the exhaustive subsumption view.
- `summary.pairs` / `pairs` — a Jaccard-ranked list of test pairs. A line
  covered by more than `max_element_tests` tests is used only to propose
  candidates, so the pair list is a **lower bound**, not a complete pair census.
  The report records `pair_search_complete: false` and `pair_search_cap`.

A missing pair in `pairs` does not mean no coverage overlap exists; use
`coverage_subsets` for the complete subset relation. The metrics of every
reported pair are still computed from the complete test sets.

## What is covered

- `collect_timings.py` has a `--repeat N` option and `combine_runs()` keeps
  median, min/max and the raw runs.
- `run_suite` without a JUnit report is covered by a monkeypatched-subprocess
  test: it returns a failed record instead of a crash.
- `coverage_overlap` labels the pair search as incomplete and never presents it
  as exhaustive.
- The three-run baseline is committed for reproducibility.

## Limitations

- The reference machine is not an isolated benchmark host; desktop load is part
  of the range.
- Three runs estimate dispersion, not a confidence interval.
- The comparison is per suite; the aggregate is a sum of medians.
- The pair-search cap remains a candidate-generation filter. It is documented
  and testable, not silently exhaustive.
