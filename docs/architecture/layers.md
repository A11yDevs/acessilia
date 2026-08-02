# Layered Architecture

## Assessment
The project is organized predominantly in layers, with a clear runtime flow from input handling to orchestration, structured extraction, canonical transformation, and output generation.

It is not a strict layered architecture in the classic sense because some runtime and compatibility concerns cross layer boundaries for pragmatic reasons:
- the orchestrator coordinates both processing and infrastructure services;
- backward-compatible wrappers still exist under backend/adapters/exporters;
- some utilities are shared across multiple layers.

In practice, the codebase can be understood as a layered architecture with controlled cross-cutting services.

## Layer Map
1. Interface and entrypoints
   - ../../frontend/run.py
   - ../../frontend/telegram/handlers/start.py
   - ../../frontend/telegram/handlers/document.py
   - ../../frontend/telegram/handlers/errors.py
   - ../../frontend/telegram/middlewares/pause_middleware.py

2. Application orchestration
   - ../../backend/service.py
   - ../../backend/agents/orchestrator.py
   - ../../backend/agents/state_manager.py
   - ../../backend/services/queue_service.py

3. Extraction and AI integration
   - ../../backend/agents/reader_agent.py
   - ../../backend/agents/vision_agent.py
   - ../../backend/agents/data_agent.py
   - ../../backend/agents/editor_agent.py
   - ../../backend/ai/models/ai_client.py
   - ../../backend/ai/prompts/
   - ../../backend/pipeline/structure_parser.py

4. Canonical document layer
   - ../../backend/pipeline/canonical_builder.py
   - ../../backend/pipeline/sanitizer.py
   - ../../backend/pipeline/validators.py
   - ../../backend/pipeline/verbosity_manager.py
   - ../../backend/pipeline/pandoc_ast_builder.py
   - ../schemas/accessible_document.schema.json

5. Output and rendering
   - ../../backend/export/pandoc_exporter.py
   - ../../backend/export/renderers/txt_renderer.py
   - ../../backend/export/renderers/docx_renderer.py
   - ../../backend/export/renderers/pdf_renderer.py
   - ../../backend/export/renderers/html_renderer.py
   - ../../backend/export/exporters/

6. Infrastructure and persistence
   - ../../backend/services/cache.py
   - ../../backend/services/history_service.py
   - ../../backend/services/cleanup_service.py
   - ../../frontend/telegram/adapters/file_service.py
   - ../../backend/config/settings.py

7. Cross-cutting utilities
   - ../../backend/tools/logger.py
   - ../../frontend/telegram/adapters/status_tracker.py
   - ../../backend/tools/validators.py
   - ../../backend/tools/pdf_splitter.py
   - ../../backend/tools/image_converter.py
   - ../../backend/tools/image_enhancer.py
   - ../../backend/tools/text_processor.py

## Intended Dependency Direction
The preferred dependency direction is top-down:

Interface -> Orchestration -> Extraction -> Canonical Document -> Output

Infrastructure and utilities support multiple layers but should not own business decisions.

## Why This Is Layered
- Input handling is isolated from document transformation logic.
- The orchestrator centralizes workflow control instead of embedding it in handlers.
- Extraction concerns are separated from canonical document validation and rendering.
- Output generation depends on the canonical representation rather than raw extraction text.

## Current Exceptions
1. backend/adapters/exporters still acts as a compatibility surface while the main export pipeline lives in ../../backend/export/pandoc_exporter.py.
2. The orchestrator (backend/service.py) coordinates both application flow and infrastructure concerns such as cache/history access.
3. Utility modules are shared broadly instead of being owned by a single layer.

## Architectural Conclusion
Yes: the project is currently organized in layers as its main architectural shape.

More precisely, it is a pragmatic layered architecture with:
- a clear top-down processing flow;
- a canonical document core;
- infrastructure and utility modules reused across layers;
- a few transitional compatibility points during the migration to the new architecture.

## Related Artifacts
- ../architecture.md
- layers.puml
- architecture.puml
