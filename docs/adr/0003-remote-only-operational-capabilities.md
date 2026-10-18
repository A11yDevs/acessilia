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
- **Known deviations, tracked in the #152 audit:** the core still imports
  PyMuPDF in about eleven modules, including the orchestrator's page render,
  `PyMuPDFStructurer`, `pymupdf_extractor` and `image_tools`. It also imports
  Pillow, OpenCV (`image_enhancer`), and docling without declaring it
  (`formula_worker`). These are removed in follow-up issues before `pymupdf`,
  `pillow` and `opencv-python` leave `pyproject.toml`.
- **Planned verification (#152):** a core architecture test that forbids
  `fitz`, `PIL`, `cv2` and `docling` imports, and `subprocess` calls to
  pandoc, LaTeX engines or veraPDF. It keeps an allowlist of the current
  offenders that can only shrink.
