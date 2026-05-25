# Design and Integration Patterns

## Identified patterns

## 1. Canonical document pipeline
- Implementation: [pipeline/canonical_builder.py](../pipeline/canonical_builder.py), [pipeline/validators.py](../pipeline/validators.py), [pipeline/pandoc_ast_builder.py](../pipeline/pandoc_ast_builder.py), [exporters/pandoc_exporter.py](../exporters/pandoc_exporter.py)
- Role: normalize structured page payloads into a canonical JSON document, validate it, build the intermediate AST, and hand it to the renderers.
- Benefit: deterministic output and a clear source of truth for all exporters.

## 2. Pipeline orchestrator
- Implementation: [bot/agente_mestre.py](../bot/agente_mestre.py)
- Role: coordinates state, cache, history, agent execution, and fallback.
- Benefit: centralizes conversion business rules.

## 3. Strategy for AI client
- Implementation: [bot/agents/agente_unico.py](../bot/agents/agente_unico.py) selects client by [config/settings.py](../config/settings.py) settings.ai_client.
- Strategies:
   - [bot/clients/opencode.py](../bot/clients/opencode.py)
   - [bot/clients/openrouter.py](../bot/clients/openrouter.py)
- Benefit: backend can be switched without changing the main flow.

## 4. Local-first extraction strategy
- Implementation: [bot/agents/agente_unico.py](../bot/agents/agente_unico.py) using PyMuPDF extraction and threshold-based fallback.
- Role:
   - use local PDF text extraction first,
   - call AI vision only for scanned/no-text pages and direct image inputs,
   - keep page-level cache regardless of extraction path.
- Benefit: lower cost/latency and reduced dependency on external AI for text-native PDFs.

## 5. Export adapter
- Implementation: [exporters/pandoc_exporter.py](../exporters/pandoc_exporter.py) and [bot/exporters/txt_exporter.py](../bot/exporters/txt_exporter.py), [bot/exporters/docx_exporter.py](../bot/exporters/docx_exporter.py), [bot/exporters/pdf_exporter.py](../bot/exporters/pdf_exporter.py)
- Benefit: same canonical document produces multiple output formats through deterministic renderers.

## 6. Retry with backoff
- Implementation:
   - [bot/handlers/document.py](../bot/handlers/document.py) (Telegram sending)
   - [bot/clients/openrouter.py](../bot/clients/openrouter.py) (429/5xx)
   - [bot/clients/opencode.py](../bot/clients/opencode.py) (500/read/connect)
- Benefit: stronger resilience against transient failures.

## 7. In-memory state machine
- Implementation: [bot/agents/state_manager.py](../bot/agents/state_manager.py)
- Observed states: processing, done, error, cancelled.
- Benefit: progress tracking, cancellation support, and task lifecycle consistency.

## 8. Cache-aside
- Implementation:
   - global file cache in [bot/agente_mestre.py](../bot/agente_mestre.py) + [bot/services/cache.py](../bot/services/cache.py)
   - page-level cache in [bot/agents/agente_unico.py](../bot/agents/agente_unico.py)
- Benefit: reduced AI cost and latency.

## 9. Health check and external bootstrap
- Implementation: [bot/services/opencode_launcher.py](../bot/services/opencode_launcher.py) and /health command in [bot/handlers/start.py](../bot/handlers/start.py)
- Benefit: operational visibility and dependency-oriented startup.

## 10. Single-instance lock
- Implementation: [run.py](../run.py)
- Benefit: prevents concurrent local instances on the same host.

## Data and persistence patterns
1. Simplified repository style via async functions in history_service (SQLite).
2. Event logging with loguru and daily rotating files.
3. Runtime data segregation (temp/cache/logs/data) through centralized configuration.

## Anti-patterns and current risks
1. Drift between raw text and canonical document must be avoided.
2. Renderers should stay deterministic and only consume validated canonical data.
3. Queue service is available, but the current handler flow still calls process directly.
4. Test coverage is growing, but handlers and orchestration still need direct integration tests.
5. Tesseract configuration exists but runtime extraction currently does not use it, which may confuse operations.

## Architectural recommendations
1. Keep the canonical document schema and renderers in sync whenever the output contract changes.
2. Consolidate official path: direct process or process_with_queue.
3. Add integration tests for:
   - file submission through handler,
   - page-by-page processing,
   - fallback on AI error,
   - task cancellation.
4. Define a common AI client interface (protocol/ABC) to formalize contract.
