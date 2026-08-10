# Automated Test Suite

The suite covers the canonical pipeline, both processing engines (`legacy` and `pddl`), and the interface clients. Tests are unit-level and fast: filesystem work uses temporary directories, network and LLM calls are mocked, and async flows run under `pytest-asyncio`.

Per the constitution, the container run is the gate: tests must pass inside Docker (production-equivalent) before merge; native runs are a secondary check.

## Layout

### Canonical document and export
- `test_canonical_pipeline.py` — building the canonical document (sections, ids, heading titles) from raw and structured payloads.
- `test_structure_parser.py` — text-to-block parsing.
- `test_pandoc_ast_builder.py` — canonical → Pandoc AST (including table nodes).
- `test_pandoc_filters.py` — accessibility filters over the AST.
- `test_renderers.py` — deterministic TXT/DOCX/PDF/HTML rendering.
- `test_exporters.py` — the export adapters and empty-input handling.

### Validation
- `test_validators.py` — file extension and size validation.
- `test_pipeline_validation.py` — canonical schema and output-text validation.
- `test_audit_validation.py` — `audit_canonical_document`: missing sections, blockers vs warnings.

### PDDL planning engine (`backend/core/`)
- `test_processing_manifest.py` — the Informational-Structural agent builds a valid manifest with processing obligations; schema is enforced.
- `test_pymupdf_manifest_extractor.py` — the PyMuPDF extractor builds a pseudo-document and infers headings.
- `test_pddl_planning.py` — domain/version bundling, problem compilation, dependency closure, and rejection of invalid obligations.
- `test_agno_executor.py` — the Executor runs a nominal plan as an Agno Workflow (dry run), records failed methods, and triggers replanning.
- `test_pddl_orchestrator.py` — the PDDL structured payload stays compatible with the canonical builder (fallbacks, callout/note mapping).

### Engine selection
- `test_service_engine.py` — `PIPELINE_ENGINE` normalization and orchestrator selection in `backend/service.py` (`legacy`, `pddl`, and the `pmv` alias).

### Interfaces and clients
- `test_api.py` — REST API endpoints (`health`, `stats`, `history`, jobs).
- `test_api_client.py` — the shared client: submit, status, cancel.
- `test_web_panel.py` — the Web panel pages and upload delegating to the API.
- `test_telegram_client.py` — the Telegram document flow (mode, source, email, download link).
- `test_cli_entrypoints.py` — CLI commands respond to `--help`.

## How to run

```bash
# Native (secondary check)
poetry run pytest tests/

# Container (the merge gate — the `test` stage of infra/Dockerfile)
docker build -f infra/Dockerfile --target test -t acessilia:test-docling .
docker run --rm -v "$PWD:/app" -w /app acessilia:test-docling pytest tests/
```

## Related documentation
- [Architecture](../docs/architecture.md)
- [PDDL + Agno pipeline](../docs/pmv_agno_pddl.md)
- [Use Cases](../docs/use_cases.md)
