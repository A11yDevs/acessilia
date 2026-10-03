# XY-cut reading order for multi-column pages

> Portuguese version: [reading_order_xycut.pt-br.md](reading_order_xycut.pt-br.md)

An optional step of the multi-provider fusion (`docstruct.fusion`) that fixes the
reading order of **multi-column pages**. It is **off by default**; nothing changes
unless a policy turns it on.

## The problem

The fusion takes its reading order from one provider (MinerU, the "skeleton").
On pages with two or more text columns the skeleton sometimes reads **row by
row across the columns** instead of finishing one column before starting the
next:

```
  what the page looks like          skeleton order (wrong)      expected order

  +---------+  +---------+          1 -> 2                      1    3
  |    A    |  |    C    |          |  /                        |    |
  +---------+  +---------+          v /                         v    v
  +---------+  +---------+          3 -> 4                      2    4
  |    B    |  |    D    |
  +---------+  +---------+          A, C, B, D                  A, B, C, D
```

In the Dr.DocBench plan this is item **S6.3 / lever D** ("geometric order for
`three_column` / `1andmore` pages").

## The idea

**XY-cut** is a classic geometric method: look at the block boxes, find the
vertical white gaps ("gutters") that split the page into columns, read the
columns left to right, and inside each column read top to bottom. Blocks that
span the full width (a title, a wide table) act as section breaks. It uses only
the boxes already produced by the providers — no model, no OCR, no LLM, about
0.1 ms per page.

It is the method that performed best in the reading-order study on multi-column
official gazettes that motivated this contribution (Kendall tau 0.837).

## When it acts (and when it does not)

Applying XY-cut to every page makes things worse: on single-column pages the
expected order often departs from a pure top-down reading (figures, captions,
sidebars). So the step is guarded by two gates:

| Gate | Policy field | Meaning |
|---|---|---|
| multi-column | `xycut_min_columns` (default `2`) | only pages whose boxes form at least this many top-level columns |
| balanced columns | `xycut_min_balance` (default `0.0` = off; `0.7` recommended) | the narrowest column must be at least this fraction of the widest one |

The second gate separates real text columns from a **main column next to a
narrow sidebar** — the case where XY-cut loses.

Both gates set full-width blocks aside before looking for columns: a title or
a wide table that spans two columns bridges the gutter and would otherwise make
the page look like a single column. For the same reason a dominant text column
(60% or more of the text span) next to a narrow margin column is treated as a
single-column page.

The step only changes the *sequence* of the blocks that survived the previous
fusion stages: nothing is added, dropped or rewritten. Blocks without a usable
box travel with the block before them. Headers, footers and page numbers stay
in the decor tail.

## How to enable it

Python:

```python
from dataclasses import replace
from docstruct.policy import FusionPolicy

policy = replace(FusionPolicy.drbench_v13(), order_xycut="multicol", xycut_min_balance=0.7)
```

Dr.DocBench experiment script:

```bash
python -m scripts.drbench.experiments.differ.lib_fuse \
  --docling runs/docling/predictions --mineru runs/mineru/predictions \
  --out runs/fusion-xycut/predictions --policy v13 \
  --xycut multicol --xycut-min-balance 0.7
```

Slurm:

```bash
sbatch --export=ALL,SPLIT=dev,POLICY=v13,XYCUT=multicol,XYCUT_MIN_BALANCE=0.7,RUN_NAME=lib-fuse-v13-xycut-bal07 \
  scripts/drbench/experiments/slurm/lib_fuse.sbatch
```

`order_xycut` accepts `off` (default), `multicol` and `always` (every page;
kept for comparison only). Decisions are counted in `decisions.csv`:
`xycut-applied`, `xycut-moved`, `xycut-columns:<n>`,
`xycut-skipped:single-column`, `xycut-skipped:unbalanced-columns`,
`xycut-skipped:few-boxes`.

## Experiment (small batch)

**Setup.** Local replica of the acceptance protocol: the fixed **dev-120**
subset (`docs/drbench/experiments/dev120-subset.json`), official DrDocBench
evaluator (`multipage_md2md_dataset`, 1-page windows, no CDM; ground truth
scored against itself gives 100), Docling through the Toolbox, MinerU 2.7.6
`pipeline` backend on CPU converted by the Toolbox adapter, fusion with
`lib_fuse.py --policy v13`. 119 pages are scorable (113 have a reading-order
score). Comparison is **paired per page** against the same fusion without
XY-cut.

| Variant (on top of fusion v13) | RO delta | 95% CI | pages up / down | sign test p | Overall delta |
|---|---|---|---|---|---|
| XY-cut on every page (`always`) | -0.29 | [-3.0, +2.5] | 12 / 13 | 1.00 | -0.14 |
| `multicol` | +1.12 | [-1.2, +3.6] | 12 / 8 | 0.50 | +0.53 |
| `multicol` + balance 0.5 | +1.91 | [+0.15, +3.98] | 10 / 2 | 0.039 | +0.91 |
| **`multicol` + balance 0.7** | **+2.14** | **[+0.75, +3.97]** | **9 / 0** | **0.004** | **+1.02** |

Text edit distance is unchanged in every variant (the evaluator matches blocks
regardless of order). Policy v12 gives the same +2.14.

By page layout:

| Layout (pages) | RO delta, `multicol` | RO delta, `multicol` + balance 0.7 |
|---|---|---|
| double_column (26) | +7.1 (6 up, 0 down) | +6.0 (5 up, 0 down) |
| three_column (9) | +5.6 (2 up, 0 down) | +1.0 (1 up, 0 down) |
| 1andmore_column (22) | -2.1 (3 up, 5 down) | +3.4 (3 up, 0 down) |
| other_layout (8) | -7.0 (0 up, 2 down) | 0.0 (not touched) |
| single_column (48) | -0.1 | 0.0 (not touched) |

Per-page numbers: [`drbench/experiments/xycut-dev120-local_per_page.csv`](drbench/experiments/xycut-dev120-local_per_page.csv).

### How robust is the +2.14?

The result was put through an adversarial review; these are the stricter
checks, all for `multicol` + balance 0.7:

| Check | Result |
|---|---|
| Even half of the pages (ids sorted, even positions) | +3.06 (6 up, 0 down) |
| Odd half | +1.13 (3 up, 0 down) |
| 95% CI resampling whole **documents** (48 books) instead of pages | [+0.39, +4.38] |
| Documents that improve / get worse | 5 / 0 |
| Without the strongest document | +1.51 |
| Without the two strongest documents | +0.90 |

So the direction holds in both halves and no page or document gets worse, but
the size depends on a handful of books: the gain comes from **5 of the 48
documents** (cooking, gardening, social science, transportation, house & home).

Ceiling check: XY-cut applied to the *ground-truth* boxes reproduces the
ground-truth order with RO 87.1 on multi-column pages, 84.6 on single-column
pages and 61.8 on `other_layout`, which is why the gates exist.

## Limitations — read before using the numbers

- **Local replica, not the cluster.** Docling ran without `force_ocr` and
  rotation fixes, MinerU on CPU, and tables were not rendered in the local
  blocks (TEDS n=0). Absolute scores are therefore lower than the cluster runs
  (fusion RO 69.8 here vs 79.3 on dev-986) and are **not comparable**; only the
  paired difference between variants is meaningful.
- **The 0.7 threshold was chosen on dev-120** (0.5 and 0.7 were tried). Going
  from no balance gate to 0.7 accounts for about half of the gain, by leaving
  out the pages that lost. It must be confirmed on **dev-986 with the cluster
  evaluator** before any EvalAI submission (acceptance rule: at least +0.3
  `evalai_style`, no component dropping more than 0.3).
- The gain is **small and concentrated** (about +2 RO on average, from 9 pages
  in 5 books). It does not close the reading-order gap to the leaderboard
  leaders by itself.
- The column gates are geometric. A legitimate asymmetric layout (for example
  a 65% text column with a 35% column of continuous notes) is left untouched
  by design; the gutter constant (4 pt on an A4 page) comes from the gazette
  study and was not re-tuned for books.
- It is independent from the `order_relations` option (conservative placement
  of Docling-only blocks): that one fixes insertions, this one fixes the
  skeleton order on multi-column pages. Applying `order_relations` first and
  XY-cut afterwards passed both test suites in a local merge.

## Code

- `libs/docstruct/src/docstruct/fusion/xycut.py` — `xycut_order`, `count_columns`, `column_balance`, `reorder`
- `libs/docstruct/src/docstruct/policy.py` — `order_xycut`, `xycut_min_columns`, `xycut_min_balance`
- `libs/docstruct/src/docstruct/fusion/differ.py` — hook at the end of `merge_blocks`
- `libs/docstruct/tests/test_xycut.py` — 29 tests

## Additional held-out books (2026-10-03)

The same corrected implementation and frozen `multicol` / balance `0.7`
configuration were evaluated on 60 additional DrDocBench pages from 16 books
absent from dev-120. Selection seed: `3102026`; dataset
`2077AIDataFoundation/DrDocBench` at revision `7a2bc3882dff68e883fb55d10d4df22865ce2b07`.
The accompanying [per-page CSV](drbench/experiments/xycut-new60-local_per_page.csv)
identifies every selected page, including one page without evaluable content.

Official md2md evaluation, window 1, no CDM: 59 paired pages. Unlike the
earlier local run, the baseline here preserves recovered HTML tables; this
particular held-out sample has no table/formula GT. Do not pool absolute scores
with dev-120 or treat this as full dev-986 confirmation.

| Metric | Baseline | XY-cut | Paired delta |
|---|---:|---:|---:|
| Overall, without CDM | 73.1276 | 73.3544 | +0.2269 |
| Reading order | 72.9665 | 73.4202 | +0.4537 |

Text scores are unchanged. Overall: 4 improvements,
1 regression, 54 ties (tolerance 0.05 points).
The paired Overall 95% interval from resampling whole books is
[0.0000, 0.6249].
The smaller gain and observed regression support keeping the option disabled
by default. A further 120-page DrDocBench holdout and a separate 120-page
OmniDocBench diagnostic are in progress; no result from those unfinished runs
is claimed here.
