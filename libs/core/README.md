# acessilia-core

Brazilian Portuguese: [português brasileiro](README.pt-br.md).

Acessilia's core: the PDDL pipeline that plans and executes a document's
accessibility, with its agents, enrichment stages and exporters
([ADR-0016](../../docs/adr/0016-core-package.md)).

It imports nothing from the service (`backend`) or the front ends
(`frontend`), and reads no environment variable. Its caller passes what it
needs:

- a `CoreConfig` per run (`acessilia_core.config`);
- the run's `RunPorts`: the region cache, the job's checkpoints and its
  registry of remote operations (`acessilia_core.ports`);
- the model-call runner (`acessilia_core.agents.model_calls`);
- the process setup, once: the logger, the offered locales and the server
  locale (`acessilia_core.logger`, `acessilia_core.i18n`).

`tests/test_core_boundary.py`, at the repository root, checks the boundary.

## Format catalogue

`acessilia_core.export.catalog` provides frozen `FormatDelivery` records in
`CATALOG` and the `downloadable_formats()` projection. Format identity is the
pure `docstruct.export.formats.FormatSpec`; delivery policy is Core-owned.
The API, token service and web panel reuse MIME types, public filenames and
labels. Historical API label tokens remain unchanged and separate from display
msgids. DOCX/PDF/UA bind to the public SDK capability registry.

The service worker owns order, flags, optional failures, progress and packaging
through `backend.api.export_plan`; Core imports no service code. Legacy PDF is
download-only, benchmark Markdown is internal, and ZIP is packaging. Existing
profile filters and export validation remain unchanged. Detail levels describe
format capacity, not profile selection. See
[ADR 0025](../../docs/adr/0025-format-catalogue-ownership.md).
