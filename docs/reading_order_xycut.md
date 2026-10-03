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
`lib_fuse.py --policy v13`. 119 pages are scorable. Comparison is **paired per
page** against the same fusion without XY-cut.

| Variant (on top of fusion v13) | RO delta | 95% CI | pages up / down | sign test p | Overall delta |
|---|---|---|---|---|---|
| XY-cut on every page (`always`) | -0.29 | [-3.0, +2.5] | 12 / 13 | 1.00 | -0.14 |
| `multicol` | +0.84 | [-1.1, +3.0] | 8 / 5 | 0.58 | +0.40 |
| `multicol` + balance 0.5 | +1.17 | [-0.4, +3.0] | 7 / 2 | 0.18 | +0.56 |
| **`multicol` + balance 0.7** | **+1.65** | **[+0.45, +3.30]** | **7 / 0** | **0.016** | **+0.79** |

Text edit distance is unchanged in every variant (the evaluator matches blocks
regardless of order). Policy v12 shows the same pattern.

By page layout, `multicol` → `multicol` + balance 0.7:

| Layout (pages) | RO delta without balance | RO delta with balance 0.7 |
|---|---|---|
| double_column (26) | +6.0 | +4.5 (4 up, 0 down) |
| three_column (9) | +1.0 | +1.0 |
| 1andmore_column (22) | -0.7 | +2.8 (2 up, 0 down) |
| other_layout (8) | -7.0 | 0.0 (not touched) |
| single_column (48) | 0.0 | 0.0 (not touched) |

Per-page numbers: [`drbench/experiments/xycut-dev120-local_per_page.csv`](drbench/experiments/xycut-dev120-local_per_page.csv).

Ceiling check: XY-cut applied to the *ground-truth* boxes reproduces the
ground-truth order with RO 87.1 on the pages the multi-column gate selects
(84.6 on single-column pages and 61.8 on `other_layout`, which is why the gate
exists).

## Limitations — read before using the numbers

- **Local replica, not the cluster.** Docling ran without `force_ocr` and
  rotation fixes, MinerU on CPU, and tables were not rendered in the local
  blocks (TEDS n=0). Absolute scores are therefore lower than the cluster runs
  (fusion RO 69.8 here vs 79.3 on dev-986) and are **not comparable**; only the
  paired difference between variants is meaningful.
- **The 0.7 threshold was chosen on dev-120** (only 0.5 and 0.7 were tried).
  It must be confirmed on **dev-986 with the cluster evaluator** before any
  EvalAI submission (acceptance rule: at least +0.3 `evalai_style`, no
  component dropping more than 0.3).
- The gain is **small and local** (about +1.6 RO on average, concentrated in
  ~25 multi-column pages). It does not close the reading-order gap to the
  leaderboard leaders by itself.
- It is independent from the `order_relations` option (conservative placement
  of Docling-only blocks): that one fixes insertions, this one fixes the
  skeleton order on multi-column pages. Applying `order_relations` first and
  XY-cut afterwards passed both test suites in a local merge.

## Code

- `libs/docstruct/src/docstruct/fusion/xycut.py` — `xycut_order`, `count_columns`, `column_balance`, `reorder`
- `libs/docstruct/src/docstruct/policy.py` — `order_xycut`, `xycut_min_columns`, `xycut_min_balance`
- `libs/docstruct/src/docstruct/fusion/differ.py` — hook at the end of `merge_blocks`
- `libs/docstruct/tests/test_xycut.py` — 25 tests
