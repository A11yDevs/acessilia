# Component dependencies

> A Brazilian Portuguese translation is available in [dependencies.pt-br.md](dependencies.pt-br.md).

Diagram: [dependencies.puml](dependencies.puml). This page describes it in text.

The ecosystem has four components; [ADR-0002](../adr/0002-component-responsibilities.md) fixes which may depend on which.

**Allowed dependencies:**

- **Core → SDK and docstruct.** The core (`backend/`, `frontend/`) plans and orchestrates. It imports the SDK to reach the Toolbox and docstruct for pure structural algorithms.
- **SDK → docstruct.** The SDK (`libs/sdk`) holds contracts and Toolbox clients; its only runtime dependency besides docstruct is `httpx`.
- **SDK → the Toolbox's published HTTP contract.** The SDK calls the Toolbox over HTTP and never imports its code. The contract (capabilities, schemas, `ArtifactRef`) is what the Toolbox publishes.
- **Toolbox → docstruct.** The Toolbox imports docstruct as a pinned wheel built from this repository.
- **Toolbox → its sidecars, over HTTP.** Heavy tools such as Pandoc with TeX Live, MathJax with MathCAT, and veraPDF run in sidecar containers.
- **docstruct → nothing in the ecosystem.** docstruct has no runtime dependency at all.

**Forbidden dependencies, and the tests that guard them:**

- The core must not import the Toolbox package (`tests/test_architecture_layers.py`).
- The core must not import an operational library: PyMuPDF, Pillow, OpenCV, Docling, pypdf, python-docx or RapidOCR (same test). Operational work runs on the Toolbox ([ADR-0003](../adr/0003-remote-only-operational-capabilities.md)).
- docstruct must not import the core, the SDK or the Toolbox (`libs/docstruct/tests/test_purity.py`).
- The SDK must not import the core or the Toolbox (`libs/sdk/tests/test_purity.py`).
- The Toolbox must not import the SDK or the core. No test guards this yet; it is tracked in [#188](https://github.com/A11yDevs/acessilia/issues/188).

There is no dependency cycle.
