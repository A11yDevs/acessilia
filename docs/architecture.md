# Architecture

## Overview
The system is an asynchronous Telegram bot for converting documents into accessible formats, supported by an AI pipeline and local persistence.

## Layers
1. Input interface
   - [bot/main.py](../bot/main.py): creates Bot and Dispatcher, registers middlewares/routers and lifecycle hooks.
   - [bot/handlers/start.py](../bot/handlers/start.py): control commands, modes, status, health, and feedback.
   - [bot/handlers/document.py](../bot/handlers/document.py): receives files/photos, validates input, triggers processing, and sends outputs.
   - [bot/middlewares/pause_middleware.py](../bot/middlewares/pause_middleware.py): per-chat gate for deactivate/reactivate behavior.

2. Conversion orchestration
   - [bot/agente_mestre.py](../bot/agente_mestre.py): coordinates cache, task state, history, fallback, and status callback.
   - [bot/agents/state_manager.py](../bot/agents/state_manager.py): in-memory task state machine.
   - [bot/services/queue_service.py](../bot/services/queue_service.py): queue for concurrency control (max_concurrent=1).

3. AI pipeline
   - [bot/agents/agente_unico.py](../bot/agents/agente_unico.py): processes PDF/image page by page, applies preprocessing, and calls AI client.
   - [bot/clients/opencode.py](../bot/clients/opencode.py): HTTP client for OpenCode server with session and retry.
   - [bot/clients/openrouter.py](../bot/clients/openrouter.py): HTTP client for OpenRouter API with exponential backoff.
   - [bot/prompts](../bot/prompts): prompts by detail mode.

4. Persistence and local infrastructure
   - [bot/services/cache.py](../bot/services/cache.py): text cache in temp/cache.
   - [bot/services/history_service.py](../bot/services/history_service.py): SQLite in data/history.db for conversion history and OCR tables.
   - [bot/services/cleanup_service.py](../bot/services/cleanup_service.py): periodic cleanup of temporary files.
   - [bot/services/opencode_launcher.py](../bot/services/opencode_launcher.py): OpenCode bootstrap and health check at startup.
   - [config/settings.py](../config/settings.py): centralized configuration and runtime directories.

5. Output and format adapters
   - [bot/exporters/txt_exporter.py](../bot/exporters/txt_exporter.py)
   - [bot/exporters/docx_exporter.py](../bot/exporters/docx_exporter.py)
   - [bot/exporters/pdf_exporter.py](../bot/exporters/pdf_exporter.py)

6. Cross-cutting utilities
   - [bot/utils/logger.py](../bot/utils/logger.py)
   - [bot/utils/validators.py](../bot/utils/validators.py)
   - [bot/utils/status_tracker.py](../bot/utils/status_tracker.py)
   - [bot/utils/pdf_splitter.py](../bot/utils/pdf_splitter.py)
   - [bot/utils/image_converter.py](../bot/utils/image_converter.py)
   - [bot/utils/image_enhancer.py](../bot/utils/image_enhancer.py)
   - [bot/utils/text_processor.py](../bot/utils/text_processor.py)

## Main processing flow
1. User sends a document or photo.
2. Handler validates extension and size.
3. File is downloaded to a temporary directory.
4. agente_mestre.process creates the task, registers history, and checks cache.
5. AgenteUnico processes page by page:
   - splits PDF when needed,
   - converts page,
   - compresses/enhances image,
   - sends data to AI,
   - stores per-page cache.
6. Aggregated result goes through broken paragraph merge.
7. Exporters generate TXT/DOCX/PDF.
8. Files are sent to the user with retry for rate-limits.
9. Task history and state are finalized.

## External dependencies
- Telegram Bot API (via aiogram).
- Local OpenCode (when AI_CLIENT=opencode).
- OpenRouter API (when AI_CLIENT=openrouter).
- Processing libraries: pypdf, PyMuPDF, Pillow, opencv, reportlab, python-docx.

## Storage
1. Temporary
   - settings.temp_dir
   - output subfolder for final artifacts.
2. Cache
   - [temp/cache](../temp/cache)
3. History
   - [data/history.db](../data/history.db) (SQLite).
4. Logs
   - [logs](../logs)/bot_YYYY-MM-DD.log and colorized stderr.

## Architecture attention points
1. [bot/agents/agente_unico.py](../bot/agents/agente_unico.py) contains an AI_CLIENT=browser branch that references [bot.clients.browser_client](../bot/clients), a module not present in the current repository.
2. process_with_queue exists, but current handler flow calls process directly.
3. opencode_launcher.start_serve uses opencode.cmd (more Windows-oriented), requiring validation on other environments.

## Related diagrams
- [Architecture PlantUML](architecture/architecture.puml)
- [Sequence PlantUML](sequence/document_processing_sequence.puml)
- [State PlantUML](state_machine/task_state_machine.puml)
