# Toolbox capability verdicts

This document records whether each Toolbox capability is actionable in the
Acessilia core, based on the live staging contract, production call paths, and
the E2E suite. "Exposed by the Toolbox" alone does not mean a capability is
integrated. For Dr.DocBench capabilities, however, lack of activation must be
investigated along the evidence → obligation → `problem.pddl` → method →
handler → verifiable-effect path, not treated as grounds for dropping the
capability.

## Live contract snapshot

Checked against `https://www.acessilia3.inf.ufg.br/toolbox` on 2026-10-14:

- 26 capabilities and 25 providers are exposed.
- Five known contract drifts remain: three core clients target capabilities
  absent from the live Toolbox, and two provider defaults name providers the
  live Toolbox does not register.
- Six Toolbox capabilities are exposed without a core client.
- The live E2E suite passed all 42 selected tests. This covers the production
  call paths represented by the current E2E suite, not every capability in the
  live Toolbox catalogue.

## Verdicts

| Capability / family | Evidence in Acessilia | Verdict | Follow-up |
|---|---|---|---|
| `document.structure.extract` | Used by `ToolboxManifestExtractor`; exercised by pipeline comparison and fusion E2E tests | Integrated | Keep contract and E2E coverage |
| `document.layout.analyze` | `ToolboxLayoutStructurer`; direct and workflow E2E coverage | Integrated | Keep contract and E2E coverage |
| `document.ocr` | Agno wrapper and OCR client; remote OCR E2E coverage | Integrated | Keep contract and E2E coverage |
| `math.recognize`, `math.convert`, `math.verbalize` | Math tools/client; recognition, conversion, verbalization, and chained workflow E2E coverage | Integrated | Keep contract and E2E coverage |
| `pdf.split`, `pdf.render` | SDK client with direct and chained workflow E2E coverage. `pdf.render@2` renders every orchestrator page and region (`pymupdf-region`, `vision-page-inspection`, `vlm-pairwise-judge` and the picture/table enrichment, #150 F5); `pdf.split` has no production caller since `toolbox_pdf_tools.py` was removed (#150 F4) | Contract kept | Keep contract and E2E coverage, including the `pdf.render@2` clip, `max_side` and refusals the core relies on |
| `media.inspect` | Production caller in `backend/tools/media_inspect.py`; opt-in setting | Integrated, opt-in | Keep the explicit feature gate |
| `document.export.pdf_ua` | Production caller in `backend/export/pandoc_exporter.py`; enabled by default; Toolbox only since #150 F2, with no local fallback. Added after the snapshot above: checked live on 2026-10-17, after acessilia-toolbox#53 merged | Integrated | Every deployment must run `pdf-ua-render`: without it, jobs report PDF/UA as an optional export error |
| `artifact.store`, `artifact.retrieve` | Shared Toolbox client; used by extraction/upload paths | Integrated infrastructure | Keep covered by client contract tests |
| `dataset.*` | Dataset tools are used by Dr.DocBench scripts, not the document runtime | Integrated for benchmarking; outside document runtime | Preserve script call paths and tests |
| `image.page.orient` | Contract-valid client/provider; no production PDDL trigger | Pending modeling/activation | Derive an obligation from orientation evidence and validate the applied rotation |
| `document.ocr.page` | Client/default exist; live capability/provider and PDDL trigger are missing | Pending; known contract drift | Align contract/provider and route real page-OCR evidence to an obligation |
| `document.adjudicate.page`, `document.adjudicate.region` | Clients/defaults exist; live capabilities/providers and PDDL triggers are missing | Pending; known contract drift | Align contracts/providers and route divergence/region evidence to adjudication |
| `accessibility.mark` | Exposed by the Toolbox; core client and obligation/method/handler path are missing | Pending PDDL integration | Map evidence, obligation, call, and a verifiable accessibility effect |
| `chem.convert`, `chem.recognize` | Exposed by the Toolbox; core client and obligation/method/handler path are missing | Pending PDDL integration | Route observed chemistry regions to conversion and validate output |
| `code.normalize` | Exposed by the Toolbox; core client and obligation/method/handler path are missing | Pending PDDL integration | Route observed code blocks to normalization and validate semantic preservation |
| `text.postprocess` | Exposed by the Toolbox; core client and obligation/method/handler path are missing | Pending PDDL integration | Route text-noise signals to post-processing and validate the result |
| `music.omr` | Exposed by the Toolbox; core client and obligation/method/handler path are missing | Pending PDDL integration | Route detected scores to OMR transcription and validate the musical artifact |
| `cache.get`, `cache.put` | Toolbox-internal implementation detail | Not a core capability | Keep internal; no core client is required |

## Release decision

The existing Acessilia-to-Toolbox workflows are verified against the live
staging image. The integration is **not fully contract-clean** while the five
known drifts remain. Dr.DocBench capabilities without activation remain in
scope: close their PDDL path and missing contracts/providers rather than
removing them because they lack a conventional product workflow. The service-
specific REST specification for page OCR and adjudication is still required
before implementing their Toolbox adapters.
