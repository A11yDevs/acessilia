# 0003. Operational capabilities run remotely, without local fallbacks

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](0003-remote-only-operational-capabilities.pt-br.md)

- **Status:** Accepted
- **Date:** 2026-10-18
- **Components:** core, SDK, Toolbox
- **Issues:** [#150](https://github.com/A11yDevs/acessilia/issues/150), [#152](https://github.com/A11yDevs/acessilia/issues/152)

## Context

Five call sites in the core tried the Toolbox first and then fell back to a
local implementation:

- PDF/UA export (pandoc + TeX Live);
- `media.inspect` (Pillow + PyMuPDF);
- PDF split and page render (PyMuPDF);
- the structure and layout structurers (PyMuPDF).

Each site had its own enablement switch, its own rule for which errors trigger
the fallback, and its own way of reporting failures. To support these
fallbacks, the core image installs pandoc, TeX Live and the veraPDF toolchain.
The local copies also drifted: the core's media inspection can no longer
classify scanned pages, and the core's PDF/UA template ignores the requested
language.

## Decision

- **Operational capabilities run in the Toolbox.** "Operational" means
  anything that needs an external tool, a model or specialized
  infrastructure: Pandoc, TeX Live, veraPDF, PyMuPDF rendering, media
  inspection, Docling, MinerU, Nougat, AI models.
- **The production policy is `remote_only`.** The core does not run these
  capabilities in-process.
- **No local fallbacks.** The core does not add a local fallback for an
  operational capability, and does not install heavy dependencies only to
  offer one.
- **Unavailability is explicit.** When a capability is unavailable, the core
  either fails the step or degrades it as a visible, documented business
  decision. In both cases the cause is recorded (see
  [ADR-0006](0006-availability-and-failover.md)). It never silently produces
  a result through a different implementation.
- **Switches mean "run or skip".** The `TOOLBOX_*_ENABLED` settings decide
  whether the core runs a capability at all. They never select a local
  implementation.
- **Exceptions need an ADR.** A local or offline executor needs an ADR that
  states its justification, scope, owner and exit criterion (see the
  [ADR process](README.md#process)).
- **docstruct is not affected.** Pure docstruct algorithms called in-process
  are not operational capabilities, so this decision does not cover them.

## Consequences

- #150 removes the local paths, one capability per pull request, and then
  drops pandoc, TeX Live and veraPDF/JRE from `infra/Dockerfile`. The image
  size is measured before and after.
- #150 removed the local executors it covered one by one; the last, the
  local manifest extractors, went in
  [#176](https://github.com/A11yDevs/acessilia/pull/176), and `pymupdf`
  became a development dependency that tests use to build PDFs.
- **Known deviations, tracked in [#203](https://github.com/A11yDevs/acessilia/issues/203):** two local executors remain, so
  `remote_only` is not complete yet:
  - `backend/export/renderers/pdf_renderer.py` renders PDF with `reportlab`;
  - `backend/export/exporters/audio_exporter.py` synthesizes MP3 with
    `edge-tts`.

  Each is replaced by a Toolbox capability reached through the SDK. Once a
  path is gone, its library joins the list below and leaves the core's
  runtime dependencies.
- **Verification (#152):** `tests/test_architecture_layers.py` fails if
  `backend/` or `frontend/` imports an operational library (`fitz`, `PIL`,
  `cv2`, `docling`, `pypdf`, `docx`, `rapidocr`, `pypandoc`). It has no
  offenders, so it keeps no allowlist; `reportlab` and `edge_tts` are not on
  the list yet. It does not check `subprocess` calls;
  pandoc, TeX Live and veraPDF are no longer in the image.
