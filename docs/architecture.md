# Architecture

## Overview
The system converts documents into accessible formats through a hybrid extraction flow (local-first with PyMuPDF plus conditional AI vision), a canonical document pipeline, deterministic validation, and format-specific renderers. The architecture is modular: **core/** contains all business logic independent of any interface, and **interfaces/** contains pluggable front-ends (Telegram, Web).

## Layers

### 0. Core (`core/`) — Interface-agnostic business logic
- [core/orchestrator.py](../core/orchestrator.py): coordinates cache, task state, history, fallback, and status callback.
- [core/agents/state_manager.py](../core/agents/state_manager.py): in-memory task state machine with cooperative cancellation.
- [core/agents/agente_unico.py](../core/agents/agente_unico.py): processes PDF/image page by page — hybrid strategy: local PyMuPDF extraction when text is available, AI vision for scanned/no-text pages. Optionally describes embedded images.
- [core/ai/ollama.py](../core/ai/ollama.py): HTTP client for Ollama API with exponential backoff.
- [core/ai/openrouter.py](../core/ai/openrouter.py): HTTP client for OpenRouter API.
- [core/ai/base.py](../core/ai/base.py): abstract `AIClient` protocol implemented by all AI clients.
- [core/services/cache.py](../core/services/cache.py): file-hash-based text cache in `temp/cache`.
- [core/services/history_service.py](../core/services/history_service.py): SQLite persistence in `data/history.db`.
- [core/services/queue_service.py](../core/services/queue_service.py): unified async processing queue.
- [core/services/cleanup_service.py](../core/services/cleanup_service.py): periodic cleanup of temporary files.
- [core/services/email_service.py](../core/services/email_service.py): async SMTP email sender (confirmation + result).
- [core/utils/logger.py](../core/utils/logger.py): centralised loguru logger.
- [core/utils/validators.py](../core/utils/validators.py): file extension and size validation.
- [core/utils/pdf_splitter.py](../core/utils/pdf_splitter.py): single-page PDF splitter.
- [core/utils/image_converter.py](../core/utils/image_converter.py): PDF page to PNG conversion.
- [core/utils/image_enhancer.py](../core/utils/image_enhancer.py): OpenCV deskew, CLAHE, denoise.
- [core/utils/text_processor.py](../core/utils/text_processor.py): paragraph merging and Markdown parsing.

### 1. Interfaces (`interfaces/`) — Pluggable front-ends

#### Telegram (`interfaces/telegram/`)
- [interfaces/telegram/bot.py](../interfaces/telegram/bot.py): creates aiogram Bot/Dispatcher, registers routers, middlewares, and lifecycle hooks.
- [interfaces/telegram/handlers/start.py](../interfaces/telegram/handlers/start.py): control commands, modes, status, health, feedback.
- [interfaces/telegram/handlers/document.py](../interfaces/telegram/handlers/document.py): receives files/photos, validates, triggers processing, sends outputs.
- [interfaces/telegram/handlers/errors.py](../interfaces/telegram/handlers/errors.py): global exception handling.
- [interfaces/telegram/middlewares/pause_middleware.py](../interfaces/telegram/middlewares/pause_middleware.py): per-chat pause/resume gate.
- [interfaces/telegram/adapters/status_tracker.py](../interfaces/telegram/adapters/status_tracker.py): Telegram-specific progress bar.
- [interfaces/telegram/adapters/file_service.py](../interfaces/telegram/adapters/file_service.py): Telegram file download/upload.
- [interfaces/telegram/prompts/](../interfaces/telegram/prompts/): AI system prompts by mode (detalhado, medio, baixo, ocr).

#### Web (`interfaces/web/`)
- [interfaces/web/app.py](../interfaces/web/app.py): FastAPI application with upload form and processing endpoint.
- [interfaces/web/templates/index.html](../interfaces/web/templates/index.html): Bootstrap-based single-page upload form.

### 2. Canonical document pipeline (shared, no interface dependency)
- [pipeline/canonical_builder.py](../pipeline/canonical_builder.py): builds the canonical document and sections tree.
- [pipeline/sanitizer.py](../pipeline/sanitizer.py): cleans raw text, removes prompt leaks and Markdown artifacts.
- [pipeline/structure_parser.py](../pipeline/structure_parser.py): shared text-to-block parser.
- [pipeline/validators.py](../pipeline/validators.py): validates schema, heading hierarchy, links, and output text.
- [pipeline/verbosity_manager.py](../pipeline/verbosity_manager.py): defines output profiles and block filtering rules.
- [pipeline/pandoc_ast_builder.py](../pipeline/pandoc_ast_builder.py): creates the intermediate Pandoc-compatible AST.
- [schemas/accessible_document.schema.json](../schemas/accessible_document.schema.json): JSON Schema for the canonical document.

### 3. Export pipeline (shared, no interface dependency)
- [exporters/pandoc_exporter.py](../exporters/pandoc_exporter.py): single export coordinator for validation, filtering, AST build, and renderer dispatch.
- [filters/pandoc_filters.py](../filters/pandoc_filters.py): strips internal audit data and applies profile-level block filtering.
- [renderers/txt_renderer.py](../renderers/txt_renderer.py)
- [renderers/docx_renderer.py](../renderers/docx_renderer.py)
- [renderers/pdf_renderer.py](../renderers/pdf_renderer.py)
- [renderers/html_renderer.py](../renderers/html_renderer.py)

### 4. Thin wrapper exporters (`core/exporters/`)
- [core/exporters/txt_exporter.py](../core/exporters/txt_exporter.py)
- [core/exporters/docx_exporter.py](../core/exporters/docx_exporter.py)
- [core/exporters/pdf_exporter.py](../core/exporters/pdf_exporter.py)
- [core/exporters/audio_exporter.py](../core/exporters/audio_exporter.py)

### 5. Configuration
- [config/settings.py](../config/settings.py): centralized configuration with environment variable bindings, including `ENABLED_INTERFACES` to select which interfaces run at startup.

## Main processing flow
1. User sends a document via Telegram or Web upload.
2. Interface handler validates extension and size.
3. File is saved and enqueued in `UnifiedQueue` (source: "telegram" or "web").
4. Worker dequeues and calls `core.orchestrator.process()`:
   - Creates task in state manager, registers history, checks cache.
   - `AgenteUnico` processes page by page: splits PDF, extracts local text, calls AI vision when needed, stores per-page results.
   - Structured output is combined into the canonical document.
5. Canonical validators check schema, heading hierarchy, links, and output safety.
6. Canonical document is converted to a Pandoc-like AST and rendered by format-specific renderers.
7. Output files are zipped and delivered (via Telegram message or email).

## Interface activation
The `ENABLED_INTERFACES` environment variable controls which interfaces start:
- `"telegram,web"` (default): starts both Telegram polling and Web server.
- `"web"`: starts only the Web server (no BOT_TOKEN required).
- `"telegram"`: starts only the Telegram bot.

## External dependencies
- Telegram Bot API (via aiogram) — only when `telegram` interface is enabled.
- Ollama API or OpenRouter API (configurable via `AI_CLIENT`).
- Processing libraries: PyMuPDF, Pillow, opencv-python, reportlab, python-docx, pypdf.

## Storage
1. Temporary: `settings.temp_dir` with `output/` subfolder for final artifacts.
2. Cache: `temp/cache/`.
3. History: `data/history.db` (SQLite).
4. Logs: `logs/bot_YYYY-MM-DD.log` and colorized stderr.

## Key architectural decisions
1. `core/` has zero dependencies on any interface-specific library (no aiogram, no FastAPI).
2. Each interface in `interfaces/` only imports from `core/`, never from another interface.
3. Adding a new interface (Discord, CLI, etc.) means creating a new folder under `interfaces/` and connecting it to `core/`.
4. The canonical document is the source of truth; renderers should not infer structure from raw Markdown.

## Related diagrams
- [Architecture PlantUML](architecture/architecture.puml)
- [Layered Architecture](architecture/layers.md)
- [Layers PlantUML](architecture/layers.puml)
- [Sequence PlantUML](sequence/document_processing_sequence.puml)
- [State PlantUML](state_machine/task_state_machine.puml)
