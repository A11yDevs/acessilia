# Design and Integration Patterns

## Identified patterns

## 1. Pipeline orchestrator
- Implementation: [bot/agente_mestre.py](../bot/agente_mestre.py)
- Role: coordinates state, cache, history, agent execution, and fallback.
- Benefit: centralizes conversion business rules.

## 2. Strategy for AI client
- Implementation: [bot/agents/agente_unico.py](../bot/agents/agente_unico.py) selects client by [config/settings.py](../config/settings.py) settings.ai_client.
- Strategies:
   - [bot/clients/opencode.py](../bot/clients/opencode.py)
   - [bot/clients/openrouter.py](../bot/clients/openrouter.py)
- Benefit: backend can be switched without changing the main flow.

## 3. Export adapter
- Implementation: [bot/exporters/txt_exporter.py](../bot/exporters/txt_exporter.py), [bot/exporters/docx_exporter.py](../bot/exporters/docx_exporter.py), [bot/exporters/pdf_exporter.py](../bot/exporters/pdf_exporter.py)
- Benefit: same text input produces multiple output formats.

## 4. Retry with backoff
- Implementation:
   - [bot/handlers/document.py](../bot/handlers/document.py) (Telegram sending)
   - [bot/clients/openrouter.py](../bot/clients/openrouter.py) (429/5xx)
   - [bot/clients/opencode.py](../bot/clients/opencode.py) (500/read/connect)
- Benefit: stronger resilience against transient failures.

## 5. In-memory state machine
- Implementation: [bot/agents/state_manager.py](../bot/agents/state_manager.py)
- Observed states: processing, done, error, cancelled.
- Benefit: progress tracking, cancellation support, and task lifecycle consistency.

## 6. Cache-aside
- Implementation:
   - global file cache in [bot/agente_mestre.py](../bot/agente_mestre.py) + [bot/services/cache.py](../bot/services/cache.py)
   - page-level cache in [bot/agents/agente_unico.py](../bot/agents/agente_unico.py)
- Benefit: reduced AI cost and latency.

## 7. Health check and external bootstrap
- Implementation: [bot/services/opencode_launcher.py](../bot/services/opencode_launcher.py) and /health command in [bot/handlers/start.py](../bot/handlers/start.py)
- Benefit: operational visibility and dependency-oriented startup.

## 8. Single-instance lock
- Implementation: [run.py](../run.py)
- Benefit: prevents concurrent local instances on the same host.

## Data and persistence patterns
1. Simplified repository style via async functions in history_service (SQLite).
2. Event logging with loguru and daily rotating files.
3. Runtime data segregation (temp/cache/logs/data) through centralized configuration.

## Anti-patterns and current risks
1. Missing conditional dependency
   - Risk: selecting AI_CLIENT=browser causes import failure.
2. Unreachable code in export_pdf
   - There is a duplicate return after the main return.
3. Potential mismatch between queue and main flow
   - queue_service is ready, but handlers call process without enqueuing.
4. Test coverage concentrated on validators/exporters/openrouter
   - Main pipeline and handlers do not have direct automated tests.

## Architectural recommendations
1. Remove or implement browser_client and add configuration validation at startup.
2. Consolidate official path: direct process or process_with_queue.
3. Add integration tests for:
   - file submission through handler,
   - page-by-page processing,
   - fallback on AI error,
   - task cancellation.
4. Define a common AI client interface (protocol/ABC) to formalize contract.
