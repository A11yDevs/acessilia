# Modules

## Objective
Map all Python modules in the project by functional area, including main responsibility and alignment notes.

## 1. Main runtime
1. [run.py](../run.py)
   - Application bootstrap, process lock, startup, and shutdown. Reads `ENABLED_INTERFACES` to decide which interfaces to start.

## 2. Configuration
1. [config/settings.py](../config/settings.py)
   - Centralized `Settings` dataclass with environment variable bindings. Includes `enabled_interfaces`, `bot_token`, AI client config, SMTP settings, and paths.

## 3. Core — Interface-agnostic business logic (`core/`)

### 3.1. Orchestration
1. [core/orchestrator.py](../core/orchestrator.py)
   - Coordinates full conversion lifecycle: cache lookup, task state, history, AI processing, fallback, and status callbacks.
2. [core/agents/__init__.py](../core/agents/__init__.py)
3. [core/agents/agente_unico.py](../core/agents/agente_unico.py)
   - Page-by-page hybrid extraction pipeline (local PyMuPDF first, multimodal AI when needed).
4. [core/agents/state_manager.py](../core/agents/state_manager.py)
   - In-memory task state machine with cooperative cancellation.

### 3.2. AI clients
1. [core/ai/__init__.py](../core/ai/__init__.py)
2. [core/ai/base.py](../core/ai/base.py)
   - Abstract `AIClient` protocol that all AI clients implement.
3. [core/ai/ollama.py](../core/ai/ollama.py)
   - Stateless Ollama HTTP client used when `AI_CLIENT=ollama`.
4. [core/ai/openrouter.py](../core/ai/openrouter.py)
   - Stateless OpenRouter HTTP client used when `AI_CLIENT=openrouter`.

### 3.3. Infrastructure services
1. [core/services/__init__.py](../core/services/__init__.py)
2. [core/services/cache.py](../core/services/cache.py)
   - Local file-hash-based cache (JSON in `temp/cache`).
3. [core/services/history_service.py](../core/services/history_service.py)
   - SQLite persistence for conversions and OCR audit tables (`data/history.db`).
4. [core/services/cleanup_service.py](../core/services/cleanup_service.py)
   - Periodic temporary file cleanup (hourly, files older than 30 min).
5. [core/services/queue_service.py](../core/services/queue_service.py)
   - Unified async processing queue with concurrency limit (`max_concurrent=1`).
6. [core/services/email_service.py](../core/services/email_service.py)
   - Async SMTP email sender (confirmation + result with ZIP attachment).

### 3.4. Core exporters (thin wrappers)
1. [core/exporters/__init__.py](../core/exporters/__init__.py)
2. [core/exporters/txt_exporter.py](../core/exporters/txt_exporter.py)
3. [core/exporters/docx_exporter.py](../core/exporters/docx_exporter.py)
4. [core/exporters/pdf_exporter.py](../core/exporters/pdf_exporter.py)
5. [core/exporters/audio_exporter.py](../core/exporters/audio_exporter.py)
   - Delegates to `exporters.pandoc_exporter.export_accessible_document()` (txt/docx/pdf) or generates MP3 via edge-tts.

### 3.5. Core utilities
1. [core/utils/__init__.py](../core/utils/__init__.py)
2. [core/utils/logger.py](../core/utils/logger.py)
   - loguru setup with file rotation and stderr output.
3. [core/utils/validators.py](../core/utils/validators.py)
   - File extension and size validation against settings.
4. [core/utils/pdf_splitter.py](../core/utils/pdf_splitter.py)
   - Splits multi-page PDF into single-page PDFs using pypdf.
5. [core/utils/image_converter.py](../core/utils/image_converter.py)
   - PDF page to PNG via PyMuPDF.
6. [core/utils/image_enhancer.py](../core/utils/image_enhancer.py)
   - OpenCV deskew, CLAHE contrast, denoise for scanned images.
7. [core/utils/text_processor.py](../core/utils/text_processor.py)
   - Paragraph merging, Markdown and description parsing.

## 4. Telegram Interface (`interfaces/telegram/`)

1. [interfaces/telegram/__init__.py](../interfaces/telegram/__init__.py)
2. [interfaces/telegram/bot.py](../interfaces/telegram/bot.py)
   - Creates aiogram Bot/Dispatcher, registers routers, middlewares, lifecycle hooks.
3. [interfaces/telegram/handlers/__init__.py](../interfaces/telegram/handlers/__init__.py)
4. [interfaces/telegram/handlers/start.py](../interfaces/telegram/handlers/start.py)
   - UX and operation commands (/start, /help, /status, /health, /feedback, /detalhado, /medio, /baixo, /ocr, /cancelar, /desativar, /ativar, /limpar, /email).
5. [interfaces/telegram/handlers/document.py](../interfaces/telegram/handlers/document.py)
   - Document/photo input, validation, processing, ZIP generation, and output delivery via Telegram.
6. [interfaces/telegram/handlers/errors.py](../interfaces/telegram/handlers/errors.py)
   - Global exception handling in aiogram routing.
7. [interfaces/telegram/middlewares/__init__.py](../interfaces/telegram/middlewares/__init__.py)
8. [interfaces/telegram/middlewares/pause_middleware.py](../interfaces/telegram/middlewares/pause_middleware.py)
   - Paused/active chat control.
9. [interfaces/telegram/adapters/__init__.py](../interfaces/telegram/adapters/__init__.py)
10. [interfaces/telegram/adapters/status_tracker.py](../interfaces/telegram/adapters/status_tracker.py)
    - Telegram-specific progress bar with inline keyboard and message editing.
11. [interfaces/telegram/adapters/file_service.py](../interfaces/telegram/adapters/file_service.py)
    - Telegram file download and document upload helpers.
12. [interfaces/telegram/prompts/](../interfaces/telegram/prompts/)
    - AI system prompts by mode: [baixo.txt](../interfaces/telegram/prompts/baixo.txt), [medio.txt](../interfaces/telegram/prompts/medio.txt), [detalhado.txt](../interfaces/telegram/prompts/detalhado.txt), [ocr.txt](../interfaces/telegram/prompts/ocr.txt).

## 5. Web Interface (`interfaces/web/`)

1. [interfaces/web/__init__.py](../interfaces/web/__init__.py)
2. [interfaces/web/app.py](../interfaces/web/app.py)
   - FastAPI application: GET `/` renders upload form, POST `/process` accepts file + email, enqueues processing, sends result via email.
3. [interfaces/web/templates/index.html](../interfaces/web/templates/index.html)
   - Bootstrap-based single-page upload form.

## 6. Canonical pipeline (shared, no interface dependency)
1. [pipeline/canonical_builder.py](../pipeline/canonical_builder.py)
   - Builds the canonical document from raw text or structured payloads.
2. [pipeline/structure_parser.py](../pipeline/structure_parser.py)
   - Shared text-to-block parser.
3. [pipeline/sanitizer.py](../pipeline/sanitizer.py)
   - Removes prompt leaks, Markdown artifacts, normalizes text.
4. [pipeline/validators.py](../pipeline/validators.py)
   - Validates canonical shape, export profiles, and output text.
5. [pipeline/verbosity_manager.py](../pipeline/verbosity_manager.py)
   - Maps modes to verbosity and filters blocks for each profile.
6. [pipeline/pandoc_ast_builder.py](../pipeline/pandoc_ast_builder.py)
   - Builds the intermediate Pandoc-compatible AST consumed by renderers.
7. [filters/pandoc_filters.py](../filters/pandoc_filters.py)
   - Strips internal audit data and applies profile-level block filtering.
8. [schemas/accessible_document.schema.json](../schemas/accessible_document.schema.json)
   - JSON Schema for the canonical document.

## 7. Export pipeline (shared, no interface dependency)
1. [exporters/pandoc_exporter.py](../exporters/pandoc_exporter.py)
   - Canonical export coordinator, validation gate, AST build, and renderer dispatch.
2. [renderers/txt_renderer.py](../renderers/txt_renderer.py)
3. [renderers/docx_renderer.py](../renderers/docx_renderer.py)
4. [renderers/pdf_renderer.py](../renderers/pdf_renderer.py)
5. [renderers/html_renderer.py](../renderers/html_renderer.py)

## 8. Automated tests (pytest)
1. [tests/test_pandoc_filters.py](../tests/test_pandoc_filters.py)
2. [tests/test_renderers.py](../tests/test_renderers.py)
3. [tests/test_pipeline_validation.py](../tests/test_pipeline_validation.py)
4. [tests/test_structure_parser.py](../tests/test_structure_parser.py)
5. [tests/test_validators.py](../tests/test_validators.py)
6. [tests/test_ollama_client.py](../tests/test_ollama_client.py)

## 9. Root configuration/documentation artifacts
1. [requirements.txt](../requirements.txt)
2. [README.md](../README.md)
3. [.env.example](../.env.example)
4. [config.yaml](../config.yaml)

## Coverage and alignment
- **core/** contains all business logic (AI, orchestration, services, utilities) with zero interface dependencies.
- **interfaces/** contains only interface-specific adapters (Telegram aiogram, FastAPI web).
- No interface imports from another interface; all share `core/` as the single dependency.
- Adding a new interface (Discord, WhatsApp, CLI) requires only a new folder under `interfaces/` and wiring it in `run.py`.
- The canonical document is the source of truth for exports and validations.
