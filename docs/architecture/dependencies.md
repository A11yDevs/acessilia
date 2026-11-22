# Component dependencies

> A Brazilian Portuguese translation is available in [dependencies.pt-br.md](dependencies.pt-br.md).

Diagram: [dependencies.puml](dependencies.puml). This page describes it in text.

The ecosystem has four components; [ADR-0002](../adr/0002-component-responsibilities.md) fixes which may depend on which.

**Allowed dependencies:**

- **Core → SDK and docstruct.** The core (`backend/`, `frontend/`) plans and orchestrates. It imports the SDK to reach the Toolbox and docstruct for pure structural algorithms.
- **SDK → docstruct.** The SDK (`libs/sdk`) holds contracts, Toolbox clients and reusable operations. ADR-0002 lets it call docstruct's pure algorithms in-process; the operations and readers use that in-process access, so `libs/sdk/pyproject.toml` declares docstruct as a runtime dependency. Babel is the other generic dependency, used by the SDK's i18n infrastructure.
- **SDK → the Toolbox's published HTTP contract.** The SDK calls the Toolbox over HTTP and never imports its code. The contract (capabilities, schemas, `ArtifactRef`) is what the Toolbox publishes.
- **Toolbox → docstruct.** The Toolbox imports docstruct as a pinned wheel built from this repository.
- **Toolbox → its sidecars, over HTTP.** Heavy tools run in sidecar containers, configured in the acessilia-toolbox repository, not here. Two are referenced in this repository: `pdf-ua-render` (Pandoc with TeX Live, for PDF/UA and DOCX; see the [capability matrix](../toolbox_capability_matrix.md)) and `math-speech` (MathJax with MathCAT; see [ADR-0008](../adr/0008-math-capabilities-on-mathjax-and-mathcat.md)).
- **docstruct → nothing in the ecosystem.** docstruct has no runtime dependency at all.

**Forbidden dependencies, and the tests that guard them.** For legibility, the diagram draws only three of them in red; the list below is complete.

- The core must not import the Toolbox package (`tests/test_architecture_layers.py`).
- The core must not import an operational library: PyMuPDF, Pillow, OpenCV, Docling, pypdf, python-docx or RapidOCR (same test). Operational work runs on the Toolbox ([ADR-0003](../adr/0003-remote-only-operational-capabilities.md)).
- docstruct must not import anything outside the Python standard library: it declares no runtime dependency, and an optional accelerator (today only `rapidfuzz`) must be guarded by `except ImportError` and work without it (`libs/docstruct/tests/test_purity.py`).
- The SDK must not import the core or the Toolbox, and its runtime dependencies and imports stay within the standard library, `httpx`, Babel and docstruct (`libs/sdk/tests/test_purity.py`).
- The Toolbox must not import the SDK or the core (`tests/unit/test_architecture.py` in the Toolbox repository).

There is no dependency cycle.
