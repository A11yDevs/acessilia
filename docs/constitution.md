# Architectural Constitution

## 1. Purpose
Deliver document and image conversion to accessible formats through:
- **Deterministic extraction and planning** (PDDL-based task ordering and validation)
- **Multiagent AI processing** (Agno-coordinated specialized agents for vision, data, descriptions)
- High-quality descriptions in Brazilian Portuguese
- Simple Telegram-based user experience with progressive degradation on AI failures

## 2. Non-negotiable principles
1. Source-code alignment: every rule in this constitution must be traceable to real modules.
2. Accessibility first: all outputs must support screen readers and semantic structure.
3. Fault tolerance: the system must degrade gracefully with textual fallback when AI fails.
4. Local and configurable operation: behavior must be driven by environment variables and local folders.
5. Minimum observability: logs, conversion history, and task status must be available.
6. Local-first extraction: text-based PDFs should prefer deterministic local extraction before invoking AI.
7. Hybrid determinism and intelligence: the system combines deterministic planning (PDDL processing, manifesto generation) with AI-driven execution to ensure reliability and flexibility. Deterministic functions are the source of truth; LLMs provide interpretation and description.
8. Container-first validation: test suite must pass in Docker container (production-equivalent environment) before merge. Native environment testing is secondary and environment-specific.

## 3. Architectural quality rules
1. Layer separation (updated for PDDL + Agno multiagent architecture):
   
   a. **Interface Layer:**
      - Telegram handlers and middlewares
      - CLI endpoints (manifest, plan, run, benchmark commands)
      - Web FastAPI routes
   
   b. **Orchestration Layer:**
      - `core/execution/` – Executor agent; applies PDDL plans with Agno Workflow
      - `core/planning/` – PlannerAgent; generates PDDL problems and validates plans
      - `core/manifest/` – InformationalStructuralAgent; extracts processing manifesto
   
   c. **Agent Layer (Agno Multiagent):**
      - ReaderAgent (Python) – structural extraction via Docling/PyMuPDF
      - VisionAgent (Agno) – image descriptions
      - DataAgent (Agno) – tabular/formula text representation
      - EditorAgent (Python) – deduplication and accessibility tagging
   
   d. **Canonical Pipeline:**
      - `pipeline/` – canonical document construction and validation
      - `export/filters` – Pandoc filters for accessibility
      - `export/renderers` – deterministic output rendering
      - `schemas/` – JSON/PDDL schemas for manifesto, plan, execution report
   
   e. **Persistence & Support:**
      - `services/` – cache, queue, history, cleanup
      - `ai/` – Agno model registry and prompt templates
2. Centralized configuration in [config/settings.py](../config/settings.py).
3. Any potentially long-running operation must be asynchronous in bot runtime.
4. File validations must happen before the AI pipeline.
5. History persistence must register conversion start and finish.
6. The canonical document is the source of truth for every exported format.
7. Testing strategy:
   - Primary validation: pytest inside Docker container (production-equivalent)
   - Secondary validation: native environment (Python native syntax check only)
   - All tests must pass in container before merge (gate requirement)
   - Regression tests of existing agents must remain at or above current coverage

## 4. Domain contracts
1. Document processing lifecycle (extended for planning phase):
   - **Extraction Phase:** Document → ReaderAgent → processing-manifest.json
   - **Planning Phase:** manifesto + domain constraints → PlannerAgent → nominal-plan.json
   - **Execution Phase:** plan + manifesto → Executor (Agno Workflow) → execution-report.json
   - **Canonical Generation:** execution results → canonical document (accessible)
   - **Export Phase:** canonical document → renderers → output artifacts (txt/docx/pdf/html)
2. Processing manifest and plan contracts:
   - Processing manifest (1.1+) defines regions, types, and processing obligations
   - PDDL domain (v2.2+) encodes task dependencies and ordering constraints
   - Plan is deterministic output from planner (internal or fast-downward backend)
   - Execution report validates plan adherence and records task outcomes
3. Processing mode (detailed, medium, low, ocr) changes prompt and verbosity behavior.
4. Extraction is hybrid: local PDF text extraction first, then AI vision for scanned/no-text pages and image inputs.
5. Page and file cache are optimizations, not source of truth.
6. Renderers must only consume validated canonical data.
7. Planner invariants:
   - PDDL problem generation is deterministic (no LLM involvement)
   - Plan validation must succeed before execution
   - Fallback mode (deterministic extraction only) triggers on planner failure

## 5. Resilience and operational safety
1. Network retry for external channels (Telegram/OpenCode/Ollama).
2. Process lock in [run.py](../run.py) to prevent multiple instances on the same host.
3. Periodic temporary file cleanup to avoid uncontrolled disk growth.
4. Consistent shutdown with task status and history updates.
5. PDDL planning resilience:
   - Planner timeout: configurable TTL for plan generation; fallback to execution-without-plan if exceeded
   - Invalid problem: if manifesto → PDDL generation fails, log error and skip planning phase; execute deterministically
   - Planner crash: if external planner (fast-downward) fails, switch to internal planner backend

## 6. Architectural evolution
1. Pipeline changes must update diagrams in docs/sequence and docs/state_machine, plus the architecture overview docs.
2. Adding a new Agno agent or planning backend requires:
   - Agent class in `core/agents/` or `core/execution/`/`core/planning/`
   - Configuration in `config/settings.py` (model selector, timeouts)
   - Agent implementation consuming base `agno.Agent` class
   - Tool definitions (for deterministic functions like manifest extraction)
   - Dedicated test file validating agent inputs, outputs, and fallback behavior
   - Updates to `docs/proposta.md` (if architectural), `docs/modules.md`, `docs/classes.md`, and relevant sequence diagrams
   - If adding PDDL artifacts (new domain, new planner): update `schemas/` and `core/planning/domains/` plus `docs/pmv_agno_pddl.md`
3. PDDL/Planning changes (schemas, domain, planner backend):
   - Domain updates: modify `core/planning/domains/domain_vX.Y.pddl`, increment version
   - Schema changes: update `schemas/processing_manifest.schema.json`, `schemas/nominal_plan.schema.json`, `schemas/execution_report.schema.json`
   - Planner backend: register in `core/planning/models.py` (PlannerBackend enum)
   - Validation: run `pytest tests/test_pddl_planning.py` (plan generation) and `pytest tests/test_agno_executor.py` (execution)
   - Documentation: update `docs/pmv_agno_pddl.md` with new examples
4. Changing the canonical schema or renderers requires updates in [README.md](../README.md), [modules.md](modules.md), [tests.md](tests.md), and the PlantUML diagrams.
5. Accessibility regression is treated as a critical defect.
