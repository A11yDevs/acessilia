# docstruct Algorithms — Fusion, Audit, Classification and Re-inference

This document explains how the deterministic algorithms behind the `docstruct`
library work and how the Acessilia agents invoke them. It is the companion to
[`libs/docstruct/README.md`](../../libs/docstruct/README.md) (public API) and
[`pmv_agno_pddl.md`](pmv_agno_pddl.md) (PDDL orchestration).

> Also available in **Brazilian Portuguese**: [Portuguese version](docstruct_algorithms.pt-br.md)

## Scope

The `docstruct` library (`libs/docstruct/`) is a **pure** document-structure
processing core: no function touches the network, the filesystem, subprocesses,
settings, the logger, or dynamic i18n. It is the single source of truth for the
algorithms described here. The backend (`backend/`) provides the I/O, settings
and i18n bridges, and the Agno agents expose the algorithms as tools.

```
backend (Agno agents, PDDL, I/O, settings, i18n)
   │  depends on
   ▼
docstruct (pure algorithms)
```

---

## 1. Multi-provider fusion (Tree Differ)

### 1.1 Goal

Two structure-extraction providers (by default **Docling** and **MinerU**)
produce independent block lists for the same document. Each provider is good at
different things: Docling is strong on reading order and headings; MinerU is
strong on text quality and formula extraction. Fusion combines them into a
single, higher-quality block sequence.

### 1.2 Pipeline (`backend/pipeline/fusion.py`)

`extract_fused()` orchestrates the two providers and calls the pure
`docstruct.fusion.merge_blocks()`:

1. Extract with the **primary** provider (default `docling`).
2. Extract with the **secondary** provider (default `mineru`), in parallel.
3. Convert each provider's payload into canonical blocks (with bbox).
4. Group blocks by page.
5. For each page, call `merge_blocks(D, M, policy)` where `D` = Docling blocks
   and `M` = MinerU blocks.
6. Serialize the merged blocks into markdown.

**Fallback:** if the secondary provider fails, `extract_fused` silently uses
only the primary. The `dual-provider-fusion` PDDL handler treats this as a
**failure** (see [§5](#5-how-the-agents-invoke-the-algorithms)) because the
planned dual semantics was not actually executed.

### 1.3 The Tree Differ (`docstruct.fusion.differ.merge_blocks`)

`merge_blocks(D, M, policy)` is the port of the Tree Differ v2 from PR #98
(Dr.DocBench). It runs in stages:

#### Stage A — Pre-processing (noise reduction)

- **Formula demotion** (`formula_text`): formulas without a math operator are
  demoted to plain text.
- **Region suppression** (`suppress_regions`): Docling text that falls inside a
  MinerU table/figure is suppressed (unless the page has almost no text).
- **Decor-tail** (`decor_tail`): headers/footers and page numbers are split off
  and moved to the end of the page.
- **Junk filter** (`junk_filter`): blocks that look like junk (e.g. stray
  tokens) are dropped.
- **Line fusing** (`fuse_lines`): consecutive line runs are merged.
- **Paragraph re-fusion** (`merge_paragraphs`): split paragraphs are grouped
  back together.

#### Stage B — Hungarian alignment

The core matching step. Build a cost matrix where each cell is:

```
cost(i, j) = (1 - λ) * (1 - sim(text_i, text_j)) + λ * (1 - IoU(box_i, box_j))
```

- `sim(text)` is a text similarity (token overlap).
- `IoU(box)` is the intersection-over-union of the two bounding boxes.
- `λ = policy.align_lambda` (default `0.5`) weights text vs geometry.

A pure **Kuhn–Munkres** (Hungarian) assignment (`_hungarian.py`, O(n³), no
scipy) finds the minimum-cost one-to-one matching. Pairs whose cost exceeds
`policy.align_tau` (default `0.6`) are left **unmatched**.

#### Stage C — Reading-order skeleton

The reading order follows provider B (**MinerU**). For each MinerU block:

- if it matched a Docling block, the text is chosen by `_pick_text` (see below);
- if it is unilateral (no match), its own text is kept.

#### Stage D — Inserting unilateral Docling blocks

Docling blocks that did not match are inserted next to their **geometric
nearest neighbor** in the MinerU skeleton (above or below depending on the
vertical center). Short text blocks (`len < min_len`) are dropped, and blocks
that "swallow" several MinerU blocks are dropped too (`pick_guard`).

#### Stage E — Text selection (`_pick_text`)

For a matched pair, the text is chosen by `policy.text_pick`:

- `docling` → always Docling;
- `mineru` → always MinerU;
- `auto` (default) → MinerU wins in the body, unless it truncated the text or
  has worse OCR quality; Docling wins when it is significantly longer or when
  MinerU swallowed columns.

### 1.4 `FusionPolicy`

`FusionPolicy` is a frozen dataclass with **conservative, neutral defaults**.
The benchmark-tuned presets (`drbench_v12`, `drbench_v13`) are named
classmethods, never defaults, because they were overfitted to the dev split
(gap dev→test ≈ −6).

---

## 2. Canonical-document audit

### 2.1 Goal

Validate a canonical document and collect structured findings so downstream
renderers and consumers can trust its structure.

### 2.2 `validate_canonical_document`

Checks the structural invariants of a canonical document:

- required fields (`schema_version`, `id`, `title`, `language`, `sections`);
- duplicate block ids;
- heading hierarchy (exactly one H1, no skipped levels, first heading is H1);
- prompt leaks and stray markdown in paragraph text;
- code indentation consistency;
- table structure (rows, columns, cells, `table_ast`);
- broken internal links.

### 2.3 `audit_canonical_document`

Runs the base validation plus an accessibility audit, and groups findings by
severity:

| Severity | Meaning |
|---|---|
| `BLOCKER` | Structural failures (base validation errors, missing sections). |
| `WARNING` | Accessibility findings (images without alt-text, tables without explicit headers). |

Findings are returned as `(msgid, kwargs)` tuples — the canonical msgid is the
single source of truth; the backend resolves it through its i18n catalog.

---

## 3. Region classification

### 3.1 Goal

Classify a page region into a processing category so the pipeline knows how to
handle it (vision, OCR, table linearization, formula verbalization, or ignore).

### 3.2 `classify_region`

`docstruct.regions.classify.classify_region(region)` maps a `Region` to a
category:

| Region type | Possible classifications |
|---|---|
| `image` | `embedded_image` (high confidence + bytes), `unknown` (large), `ignore` |
| `table` | `table` (has text or large), `ignore` |
| `formula` | `formula` (large), `ignore` |
| `text` | `text_clean`, `text_scanned`, `code_block`, `list_block`, `unknown`, `ignore` |
| `unknown` | `unknown` (large), `ignore` |

Docling regions come pre-classified and are mapped through
`DOCLING_CLASSIFICATION`.

### 3.3 `region_needs_vision`

Returns `True` for categories that require a vision/LLM pass:
`text_scanned`, `embedded_image`, `unknown`, `table`, `formula`.

### 3.4 `needs_reinfer`

The `FusionAgent.needs_reinfer` tool classifies the region and reports whether
it needs re-inference (vision or orientation correction). This is the
deterministic gate that decides whether an LLM pass is required.

---

## 4. The `FusionAgent` (Agno tool envelope)

`backend/core/agents/fusion_agent.py` exposes the algorithms as Agno tools,
following the `InformationalStructuralAgent` pattern: each capability has a
pure `process_*` method (unit-testable without Agno) plus a thin JSON tool
envelope.

| Tool | Deterministic core | Purpose |
|---|---|---|
| `fuse_providers` | `process_fuse_providers` → `extract_fused` | Merge two toolbox providers. |
| `audit_document` | `process_audit_document` → `audit_canonical_document` | Audit a canonical document. |
| `classify_block` | `process_classify_block` → `classify_region` | Classify a region. |
| `needs_reinfer` | `process_needs_reinfer` → `classify_region` + `region_needs_vision` | Decide if a region needs re-inference. |

**Design note:** the tool envelopes intentionally do **not** serialize
`image_bytes` — they reconstruct a `Region` with `image_bytes=None`. Binary
payloads should not cross tool-call boundaries. For future multimodal
decisions, pass a persistent reference (`artifact_id` / `image_ref` /
`crop_path` / object-storage URI) instead of raw bytes.

---

## 5. How the agents invoke the algorithms

### 5.1 PDDL-driven fusion (`dual-provider-fusion`)

The PDDL planner can select the `dual-provider-fusion` method for an
obligation. The flow is:

```
PDDL plan
   │  selects dual-provider-fusion
   ▼
ExecutorAgent (Agno Workflow)
   │  calls the registered handler
   ▼
_handle_dual_provider_fusion_method (backend/agents/pddl_orchestrator.py)
   │  calls extract_fused()
   ▼
backend.pipeline.fusion.extract_fused
   │  extracts with docling + mineru (parallel)
   ▼
docstruct.fusion.merge_blocks (Tree Differ)
   │  returns fused markdown blocks
   ▼
handler persists payload to data_dir/artifacts/fusion/<obligation_id>.json
   │  returns MethodResult(artifacts=[fusion_artifact])
   ▼
ExecutorAgent incorporates the artifact into the manifest
   and associates its id with the executed attempt (provenance)
```

The handler is **strict**: if only one provider participated (the single
provider fallback inside `extract_fused`), the planned `dual-provider-fusion`
action is treated as a **failure**, recording `(tried ...)` and allowing
replanning to a single-provider method. This keeps the planned semantics
aligned with what actually executed.

### 5.2 Direct tool invocation

The `FusionAgent` tools can also be invoked directly (e.g. by an LLM agent or
by the AgentOS runtime) to fuse, audit, classify, or decide re-inference
without going through the PDDL planner.

---

## 6. Related documentation

- [libs/docstruct/README.md](../../libs/docstruct/README.md) — public API.
- [pmv_agno_pddl.md](pmv_agno_pddl.md) — PDDL orchestration and the
  `dual-provider-fusion` method.
- [architecture.md](architecture.md) — system architecture.
- [patterns.md](patterns.md) — design patterns (pattern 12: deterministic
  fusion agent).
- [drbench.md](drbench.md) — the Dr.DocBench benchmark that motivated the
  Tree Differ.