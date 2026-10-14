# Toolbox × core capability matrix

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](toolbox_capability_matrix.pt-br.md)

> This is the single source of truth for the contract between the core
> (`A11yDevs/acessilia`) and the capability gateway (`A11yDevs/acessilia-toolbox`).
> It is verified mechanically by `scripts/check_capability_contract.py` and by
> `tests/test_toolbox_contract_drift.py`.

## Why this exists

The core reaches the Toolbox by hard-coding capability and provider ids that are
declared in another repository. Nothing verified that both sides still agreed, so
renaming a capability on the Toolbox side produced a client that could only fail
at runtime — the failure surfaced as a `ToolboxCapabilityError` on a customer
document, not as a broken build.

The matrix below is the *contract*. The checker compares it against a live
Toolbox (`--url`) or against the captured fixture
(`tests/fixtures/toolbox-contract.json`, regenerated with
`scripts/capture_toolbox_contract.py`).

## Required capability entry points

A capability is only *actionable* in the core when all four links exist. A
capability missing any link is a dead capability from the product's point of view.

| Link | Artifact | Location |
|---|---|---|
| Client | `Toolbox*Client` with the capability id | `backend/tools/toolbox_*_client.py` |
| Provider default | `TOOLBOX_*_PROVIDER` (or `TOOLBOX_PROVIDER`) | `backend/config/settings.py` |
| Manifest | `capabilities/*.yaml` | `acessilia-toolbox` |
| Provider registration | `providers-config.yaml` entry with an adapter | `acessilia-toolbox` |

For planning-driven work there are two further links: the obligation/method entry
in `DEFAULT_METHOD_COSTS` (`backend/core/manifest/builder.py`) and a registered
handler in `PddlAccessibilityOrchestrator._build_executor`
(`backend/agents/pddl_orchestrator.py`).

## Matrix

Legend for **Call path**: how the core reaches the capability.

| Capability | Core client | Core provider default | Toolbox provider | Call path |
|---|---|---|---|---|
| `document.structure.extract` | `toolbox_client.py` (inline URL) | `TOOLBOX_PROVIDER=docling` | `docling`, `mineru`, `nougat`, `teleocr` | `ToolboxManifestExtractor` → PDDL extraction |
| `document.layout.analyze` | `toolbox_layout_client.py` | `TOOLBOX_LAYOUT_PROVIDER=docling-layout` | `docling-layout`, `mineru-layout` | `ToolboxLayoutStructurer` via `STRUCTURER=toolbox-layout` |
| `document.ocr` | `toolbox_ocr_client.py` | `TOOLBOX_OCR_PROVIDER=docling-ocr` | `docling-ocr`, `mineru-ocr` | `toolbox_ocr_tools.py` (Agno wrapper) |
| `math.recognize` | `toolbox_math_client.py` | `TOOLBOX_MATH_RECOGNIZE_PROVIDER=docling-math` | `docling-math`, `rapid-latex-ocr` | `toolbox_math_tools.py` |
| `math.convert` | `toolbox_math_client.py` | `TOOLBOX_MATH_PROVIDER=pure-math` | `pure-math` | `toolbox_math_tools.py` |
| `math.verbalize` | `toolbox_math_client.py` | `TOOLBOX_MATH_PROVIDER=pure-math` | `pure-math` | `toolbox_math_tools.py` |
| `pdf.split` | `toolbox_pdf_client.py` | `TOOLBOX_PDF_PROVIDER=pymupdf-pdf` | `pymupdf-pdf` | `toolbox_pdf_tools.py` (validates, then splits locally) |
| `pdf.render` | `toolbox_pdf_client.py` | `TOOLBOX_PDF_PROVIDER=pymupdf-pdf` | `pymupdf-pdf` | `toolbox_pdf_tools.py` (falls back to local PyMuPDF) |
| `media.inspect` | `toolbox_media_inspect_client.py` | `TOOLBOX_MEDIA_INSPECT_PROVIDER=pure-media-inspect` | `pure-media-inspect` | `backend/tools/media_inspect.py`, gated by `TOOLBOX_MEDIA_INSPECT_ENABLED` |
| `artifact.store` / `artifact.retrieve` | `toolbox_client.py` REST `/v1/artifacts` | — | `minio`, `filesystem` | upload before extraction |
| `dataset.*` (8 capabilities) | `toolbox_client.py` REST `/v1/datasets` | — | `dataset-github`, `dataset-huggingface` | `toolbox_dataset_tools.py` (Dr.DocBench scripts) |
| `document.ocr.page` | `toolbox_page_ocr_client.py` | `TOOLBOX_PAGE_OCR_PROVIDER=qwen3-vl-page` | **absent** | **no caller** |
| `document.adjudicate.page` | `toolbox_adjudicate_client.py` | `TOOLBOX_ADJUDICATE_PROVIDER=qwen3-vl-judge` | **absent** | **no caller** |
| `document.adjudicate.region` | `toolbox_adjudicate_client.py` | `TOOLBOX_ADJUDICATE_PROVIDER=qwen3-vl-judge` | **absent** | **no caller** |
| `image.page.orient` | `toolbox_orientation_client.py` | `TOOLBOX_ORIENTATION_PROVIDER=rapidocr-orient` | `rapidocr-orient` | contract-valid, **no production caller yet** |
| `accessibility.mark` | **absent** | — | `pure-accessibility` | — |
| `chem.convert` | **absent** | — | `pure-chem` | — |
| `chem.recognize` | **absent** | — | `docling-chem` | — |
| `code.normalize` | **absent** | — | `pure-code` | — |
| `text.postprocess` | **absent** | — | `pure-text` | — |
| `music.omr` | **absent** | — | `homr`, `audiveris` | — |
| `cache.get` / `cache.put` | — (internal) | — | `valkey` | Toolbox-internal cache; not a public capability |

## Confirmed drift (as of the review)

Measured against the running staging Toolbox with
`python scripts/check_capability_contract.py --snapshot tests/fixtures/toolbox-contract.json`:

1. Three capabilities are consumed by the core but do not exist in the Toolbox
   catalogue: `document.ocr.page`, `document.adjudicate.page`,
   `document.adjudicate.region`.
2. Two provider defaults in `settings.py` point at providers the Toolbox does
   not register: `qwen3-vl-page`, `qwen3-vl-judge`.
3. Six capabilities have no core client at all (see the matrix).

The orientation drift was resolved: the client posted to
`document.orientation.detect` with provider `rapidocr-orientation`, neither of
which the Toolbox knows, while the Toolbox exposes `image.page.orient`
implemented by `rapidocr-orient`. The client and the default now match the
catalogue. The client still has no production caller, so its verdict is
"integrate or retire" rather than "done".

The known drift is pinned in `tests/test_toolbox_contract_drift.py`; any *new*
drift fails the suite, and fixing a finding requires removing it from the pinned
list.

## PDDL actionability (measured against the live Toolbox)

### State before the fix

Running the PDDL pipeline locally against the homologation Toolbox with
`PDDL_EXECUTE_DRY_RUN=false` failed on the first obligation:

```
obligations: 7  kinds: {preserve-code-semantics: 6, describe-image: 1}
plan steps: 9
  1 execute-obligation describe-image vision-description cost=20
REAL execution status: failed   failed_step: 1   replan_required: False
  step 1 vision-description status=failed msg='RuntimeError: No handler registered for vision-description'
```

`PddlAccessibilityOrchestrator._build_executor` registered 3 real handlers
(`mathml`, `latex-verbalizer`, `dual-provider-fusion`) plus a no-op fallback for
8 names, so 11 of the 24 methods in `DEFAULT_METHOD_COSTS` were registered and 20
were not. The admissible set is slightly smaller than the cost table: the
obligation tables (`OBLIGATION_BY_TYPE` plus `V23_OBLIGATION_BY_KIND`) admit 23
methods, of which 19 had no handler. Every plan step whose method was one of those
raised at execution time and nothing was retried or downgraded.

Worse, the no-op fallback returned `success=True, validated=True` with the message
*"Handler padrão (sem operação real)"*. Eight method names therefore marked
obligations **satisfied** while doing nothing at all — a silent lie that made the
test suite pass on `develop`.

`replan_required` stayed `False` for a different reason than "alternatives were
exhausted": `Executor` raises `EXE_NO_HANDLER_REGISTERED` when `handler is None`,
and that raise sits *outside* the `try/except` that computes `alternatives` and
sets the flag. The flag was therefore never evaluated for an unregistered method.

On top of that, `executar()` invoked the executor only inside
`if self.execute_dry_run:`, so `PDDL_EXECUTE_DRY_RUN=false` produced **no execution
at all** and `execution_report=None`. The dry-run default is what kept the pipeline
looking healthy; turning it off skipped execution entirely rather than exposing the
gap.

### State after the fix

- **Every admissible method is accounted for.** Each one now resolves to a
  registered handler or is reported to the planner as unavailable;
  `tests/test_pddl_actionability.py` fails on any method that is neither.
- **15 handlers registered** (was 3 real + 8 no-op): the 3 model-backed ones plus
  12 deterministic handlers covering `vision-description`, `pandoc-table`,
  `pandoc-code`, `pymupdf-region`, `latex-normalizer`, `norm-fix`,
  `line-number-extractor`, `verse-chunker`, `tailjoin`, `tailjoin-positioned`,
  `deterministic-heading-repair`. They *validate* the work the pipeline already
  performed instead of pretending to perform it.
- **The silent no-op is gone.** A handler that claims success must set
  `validated=True` on real work.
- **`human-review` has its own semantics.** It is the terminal escalation every
  obligation lists last. It reports `success=False` with an explicit escalation
  message rather than marking an obligation satisfied that no automated method
  performed.
- **The planner is told what is unavailable.** `_unavailable_methods(manifest)`
  restricts the set to methods the manifest actually declares (the compiler rejects
  unknown names), so `_validate_methods` fails early, at plan time, instead of
  letting an unexecutable step reach the executor.
- **`PDDL_EXECUTE_DRY_RUN` now selects the mode, not whether execution happens.**
- **`replan-required` is no longer terminal.** `executar()` replans up to
  `PDDL_MAX_REPLANS` (default 2) times, reusing the `(tried ?o ?m)` state the
  executor recorded, so a failed method moves to the next admissible one.

Nine methods remain **declared unavailable** rather than implemented:
`skeleton-order`, `xycut-order`, `agreement-rule`, `rep-guard`, `rescue-omitted`,
`single-provider`, `table-smart-fusion`, `table-specialist`, `vlm-pairwise-judge`.
They are all v2.3 methods that depend on provider disagreement or a VLM judge; the
planner never emits a step for them today. They are listed as a ratchet in
`KnownUnavailable` inside the test file, so implementing one fails the test until
it is removed from the list.

### Live evidence

Against the homologation Toolbox, `001.pdf`, `PDDL_EXECUTE_DRY_RUN=false`:

```
plan steps: 9
status: completed
  [0] start-job                          -> succeeded
  [1] execute-obligation vision-description -> succeeded
      "Descrição validada para 1 imagem(ns)"
```

Before the fix the same input produced `failed` with
`RuntimeError: No handler registered for vision-description`.

### Deferred

`_validate_methods` only raises when an obligation has **zero** available
candidates. When a compiler-declared unavailable method simply disappears from the
compiled problem while the manifest's admissible list still contains it, the
planner is still offered a method that cannot run: the `available` predicate is
emitted only for `available_methods`, and `InternalReferencePlanner` filters on it,
but `FastDownwardPlanner` relies on the domain's precondition instead. Not yet
fixed.

## Verdicts

Per-capability verdicts (integrate / keep as opt-in / retire) and their
justification are tracked in `docs/toolbox_capability_verdicts.md`.
