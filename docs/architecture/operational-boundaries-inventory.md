# Inventory: structural contracts and operational boundaries (#470, phase 1)

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](operational-boundaries-inventory.pt-br.md)

[#470](https://github.com/A11yDevs/acessilia/issues/470) proposes to make
docstruct the portable structural core of the ecosystem, and to let the SDK
offer deterministic operations and workflows, not only transport. Its phase 1
asks for a diagnosis before any decision. This page records what the code and
the ADRs already settle, and what is still open. It was measured on develop at
8d7465e4, with an AST scan that includes imports inside functions.
[ADR-0017](../adr/0017-operational-sdk-and-agentic-core.md) takes its
decisions from here.

## What is already decided and enforced

Much of #470 restates [ADR-0002](../adr/0002-component-responsibilities.md),
which is accepted:

| #470 principle | Where it already holds |
|---|---|
| P1, portability (standard library only, guarded optional accelerators) | ADR-0002 table and compliance; `libs/docstruct/tests/test_purity.py` checks that `pyproject.toml` declares no runtime dependency, that every other import is a listed accelerator behind `except ImportError`, and that every module imports in an interpreter that refuses anything outside the standard library. The only accelerator is `rapidfuzz`, in `evaluation/metrics/text_ed.py`. #470's alternative A is therefore already in place. |
| P2, shared structural contracts | [ADR-0007](../adr/0007-manifest-model-and-mathml-conversion.md) and #203: `docstruct.manifest` is the normative document model. The core's and the Toolbox's Pydantic models stay only as the 1.1.0 wire models, checked against `docstruct.manifest.field_specs` in contract tests. |
| P3, independence from infrastructure | The ADR-0002 table for docstruct, and `test_purity.py`. |
| Direction of dependencies, no cycles | ADR-0002 already allows **SDK → docstruct**, and offers "in-process access to docstruct's pure algorithms" through the SDK. The SDK's `test_purity.py` keeps its dependencies "within `httpx` and docstruct". |
| P7, one implementation per structural algorithm | ADR-0002 and #203; `tests/test_docstruct_bridges.py` fails on a new copy of a bridged algorithm. |
| Toolbox does not import the core or the SDK | The Toolbox's `tests/unit/test_architecture.py`. Outside it, `acessilia_sdk` and `backend` appear only in one cross-project test (`tests/cross_project/test_core_storage_outage.py`). |

## What differs between the ADRs and the code

- **The SDK does not use docstruct, and its isolated CI job forbids it.**
  ADR-0002 allows the dependency, but `libs/sdk/pyproject.toml` declares only
  `httpx`. The `SDK alone` job refuses `docstruct` together with `backend`,
  the Toolbox, Agno and FastAPI. If the SDK composes docstruct algorithms
  (#470, P5), the dependency and that job change.
- **The Toolbox pins an older docstruct.** Its `pyproject.toml` installs the
  `docstruct-v0.4.0` wheel, while `libs/docstruct` is at 0.5.0. Nothing checks
  that the two still agree on the shared models: this is #470's P8 risk.
- **docstruct has no isolated install job.** `test_purity.py` refuses
  non-standard imports in a subprocess, but no CI job installs docstruct alone
  in a clean environment, as `SDK alone` does for the SDK.

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
| `_table_ast_from_rows` (orchestrator) | `docstruct.tables.ast.table_ast_from_rows` | Near-duplicate with different behaviour: `{"body": []}` against `None` for no rows. Recorded in the orchestrator inventory; merging it is a behaviour decision. |
| `_block_kind` (orchestrator) | `docstruct.fusion.convert.classify_kind` | Near-duplicate with different behaviour. Recorded in the orchestrator inventory. |
| `_area` (`backend/core/manifest/slides.py`) | `docstruct.fusion.similarity.area` | The same computation, for a box that is present. |
| `_overlaps`, `_union_area` (`slides.py`) | none | Pure box geometry; docstruct candidates. (docstruct's `_overlaps` compares text spans, not boxes.) |
| `decide` (`planning/toolbox_gate.py`) | `docstruct.fusion.adjudication.decide` | Same name only; unrelated. |
| callout clustering (Toolbox normalization builder) | `docstruct.regions.grouping` | Known deviation of ADR-0002 ([acessilia-toolbox#72](https://github.com/A11yDevs/acessilia-toolbox/issues/72)). |

## Deterministic operations in the core

Under #470's P4, these are mechanisms the core runs with explicit parameters,
next to the policy that decides when and on what. They are candidates for SDK
operations, with the decision part staying in the core:

| Operation | Today | Mechanism (SDK candidate) | Decision (stays in the core) |
|---|---|---|---|
| Formula chain | `_formula_recognition_crop`, `toolbox_math_tools`, the formula enrichment | render a region, then `math.recognize`, `math.convert` and `math.verbalize` in sequence | which formulas, the text-layer agreement gate, the vision fallback, the breaker |
| Page judge | `_render_page_png`, `_judge_page`, `_judge_one_page` | render a page, then `document.adjudicate.page`, read `pB` | which pages, the threshold, whether to swap |
| Media inspection | `backend/tools/media_inspect.py` | `media.inspect` | what a slide deck or a page limit means for the job |
| PDF/UA audit | `backend/tools/pdf_ua_audit.py` | `pdf.validate.pdf_ua` | what a failed audit does to the job |
| Text spans | `backend/tools/text_spans.py` | already `ToolboxPdfClient.text_spans_by_page` (#455) | which pages, the per-document cache |
| Pandoc export | `backend/export/pandoc_exporter.py` | `document.export.pdf_ua`, `document.export.docx` | which profile, which formats |

## Open, for ADR-0017 and its follow-ups

- Which of these operations become SDK operations, and in which order. The
  formula chain is the proof of concept #402 and #470 both name.
- What docstruct's stable public API is.
- How a docstruct change reaches the Toolbox, and how the two are checked
  against each other.
- Whether the SDK should execute an operational plan contract. #470 lists the
  risk that the SDK becomes a second orchestrator.
