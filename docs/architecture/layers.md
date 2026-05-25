# Layered Architecture

## Assessment
The project is organized predominantly in layers, with a clear runtime flow from input handling to orchestration, structured extraction, canonical transformation, and output generation.

It is not a strict layered architecture in the classic sense because some runtime and compatibility concerns cross layer boundaries for pragmatic reasons:
- the orchestrator coordinates both processing and infrastructure services;
- backward-compatible wrappers still exist under bot/exporters;
- some utilities are shared across multiple layers.

In practice, the codebase can be understood as a layered architecture with controlled cross-cutting services.

## Layer Map
1. Interface and entrypoints
   - ../../bot/main.py
   - ../../bot/handlers/start.py
   - ../../bot/handlers/document.py
   - ../../bot/handlers/errors.py
   - ../../bot/middlewares/pause_middleware.py

2. Application orchestration
   - ../../bot/agente_mestre.py
   - ../../bot/agents/state_manager.py
   - ../../bot/services/queue_service.py

3. Extraction and AI integration
   - ../../bot/agents/agente_unico.py
   - ../../bot/clients/opencode.py
   - ../../bot/clients/openrouter.py
   - ../../bot/prompts/
   - ../../pipeline/structure_parser.py

4. Canonical document layer
   - ../../pipeline/canonical_builder.py
   - ../../pipeline/sanitizer.py
   - ../../pipeline/validators.py
   - ../../pipeline/verbosity_manager.py
   - ../../pipeline/pandoc_ast_builder.py
   - ../../schemas/accessible_document.schema.json

5. Output and rendering
   - ../../exporters/pandoc_exporter.py
   - ../../renderers/txt_renderer.py
   - ../../renderers/docx_renderer.py
   - ../../renderers/pdf_renderer.py
   - ../../renderers/html_renderer.py
   - ../../bot/exporters/

6. Infrastructure and persistence
   - ../../bot/services/cache.py
   - ../../bot/services/history_service.py
   - ../../bot/services/cleanup_service.py
   - ../../bot/services/file_service.py
   - ../../bot/services/opencode_launcher.py
   - ../../config/settings.py

7. Cross-cutting utilities
   - ../../bot/utils/logger.py
   - ../../bot/utils/status_tracker.py
   - ../../bot/utils/validators.py
   - ../../bot/utils/pdf_splitter.py
   - ../../bot/utils/image_converter.py
   - ../../bot/utils/image_enhancer.py
   - ../../bot/utils/text_processor.py

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
1. bot/exporters still acts as a compatibility surface while the main export pipeline lives in ../../exporters/pandoc_exporter.py.
2. agente_mestre coordinates both application flow and infrastructure concerns such as cache/history access.
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