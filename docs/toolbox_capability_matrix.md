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

Running the PDDL pipeline locally against the homologation Toolbox with
`PDDL_EXECUTE_DRY_RUN=false` fails on the first obligation:

```
obligations: 7  kinds: {preserve-code-semantics: 6, describe-image: 1}
plan steps: 9
  1 execute-obligation describe-image vision-description cost=20
REAL execution status: failed   failed_step: 1   replan_required: False
  step 1 vision-description status=failed msg='RuntimeError: No handler registered for vision-description'
```

`PddlAccessibilityOrchestrator._build_executor` registers 3 real handlers
(`mathml`, `latex-verbalizer`, `dual-provider-fusion`) plus a no-op fallback for
8 names, so 11 of the 24 methods in `DEFAULT_METHOD_COSTS` are registered and 20
are not. The admissible set is slightly smaller than the cost table: the
obligation tables (`OBLIGATION_BY_TYPE` plus `V23_OBLIGATION_BY_KIND`) admit 23
methods, of which 19 have no handler. Every plan step whose method is one of
those raises at execution time and nothing is retried or downgraded.

`replan_required` stays `False` for a different reason than "alternatives were
exhausted": `Executor` raises `EXE_NO_HANDLER_REGISTERED` when `handler is None`,
and that raise sits *outside* the `try/except` that computes `alternatives` and
sets the flag. The flag is therefore never evaluated for an unregistered method.
That also hides a latent bug — `describe-image` admits `vision-description` and
`human-review`, and `human-review` *is* registered, so a replan would have been
possible had the failure gone through the handler path.

In other words: the homologation default `PDDL_EXECUTE_DRY_RUN=true` is what keeps
the pipeline looking healthy. Turning it off would fail every job. This is why
"make every admissible method actionable" is a prerequisite for any real-execution
work, not a nicety.

## Verdicts

Per-capability verdicts (integrate / keep as opt-in / retire) and their
justification are tracked in `docs/toolbox_capability_verdicts.md`.
