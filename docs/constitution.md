# Architectural Constitution

## 1. Purpose
Deliver document and image conversion to accessible formats, focused on high-quality descriptions in Brazilian Portuguese and a simple Telegram-based user experience.

## 2. Non-negotiable principles
1. Source-code alignment: every rule in this constitution must be traceable to real modules.
2. Accessibility first: all outputs must support screen readers and semantic structure.
3. Fault tolerance: the system must degrade gracefully with textual fallback when AI fails.
4. Local and configurable operation: behavior must be driven by environment variables and local folders.
5. Minimum observability: logs, conversion history, and task status must be available.
6. Local-first extraction: text-based PDFs should prefer deterministic local extraction before invoking AI.

## 3. Architectural quality rules
1. Layer separation:
   - Telegram interface in handlers and middlewares.
   - Orchestration in [backend/service.py](../backend/service.py) and [backend/agents/orchestrator.py](../backend/agents/orchestrator.py).
   - AI integration in [backend/agents](../backend/agents) and [backend/ai/models](../backend/ai/models).
   - Canonical pipeline in [backend/pipeline](../backend/pipeline), [backend/export/filters](../backend/export/filters), and [schemas](schemas).
   - Persistence in [backend/services](../backend/services).
   - Output adapters in [backend/export/pandoc_exporter.py](../backend/export/pandoc_exporter.py), [backend/export/renderers](../backend/export/renderers), and [backend/export/exporters](../backend/export/exporters).
2. Centralized configuration in [backend/config/settings.py](../backend/config/settings.py).
3. Any potentially long-running operation must be asynchronous in bot runtime.
4. File validations must happen before the AI pipeline.
5. History persistence must register conversion start and finish.
6. The canonical document is the source of truth for every exported format.

## 4. Domain contracts
1. A task has a lifecycle controlled by state_manager.
2. A conversion produces a canonical document and up to five output artifacts (txt/docx/pdf/html/mp3).
3. Processing mode (detailed, medium, low, ocr) changes prompt and verbosity behavior.
4. Extraction is hybrid: local PDF text extraction first, then AI vision for scanned/no-text pages and image inputs.
5. Page and file cache are optimizations, not source of truth.
6. Renderers must only consume validated canonical data.

## 5. Resilience and operational safety
1. Network retry for external channels (Telegram/OpenRouter/Ollama).
2. Process lock in [frontend/run.py](../frontend/run.py) to prevent multiple instances on the same host.
3. Periodic temporary file cleanup to avoid uncontrolled disk growth.
4. Consistent shutdown with task status and history updates.

## 6. Architectural evolution
1. Pipeline changes must update diagrams in docs/sequence and docs/state_machine, plus the architecture overview docs.
2. Adding a new AI provider requires:
   - configuration in Settings,
   - model setup in [backend/ai/models/ai_client.py](../backend/ai/models/ai_client.py),
   - updates in [modules.md](modules.md), [classes.md](classes.md), and [architecture.puml](architecture/architecture.puml).
3. Changing the canonical schema or renderers requires updates in [README.md](../README.md), [modules.md](modules.md), [tests/README.md](../tests/README.md), and the PlantUML diagrams.
4. Accessibility regression is treated as a critical defect.
