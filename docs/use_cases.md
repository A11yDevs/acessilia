# Use Cases

## Actors
1. Telegram end user.
2. Operator/Architect (environment setup and diagnostics).
3. AI service (OpenCode or OpenRouter), used conditionally.
4. Local filesystem and SQLite database.

## Main use cases

## UC-01 Submit document and receive accessible outputs
- Primary actor: End user.
- Goal: convert PDF/image/document into accessible outputs.
- Input: supported file.
- Output: TXT, DOCX, PDF, and HTML delivered in chat or as files.
- Implementation:
  - input/validation: [bot/handlers/document.py](../bot/handlers/document.py), [bot/utils/validators.py](../bot/utils/validators.py)
  - processing: [bot/agente_mestre.py](../bot/agente_mestre.py), [bot/agents/agente_unico.py](../bot/agents/agente_unico.py), [pipeline/canonical_builder.py](../pipeline/canonical_builder.py)
  - export: [exporters/pandoc_exporter.py](../exporters/pandoc_exporter.py), [bot/exporters](../bot/exporters), [renderers](../renderers)

## UC-02 Select description level
- Primary actor: End user.
- Goal: define detailed/medium/low/ocr mode.
- Implementation:
  - commands: [bot/handlers/start.py](../bot/handlers/start.py)
  - prompts by mode: [bot/prompts](../bot/prompts)
  - application in processing: [bot/agents/agente_unico.py](../bot/agents/agente_unico.py)

## UC-03 Check status and cancel
- Primary actor: End user.
- Goal: monitor progress and interrupt task.
- Implementation:
  - /status and /cancelar commands: [bot/handlers/start.py](../bot/handlers/start.py)
  - state/cancellation: [bot/agents/state_manager.py](../bot/agents/state_manager.py)

## UC-04 Deactivate/reactivate bot per chat
- Primary actor: End user.
- Goal: pause service in one chat without shutting down process.
- Implementation:
  - /desativar and /ativar commands: [bot/handlers/start.py](../bot/handlers/start.py)
  - control: [bot/middlewares/pause_middleware.py](../bot/middlewares/pause_middleware.py)

## UC-05 Operational health check
- Primary actor: Operator.
- Goal: verify AI backend availability and local resources.
- Implementation:
  - /health command: [bot/handlers/start.py](../bot/handlers/start.py)
  - launcher/check: [bot/services/opencode_launcher.py](../bot/services/opencode_launcher.py)

## UC-06 Submit feedback
- Primary actor: End user.
- Goal: send conversion quality feedback.
- Implementation:
  - FSM and /feedback command: [bot/handlers/start.py](../bot/handlers/start.py)
  - simplified local persistence: feedback.txt in temp_dir

## UC-07 Persist conversion history
- Primary actor: System.
- Goal: store conversion and OCR audit trail.
- Implementation:
  - history lifecycle: [bot/services/history_service.py](../bot/services/history_service.py)
  - flow calls: [bot/agente_mestre.py](../bot/agente_mestre.py)

## UC-08 Reuse cache for performance
- Primary actor: System.
- Goal: avoid repeated file/page processing.
- Implementation:
  - cache service: [bot/services/cache.py](../bot/services/cache.py)
  - usage in flow: [bot/agente_mestre.py](../bot/agente_mestre.py) and [bot/agents/agente_unico.py](../bot/agents/agente_unico.py)

## UC-09 Safe single-instance operation
- Primary actor: Operator.
- Goal: prevent unintended concurrent local execution.
- Implementation: [run.py](../run.py)

## Main flow summary
1. User submits file.
2. System validates and downloads it.
3. System creates task and registers history.
4. System processes page by page with a hybrid strategy:
  - extracts text locally from text-based PDF pages,
  - uses AI vision only for scanned/no-text pages or direct image files.
5. System consolidates pages into the canonical document, validates it, renders formats, and sends the results.
6. System finalizes history and task state.

## Alternative flows
1. Invalid extension or oversized file
   - immediate user-friendly error response (validators + handler).
2. AI backend failure
  - simple extraction fallback in [bot/agente_mestre.py](../bot/agente_mestre.py), with canonical export still available.
3. Text-based PDF page
  - page is extracted locally and does not require AI call for main text.
4. Telegram/AI backend rate-limit (OpenRouter or OpenCode)
   - retries with incremental wait.
5. Task cancellation
   - state marked as cancelled and processing interrupted.

## Covered non-functional requirements
1. Reliability: retries, fallback, and logs.
2. Performance: file/page cache and image compression.
3. Operability: health checks, process lock, periodic cleanup.
4. Maintainability: package organization, canonical pipeline, and separation of responsibilities.

## UML Diagram
- [Use cases PlantUML](use_cases/use_cases.puml)
