# Design and Integration Patterns

## Identified Patterns

### 1. Canonical Document Pipeline
- Implementation: [backend/pipeline/canonical_builder.py](../backend/pipeline/canonical_builder.py), [backend/pipeline/validators.py](../backend/pipeline/validators.py), [backend/pipeline/structure_parser.py](../backend/pipeline/structure_parser.py), [backend/export/pandoc_exporter.py](../backend/export/pandoc_exporter.py)
- Role: normalize structured region payloads into a canonical document schema, validate structure and heading hierarchy, build intermediate AST, and dispatch to renderers.
- Benefit: deterministic output and a single source of truth for all output exporters.

### 2. Multi-Agent Pipeline Orchestration (legacy engine)
- Implementation: [backend/agents/orchestrator.py](../backend/agents/orchestrator.py) (`AccessibilityOrchestrator`), used when `PIPELINE_ENGINE=legacy` (the default). The `pddl` engine uses the planning-based orchestration in pattern 10 instead.
- Role: coordinates multi-agent lifecycle: local structural reading, parallel visual/data processing, text editing/deduplication, cache, history logging, and fallback.
- Benefit: centralizes business rules and isolates step responsibilities.

### 3. Strategy & Model Abstraction for AI (Agno)
- Implementation: [backend/ai/models/ai_client.py](../backend/ai/models/ai_client.py) (`get_agno_model()`)
- Strategies:
  - Ollama (local open-weights models like LLaVA/Qwen-VL)
  - OpenRouter (cloud API models like Claude/GPT-4o)
- Benefit: AI model provider can be switched seamlessly via environment configuration without changing agent logic.

### 4. Local-First Extraction Strategy
- Implementation: [backend/agents/reader_agent.py](../backend/agents/reader_agent.py) using PyMuPDF and Docling.
- Role:
  - perform local deterministic PDF text and region extraction first,
  - call Agno vision/data agents only for scanned pages, images, complex tables, and formulas,
  - maintain page-level and region-level caching.
- Benefit: lower latency, lower operational cost, and privacy preservation for text-native PDFs.

### 5. Multi-Agent Specialization
- Implementation:
  - [backend/agents/reader_agent.py](../backend/agents/reader_agent.py) (`ReaderAgent` - deterministic region splitting)
  - [backend/agents/vision_agent.py](../backend/agents/vision_agent.py) (`VisionAgent` - Agno LLM visual alt-text & audio descriptions)
  - [backend/agents/data_agent.py](../backend/agents/data_agent.py) (`DataAgent` - Agno LLM tables & math formulas)
  - [backend/agents/editor_agent.py](../backend/agents/editor_agent.py) (`EditorAgent` - deterministic sanitization, fingerprint deduplication, and accessibility tagging)
- Benefit: clean separation of concerns and parallel execution (`asyncio.gather`).

### 6. Export Adapters & Renderers
- Implementation: [backend/export/pandoc_exporter.py](../backend/export/pandoc_exporter.py) and renderers in `backend/export/renderers/` (TXT, DOCX, PDF, HTML, MP3 Audio via edge-tts).
- Benefit: identical canonical document produces multiple output formats cleanly.

### 7. In-Memory State Machine & Cooperative Cancellation
- Implementation: [backend/agents/state_manager.py](../backend/agents/state_manager.py)
- Observed states: `processing`, `done`, `error`, `cancelled`.
- Benefit: real-time progress tracking and cancellation support.

### 8. Cache-Aside Pattern
- Implementation:
  - global file cache in `backend/services/cache.py`
  - region cache in `backend/agents/orchestrator.py`
- Benefit: eliminates duplicate LLM calls for unchanged documents or images.

### 9. Single-Instance Execution & Process Lock
- Implementation: [frontend/run.py](../frontend/run.py)
- Benefit: prevents process collisions on the host machine.

### 10. Deterministic Planning with PDDL (optional engine)
- Implementation: [backend/core/manifest/](../backend/core/manifest/), [backend/core/planning/](../backend/core/planning/), [backend/core/execution/](../backend/core/execution/), coordinated by [backend/agents/pddl_orchestrator.py](../backend/agents/pddl_orchestrator.py). Active when `PIPELINE_ENGINE=pddl`.
- Role: separate *what to do* from *doing it*. A deterministic manifest describes the document's regions and obligations; a PDDL planner compiles it into a validated, ordered plan; an Agno Workflow executor applies the plan, calling the Vision/Data agents only where the plan requires. See [pmv_agno_pddl.md](pmv_agno_pddl.md).
- Benefit: task ordering and dependencies become explicit and auditable, and planning stays deterministic (no LLM writes PDDL) while AI is confined to description. Falls back to deterministic extraction if planning fails.

### 11. REST API with Interface Clients
- Implementation: [backend/api/](../backend/api/); clients in [frontend/clients/api_client.py](../frontend/clients/api_client.py), consumed by the Telegram bot and Web panel.
- Benefit: one place owns the queue and pipeline; every interface (API callers, Telegram, Web, CLI) is a thin client, so behavior stays consistent across surfaces.

---

## Architectural Evolution Roadmap

1. **Dynamic Smart Orchestration (Future Feature):**
   - The PDDL planning engine (pattern 10) is the first step toward explicit, deterministic task routing. The remaining goal is a dynamic router that also weighs document complexity, budget, and SLA to route between local Ollama models and cloud OpenRouter endpoints.
2. **Parallel Agent Scaling:**
   - Expand `asyncio.gather` execution to support distributed worker queues for high-volume document pipelines.
