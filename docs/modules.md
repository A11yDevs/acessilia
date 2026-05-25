# Modules

## Objective
Map all Python modules in the project by functional area, including main responsibility and alignment notes.

## 1. Main runtime
1. [run.py](../run.py)
   - Application bootstrap, process lock, startup, and shutdown.
2. [bot/main.py](../bot/main.py)
   - Creates bot/dispatcher, registers routers and middlewares, runs polling.
3. [bot/__main__.py](../bot/__main__.py)
   - Alternative entry point to run bot as a package.
4. [bot/__init__.py](../bot/__init__.py), [config/__init__.py](../config/__init__.py), [tests/__init__.py](../tests/__init__.py), and other __init__.py files
   - Package markers and export points.

## 2. Configuration
1. [config/settings.py](../config/settings.py)
   - Settings definition, cross-platform paths, and global parameters.

## 3. Handlers and middleware
1. [bot/handlers/start.py](../bot/handlers/start.py)
   - UX and operation commands (/start, /help, /status, /health, /feedback, etc).
2. [bot/handlers/document.py](../bot/handlers/document.py)
   - Document/photo input, validation, processing, and output delivery.
3. [bot/handlers/errors.py](../bot/handlers/errors.py)
   - Global exception handling in routing.
4. [bot/middlewares/pause_middleware.py](../bot/middlewares/pause_middleware.py)
   - Paused/active chat control.

## 4. Orchestration and agents
1. [bot/agente_mestre.py](../bot/agente_mestre.py)
   - Orchestrates full conversion lifecycle and fallback.
2. [bot/agents/agente_unico.py](../bot/agents/agente_unico.py)
   - Page-by-page hybrid extraction pipeline (local PyMuPDF first, multimodal AI when needed).
3. [bot/agents/state_manager.py](../bot/agents/state_manager.py)
   - Task state and cooperative cancellation.
4. [bot/agents/__init__.py](../bot/agents/__init__.py)
   - Agent package initialization.

## 5. AI clients
1. [bot/clients/opencode.py](../bot/clients/opencode.py)
   - Session-based OpenCode client used when AI_CLIENT=opencode.
2. [bot/clients/openrouter.py](../bot/clients/openrouter.py)
   - Stateless OpenRouter client used when AI_CLIENT=openrouter.
3. [bot/clients/__init__.py](../bot/clients/__init__.py)
   - Re-exports available clients.

## 6. Infrastructure services
1. [bot/services/file_service.py](../bot/services/file_service.py)
   - File download/upload in Telegram context.
2. [bot/services/cache.py](../bot/services/cache.py)
   - Local file-hash-based cache.
3. [bot/services/history_service.py](../bot/services/history_service.py)
   - SQLite persistence for conversions and OCR audit tables.
4. [bot/services/cleanup_service.py](../bot/services/cleanup_service.py)
   - Periodic temporary file cleanup.
5. [bot/services/queue_service.py](../bot/services/queue_service.py)
   - Processing queue with concurrency limit.
6. [bot/services/opencode_launcher.py](../bot/services/opencode_launcher.py)
   - OpenCode startup and availability checks.
7. [bot/services/__init__.py](../bot/services/__init__.py)
   - Package initialization.

## 7. Exporters
1. [exporters/pandoc_exporter.py](../exporters/pandoc_exporter.py)
   - Canonical export coordinator, validation gate, AST build, and renderer dispatch.
1. [bot/exporters/txt_exporter.py](../bot/exporters/txt_exporter.py)
2. [bot/exporters/docx_exporter.py](../bot/exporters/docx_exporter.py)
3. [bot/exporters/pdf_exporter.py](../bot/exporters/pdf_exporter.py)
4. [bot/exporters/__init__.py](../bot/exporters/__init__.py)

## 8. Canonical pipeline
1. [pipeline/canonical_builder.py](../pipeline/canonical_builder.py)
   - Builds the canonical document from raw text or structured payloads.
2. [pipeline/structure_parser.py](../pipeline/structure_parser.py)
   - Shared text-to-block parser used by the agent and fallback builder path.
3. [pipeline/sanitizer.py](../pipeline/sanitizer.py)
   - Removes prompt leaks, Markdown artifacts, and normalizes text.
4. [pipeline/validators.py](../pipeline/validators.py)
   - Validates canonical shape, export profiles, and output text.
5. [pipeline/verbosity_manager.py](../pipeline/verbosity_manager.py)
   - Maps modes to verbosity and filters blocks for each profile.
6. [pipeline/pandoc_ast_builder.py](../pipeline/pandoc_ast_builder.py)
   - Builds the intermediate AST consumed by renderers.
7. [filters/pandoc_filters.py](../filters/pandoc_filters.py)
   - Strips internal audit data and applies profile-level block filtering.
8. [schemas/accessible_document.schema.json](../schemas/accessible_document.schema.json)
   - JSON Schema for the canonical document.

## 9. Renderers
1. [renderers/txt_renderer.py](../renderers/txt_renderer.py)
2. [renderers/docx_renderer.py](../renderers/docx_renderer.py)
3. [renderers/pdf_renderer.py](../renderers/pdf_renderer.py)
4. [renderers/html_renderer.py](../renderers/html_renderer.py)

## 10. Utilities
1. [bot/utils/logger.py](../bot/utils/logger.py)
2. [bot/utils/validators.py](../bot/utils/validators.py)
3. [bot/utils/status_tracker.py](../bot/utils/status_tracker.py)
4. [bot/utils/pdf_splitter.py](../bot/utils/pdf_splitter.py)
5. [bot/utils/image_converter.py](../bot/utils/image_converter.py)
6. [bot/utils/image_enhancer.py](../bot/utils/image_enhancer.py)
7. [bot/utils/text_processor.py](../bot/utils/text_processor.py)
8. [bot/utils/__init__.py](../bot/utils/__init__.py)

## 11. AI prompts
1. [bot/prompts/baixo.txt](../bot/prompts/baixo.txt)
2. [bot/prompts/medio.txt](../bot/prompts/medio.txt)
3. [bot/prompts/detalhado.txt](../bot/prompts/detalhado.txt)
4. [bot/prompts/ocr.txt](../bot/prompts/ocr.txt)

## 12. Automated tests (pytest)
1. [tests/test_pandoc_filters.py](../tests/test_pandoc_filters.py)
2. [tests/test_renderers.py](../tests/test_renderers.py)
3. [tests/test_pipeline_validation.py](../tests/test_pipeline_validation.py)
4. [tests/test_structure_parser.py](../tests/test_structure_parser.py)
5. [tests/test_validators.py](../tests/test_validators.py)
6. [tests/test_exporters.py](../tests/test_exporters.py)
7. [tests/test_openrouter_client.py](../tests/test_openrouter_client.py)

## 13. Support and diagnostic scripts (root)
1. [check_api.py](../check_api.py)
2. [check_doc.py](../check_doc.py)
3. [check_doc2.py](../check_doc2.py)
4. [extract_api.py](../extract_api.py)
5. [extract_full.py](../extract_full.py)
6. [extract_paths.py](../extract_paths.py)
7. [full_extract.py](../full_extract.py)
8. [generate_api_doc.py](../generate_api_doc.py)
9. [list_openrouter_models.py](../list_openrouter_models.py)
10. [list_sections.py](../list_sections.py)
11. [test_opencode_client.py](../test_opencode_client.py)
12. [test_openrouter_direct.py](../test_openrouter_direct.py)

## 14. Root configuration/documentation artifacts
1. [requirements.txt](../requirements.txt)
2. [README.md](../README.md)
3. [opencode_api_doc.txt](../opencode_api_doc.txt)
4. [prompt.txt](../prompt.txt)

## Coverage and alignment
- Functional coverage: runtime, AI pipeline, canonical document pipeline, persistence, exports, utilities, tests, and support scripts.
- The export path now depends on the canonical builder, filters, AST builder, and deterministic renderers.
- Runtime extraction path is hybrid: local text extraction for text-based PDFs, AI vision for scanned/no-text pages and image inputs.
