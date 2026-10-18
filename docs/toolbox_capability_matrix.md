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
missing link identifies an integration gap; it does not prove the capability is
dead. For Dr.DocBench capabilities, investigate the evidence → obligation →
`problem.pddl` → method → handler → verifiable-effect path, rather than dropping
a capability because it is not currently activated.

| Link | Artifact | Location |
|---|---|---|
| Registry entry | `ToolboxCapability` (id, version, provider setting, output schema) | `libs/sdk/src/acessilia_sdk/toolbox/capabilities.py` |
| Client | `ToolboxCapabilityClient` subclass calling the registered id | `backend/tools/toolbox_*_client.py` |
| Provider default | `PROVIDER_DEFAULTS`, read by `TOOLBOX_*_PROVIDER` in `Settings` | `libs/sdk/src/acessilia_sdk/toolbox/capabilities.py` |
| Manifest | `capabilities/*.yaml` | `acessilia-toolbox` |
| Provider registration | `providers-config.yaml` entry with an adapter | `acessilia-toolbox` |

For planning-driven work there are further links: the obligation/method entry in
`DEFAULT_METHOD_COSTS` (`backend/core/manifest/builder.py`), a registered handler
in `PddlAccessibilityOrchestrator._build_executor`
(`backend/agents/pddl_orchestrator.py`), and real evidence that causes the
compiler to emit the required facts in `problem.pddl`.

## Matrix

Legend for **Call path**: how the core reaches the capability.

| Capability | Core client | Core provider default | Toolbox provider | Call path |
|---|---|---|---|---|
| `document.structure.extract` | `toolbox_client.py` (`ToolboxClient.extract_structure`) | `TOOLBOX_PROVIDER=docling` | `docling`, `mineru`, `nougat`, `teleocr` | `ToolboxManifestExtractor` → PDDL extraction; with `FUSION_MODE=dual`, also compares the secondary provider and passes page evidence to the manifest builder |
| `document.layout.analyze` | `toolbox_layout_client.py` | `TOOLBOX_LAYOUT_PROVIDER=docling-layout` | `docling-layout`, `mineru-layout` | `ToolboxLayoutStructurer` via `STRUCTURER=toolbox-layout` |
| `document.ocr` | `toolbox_ocr_client.py` | `TOOLBOX_OCR_PROVIDER=docling-ocr` | `docling-ocr`, `mineru-ocr` | `toolbox_ocr_tools.py` (Agno wrapper) |
| `math.recognize` | `toolbox_math_client.py` | `TOOLBOX_MATH_RECOGNIZE_PROVIDER=docling-math` | `docling-math`, `rapid-latex-ocr` | `toolbox_math_tools.py` |
| `math.convert` | `toolbox_math_client.py` | `TOOLBOX_MATH_PROVIDER=pure-math` | `pure-math` | `toolbox_math_tools.py` |
| `math.verbalize` | `toolbox_math_client.py` | `TOOLBOX_MATH_PROVIDER=pure-math` | `pure-math` | `toolbox_math_tools.py` |
| `pdf.split` | `toolbox_pdf_client.py` | `TOOLBOX_PDF_PROVIDER=pymupdf-pdf` | `pymupdf-pdf` | `toolbox_pdf_tools.py` (validates, then splits locally) |
| `pdf.render` | `toolbox_pdf_client.py` | `TOOLBOX_PDF_PROVIDER=pymupdf-pdf` | `pymupdf-pdf` | `toolbox_pdf_tools.py` (falls back to local PyMuPDF; deviation removed in #150, ADR-0003) |
| `media.inspect` | `toolbox_media_inspect_client.py` | `TOOLBOX_MEDIA_INSPECT_PROVIDER=pure-media-inspect` | `pure-media-inspect` | `backend/tools/media_inspect.py` (local fallback; deviation removed in #150, ADR-0003), gated by `TOOLBOX_MEDIA_INSPECT_ENABLED` |
| `document.export.pdf_ua` | `toolbox_pdf_ua_client.py` | `TOOLBOX_PDF_UA_PROVIDER=pandoc-pdf-ua` | `pandoc-pdf-ua` (sidecar `pdf-ua-render`) | `backend/export/pandoc_exporter.py` (Toolbox-first, PDF downloaded from `/v1/artifacts`; the local pandoc + LaTeX fallback is a deviation removed in #150, ADR-0003), gated by `TOOLBOX_PDF_UA_ENABLED` |
| `artifact.store` / `artifact.retrieve` | `toolbox_client.py` REST `/v1/artifacts` | — | `minio`, `filesystem` | upload before extraction |
| `dataset.*` (8 capabilities) | `toolbox_client.py` REST `/v1/datasets` | — | `dataset-github`, `dataset-huggingface` | `toolbox_dataset_tools.py` (Dr.DocBench scripts) |
| `document.ocr.page` | `toolbox_page_ocr_client.py` | `TOOLBOX_PAGE_OCR_PROVIDER=qwen3-vl-8b` | `qwen3-vl-8b` (acessilia-toolbox#50) | published; no PDDL method calls it yet |
| `document.adjudicate.page` | `toolbox_adjudicate_client.py` | `TOOLBOX_ADJUDICATE_PROVIDER=qwen3-vl-8b` | `qwen3-vl-8b` (acessilia-toolbox#50) | `vlm-pairwise-judge` on `adjudicate-page`; thresholds to re-validate on the 8B model |
| `document.adjudicate.region` | `toolbox_adjudicate_client.py` | `TOOLBOX_ADJUDICATE_PROVIDER=qwen3-vl-8b` | `qwen3-vl-8b` (acessilia-toolbox#50) | published; `rescue-omitted` handler pending |
| `table.recognize` | `toolbox_table_client.py` | `TOOLBOX_TABLE_PROVIDER=qwen3-vl-8b` | `qwen3-vl-8b` (acessilia-toolbox#50) | published; `table-specialist` handler pending (selection rule to decide) |
| `image.page.orient` | `toolbox_orientation_client.py` | `TOOLBOX_ORIENTATION_PROVIDER=rapidocr-orient` | `rapidocr-orient` | contract-valid; PDDL trigger and production effect validation pending |
| `accessibility.mark` | **absent** | — | `pure-accessibility` | pending: evidence-driven client and obligation/method/handler |
| `chem.convert` | **absent** | — | `pure-chem` | pending: evidence-driven client and obligation/method/handler |
| `chem.recognize` | **absent** | — | `docling-chem` | pending: evidence-driven client and obligation/method/handler |
| `code.normalize` | **absent** | — | `pure-code` | pending: evidence-driven client and obligation/method/handler |
| `text.postprocess` | **absent** | — | `pure-text` | pending: evidence-driven client and obligation/method/handler |
| `music.omr` | **absent** | — | `homr`, `audiveris` | pending: evidence-driven client and obligation/method/handler |
| `cache.get` / `cache.put` | — (internal) | — | `valkey` | Toolbox-internal cache; not a public capability |

## Confirmed drift (as of the review)

Measured against the running staging Toolbox with
`python scripts/check_capability_contract.py --snapshot tests/fixtures/toolbox-contract.json`:

1. The published generic REST API exposes
   `POST /v1/capabilities/{capability_id}:execute`, with per-capability schemas
   available from `GET /v1/capabilities/{capability_id}`. The live OpenAPI is
   `https://www.acessilia3.inf.ufg.br/toolbox/v1/openapi.json` (UI:
   `/toolbox/v1/docs`). This does not define capability-specific routes.
2. Resolved by acessilia-toolbox#50: `document.ocr.page`,
   `document.adjudicate.page` and `document.adjudicate.region` are published by
   the `qwen3-vl-8b` provider, and the SDK defaults point at it (they named
   `qwen3-vl-page` and `qwen3-vl-judge`, from the experiments' 32B profile).
3. `KNOWN_DRIFT` is empty against the Toolbox develop catalogue; staging still
   runs an image older than #50 until it is redeployed.
4. Six capabilities have no core client at all (see the matrix).

The orientation contract drift was resolved: the client posted to
`document.orientation.detect` with provider `rapidocr-orientation`, neither of
which the Toolbox knows, while the Toolbox exposes `image.page.orient`
implemented by `rapidocr-orient`. The client and the default now match the
catalogue. Its missing production trigger is a PDDL modeling/integration gap,
not grounds to retire the Dr.DocBench capability.

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
- **18 handlers registered** (was 3 real + 8 no-op): the 3 model-backed ones,
  the single-provider fallback, the
  13 deterministic handlers covering `vision-description`, `pandoc-table`,
  `pandoc-code`, `pymupdf-region`, `latex-normalizer`, `norm-fix`, `rep-guard`,
  `line-number-extractor`, `verse-chunker`, `tailjoin`, `tailjoin-positioned`,
  `xycut-order`, and `deterministic-heading-repair`; `human-review` is the
  explicit terminal escalation handler.
  `single-provider` is the executable fallback after a rejected dual-provider
  attempt; a regression test proves the PDDL replan selects it and records its
  extraction artifact.
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

### P2: evidence-driven v2.3 obligations

The manifest builder now derives v2.3 obligations from deterministic evidence:
text/formula normalization changes, a real reading-order reorder, eligible tail
joins, verse chunking and marginal line-number extraction. Dual-provider
obligations are emitted only when the extraction carries per-page fusion evidence;
text disagreement, dropped blocks, table-source decisions and repetition cuts are
not inferred from a single-provider manifest. The Toolbox's existing obligations
are preserved, and derived v2.3 obligations are deduplicated by kind and target.

The fusion pipeline now exports per-page decision counters and a repetition-cut
count (without copying provider text into the manifest). This evidence allows the
builder to distinguish an observed issue from a capability that merely exists in
the PDDL catalog. Seven methods still lack executable handlers and remain
excluded from plans until their required candidate data or Toolbox REST contracts
are available. This is an integration backlog, not a decision to discard those
Dr.DocBench capabilities. The specific REST/OpenAPI contracts for page OCR and
adjudication are pending from the service owner.

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

### Planner availability gate

Unavailable methods remain in the manifest's admissible-method list for
traceability, but the compiler does not emit `(available <method>)` for them.
The PDDL `execute-obligation` action requires `(available ?m)`, so Fast Downward
cannot select those methods. The internal planner applies the same projection
directly, and the runtime validates external plans against it before execution.
`tests/test_pddl_planning.py::test_fast_downward_respects_unavailable_methods`
regresses both the compiled availability facts and rejection of an invalid
external plan.

## Verdicts

Per-capability verdicts (integrate / keep as opt-in / retire) and their
justification are tracked in `docs/toolbox_capability_verdicts.md`.
