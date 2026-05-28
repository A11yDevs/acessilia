# Architecture

## Overview
The system is an asynchronous Telegram bot for converting documents into accessible formats through a hybrid extraction flow (local-first with PyMuPDF plus conditional AI vision), a canonical document pipeline, deterministic validation, and format-specific renderers.

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

3. AI and structured extraction pipeline
   - [bot/agents/agente_unico.py](../bot/agents/agente_unico.py): processes PDF/image page by page and applies a hybrid strategy:
     - extracts text locally from PDF pages with PyMuPDF when text is available,
     - calls AI vision only for scanned/no-text pages or direct image inputs,
     - optionally describes embedded images in text-based PDFs.
   - [bot/clients/opencode.py](../bot/clients/opencode.py): HTTP client for OpenCode server with session and retry.
   - [bot/clients/ollama.py](../bot/clients/ollama.py): HTTP client for Ollama API with exponential backoff.
   - [bot/prompts](../bot/prompts): prompts by detail mode.
   - [pipeline/structure_parser.py](../pipeline/structure_parser.py): shared text-to-block parser used by the agent and canonical builder.

4. Canonical document pipeline
   - [pipeline/canonical_builder.py](../pipeline/canonical_builder.py): builds the canonical document and sections tree.
   - [pipeline/sanitizer.py](../pipeline/sanitizer.py): cleans raw text and removes Markdown/prompt leaks.
   - [pipeline/validators.py](../pipeline/validators.py): validates schema, headings, links, markdown artifacts, and output text.
   - [pipeline/verbosity_manager.py](../pipeline/verbosity_manager.py): defines output profiles and block filtering rules.
   - [pipeline/pandoc_ast_builder.py](../pipeline/pandoc_ast_builder.py): creates the intermediate AST.
   - [schemas/accessible_document.schema.json](../schemas/accessible_document.schema.json): JSON Schema for the canonical document.

5. Output and format adapters
   - [exporters/pandoc_exporter.py](../exporters/pandoc_exporter.py): single export coordinator for validation, filtering, AST build, and renderer dispatch.
   - [renderers/txt_renderer.py](../renderers/txt_renderer.py)
   - [renderers/docx_renderer.py](../renderers/docx_renderer.py)
   - [renderers/pdf_renderer.py](../renderers/pdf_renderer.py)
   - [renderers/html_renderer.py](../renderers/html_renderer.py)
   - [bot/exporters/txt_exporter.py](../bot/exporters/txt_exporter.py), [bot/exporters/docx_exporter.py](../bot/exporters/docx_exporter.py), [bot/exporters/pdf_exporter.py](../bot/exporters/pdf_exporter.py): backward-compatible wrappers.

6. Persistence and local infrastructure
   - [bot/services/cache.py](../bot/services/cache.py): text cache in temp/cache.
   - [bot/services/history_service.py](../bot/services/history_service.py): SQLite in data/history.db for conversion history and OCR tables.
   - [bot/services/cleanup_service.py](../bot/services/cleanup_service.py): periodic cleanup of temporary files.
   - [bot/services/opencode_launcher.py](../bot/services/opencode_launcher.py): OpenCode bootstrap and health check at startup.
   - [config/settings.py](../config/settings.py): centralized configuration and runtime directories.

7. Cross-cutting utilities
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
   - extracts local text via PyMuPDF,
   - when local text is insufficient, converts/compresses/enhances image and sends to AI vision,
   - stores per-page structured payloads and cache.
6. Structured page payloads are combined into the canonical document.
7. Canonical validators check schema, heading hierarchy, links and output safety.
8. The canonical document is converted to a Pandoc-like AST and then rendered by format-specific renderers.
9. Files are sent to the user with retry for rate-limits and task history/state are finalized.

## External dependencies
- Telegram Bot API (via aiogram).
- Local OpenCode (when AI_CLIENT=opencode).
- Ollama API (when AI_CLIENT=ollama).
- Processing libraries: PyMuPDF, Pillow, opencv-python, reportlab, python-docx.
- Tesseract command is configurable in Settings, but not used in the current runtime extraction path.

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
1. The canonical document is the source of truth; renderers should not infer structure from raw Markdown.
2. [bot/exporters](../bot/exporters) remain compatibility wrappers while [exporters/pandoc_exporter.py](../exporters/pandoc_exporter.py) owns the export pipeline.
3. process_with_queue exists, but current handler flow calls process directly.
4. opencode_launcher.start_serve uses opencode.cmd (more Windows-oriented), requiring validation on other environments.
5. settings.pymupdf_text_threshold controls when a page stays local versus when AI vision is triggered.

## Related diagrams
- [Architecture PlantUML](architecture/architecture.puml)
- [Layered Architecture](architecture/layers.md)
- [Layers PlantUML](architecture/layers.puml)
- [Sequence PlantUML](sequence/document_processing_sequence.puml)
- [State PlantUML](state_machine/task_state_machine.puml)
hine.puml)
