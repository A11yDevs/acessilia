# Architectural quality baseline, November 2026

> A Brazilian Portuguese translation is available in
> [quality-baseline.pt-br.md](quality-baseline.pt-br.md).

This is the instrumentation and baseline of [issue #656](https://github.com/A11yDevs/acessilia/issues/656), PR 1. It measures the current revision and records the numbers that the next PRs will use for duplication (PR 2), coupling and cohesion (PR 3), boundaries and migrations (PR 4), and CI guards (PR 5). It changes no production code. The classification of the duplicate groups and the first consolidation are in [duplication-consolidation.md](duplication-consolidation.md).

- **Snapshot:** `develop` at `b00636fc` (2026-11-21), Python 3.12.13.
- **Tool:** [`scripts/architecture_quality.py`](../../scripts/architecture_quality.py), stdlib only.
- **Machine-readable baseline:** [`quality-baseline.json`](quality-baseline.json).
- **Scope:** the Python source of the core, SDK, docstruct, backend and frontend. Tests are outside the baseline; their duplication is tracked by [#644](https://github.com/A11yDevs/acessilia/issues/644).

## Method

The script reads every tracked `.py` file from `git` at the requested revision, so a baseline can be reproduced without checking out the commit. It uses [`scripts/architecture_metrics.py`](../../scripts/architecture_metrics.py) for the filenames and for McCabe's complexity approximation: 1 per function plus 1 per branch, loop, `except`, `with`, conditional expression, comprehension, `assert`, `match` and extra `and`/`or` operand; nested scopes are measured separately. A tracked Python file that does not parse is reported on stderr and skipped rather than silently skewing the totals.

| Measure | Definition |
|---|---|
| Size | Files, non-blank lines, functions and median function length per component |
| Complexity | Functions over 15 and over 100 lines, per component |
| Dependency edge | A file in component A imports a first-party module of component B (`acessilia_core`, `acessilia_sdk`, `docstruct`, `backend`, `frontend`); each file counts once per target, and relative imports count as the current component |
| Fan-in / fan-out | Components that import A / components A imports |
| Cycle | A simple cycle in the component graph |
| Structural duplicate | Functions whose normalized bodies have the same SHA-256 digest; names, constants, attributes and keyword names are normalized. A multi-statement function needs at least 15 non-context AST nodes, as in the original baseline; a one-statement body needs at least 15 nodes of its own, so collapsing a forwarder into one statement cannot hide it |
| Hotspot | The most complex functions and the largest modules |

A structural duplicate is a **candidate**, not a semantic clone. Two functions can share control flow and still differ in types, side effects or error handling. The reported line total is the physical span of the members (including docstrings and signatures), so it is an upper bound on duplicated logic. PR 2 decides which groups are worth consolidating. Cohesion (LCOM), module-level fan-in and semantic duplication are deliberately left to PR 3; this baseline exposes the inputs for those analyses.

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

The regenerated baseline contains **38 groups**, **91 functions** and **1,147 lines** in duplicate groups. The JSON was measured again at the same historical revision (`f812032a`) after #749 changed the detector, so the component numbers stay comparable and only duplicate membership changed. The JSON keeps the 40 largest groups; here all 38 fit. The five largest groups are:

| Group | Lines | Examples |
|---:|---:|---|
| 5 functions | 39 | frontend Telegram handlers `cmd_detailed`, `cmd_low`, `cmd_medium`, `cmd_normal`, `cmd_ocr` |
| 5 functions | 15 | generated SDK dataset readers (`read_dataset_list`, `read_dataset_sample`, `read_dataset_splits`, …) |
| 4 functions | 32 | backend history readers (`listar_historico`, `listar_ocr_raw`, …) |
| 4 functions | 33 | core schema writers (`write_execution_report_schema`, `write_processing_manifest_schema`, …) |
| 3 functions | 17 | core config helpers (`_tool_config`, `_export_config`, `_toolbox_config`) |

Two groups cross component boundaries. The substantive one is `backend/config/settings.py::_locales_from_env` ≡ `libs/core/src/acessilia_core/i18n/__init__.py::_locales_from_raw` (2 functions, 30 lines) — a candidate for PR 2's ownership question. The other is trivial (`JobOperations.__init__` / `_FurnitureView.__init__`, 2 functions, 6 lines). The SDK dataset readers live in `_dataset_generated.py`, whose header says “do not edit by hand”; they are a signal for the generator, not for manual consolidation.

The remaining groups are candidates, not verdicts: equal normalized control flow is not semantic equivalence. The detector ignores docstrings and AST context nodes. Since [#749](https://github.com/A11yDevs/acessilia/issues/749) a substantive one-statement body is fingerprinted instead of exempted, so a documented forwarding wrapper stays visible when its temporary is inlined. PR 2 evaluates each group before touching it.

### Hotspots

| Function | Component | Complexity | Lines |
|---|---|---:|---:|
| `merge_blocks` (`fusion/differ.py`) | docstruct | 89 | 198 |
| `table_ast_from_docling_grid` (`tables/ast.py`) | docstruct | 63 | 147 |
| `decode` (`toolbox/results/_model.py`) | SDK | 56 | 109 |
| `recover_empty_lettered_list_items` (`blocks/lists.py`) | docstruct | 53 | 131 |
| `JobExecutor.run` (`api/worker.py`) | backend | 43 | 325 |

The largest modules by total lines are the core payload (899; 801 non-blank), the core vision agent (885; 793), the backend worker (871; 788), the core orchestrator (871; 808) and docstruct's `tables/ast.py` (828; 691). D4's 900-line guard applies only to `libs/core/src/acessilia_core`, and the payload is one line under it; the backend and docstruct modules are outside that guard. They are the first candidates for PR 3's coupling review.

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

The committed JSON records the measured commit in `rev` and the Python version in `python`. Duplicate-group identity is comparable only on the same Python minor version, because `ast.dump` can change with the grammar; size, complexity and dependency edges are stable. The script is a diagnostic only: it exits 0 even when the numbers grow. PR 5 decides which measures become a ratchet, with the allowlist and update workflow of the existing #652 and Ruff baselines.

## What this PR does not decide

- It does not remove a duplicate, move a module or change a component boundary.
- It does not claim that a structural duplicate is safe to merge.
- It does not measure cohesion or semantic duplication yet.
- It does not add a CI failure; a baseline that fails the build before PR 2 would freeze unrelated work.

The intended sequence remains PR 1 (this baseline), PR 2 (duplication and consolidation), PR 3 (coupling and cohesion), PR 4 (boundaries and migrations) and PR 5 (guards), with smaller PRs when a change is substantial.
