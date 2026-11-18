# Inventory: structural contracts and operational boundaries (#470, phase 1)

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](operational-boundaries-inventory.pt-br.md)

[#470](https://github.com/A11yDevs/acessilia/issues/470) proposes to make
docstruct the portable structural core of the ecosystem, and to let the SDK
offer deterministic operations and workflows, not only transport. Its phase 1
asks for a diagnosis before any decision. This page records what the code and
the ADRs already settle, and what is still open. It was measured on develop at
8d7465e4 (the Toolbox at the refs in its section below), with an AST scan that includes imports inside functions.
[ADR-0017](../adr/0017-operational-sdk-and-agentic-core.md) takes its
decisions from here.

## What is already decided and enforced

Much of #470 restates [ADR-0002](../adr/0002-component-responsibilities.md),
which is accepted:

| #470 principle | Where it already holds |
|---|---|
| P1, portability (standard library only, guarded optional accelerators) | ADR-0002 table and compliance; `libs/docstruct/tests/test_purity.py` checks that `pyproject.toml` declares no runtime dependency, that every other import is a listed accelerator behind `except ImportError`, and that every module imports in an interpreter that refuses anything outside the standard library. The only accelerator is `rapidfuzz`, in `evaluation/metrics/text_ed.py`. #470's alternative A is therefore already in place. |
| P2, shared structural contracts | [ADR-0007](../adr/0007-manifest-model-and-mathml-conversion.md) and #203: `docstruct.manifest` is the normative document model. The core's and the Toolbox's Pydantic models stay only as the 1.1.0 wire models, checked against `docstruct.manifest.field_specs` in contract tests. |
| P3, independence from infrastructure | **Partly.** The ADR-0002 table states the rule. `test_purity.py` checks dependencies and imports, but it allows the whole standard library: a module that reads `os.environ` or a file when it is imported still passes, as the review of #471 reproduced. **Covered by phase 2 of #470, for ADR-0017's four (network, environment, files, processes):** `test_infrastructure.py` refuses, statically, the standard library modules, built-ins and `sys` attributes it lists, and fails an import that opens a file, reads the environment, creates a socket, starts a process, prints or configures logging. The clock, randomness and threads are not in the rule. |
| Direction of dependencies, no cycles | ADR-0002 already allows **SDK → docstruct**, and offers "in-process access to docstruct's pure algorithms" through the SDK. The SDK's `test_purity.py` keeps its dependencies "within `httpx` and docstruct". |
| P7, one implementation per structural algorithm | ADR-0002 and #203; `tests/test_docstruct_bridges.py` fails on a new copy of a bridged algorithm. |
| Toolbox does not import the core or the SDK | The Toolbox's `tests/unit/test_architecture.py`. Outside it, `acessilia_sdk` and `backend` appear only in one cross-project test (`tests/cross_project/test_core_storage_outage.py`). |

## What differs between the ADRs and the code

- **The SDK does not use docstruct, and its isolated CI job forbids it.**
  ADR-0002 allows the dependency, but `libs/sdk/pyproject.toml` declares only
  `httpx`. The `SDK alone` job refuses `docstruct` together with `backend`,
  the Toolbox, Agno and FastAPI. If the SDK composes docstruct algorithms
  (#470, P5), the dependency and that job change. **Closed by phase 3 of
  #470:** the formula operation composes `best_effort_clip` and
  `ranked_latex_candidates`, the SDK declares docstruct, and `SDK alone`
  installs it.
- **The Toolbox and the core agree on docstruct by convention only.** Each
  branch of the Toolbox pins the docstruct release wheel by SHA-256, and the
  pins match the core's branches:

  | Branch | Core (`libs/docstruct`) | Toolbox (`pyproject.toml`) |
  |---|---|---|
  | `main` | 0.4.0 (cac215df) | `docstruct-v0.4.0` (e77869be) |
  | `develop` | 0.5.0 (b6ca0ecf) | `docstruct-v0.5.0` (77c7df7c), since acessilia-toolbox db866c60 (2026-11-02) |

  So there is no gap today. But nothing checked that a docstruct release and
  the Toolbox's pin move together, or that the two still agree on the shared
  models: this is #470's P8 risk. **The pin half is checked since phase 2 of
  #470:** `scripts/check_docstruct_pin.py` reads the pin on the paired Toolbox
  branch, checks it against the published release and its wheel's SHA-256,
  and reports a Toolbox behind the newest release for the core's version. It
  warns in pull requests and fails the scheduled monitoring. **The models
  half has shared cases since docstruct 0.5.5:** `docstruct.manifest_cases`
  holds a valid example, changes that break one rule each, and changes that
  must stay valid. The core's contract test and the SDK's manifest reader run
  them against their own models. **The Toolbox does not run them yet:** its
  contract test will adopt them when it pins docstruct 0.5.5, after that
  release is published, and until then the models half stays open.
- **docstruct had no isolated install job.** `test_purity.py` refuses
  non-standard imports in a subprocess, but no CI job installed docstruct alone
  in a clean environment, as `SDK alone` does for the SDK. **Closed by phase 2
  of #470:** the `docstruct alone` job installs it from its wheel, with pytest,
  and runs its suite with no core, SDK, Toolbox or optional accelerator
  (`rapidfuzz`) importable.
- **docstruct's independence from infrastructure was not tested.** See P3
  above. An isolated install job would not catch it either: it needs a test
  that a module does not read the environment or files, open sockets or start
  subprocesses. **Closed by phase 2 of #470**, for what `libs/docstruct/tests/test_infrastructure.py` lists (see P3).

## Structural algorithms: core and docstruct

19 functions share a name between the core and docstruct. 15 are adapters
that call docstruct, so nothing is duplicated there:
- `pipeline/canonical_builder.py`, `pipeline/validators.py` and
  `pipeline/table_ast.py`;
- `refine_reading_order` and `is_unstructured_page_placeholder` in the
  manifest builder;
- the orchestrator's `_pair_block`, `_letterhead_groups`,
  `_recover_empty_lettered_list_items` and `_implicit_product_variables`;
- `wrap_latex`.

The rest, with the duplicates already on record:

| Core | docstruct | Finding |
|---|---|---|
| `_table_ast_from_rows` (orchestrator) | `docstruct.tables.ast.table_ast_from_rows` | Near-duplicate with different behaviour: `{"body": []}` against `None` for no rows. Recorded in the orchestrator inventory; merging it is a behaviour decision. **Resolved:** the core uses docstruct's (#470, phase 4); the only difference, blank rows, is recorded in `tests/test_table_ast_from_rows_parity.py`. |
| `_block_kind` (orchestrator) | `docstruct.fusion.convert.classify_kind` | Near-duplicate with different behaviour. Recorded in the orchestrator inventory. |
| `_area` (`libs/core/src/acessilia_core/manifest/slides.py`) | `docstruct.fusion.similarity.area` | The same computation, for a box that is present. **Resolved:** `slides.py` uses docstruct's (#470, phase 4). |
| `_overlaps`, `_union_area` (`slides.py`) | none | Pure box geometry. **Moved** to `docstruct.geometry.boxes` as `boxes_overlap` and `union_area` (docstruct 0.5.6, #470, phase 4). (docstruct's `_overlaps` compares text spans, not boxes.) |
| `decide` (`planning/toolbox_gate.py`) | `docstruct.fusion.adjudication.decide` | Same name only; unrelated. |
| callout clustering (Toolbox normalization builder) | `docstruct.regions.grouping` | Known deviation of ADR-0002 ([acessilia-toolbox#72](https://github.com/A11yDevs/acessilia-toolbox/issues/72)). |

## Deterministic operations in the core

Under #470's P4, these are mechanisms the core runs with explicit parameters,
next to the policy that decides when and on what. They are candidates for SDK
operations, with the decision part staying in the core:

| Operation | Today | Mechanism (SDK candidate) | Decision (stays in the core) |
|---|---|---|---|
| Formula chain | `_formula_recognition_crop`, `toolbox_math_tools`, the formula enrichment (crop, recognition, MathML and speech now call `acessilia_sdk.operations.formula`, phase 3 of #470) | render a region, then `math.recognize`, `math.convert` and `math.verbalize` in sequence | which formulas, the text-layer agreement gate, the vision fallback, the breaker |
| Page judge | `_render_page_png`, `_judge_page`, `_judge_one_page` (in `libs/core/src/acessilia_core/pipeline/judge.py` since step 6 of #402). **The mechanism is an SDK operation** since #470 phase 4, `acessilia_sdk.operations.page_judge` (#605), and the core's judge calls its steps | render a page, then `document.adjudicate.page`, read `pB` | which pages, the threshold, whether to swap |
| Media inspection | `libs/core/src/acessilia_core/toolbox/media_inspect.py` | `media.inspect` | what a slide deck or a page limit means for the job |
| PDF/UA audit | `libs/core/src/acessilia_core/toolbox/pdf_ua_audit.py` | `pdf.validate.pdf_ua` | what a failed audit does to the job |
| Text spans | `libs/core/src/acessilia_core/toolbox/text_spans.py` | already `ToolboxPdfClient.text_spans_by_page` (#455) | which pages, the per-document cache |
| Pandoc export | `libs/core/src/acessilia_core/export/pandoc_exporter.py` | `document.export.pdf_ua`, `document.export.docx` | which profile, which formats |

**Phase 4 outcome (#470).** Two of these are SDK operations, and the core
calls their steps: the formula chain (#504, #507, #509) and the page judge
(#605, #607). Each was a fixed sequence of mechanical steps that the core
used to run itself. The other four are not operations, and stay as they are:

| Row | The mechanism is already | What stays in the core is |
|---|---|---|
| Media inspection | one call, `ToolboxMediaInspectClient.inspect`, which also refuses an answer without a document object | whether the step runs (`media_inspect_enabled`), the remote cache choice, the localized log |
| PDF/UA audit | one call, `ToolboxPdfValidateClient.validate` | `summarize_audit`: the localized e-mail lines of the verdict and the failed rules |
| Text spans | one call, `ToolboxPdfClient.text_spans_by_page` (#455) | which pages, the per-document cache |
| Pandoc export | one call per format, the export clients' `export`; `degrade_math_to_text` is docstruct's | whether a format is enabled, and the retry of a rejected PDF/UA with its math as literal text, a degradation policy (P6) |

An SDK operation for any of them would wrap one client call. It would take
nothing out of the core, and moving what the core keeps would put a decision
or a localized presentation in the SDK, which ADR-0017 rules out.

## Open, for ADR-0017 and its follow-ups

- ~~Which of these operations become SDK operations, and in which order.~~
  Settled by phase 4 of #470: the formula chain and the page judge (see the
  outcome above).
- What docstruct's stable public API is.
- How a docstruct change reaches the Toolbox, and how the two are checked
  against each other.
- Whether the SDK should execute an operational plan contract. #470 lists the
  risk that the SDK becomes a second orchestrator.
