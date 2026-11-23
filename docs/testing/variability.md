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
  --output var/timings/variability.json \
  --summary var/timings/variability.md

# Copy the machine-readable record and a generated summary when refreshing
cp var/timings/variability.json docs/testing/variability.json
cp var/timings/variability.md docs/testing/variability.md
```

Each suite runs three times in the same invocation. The runner uses the same
sanitized pytest environment as the mutation harness: ambient `PYTEST_ADDOPTS`,
`PYTEST_PLUGINS`, `PYTEST_DISABLE_PLUGIN_AUTOLOAD`, `PYTEST_CURRENT_TEST`,
`PYTEST_DEBUG` and `PYTEST_DEBUG_TEMPROOT` are removed. The suite record keeps:

- the three raw runs (`runs`);
- the median `junit_seconds`, `wall_seconds`, p50 and p95;
- `wall_seconds_min` and `wall_seconds_max`;
- `runs_count` and the last run's coverage totals.

`compare` still works on the medians. A single run is no longer presented as a
stable measurement.

## Three-run result

| Suite | Tests | Wall median (s) | Range (s) | JUnit median (s) |
|---|---:|---:|---:|---:|
| Application | 3,303 | 254.45 | 249.25–369.78 | 240.99 |
| docstruct | 1,863 | 74.34 | 62.43–91.27 | 57.55 |
| SDK | 702 | 34.88 | 28.58–63.61 | 32.62 |
| core | 1,397 | 116.11 | 88.84–143.81 | 112.83 |
| **Total** | **7,265** | **479.78** | — | **444.00** |

The ranges are the point: the docstruct suite moved between 62.4s and 91.3s and
the application between 249.3s and 369.8s in the same session. Delays observed
in one run should not be attributed to a code change without repeated
measurements and comparable machine conditions.

This table is **not** a before/after comparison. It includes tests and load
conditions different from earlier baselines; the docstruct cache effect remains
the stable observation (the slowest test stays around 2–6s depending on load —
6.174s in the committed record — instead of 23s, not the aggregate suite
time).

## Exhaustive coverage subsumption vs. pair search

The overlap report now exposes both:

- `summary.coverage_subsets` / `coverage_subsets` — complete coverage-subset
  relations between **unique signatures**, independent of Jaccard and of the
  pair-search cap. The summary counts are exhaustive; the JSON array itself is
  still capped by `--top`.
- `summary.pairs` / `pairs` — a Jaccard-ranked list of test pairs. A line
  covered by more than `max_element_tests` tests is dropped from candidate
  generation, so pairs sharing only such lines are missing; the pair list is a
  **lower bound**, not a complete pair census.
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
