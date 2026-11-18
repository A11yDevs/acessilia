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

`tests/test_boundary.py` checks the boundary on the package's source, and
`tests/test_smoke.py` checks that the installed package works on its own: CI
installs it from its lock, outside the checkout, and runs the smoke test from
there. Run both with `uv run --extra dev pytest` in this folder (`make test-all`
runs them too).

`examples/table_stage.py` runs the table-structure stage from a script,
with an explicit `CoreConfig` and a model-call runner of its own, and imports
neither the service nor FastAPI (ADR-0016's proof of concept):

```bash
uv run --extra dev python examples/table_stage.py \
  examples/fixtures/tables_manifest.json tables.pdf tables.json
```

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
profile filters remain unchanged. Detail levels describe
format capacity, not profile selection. See
[ADR 0025](../../docs/adr/0025-format-catalogue-ownership.md).

## Strict canonical export gate (0.2.0)

All public TXT/HTML/DOCX/PDF/UA exporters share
`export_accessible_document`. After existing normalization and audit, Core
injects `jsonschema.validate` into docstruct's packaged-schema API before
profile selection, AST construction or rendering. Previously accepted invalid
canonical mappings now fail with localized `ValueError`; no strictness flag is
added. Pure serializers retain their fallback behavior. See the
[breaking-change migration](CHANGELOG.md),
[compatibility corpus](../../tests/fixtures/export_schema_gate/README.md) and
[ADR 0026](../../docs/adr/0026-strict-canonical-export-gate.md).
