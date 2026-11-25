# Evaluation: core, SDK and docstruct after the refactoring (#470, phase 5)

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](core-sdk-docstruct-evaluation.pt-br.md)

Phase 5 of [#470](https://github.com/A11yDevs/acessilia/issues/470) asks what
the refactoring of #402 and #470 changed, measured. This page compares the
code before the refactoring with the code after it, under six headings:

1. the core's size and residual complexity;
2. the cost of installing docstruct and the SDK alone;
3. the external dependencies of each component;
4. the time of the local tests;
5. the reuse of SDK operations by scripts and benchmarks;
6. functional and structural regressions.

It ends with the consequences observed and the follow-ups they suggest.

## Method

- **Baseline:** `66a078b2`, develop on 2026-11-09, the parent of the first
  commit of #402 (`5e142e50`). The core was then part of the service, under
  `backend/`.
- **Now:** `c22340d0`, develop on 2026-11-18, after #609 and #610.
- **Code measures:** [`scripts/architecture_metrics.py`](../../scripts/architecture_metrics.py).
  It reads each file from git at a revision, so the baseline is measured
  without checking it out. It reports files, non-blank lines, functions,
  functions over 100 lines, and functions whose complexity is over 15.
  Complexity is McCabe's, approximated on the AST: 1 per function, plus 1 per
  branch, loop, `except`, `with`, conditional expression, comprehension,
  `assert`, `match` and extra `and`/`or` operand. Nested functions, lambdas
  and classes are not descended into (they are measured separately). Repeat a
  row with, for example:

  ```bash
  python scripts/architecture_metrics.py --rev 66a078b2 backend
  python scripts/architecture_metrics.py --rev HEAD backend libs/core/src
  ```

- **Install measures:** a clean Python 3.11 virtual environment per
  component, installed with `uv pip install` from the local checkout, without
  uv's cache for docstruct, the SDK and the core. The size is the
  environment's `site-packages`.
- **Test time:** `make test-all`, run twice on a development laptop (macOS,
  the main suite with `-n 4`). The two runs differ by up to 20 %, so each time
  is given as a range.

## 1. Size and residual complexity

| Code | Files | Non-blank lines | Functions | Over 100 lines | Complexity over 15 |
|---|---:|---:|---:|---:|---:|
| **Baseline:** service and core (`backend/`) | 114 | 20,042 | 741 | 26 | 48 |
| **Now:** service and core (`backend/`, `libs/core/src`) | 151 | 24,598 | 883 | 24 | 46 |
| of which the service (`backend/`) | 46 | 5,081 | 238 | 3 | 5 |
| of which the core (`libs/core/src`) | 105 | 19,517 | 645 | 21 | 41 |
| docstruct (`libs/docstruct/src`), baseline → now | 75 → 83 | 10,142 → 11,790 | 433 → 581 | 5 → 6 | 40 → 39 |
| SDK (`libs/sdk/src`), baseline → now | 28 → 44 | 2,484 → 5,289 | 95 → 208 | 0 → 1 | 1 → 3 |

- **The orchestrator went from 6,103 lines to 790.**
  `backend/agents/pddl_orchestrator.py` became
  `libs/core/src/acessilia_core/pipeline/orchestrator.py`. Its handlers,
  enrichment stages, payload and judge became modules of their own (#402
  phase 3, step 6).
- **The service is now small:** 5,081 lines, with 3 long functions and 5
  complex ones. The decisions moved into the core package, which the service
  calls with an explicit `CoreConfig` and ports (ADR-0016).
- **The total grew by 4,556 lines (23 %),** for two reasons:
  - **new features shipped in the same nine days.** Among them: operation
    identifiers and cancellation (ADR-0019), the job journal (ADR-0020),
    bounded model calls (ADR-0021), the strict export gate (ADR-0026),
    checkpoint identities (#549), and the `CoreConfig` and ports that replaced
    the core's reads of `settings`;
  - **the moves add a docstring and imports per new module.** The core has
    105 files where its code had 69.
- **The SDK doubled,** with two operations (about 470 lines), typed results
  and readers (#213), the command line and cancellation (ADR-0019).
- **The residual complexity remains concentrated where it was.** 46 functions
  across the service and core are over 15 (down from 48 at the baseline; 41
  in the core alone), and the most complex function is the same. The refactoring
  moved responsibilities by design, one per pull request with behaviour
  preserved, so it did not simplify function logic. The core's five most
  complex functions:

  | Function | Module | Complexity | Lines |
  |---|---|---:|---:|
  | `_derive_v23_processing_needs` | `manifest/builder.py` | 71 (73 at the baseline) | 269 |
  | `apply_page_routes` | `pipeline/fusion.py` | 35 | 100 |
  | `_execute_step` | `execution/executor.py` | 33 | 161 |
  | `_absorb_near_pictures` | `manifest/slides.py` | 33 | 80 |
  | `_extract_with` | `manifest/toolbox_extractor.py` | 33 | 234 |

  Of the 41 complex functions in the core, 24 are in `pipeline` and 9 in
  `manifest`.

## 2. Cost of an isolated install

| Install | Packages | `site-packages` | Time |
|---|---:|---:|---:|
| docstruct alone | 1 | 0.75 MB | about 1 s |
| SDK (with docstruct) | 10 | 2 MB | about 1 s |
| core (with the SDK and docstruct) | 57 | 102 MB | about 3 s |
| the service (the repository's runtime dependencies) | 75 | 119 MB | about 3 s, warm cache |

- **A script that only needs the Toolbox and the structural algorithms
  installs 10 packages and 2 MB:** `httpx` and its dependencies, the SDK and
  docstruct. At the baseline, the SDK depended on `httpx` alone, and the core
  could not be installed without the service.
- **The core alone is almost as heavy as the service.** Its weight is the
  agent stack: `babel` (32 MB), `agno` (19 MB) and `openai` (10 MB) are the
  largest packages. The service adds 18 packages and 17 MB on top
  (FastAPI, uvicorn, aiogram, SQLAlchemy and the rest).
- **The CI checks each one alone:** the `docstruct alone`, `SDK alone` and
  `core alone` jobs install from their own lock and refuse what must not be
  importable next to them.

## 3. External dependencies per component

Runtime dependencies declared in each `pyproject.toml`:

| Component | Count | Dependencies |
|---|---:|---|
| docstruct | 0 | none: the standard library only, with one optional accelerator behind `except ImportError` |
| SDK | 2 | `httpx`, docstruct |
| core | 11 | docstruct, the SDK, `agno`, `openai`, `ollama`, `pydantic`, `loguru`, `babel`, `jsonschema`, `rapidfuzz`, `edge-tts` |
| service | 22 | the core, the SDK and docstruct, plus the web, bot, mail, database and settings stack |
| Toolbox | 5 | plus seven extras (`api`, `cache`, `media`, `music`, `pdf`, `storage`, `dev`) for its providers |

The direction of the dependencies is checked by tests:
- docstruct imports no project package, and touches no network, environment,
  files or processes (`test_purity.py`, `test_infrastructure.py`);
- the SDK imports neither the core nor the Toolbox (`libs/sdk/tests/test_purity.py`);
- the core imports nothing from the service (`libs/core/tests/test_boundary.py`)
  and uses only the SDK's public API (ADR-0018, `tests/test_sdk_public_api.py`);
- the Toolbox imports neither the SDK nor the core (its `test_architecture.py`).

## 4. Time of the local tests

| Suite | Test functions, baseline → now | Time now |
|---|---:|---:|
| main (`tests/`, `-n 4`) | 1,512 → 1,497 | 111 s |
| docstruct (`libs/docstruct/tests`) | 808 → 978 | 6–9 s |
| SDK (`libs/sdk/tests`) | 203 → 388 | 11–17 s |
| core (`libs/core/tests`) | none → 755 | 30 s |

- **The libraries' suites run in seconds on their own,** so a change to
  docstruct or the SDK gets its feedback without the main suite.
- **The main suite is still the bulk of the time**, but it now holds the
  service and API tests; the core's own suite runs in about 30 s in its own
  environment. The core's tests moved from `tests/` to `libs/core/tests` in
  #613, with the boundary and smoke tests.
- The baseline's suites were not timed: their environment cannot be rebuilt
  as it was, so only the counts are compared.
- The main/core counts and times are the post-#613/#612 measurement (one local
  run); the rest of this page is at `ec3ddf0b`.

## 5. Reuse of operations

The SDK has two operations, the formula chain and the page judge (ADR-0017).
Their callers outside the SDK:

| Caller | Uses |
|---|---|
| the core's formula enrichment | `crop_formula_region`, `recognize_formula`, `convert_formula`, `verbalize_formula` (#507, #509) |
| the core's page judge | `render_judge_page`, `judge_page` (#607) |
| the SDK's command line | `python -m acessilia_sdk formula` runs the formula chain from the SDK's own wheel |
| `scripts/bench` | SDK clients (datasets, the Toolbox catalogue), but no operation |

**No script or benchmark of this repository calls an operation yet.** The
page judge has no command of its own. The benchmark repository was not
measured here.

## 6. Regressions

**Structural:** every move was checked on its own, with evidence in its pull
request:
- identical AST, a differential test of 20,000 cases and a mutant for each
  move out of the orchestrator (#454 to #493);
- differential tests against develop's code for the formula chain (#507,
  #509);
- committed parity or characterization tests for the latest moves (#596,
  #600, #607), with any difference declared.

**Functional:**
- **Case 036 matched before and after the formula chain moved** to the SDK
  (ADR-0017 acceptance, #511): 0 differences in its 16 formulas.
- **After the core moved to `libs/core` (#572),** staging processed case 036
  on 2026-11-18 with every output delivered and PDF/UA compliant. One
  heading regressed, but the cause is the Toolbox's extraction
  (acessilia-toolbox#162): the core's manifests are identical before and
  after the move.
- **Case 006 (slides) now has a repeatable staging comparison.** The 42-slide
  deck is already in acessilia-dataset (`input/006.pdf`) with its
  `input/presentation-reference/` ground truth, and the service keeps a
  byte-identical copy in `tests/fixtures/presentations/`.
  `tests/test_slide_case_e2e.py` uploads it to the deployed core and scores
  the delivered TXT and PDF/UA with `scripts/bench/slide_case.py`: 42 slide
  headings and titles, floors for text, tables and formulas, the absence of
  fallback patterns, and picture/chemical-structure floors. It runs with
  `CORE_BASE_URL` and the dataset clone.
  **Observed on 2026-11-25 at staging `d2714cd`:** PDF/UA 187/225 objects
  (text 65/72, table rows 66/95, images 30/31, chemical structures 5/5,
  formulas 10/10, 0 pattern violations); TXT 183/225 with 10 known
  `english-table-row` violations. veraPDF reports a `.notdef` glyph failure
  (#868); the missing image-only table rows are #870 and the TXT linearization
  is #869. The full deck is a manual/slow run, not a scheduled gate. The
  pre-migration scorecard was not archived, so the floors use the current
  staging score plus the dataset ground truth.

## Consequences observed

- **The boundaries are now tested rules, not conventions.** Each component
  installs and runs alone in CI. The direction of dependencies, the core's
  independence from the service and its use of the SDK's public API are
  guarded by tests, and the core, the SDK and the Toolbox check their models
  against one shared catalog of cases (`docstruct.manifest_cases`).
- **Scripts got a light path:** 10 packages and 2 MB give the Toolbox
  clients, two operations and the structural algorithms, without agents or
  the service.
- **The refactoring did not reduce complexity significantly, by design.** It
  moved code to where it belongs and kept behaviour. The count of complex
  functions dropped slightly (48 → 46 across service and core; 41 in the core
  alone), but the complex functions are largely the same ones, now in smaller
  modules with one responsibility each, which makes them the next targets.
- **The core is not light,** because its agents need `agno`, `openai` and
  `babel`. A caller that only wants the core's deterministic parts still
  installs the agent stack.

## Follow-ups this suggests

1. ~~**Simplify the complex functions:** the five above first, starting with
   `_derive_v23_processing_needs` (complexity 71). This is the internal
   modularization #381 asked for, now on modules that have clear boundaries.~~
   Done in #612 (`_derive_v23_processing_needs` → `manifest/detectors/`
   plus `apply_page_routes`, `_execute_step`, `_absorb_near_pictures`,
   `_extract_with` and the remaining complex and long functions; functions over
   15 in the core: 41 → 0; functions over 100 lines in the core: 21 → 0; every
   module in `libs/core/src` below the 900-line limit).
2. ~~**Move the core's tests to `libs/core/tests`** where they test the core
   alone, so the core's suite runs without the service.~~ Done in #613.
3. **Give the operations users:** a `judge` command in the SDK's command line,
   and the math benchmark (`scripts/bench`) on the formula chain instead of
   the core.
4. ~~**Run the case 006 comparison on staging** after the move
   (`tests/test_slide_case_e2e.py`).~~ Done on 2026-11-25 at `d2714cd`; follow
   the product gaps in #868, #869 and #870.
5. **Decide whether the agent stack should be an extra of the core**, if a
   caller needs the core without agents. Nothing asks for it today.
