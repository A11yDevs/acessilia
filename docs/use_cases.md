# Use Cases

## Actors
1. End user, via the REST API directly or through the Telegram bot or Web panel (both clients of the API). The Telegram-specific commands below (status, cancel, pause, feedback) apply to the bot interface.
2. Operator/Architect (environment setup and diagnostics).
3. AI service (OpenRouter or Ollama), used conditionally.
4. Local filesystem and SQLite database.

## Main use cases

## UC-01 Submit document and receive accessible outputs
- Primary actor: End user.
- Goal: convert PDF/image/document into accessible outputs.
- Input: supported file.
- Output: TXT, DOCX, PDF, HTML, and MP3 delivered in chat or as files.
- Implementation:
  - input/validation: [frontend/telegram/handlers/document.py](../frontend/telegram/handlers/document.py), [backend/tools/validators.py](../backend/tools/validators.py)
  - processing: [backend/service.py](../backend/service.py) selects the engine (`PIPELINE_ENGINE`): the legacy orchestrator [backend/agents/orchestrator.py](../backend/agents/orchestrator.py) or the PDDL orchestrator [backend/agents/pddl_orchestrator.py](../backend/agents/pddl_orchestrator.py); both feed [backend/pipeline/canonical_builder.py](../backend/pipeline/canonical_builder.py)
  - export: [backend/export/pandoc_exporter.py](../backend/export/pandoc_exporter.py), [backend/export/exporters](../backend/export/exporters), [backend/export/renderers](../backend/export/renderers)

## UC-02 Select description level
- Primary actor: End user.
- Goal: define detailed/medium/low/ocr mode.
- Implementation:
  - commands: [frontend/telegram/handlers/start.py](../frontend/telegram/handlers/start.py)
  - prompts by mode: [backend/ai/prompts](../backend/ai/prompts)
  - application in processing: [backend/agents/vision_agent.py](../backend/agents/vision_agent.py)

## UC-03 Check status and cancel
- Primary actor: End user.
- Goal: monitor progress and interrupt task.
- Implementation:
  - /status and /cancelar commands: [frontend/telegram/handlers/start.py](../frontend/telegram/handlers/start.py)
  - state/cancellation: [backend/agents/state_manager.py](../backend/agents/state_manager.py)

## UC-04 Deactivate/reactivate bot per chat
- Primary actor: End user.
- Goal: pause service in one chat without shutting down process.
- Implementation:
  - /desativar and /ativar commands: [frontend/telegram/handlers/start.py](../frontend/telegram/handlers/start.py)
  - control: [frontend/telegram/middlewares/pause_middleware.py](../frontend/telegram/middlewares/pause_middleware.py)

## UC-05 Operational health check
- Primary actor: Operator.
- Goal: verify AI backend availability and local resources.
- Implementation:
  - /health command: [frontend/telegram/handlers/start.py](../frontend/telegram/handlers/start.py)
  - AI backend client: [backend/ai/models/ai_client.py](../backend/ai/models/ai_client.py)

## UC-06 Submit feedback
- Primary actor: End user.
- Goal: send conversion quality feedback.
- Implementation:
  - FSM and /feedback command: [frontend/telegram/handlers/start.py](../frontend/telegram/handlers/start.py)
  - simplified local persistence: feedback.txt in temp_dir

## UC-07 Persist conversion history
- Primary actor: System.
- Goal: store conversion and OCR audit trail.
- Implementation:
  - history lifecycle: [backend/services/history_service.py](../backend/services/history_service.py)
  - flow calls: [backend/service.py](../backend/service.py)

## UC-08 Reuse cache for performance
- Primary actor: System.
- Goal: avoid repeated file/page processing.
- Implementation:
  - cache service: [backend/services/cache.py](../backend/services/cache.py)
  - usage in flow: [backend/service.py](../backend/service.py) and [backend/agents/orchestrator.py](../backend/agents/orchestrator.py)

## UC-09 Safe single-instance operation
- Primary actor: Operator.
- Goal: prevent unintended concurrent local execution.
- Implementation: [frontend/run.py](../frontend/run.py)

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
  - simple extraction fallback in [backend/service.py](../backend/service.py), with canonical export still available.
3. Text-based PDF page
  - page is extracted locally and does not require AI call for main text.
4. Telegram/AI backend rate-limit (Ollama or OpenRouter)
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
