# Architectural Constitution

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](constitution.pt-br.md)

- **Version:** 2.0.0 (2026-10-18). See the [changelog](#9-changelog) for how
  versions are numbered.

## 1. Purpose
Deliver document and image conversion to accessible formats through:
- **Deterministic extraction and planning** (PDDL-based task ordering and validation)
- **Multiagent AI processing** (Agno-coordinated specialized agents for vision, data, descriptions)
- High-quality descriptions in US English or Brazilian Portuguese (determined by the user's locale)
- Simple Telegram-based user experience with progressive degradation on AI failures

## 2. Non-negotiable principles
1. Source-code alignment: every rule in this constitution must be traceable to real modules.
2. Accessibility first: all outputs must support screen readers and semantic structure.
3. Fault tolerance: the system must degrade gracefully with textual fallback when AI fails. Degradation is a visible, documented business decision. An operational capability never falls back silently to a different implementation (principles P4 and P6).
4. Configurable operation: behavior must be driven by environment variables and local folders. Configuration selects where capabilities run (for example the Toolbox endpoint); it does not imply local execution (P4).
5. Deterministic-first extraction: text-based PDFs should prefer deterministic extraction before invoking AI. Deterministic extraction runs as a Toolbox capability or a docstruct algorithm, not as a local operational executor in the core (P4).
6. Hybrid determinism and intelligence: the system combines deterministic planning (PDDL processing, manifesto generation) with AI-driven execution to ensure reliability and flexibility. Deterministic functions are the source of truth; LLMs provide interpretation and description.
7. Container-first validation: test suite must pass in Docker container (production-equivalent environment) before merge. Native environment testing is secondary and environment-specific.
8. **English-first documentation with Brazilian Portuguese as official secondary language**: all source code (identifiers, comments, docstrings, log messages), Markdown documentation, issues, pull requests, and commit messages must be written in English — the mandatory, authoritative language. Brazilian Portuguese is the official secondary language: desirable for all documentation, and every `*.pt-br.md` mirror must be updated in the same PR whenever its English source changes. The English version is authoritative in case of divergence. Translation and support for other languages is an important secondary goal (internationalization/i18n) aimed at a broad, inclusive audience; localized content for other languages is welcome but never blocks a merge. User-facing content (Telegram messages, rendered output, prompts for the AI models) must be localized according to the user's locale — including English and Brazilian Portuguese, and extended to other languages as the i18n effort grows. Educational materials are a priority domain for internationalization: they should be produced in the audience's language whenever possible, with English and Brazilian Portuguese as the primary supported languages.

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
      - ReaderAgent (Python) – structural extraction through Toolbox capabilities (Docling, MinerU…); its remaining in-process PyMuPDF use is a tracked deviation ([ADR-0003](adr/0003-remote-only-operational-capabilities.md))
      - VisionAgent (Agno) – image descriptions
      - DataAgent (Agno) – tabular/formula text representation
      - EditorAgent (Python) – deduplication and accessibility tagging
   
   d. **Canonical Pipeline:**
      - `pipeline/` – canonical document construction and validation
      - `export/filters` – Pandoc AST filters for accessibility (pure transforms from docstruct; Pandoc itself runs in the Toolbox)
      - `export/renderers` – deterministic output rendering
      - `schemas/` – JSON/PDDL schemas for manifesto, plan, execution report
   
   e. **Persistence & Support:**
      - `services/` – cache, queue, history, cleanup
      - `ai/` – Agno model registry and prompt templates
2. Centralized configuration in [backend/config/settings.py](../backend/config/settings.py).
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
   - **Export Phase:** canonical document → renderers and export adapters → output artifacts (txt/docx/pdf/pdf_ua/html/mp3), packaged as a zip
2. Processing manifest and plan contracts:
   - Processing manifest (1.1+) defines regions, types, and processing obligations
   - PDDL domain (v2.2+) encodes task dependencies and ordering constraints
   - Plan is deterministic output from planner (internal or fast-downward backend)
   - Execution report validates plan adherence and records task outcomes
3. Processing mode changes prompt and verbosity behavior. The accepted values are `detalhado`, `medio` (with `normal` as an alias), `baixo` and `ocr`; an unknown value falls back to `medio`. They map to prompts in `backend/ai/prompts` and to verbosity profiles in `backend/pipeline/verbosity_manager.py`.
4. Extraction is hybrid: deterministic text extraction first, then AI vision for scanned/no-text pages and image inputs (see principle 2.5).
5. Page and file cache are optimizations, not source of truth.
6. Renderers must only consume validated canonical data.
7. Planner invariants:
   - PDDL problem generation is deterministic (no LLM involvement)
   - Plan validation must succeed before execution
   - Fallback mode (deterministic extraction only) triggers on planner failure

## 5. Resilience and operational safety
1. Network retry for external channels (Telegram/OpenRouter/Ollama).
2. Process lock in [frontend/run.py](../frontend/run.py) to prevent multiple instances on the same host.
3. Periodic temporary file cleanup to avoid uncontrolled disk growth.
4. Consistent shutdown with task status and history updates.
5. PDDL planning resilience:
   - Planner timeout: configurable TTL for plan generation; fallback to execution-without-plan if exceeded
   - Invalid problem: if manifesto → PDDL generation fails, log error and skip planning phase; execute deterministically
   - Planner crash: if external planner (fast-downward) fails, switch to internal planner backend
6. Toolbox unavailability: availability comes from Toolbox replicas behind a load balancer, with bounded SDK retries for idempotent calls ([ADR-0006](adr/0006-availability-and-failover.md)). When a capability stays unavailable, the step fails or degrades visibly, and the cause is recorded in the job; there is no local fallback.

## 6. Architectural evolution
1. Pipeline changes must update diagrams in docs/sequence and docs/state_machine, plus the architecture overview docs.
2. Adding a new Agno agent or planning backend requires:
   - Agent class in `core/agents/` or `core/execution/`/`core/planning/`
   - Configuration in `config/settings.py` (model selector, timeouts)
   - Agent implementation consuming base `agno.Agent` class
   - Tool definitions (for deterministic functions like manifest extraction)
   - Dedicated test file validating agent inputs, outputs, and fallback behavior
   - Updates to [architecture.md](architecture.md) and [patterns.md](patterns.md), and relevant sequence diagrams
   - If adding PDDL artifacts (new domain, new planner): update `schemas/` and `core/planning/domains/` plus `docs/pmv_agno_pddl.md`
3. PDDL/Planning changes (schemas, domain, planner backend):
   - Domain updates: modify `core/planning/domains/domain_vX.Y.pddl`, increment version
   - Schema changes: update `schemas/processing_manifest.schema.json`, `schemas/nominal_plan.schema.json`, `schemas/execution_report.schema.json`
   - Planner backend: register in `core/planning/models.py` (PlannerBackend enum)
   - Validation: run `pytest tests/test_pddl_planning.py` (plan generation) and `pytest tests/test_agno_executor.py` (execution)
   - Documentation: update `docs/pmv_agno_pddl.md` with new examples
4. Changing the canonical schema or renderers requires updates in [README.md](../README.md), [architecture.md](architecture.md), [tests/README.md](../tests/README.md), and the PlantUML diagrams.
5. Accessibility regression is treated as a critical defect.
6. Adding a Toolbox capability or provider follows [toolbox_integration.md](toolbox_integration.md) §4, and decides where each piece of code goes with the guide in [ADR-0002](adr/0002-component-responsibilities.md#decision).
7. A decision that changes responsibilities or dependencies between the core, the SDK, docstruct and the Toolbox, changes a public contract, or makes an exception to section 7, is recorded as an ADR in [docs/adr/](adr/README.md) before or with the change.

## 7. Ecosystem architecture principles

These principles govern how the four components of the ecosystem divide the
work: the core (`backend/`), the SDK (`libs/sdk`), docstruct (`libs/docstruct`)
and the [Acessilia Toolbox](https://github.com/A11yDevs/acessilia-toolbox). Each
one links to the ADR that details it and says how compliance is checked. An
exception requires an ADR that states its justification, scope, owner and exit
criterion ([ADR process](adr/README.md#process)); it is reviewed by the owners
of the affected components.

**In one sentence:** the core decides and orchestrates; the SDK provides
interfaces and access; docstruct implements reusable structural algorithms; the
Toolbox executes operational capabilities.

1. **P1 — One owner per functionality.**
   - **Rule:** each functionality has one architectural owner and one
     reference implementation. Python, REST and MCP interfaces may expose the
     same implementation; components reuse shared libraries instead of copying
     code.
   - **Detail:** [ADR-0002](adr/0002-component-responsibilities.md).
   - **Checked by:** review, and the duplication inventory of #152.
2. **P2 — Separation of responsibilities.**
   - **Rule:** the core holds agents, planning, strategies, policies and
     flows. The SDK holds contracts, clients, adapters, artifact references and
     access to reusable libraries, without mandatory heavy dependencies.
     docstruct holds deterministic, infrastructure-free structural algorithms.
     The Toolbox holds providers, conversion, rendering, OCR, validation,
     artifacts, jobs, sidecars and REST/MCP interfaces.
   - **Detail:** [ADR-0002](adr/0002-component-responsibilities.md).
   - **Checked by:** review, using the "where does new code go?" guide.
3. **P3 — Directional dependencies.**
   - **Rule:** core → SDK, docstruct; SDK → docstruct and the Toolbox's
     published contract; Toolbox → docstruct; docstruct → nothing in the
     ecosystem. No circular dependencies, and no dependency on another
     component's internals.
   - **Detail:** [ADR-0002](adr/0002-component-responsibilities.md).
   - **Checked by:** `tests/test_architecture_layers.py`,
     `libs/docstruct/tests/test_purity.py` and `libs/sdk/tests/test_purity.py`.
4. **P4 — Lightweight core, remote execution.**
   - **Rule:** operations that need heavy dependencies or specialized
     infrastructure run in the Toolbox. The production policy is `remote_only`.
     The core adds no local fallbacks and installs no heavy dependency only to
     offer one.
   - **Detail:** [ADR-0003](adr/0003-remote-only-operational-capabilities.md).
   - **Checked by:** review, and planned architecture tests that forbid heavy
     imports and tool subprocesses in the core, with an allowlist that can only
     shrink.
5. **P5 — Reference-oriented processing.**
   - **Rule:** persisted artifacts are processed where they are stored and
     passed as typed, opaque `ArtifactRef` references. Materialization is
     explicit and verified; references are immutable and scoped.
   - **Detail:** [ADR-0005](adr/0005-artifact-references.md).
   - **Checked by:** SDK tests (`libs/sdk/tests/test_failover.py`), and
     contract tests once the Toolbox publishes `artifact-ref@1`.
6. **P6 — Reliability without operational duplication.**
   - **Rule:** availability comes from redundant infrastructure (replicas
     behind a load balancer sharing storage), timeouts, bounded retries and
     explicit failure handling, not from duplicate executors in the core. There
     are no silent fallbacks.
   - **Detail:** [ADR-0006](adr/0006-availability-and-failover.md).
   - **Checked by:** SDK failover tests, and a planned end-to-end test with
     replicas.
7. **P7 — One source of truth per contract.**
   - **Rule:** docstruct owns the canonical document models and schemas. The
     Toolbox owns the operational API contracts (`ArtifactRef`, jobs,
     capabilities). The SDK consumes the Toolbox's contracts, preferably
     generated. The core uses the public contracts without redefining them.
   - **Detail:** [ADR-0004](adr/0004-single-source-of-truth-for-contracts.md).
   - **Checked by:** `scripts/check_capability_contract.py` for the
     operational contracts the SDK consumes (capability ids, exact versions,
     providers). Ownership of the canonical models is checked in review and by
     the duplication inventory of #152.
8. **P8 — Incremental evolution.**
   - **Rule:** refactorings are small and verifiable. Extract and reuse code
     before replacing it. Do not mix architectural and behavioral changes in
     one pull request. New capabilities keep algorithms, policies and execution
     apart.
   - **Checked by:** review, and the regression, contract and integration tests
     required by section 3.7.
9. **P9 — Traceability and contract compatibility.**
   - **Rule:** public contracts are versioned and tested. Document
     transformations preserve provenance. Results identify the relevant
     algorithm, provider and parameter versions. Structural changes stay
     compatible or declare their migration.
   - **Detail:** Toolbox constitution, principles 9 and 12.
   - **Checked by:** the SDK's exact contract versions
     (`TOOLBOX_CAPABILITIES`), and `scripts/check_capability_contract.py`.

## 8. Related documents

- [Architecture Decision Records](adr/README.md)
- [Libraries (`libs/`)](../libs/README.md)
- [Toolbox integration](toolbox_integration.md)
- [Acessilia Toolbox constitution](https://github.com/A11yDevs/acessilia-toolbox/blob/main/docs/constitution.md)

## 9. Changelog

Versions follow `MAJOR.MINOR.PATCH`:

- **MAJOR:** a principle or rule is added, removed, or changes meaning, so code
  or documents that complied before may no longer comply.
- **MINOR:** a compatible addition, such as a new section, example or
  verification.
- **PATCH:** wording, links and translations, with no change in meaning.

The unversioned text before 2026-10-18 counts as **1.0.0**.

- **2.0.0 (2026-10-18):** a major version, because principles 2.4 and 2.5 and
  contract 4.4 change meaning. added the ecosystem architecture principles P1–P9
  (section 7) and the ADRs that detail them
  ([#152](https://github.com/A11yDevs/acessilia/issues/152)). Aligned
  principles 2.3–2.5, the ReaderAgent and filter descriptions in 3.1, contract
  4.4, resilience 5.6 and evolution 6.6–6.7 with remote-only execution.
  Version numbers and this changelog start here. The Brazilian Portuguese
  mirror now covers the whole document.
- **1.0.0:** the earlier, unversioned revisions; see the git history of this
  file.
