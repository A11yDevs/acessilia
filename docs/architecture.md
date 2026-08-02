# Architecture

## Overview
The system converts documents into accessible formats through a multi-agent extraction pipeline (local-first structural extraction with PyMuPDF/Docling plus Agno-powered multimodal AI vision and data agents), a canonical document pipeline, deterministic validation, and format-specific renderers. The architecture is modular: **backend/** contains all business logic independent of any interface, **frontend/** contains pluggable user interfaces (Telegram, Web, CLI), and **infra/** manages containerization with Docker.

---

## Layers

### 0. Backend (`backend/`) — Interface-agnostic business logic and AI pipeline

#### 0.1. Multi-Agent Pipeline & Orchestration (`backend/agents/`)
- [backend/agents/orchestrator.py](../backend/agents/orchestrator.py): `AccessibilityOrchestrator` coordinates the multi-agent execution pipeline, cache lookup, task state, history, and status callbacks.
- [backend/agents/reader_agent.py](../backend/agents/reader_agent.py): `ReaderAgent` performs local-first PDF/image structural parsing (via PyMuPDF or Docling), splits pages, and classifies content regions (image, table, formula, text).
- [backend/agents/vision_agent.py](../backend/agents/vision_agent.py): `VisionAgent` utilizes Agno (`agno.agent.Agent`) and LLM multimodal capabilities (`agno.media.Image`) to produce detailed alt-text and audio descriptions for visual elements and scanned pages.
- [backend/agents/data_agent.py](../backend/agents/data_agent.py): `DataAgent` utilizes Agno (`agno.agent.Agent`) and LLM capabilities to convert complex tables and mathematical formulas into structured Markdown and LaTeX representations.
- [backend/agents/editor_agent.py](../backend/agents/editor_agent.py): `EditorAgent` sanitizes content, applies semantic/temporal deduplication via MD5 fingerprints, and inserts accessibility tags into the final document structure.
- [backend/agents/state_manager.py](../backend/agents/state_manager.py): in-memory task state machine with cooperative cancellation support.
- [backend/agents/types.py](../backend/agents/types.py): shared data contracts and task types (`RegionTask`).

#### 0.2. AI Client Integration (`backend/ai/`)
- [backend/ai/models/ai_client.py](../backend/ai/models/ai_client.py): central `get_agno_model()` initializer that instantiates Agno Model wrappers for Ollama or OpenRouter based on environment settings.

#### 0.3. Infrastructure Services (`backend/services/`)
- [backend/services/cache.py](../backend/services/cache.py): file-hash-based text cache in `temp/cache`.
- [backend/services/history_service.py](../backend/services/history_service.py): MariaDB/SQLite persistence for conversions and audit logs in `data/history.db`.
- [backend/services/queue_service.py](../backend/services/queue_service.py): unified async processing queue with concurrency limits.
- [backend/services/cleanup_service.py](../backend/services/cleanup_service.py): periodic cleanup of temporary files.
- [backend/services/email_service.py](../backend/services/email_service.py): async SMTP email sender (confirmation + result with ZIP attachments).
- [backend/services/download_token_service.py](../backend/services/download_token_service.py): token generation for secure Web download links.

#### 0.4. Domain Tools & Utilities (`backend/tools/`)
- [backend/tools/logger.py](../backend/tools/logger.py): centralized loguru logger setup.
- [backend/tools/validators.py](../backend/tools/validators.py): file extension and size validation.
- [backend/tools/pdf_splitter.py](../backend/tools/pdf_splitter.py): single-page PDF splitter.
- [backend/tools/image_converter.py](../backend/tools/image_converter.py): PDF page to PNG conversion.
- [backend/tools/image_enhancer.py](../backend/tools/image_enhancer.py): OpenCV deskew, CLAHE contrast, and denoise for scanned pages.
- [backend/tools/text_processor.py](../backend/tools/text_processor.py): text normalization and Markdown parsing.
- [backend/tools/image_tools.py](../backend/tools/image_tools.py): image cropping and region extraction.
- [backend/tools/prompt_tools.py](../backend/tools/prompt_tools.py): prompt loader and template resolver.

---

### 1. Frontend (`frontend/`) — Pluggable User Interfaces

#### Telegram Bot (`frontend/telegram/`)
- [frontend/telegram/bot.py](../frontend/telegram/bot.py): initializes aiogram Bot/Dispatcher, registers routers, middlewares, and lifecycle hooks.
- [frontend/telegram/handlers/start.py](../frontend/telegram/handlers/start.py): control commands (/start, /help, /status, /health, /feedback, modes, /cancelar).
- [frontend/telegram/handlers/document.py](../frontend/telegram/handlers/document.py): receives files/photos, validates, triggers processing, sends outputs.
- [frontend/telegram/handlers/errors.py](../frontend/telegram/handlers/errors.py): global exception handling.
- [frontend/telegram/adapters/status_tracker.py](../frontend/telegram/adapters/status_tracker.py): Telegram-specific progress bar.
- [frontend/telegram/adapters/file_service.py](../frontend/telegram/adapters/file_service.py): Telegram file download/upload helpers.

#### Web Interface & API (`frontend/web/`)
- [frontend/web/app.py](../frontend/web/app.py): FastAPI application with file upload forms, REST API endpoints, and processing status endpoints.

#### Command Line Interface (`frontend/cli/`)
- [frontend/cli/run.py](../frontend/cli/run.py): CLI entrypoint for batch processing and standalone execution.

---

### 2. Canonical Document & Export Pipeline (`backend/pipeline/`, `backend/export/`)

- [backend/pipeline/canonical_builder.py](../backend/pipeline/canonical_builder.py): builds the canonical document and sections tree.
- [backend/pipeline/sanitizer.py](../backend/pipeline/sanitizer.py): cleans raw text, removes prompt leaks and Markdown artifacts.
- [backend/pipeline/structure_parser.py](../backend/pipeline/structure_parser.py): shared text-to-block parser.
- [backend/pipeline/validators.py](../backend/pipeline/validators.py): validates schema, heading hierarchy, links, and output text; `audit_canonical_document` classifies structural and accessibility issues as `BLOCKER` or `WARNING`.
- [backend/export/pandoc_exporter.py](../backend/export/pandoc_exporter.py): single export coordinator for validation, filtering, AST build, and renderer dispatch; acts as a deterministic gatekeeper that halts export when the audit returns any `BLOCKER`.
- [backend/export/renderers/](../backend/export/renderers/): renderers for TXT, DOCX, PDF, HTML, and MP3 Audio (via edge-tts).

---

## Layering & Dependency Direction

The codebase follows a pragmatic layered architecture with a top-down flow: Interface → Orchestration → Extraction → Canonical Document → Output. Infrastructure services and shared tools support multiple layers but do not own business decisions. A few controlled exceptions exist: `backend/adapters/exporters` is a thin compatibility wrapper over `backend/export`, and the orchestrator coordinates both processing and infrastructure concerns (cache, history).

---

## Main Processing Flow

1. User submits a document via Telegram, Web UI, or CLI.
2. The interface handler validates the file extension and size.
3. The file is saved and enqueued in `ProcessingQueue`.
4. The worker dequeues the task and invokes `AccessibilityOrchestrator.process()`:
   - Registers task in `StateManager` and checks local text cache.
   - **`ReaderAgent`** splits pages, extracts local text (PyMuPDF/Docling), and classifies regions (images, tables, formulas, text).
   - **`VisionAgent`** and **`DataAgent`** run in parallel to describe visual elements and structure data using Agno `Agent` instances.
   - **`EditorAgent`** sanitizes results, applies deduplicação via fingerprints, and inserts accessibility tags into the final canonical structure.
5. Canonical validators verify schema adherence, heading hierarchy, and output safety.
6. Format renderers build output artifacts (TXT, DOCX, PDF, HTML, MP3).
7. Output files are packaged and delivered to the user (via Telegram message, Web download link, or email).

---

## Interface Activation

The `ENABLED_INTERFACES` environment variable controls which interfaces start at boot:
- `"telegram,web"` (default): starts both Telegram polling and Web server.
- `"web"`: starts only the FastAPI Web server.
- `"telegram"`: starts only the Telegram bot.

---

## External Dependencies

- **Agno Framework:** multi-agent orchestration and unified multimodal LLM interface.
- **AI Providers:** Ollama API (local models like LLaVA/Qwen-VL) or OpenRouter API (cloud models like Claude/GPT-4o).
- **Processing Libraries:** PyMuPDF, Docling, Pillow, OpenCV, reportlab, python-docx, pypdf, edge-tts, aiogram, FastAPI.

---

## Key Architectural Decisions

1. **`backend/` Interface Independence:** `backend/` has zero dependencies on interface-specific frameworks (no aiogram, no FastAPI).
2. **Modular Multi-Agent Architecture:** Separates structural reading, visual description, data formatting, and text editing into distinct agents.
3. **Canonical Document Source of Truth:** All renderers consume the validated canonical document schema to guarantee screen reader compatibility.
