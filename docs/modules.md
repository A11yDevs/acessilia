# Modules

## Objective
Map all Python modules in the project by functional area, including main responsibility and alignment notes.

---

## 1. Main Runtime & Configuration

1. [frontend/run.py](../frontend/run.py)
   - Application bootstrap, process lock, startup, and shutdown. Reads `ENABLED_INTERFACES` to decide which interfaces to start.
2. [backend/config/settings.py](../backend/config/settings.py)
   - Centralized `Settings` dataclass with environment variable bindings (`enabled_interfaces`, `bot_token`, AI client config, SMTP settings, directory paths).

---

## 2. Backend — Domain Logic & Multi-Agent Architecture (`backend/`)

### 2.1. Agents & Orchestration (`backend/agents/`)
1. [backend/agents/orchestrator.py](../backend/agents/orchestrator.py)
   - `AccessibilityOrchestrator`: Coordinates conversion lifecycle, task state, cache, multi-agent dispatch, fallback, and status callbacks.
2. [backend/agents/reader_agent.py](../backend/agents/reader_agent.py)
   - `ReaderAgent`: Local-first PDF/image structural parsing (via PyMuPDF or Docling), page splitting, and region classification.
3. [backend/agents/vision_agent.py](../backend/agents/vision_agent.py)
   - `VisionAgent`: Agno multimodal Agent generating detailed alt-text and audio descriptions for visual elements and scanned pages.
4. [backend/agents/data_agent.py](../backend/agents/data_agent.py)
   - `DataAgent`: Agno Agent converting complex tables and formulas into structured Markdown and LaTeX.
5. [backend/agents/editor_agent.py](../backend/agents/editor_agent.py)
   - `EditorAgent`: Sanitizes content, applies MD5 fingerprint deduplication, and formats accessibility tags.
6. [backend/agents/state_manager.py](../backend/agents/state_manager.py)
   - `StateManager`: In-memory task state machine with cooperative cancellation support.
7. [backend/agents/types.py](../backend/agents/types.py)
   - Task types and data structures (`RegionTask`).

### 2.2. AI Integration (`backend/ai/`)
1. [backend/ai/ai_client.py](../backend/ai/ai_client.py)
   - `get_agno_model()`: Factory function returning configured Agno Model instances for Ollama or OpenRouter.

### 2.3. Services (`backend/services/`)
1. [backend/services/cache.py](../backend/services/cache.py)
   - Local file-hash-based cache (`temp/cache`).
2. [backend/services/history_service.py](../backend/services/history_service.py)
   - MariaDB/SQLite persistence for conversions and OCR audit logs (`data/history.db`).
3. [backend/services/cleanup_service.py](../backend/services/cleanup_service.py)
   - Periodic temporary file cleanup.
4. [backend/services/queue_service.py](../backend/services/queue_service.py)
   - Unified async processing queue with concurrency control.
5. [backend/services/email_service.py](../backend/services/email_service.py)
   - Async SMTP email sender (confirmation + result with ZIP attachments).
6. [backend/services/download_token_service.py](../backend/services/download_token_service.py)
   - Generates secure download tokens for Web outputs.

### 2.4. Exporters & Renderers (`backend/export/`)
1. [backend/export/pandoc_exporter.py](../backend/export/pandoc_exporter.py)
   - Coordinates canonical validation, profile filtering, AST build, and renderer dispatch.
2. [backend/export/renderers/](../backend/export/renderers/)
   - Renderers for TXT, DOCX, PDF, HTML, and MP3 audio (via edge-tts).

### 2.5. Tools & Utilities (`backend/tools/`)
1. [backend/tools/logger.py](../backend/tools/logger.py)
   - loguru setup with file rotation and stderr logging.
2. [backend/tools/validators.py](../backend/tools/validators.py)
   - File extension and size validation.
3. [backend/tools/pdf_splitter.py](../backend/tools/pdf_splitter.py)
   - Multi-page PDF page splitting via pypdf.
4. [backend/tools/image_converter.py](../backend/tools/image_converter.py)
   - PDF page to PNG conversion via PyMuPDF.
5. [backend/tools/image_enhancer.py](../backend/tools/image_enhancer.py)
   - OpenCV deskew, CLAHE contrast, and denoise.
6. [backend/tools/text_processor.py](../backend/tools/text_processor.py)
   - Text normalization, paragraph merging, and Markdown parsing.
7. [backend/tools/image_tools.py](../backend/tools/image_tools.py)
   - Region cropping and image manipulation.
8. [backend/tools/prompt_tools.py](../backend/tools/prompt_tools.py)
   - Prompt loading and mode template resolution.

---

## 3. Frontend Interfaces (`frontend/`)

### 3.1. Telegram Interface (`frontend/telegram/`)
1. [frontend/telegram/bot.py](../frontend/telegram/bot.py)
   - Initializes aiogram Bot/Dispatcher, registers handlers, middlewares, and lifecycle hooks.
2. [frontend/telegram/handlers/start.py](../frontend/telegram/handlers/start.py)
   - Command handlers (/start, /help, /status, /health, /feedback, modes, /cancelar).
3. [frontend/telegram/handlers/document.py](../frontend/telegram/handlers/document.py)
   - Document/photo input handling, validation, queuing, and output delivery.
4. [frontend/telegram/handlers/errors.py](../frontend/telegram/handlers/errors.py)
   - Global exception handling in aiogram routing.
5. [frontend/telegram/adapters/status_tracker.py](../frontend/telegram/adapters/status_tracker.py)
   - Telegram progress bar and inline keyboard updater.
6. [frontend/telegram/adapters/file_service.py](../frontend/telegram/adapters/file_service.py)
   - File download/upload helpers for Telegram.

### 3.2. Web Interface (`frontend/web/`)
1. [frontend/web/app.py](../frontend/web/app.py)
   - FastAPI application providing Web UI upload forms, REST API endpoints, and download handlers.

### 3.3. CLI Interface (`frontend/cli/`)
1. [frontend/cli/run.py](../frontend/cli/run.py)
   - CLI execution script (`poetry run bot-acess`).

---

## 4. Automated Tests (`tests/`)

1. [tests/test_audit_validation.py](../tests/test_audit_validation.py)
2. [tests/test_canonical_pipeline.py](../tests/test_canonical_pipeline.py)
3. [tests/test_exporters.py](../tests/test_exporters.py)
4. [tests/test_pandoc_filters.py](../tests/test_pandoc_filters.py)
5. [tests/test_pipeline_validation.py](../tests/test_pipeline_validation.py)
6. [tests/test_renderers.py](../tests/test_renderers.py)
7. [tests/test_structure_parser.py](../tests/test_structure_parser.py)
8. [tests/test_validators.py](../tests/test_validators.py)

---

## Coverage and Alignment
- **`backend/`** contains all business logic (agents, AI, services, tools) with zero interface dependencies.
- **`frontend/`** contains only interface-specific adapters (Telegram aiogram, FastAPI web, CLI).
- The canonical document is the single source of truth for all exported formats.
