# Architectural quality baseline, November 2026

> A Brazilian Portuguese translation is available in
> [quality-baseline.pt-br.md](quality-baseline.pt-br.md).

This is the instrumentation and baseline of [issue #656](https://github.com/A11yDevs/acessilia/issues/656), PR 1. It measures the current revision and records the numbers that the next PRs will use for duplication (PR 2), coupling and cohesion (PR 3), boundaries and migrations (PR 4), and CI guards (PR 5). It changes no production code.

- **Snapshot:** `develop` at `b00636fc` (2026-11-21), Python 3.12.13.
- **Tool:** [`scripts/architecture_quality.py`](../../scripts/architecture_quality.py), stdlib only.
- **Machine-readable baseline:** [`quality-baseline.json`](quality-baseline.json).
- **Scope:** the Python source of the core, SDK, docstruct, backend and frontend. Tests are outside the baseline; their duplication is tracked by [#644](https://github.com/A11yDevs/acessilia/issues/644).

## Method

The script reads every tracked `.py` file from `git` at the requested revision, so a baseline can be reproduced without checking out the commit. It uses [`scripts/architecture_metrics.py`](../../scripts/architecture_metrics.py) for the filenames and for McCabe's complexity approximation: 1 per function plus 1 per branch, loop, `except`, `with`, conditional expression, comprehension, `assert`, `match` and extra `and`/`or` operand; nested scopes are measured separately.

| Measure | Definition |
|---|---|
| Size | Files, non-blank lines, functions and median function length per component |
| Complexity | Functions over 15 and over 100 lines, per component |
| Dependency edge | A file in component A imports a first-party module of component B (`acessilia_core`, `acessilia_sdk`, `docstruct`, `backend`, `frontend`); each file counts once per target, and relative imports count as the current component |
| Fan-in / fan-out | Components that import A / components A imports |
| Cycle | A simple cycle in the component graph |
| Structural duplicate | Functions with at least 20 AST nodes and two statements whose normalized bodies have the same SHA-256 digest; names, constants, attributes and keyword names are normalized |
| Hotspot | The most complex functions and the largest modules |

A structural duplicate is a **candidate**, not a semantic clone. Two functions can share control flow and still differ in types, side effects or error handling. PR 2 decides which groups are worth consolidating. Cohesion (LCOM), module-level fan-in and semantic duplication are deliberately left to PR 3; this baseline exposes the inputs for those analyses.

## Baseline

### Size and complexity

| Component | Files | Non-blank lines | Functions | > 100 lines | Complexity > 15 |
|---|---:|---:|---:|---:|---:|
| Core (`libs/core/src/acessilia_core`) | 112 | 21,367 | 799 | 0 | 0 |
| SDK (`libs/sdk/src/acessilia_sdk`) | 45 | 5,783 | 221 | 1 | 3 |
| docstruct (`libs/docstruct/src/docstruct`) | 89 | 13,883 | 680 | 6 | 40 |
| Backend (`backend`) | 46 | 5,100 | 238 | 3 | 5 |
| Frontend (`frontend`) | 24 | 2,294 | 89 | 1 | 1 |

The core carries the #612 result: none of its functions is over 100 lines or complexity 15. The residual complexity is concentrated in docstruct (40 functions over 15), followed by the backend (5), the SDK (3) and the frontend (1).

### Component dependencies

| From | To | Files |
|---|---|---:|
| Backend | Core | 27 |
| Backend | docstruct | 1 |
| Backend | SDK | 3 |
| Core | docstruct | 47 |
| Core | SDK | 19 |
| Frontend | Backend | 9 |
| Frontend | Core | 13 |
| SDK | docstruct | 4 |

No component cycle was found. Fan-in: Core 2, SDK 2, docstruct 3, backend 1, frontend 0. Fan-out: Core 2, SDK 1, docstruct 0, backend 3, frontend 2.

### Structural duplicates

The baseline contains **50 groups**, **133 functions** and **1,529 lines** in duplicate groups. The JSON keeps the 40 largest groups; totals cover every group. The five largest groups are:

| Group | Lines | Examples |
|---:|---:|---|
| 9 functions | 99 | `FusionAgent` operation wrappers (`move_header_footer_to_end`, `normalize_formula`, `normalize_text`, `refine_reading_order`, …) |
| 7 functions | 87 | `AdjudicationAgent` and `OrderAdjudicationAgent` wrappers (`decide_from_transcription`, `complete_order`, `kendall_tau`, `parse_order`, …) |
| 7 functions | 33 | `FusionAgent.process_*` and `OrderAdjudicationAgent.process_refine_reading_order` |
| 6 functions | 22 | `OrderAdjudicationAgent.process_*` and `PageLevelAgent.process_decide_orientation` |
| 5 functions | 15 | SDK dataset readers (`read_dataset_list`, `read_dataset_sample`, `read_dataset_splits`, …) |

The first groups are dominated by process/wrapper methods around the Agno agents. They may be legitimate adapters or may hide a reusable operation; PR 2 evaluates each group before touching it. The detector found no cross-component group large enough to change the ownership map on its own.

### Hotspots

| Function | Component | Complexity | Lines |
|---|---|---:|---:|
| `merge_blocks` (`fusion/differ.py`) | docstruct | 89 | 198 |
| `table_ast_from_docling_grid` (`tables/ast.py`) | docstruct | 63 | 147 |
| `decode` (`toolbox/results/_model.py`) | SDK | 56 | 109 |
| `recover_empty_lettered_list_items` (`blocks/lists.py`) | docstruct | 53 | 131 |
| `JobExecutor.run` (`api/worker.py`) | backend | 43 | 325 |

The largest modules are the core orchestrator (808 lines), the core payload (801), the core vision agent (793), the backend worker (788) and the core toolbox extractor (751). All are below the current 900-line module limit, but they are the first candidates for PR 3's coupling review.

## Reproduction

```bash
# Full JSON baseline on the current revision (stdout)
python scripts/architecture_quality.py --rev HEAD

# Rewrite the committed snapshot
python scripts/architecture_quality.py --rev HEAD \
  --output docs/architecture/quality-baseline.json

# The shape and the duplicate detector
python -m pytest tests/test_architecture_quality.py
```

The committed JSON records the measured commit in `rev`. The script is a diagnostic only: it exits 0 even when the numbers grow. PR 5 decides which measures become a ratchet, with the allowlist and update workflow of the existing #652 and Ruff baselines.

## What this PR does not decide

- It does not remove a duplicate, move a module or change a component boundary.
- It does not claim that a structural duplicate is safe to merge.
- It does not measure cohesion or semantic duplication yet.
- It does not add a CI failure; a baseline that fails the build before PR 2 would freeze unrelated work.

The intended sequence remains PR 1 (this baseline), PR 2 (duplication and consolidation), PR 3 (coupling and cohesion), PR 4 (boundaries and migrations) and PR 5 (guards), with smaller PRs when a change is substantial.
