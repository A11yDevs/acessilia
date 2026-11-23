# Architecture

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](architecture.pt-br.md)

## Overview
The system converts documents into accessible formats through a multi-agent extraction pipeline (structural extraction through Acessilia Toolbox capabilities plus Agno-powered multimodal AI vision and data agents), a canonical document pipeline, deterministic validation, and format-specific renderers. The architecture is modular: **backend/** holds the domain logic plus the REST API that exposes it, **frontend/** holds the interface clients (Telegram, Web, CLI) that talk to that API, and **infra/** holds the Dockerfile (the Compose file sits at the repository root).

The system combines **deterministic planning with AI-driven execution**: deterministic functions (extraction, PDDL problem generation, contract validation) are the source of truth, and LLMs provide interpretation and description. Documents run through the **`pddl`** pipeline engine (`PIPELINE_ENGINE`, default `pddl`): a processing manifest is extracted, a PDDL plan is generated and validated, and an Agno Workflow executor applies it. See [pddl_pipeline.md](pddl_pipeline.md).

The former **`legacy`** engine (`AccessibilityOrchestrator`: Reader → Vision/Data → Editor) is disabled: `backend/service.py` accepts only `pddl` (the old `pmv` alias is normalized to it, and is deprecated: it logs a warning at startup and will be removed) and refuses any other value. Its code has been removed.

---

## Layers

### 0. Core and service (`libs/core/src/acessilia_core`, `backend/`) — Interface-agnostic business logic and AI pipeline

The core is the `acessilia_core` package in `libs/core` ([ADR-0016](adr/0016-core-package.md)); the service in `backend/` builds its configuration and ports and delivers its results.

#### 0.1. Multi-Agent Pipeline & Orchestration (`libs/core/src/acessilia_core/agents/`)
- [libs/core/src/acessilia_core/agents/vision_agent.py](../libs/core/src/acessilia_core/agents/vision_agent.py): `VisionAgent` utilizes Agno (`agno.agent.Agent`) and LLM multimodal capabilities (`agno.media.Image`) to produce detailed alt-text and audio descriptions for visual elements and scanned pages.
- [libs/core/src/acessilia_core/agents/data_agent.py](../libs/core/src/acessilia_core/agents/data_agent.py): `DataAgent` utilizes Agno (`agno.agent.Agent`) and LLM capabilities to convert complex tables and mathematical formulas into structured Markdown and LaTeX representations.
- [backend/agents/state_manager.py](../backend/agents/state_manager.py): in-memory task state machine with cooperative cancellation support (the service's job state; it stays outside the core).

#### 0.2. AI Client Integration (`libs/core/src/acessilia_core/agents/ai_client.py`)
- [libs/core/src/acessilia_core/agents/ai_client.py](../libs/core/src/acessilia_core/agents/ai_client.py): central `get_agno_model(models, toolbox)` initializer that instantiates Agno Model wrappers for Ollama, OpenRouter or the Toolbox VLM gateway (`AI_CLIENT=toolbox`, [ADR-0012](adr/0012-agents-reach-the-vlm-through-the-toolbox.md)) from the run's `ModelConfig` and `ToolboxConfig` ([ADR-0016](adr/0016-core-package.md), step 3).
- [libs/core/src/acessilia_core/agents/prompt_tools.py](../libs/core/src/acessilia_core/agents/prompt_tools.py): prompt loader and template resolver over the prompts in [libs/core/src/acessilia_core/agents/prompts/](../libs/core/src/acessilia_core/agents/prompts/).

**DataAgent call deadline (#276, step 1).** Each `process_region` call awaits
`Agent.run` for at most `DATA_AGENT_TIMEOUT_SECONDS + 30` seconds. The HTTP
client still uses `DATA_AGENT_TIMEOUT_SECONDS`; the extra grace bounds the
asynchronous wait even if a provider keeps resetting the per-read HTTP timeout
by trickling bytes. With `AI_CLIENT=toolbox`, the timeout also includes the wait
for a VLM gateway slot, so it must allow for that queue (see
[ADR-0012](adr/0012-agents-reach-the-vlm-through-the-toolbox.md)).

For the OpenAI-compatible OpenRouter and Toolbox clients, implicit retries are
disabled (`max_retries=0`): the OpenAI SDK's two extra attempts are removed.
Ollama does not consume this option and keeps its existing retry policy.
A transient transport failure returns `None` through the existing logged
degradation path. Successful answers still undergo structured-output and
region-kind validation. Table rereads (`_TABLE_REREAD_ATTEMPTS`) and the
`_retry_failed` pass keep their own policies;
the deadline bounds one model call, not the whole table or document.

**Shared model execution (#276, step 2).** VisionAgent and DataAgent receive the
core's `ModelCallRunner` port by composition. The application owns its
implementation, `backend.services.model_calls.ModelCallExecutor`, independently
of event loops. Each run receives its runner explicitly:
`PddlAccessibilityOrchestrator.execute(..., config=, model_calls=, ports=)`
requires the run's `CoreConfig`, the runner and the run's `RunPorts` (ADR-0016,
step 4), and opens the runner's
`model_call_scope` for the agents it builds (ADR-0016, step 3). Nothing falls
back to the service's process owner or settings. Agents read no
execution-capacity settings. AgentOS's separate
Agno chat agents are outside this execution path.

`MODEL_CALL_WORKERS` (default 4) bounds worker reservations across jobs and
transient loops; `MODEL_CALL_MAX_PENDING` (default 4) bounds additional waiting
calls. These are process setup, not per-run CoreConfig values. Only worker
reservations reach the ThreadPoolExecutor. Pending calls stay in a bounded FIFO
that removes cancelled/expired closures promptly; a pending call cannot start
inference after abandonment. Saturation raises an explicit `ModelCallRejected`
and follows the existing agent degradation path. With zero pending capacity,
every occupied worker immediately counts toward saturation.

The overall per-attempt deadline includes local queue wait and execution; with
the Toolbox it also includes the gateway's slot wait. `VISION_CONCURRENCY`
continues to limit one stage of one document, and the Toolbox independently owns
its provider's slots. Size the Core workers for that gateway capacity and keep
the model timeout large enough for legitimate queue wait. Table rereads and the
VisionAgent's timeout retry remain separate from this execution mechanism.

Each submission copies its ContextVars, including request locale. Synchronous
region/page handlers preserve that context through their transient-loop bridge.
`run_blocking`, cache I/O and structural extraction keep their existing executor
and cancellation policies. Localized logs record saturation, deadline expiry,
abandonment, queue wait and execution duration. `snapshot()` exposes active
worker reservations, pending/abandoned calls, rejections and deadline expirations
for observability (#385), without logging image/prompt content.

An expired/cancelled running call still retains its reservation, thread,
connection and per-call Agent/model client until the provider finishes. Its late
result is discarded. `asyncio.run()` never joins this application-owned pool.
API/CLI shutdown uses `close(wait=False)` to close admission, remove pending work
and wake pending and active awaiters with `ModelCallRejected`. Active provider
threads continue, retain their reservations until they finish, and have their
late results discarded. Closing does not kill threads or guarantee immediate process
termination: Python still joins executor threads at interpreter exit. A provider
that never returns may require external process termination. A subsequent
application lifecycle in the same process cannot replace a closed pool while
abandoned workers remain; calls are rejected until those workers finish.
Standalone users own and close their runner explicitly. See
[ADR-0021](adr/0021-bounded-model-call-execution.md).

#### 0.3. Infrastructure Services (`backend/services/`)
- [backend/services/cache.py](../backend/services/cache.py): file-hash-based text cache in `var/temp/cache`.
- [backend/services/history_service.py](../backend/services/history_service.py): SQLite persistence (WAL mode) for conversions and audit logs, in `var/data/history.db`.
- [backend/services/queue_service.py](../backend/services/queue_service.py): unified async processing queue with concurrency limits.
- [backend/services/cleanup_service.py](../backend/services/cleanup_service.py): periodic cleanup of temporary files.
- [backend/services/email_service.py](../backend/services/email_service.py): async SMTP email sender (confirmation + result with ZIP attachments).
- [backend/services/download_token_service.py](../backend/services/download_token_service.py): token generation for secure Web download links.
- [backend/services/validators.py](../backend/services/validators.py): upload validation (file extension and size).
- [backend/services/access_log_filter.py](../backend/services/access_log_filter.py) and [backend/services/filenames.py](../backend/services/filenames.py): the access log filter and bounded output file names.

#### 0.4. Core Utilities and Toolbox Adapters (`libs/core/src/acessilia_core/`)
- [libs/core/src/acessilia_core/toolbox/](../libs/core/src/acessilia_core/toolbox/): the core's adapters over the Toolbox, through the SDK (client from the settings, math, media inspection, PDF/UA audit, text spans, vision payload).
- [libs/core/src/acessilia_core/config.py](../libs/core/src/acessilia_core/config.py): `CoreConfig`, the core's configuration in frozen groups, which the service builds from its settings in [backend/config/core_config.py](../backend/config/core_config.py) (ADR-0016, step 3).
- [libs/core/src/acessilia_core/ports.py](../libs/core/src/acessilia_core/ports.py): `RunPorts`, the service state a run reaches (the region cache, the job's checkpoints and its registry of remote operations), built by the service for each job in [backend/services/run_ports.py](../backend/services/run_ports.py); `RunPorts.none()` keeps no state (ADR-0016, step 4).
- [libs/core/src/acessilia_core/logger.py](../libs/core/src/acessilia_core/logger.py): centralized loguru logger setup; the level and the log directory are passed at process start by [backend/config/process_setup.py](../backend/config/process_setup.py), with the offered locales (ADR-0016, step 3).
- [libs/core/src/acessilia_core/formula_tools.py](../libs/core/src/acessilia_core/formula_tools.py): `wrap_latex` and the spoken-formula label; `normalize_latex` and `ensure_math_delimiters` are deprecated re-exports of `docstruct.text.latex`.
- [docstruct.text.paragraphs](../libs/docstruct/src/docstruct/text/paragraphs.py): text normalization and Markdown parsing.

#### 0.5. Planning Layer (`libs/core/src/acessilia_core/`) — PDDL engine

This is the only active engine. It turns document structure into an explicit plan before any AI runs, so task ordering and dependencies are deterministic and auditable.

- `libs/core/src/acessilia_core/manifest/`: the Informational-Structural agent extracts a `processing-manifest.json` from the document (regions, types, and processing obligations) through the Toolbox (`ToolboxManifestExtractor`, capability `document.structure.extract`). The local Docling/PyMuPDF extractors are disabled for this engine.
- `libs/core/src/acessilia_core/planning/`: the `PlannerAgent` compiles the manifest plus a PDDL domain into a problem, generates a `nominal-plan.json` (internal planner or Fast Downward backend), and validates it. PDDL problem generation is deterministic — no LLM writes PDDL. The coordination path asks the `PlanningEngine` protocol (`planning/engine.py`) for plans; the default engine, `PddlPlanningEngine`, wraps the `PlannerAgent` and owns the backend choice. An injected engine replaces it for planning and replanning, and its identity enters the planning checkpoint and the report's `mode`.
- `libs/core/src/acessilia_core/execution/`: the Executor applies the validated plan as an Agno Workflow, invoking the Vision/Data agents where the plan requires them, and produces an `execution-report.json`.
- `libs/core/src/acessilia_core/agents/fusion_agent.py`: the `FusionAgent` exposes deterministic Agno tools over the pure `docstruct` library — `fuse_providers`, `audit_document`, `classify_block`, and `needs_reinfer`. The `dual-provider-fusion` PDDL method reuses `acessilia_core.pipeline.fusion.extract_fused` and is only admissible when `FUSION_MODE=dual`. See [docstruct_algorithms.md](docstruct_algorithms.md) for how these algorithms work.
- `libs/core/src/acessilia_core/pipeline/orchestrator.py`: `PddlAccessibilityOrchestrator.execute()` coordinates the manifest → plan → execution phases. A planning failure fails the job; there is no fallback to deterministic extraction. Its [inventory](architecture/pddl-orchestrator-inventory.md) assigns each part to the core, docstruct or the SDK (#402). How the observed state becomes the PDDL problem is in [pddl-state-projection.md](architecture/pddl-state-projection.md).

The PDDL domain lives under `libs/core/src/acessilia_core/planning/domains/`. The JSON schemas (manifest, plan, comparison, execution report) live in `schemas/` at the repository root and are generated by `scripts/generate_pddl_schemas.py`.

---

### 1. Frontend (`frontend/`) — Interface Clients and Runtimes

#### Telegram Bot (`frontend/telegram/`)
- [frontend/telegram/bot.py](../frontend/telegram/bot.py): initializes aiogram Bot/Dispatcher, registers routers, middlewares, and lifecycle hooks.
- [frontend/telegram/handlers/start.py](../frontend/telegram/handlers/start.py): control commands (/start, /help, /status, /health, /feedback, modes, /cancelar).
- [frontend/telegram/handlers/document.py](../frontend/telegram/handlers/document.py): receives files/photos, validates, triggers processing, sends outputs.
- [frontend/telegram/handlers/errors.py](../frontend/telegram/handlers/errors.py): global exception handling.
- [frontend/telegram/adapters/status_tracker.py](../frontend/telegram/adapters/status_tracker.py): Telegram-specific progress bar.
- [frontend/telegram/adapters/file_service.py](../frontend/telegram/adapters/file_service.py): Telegram file download/upload helpers.

#### Web Panel (`frontend/web/`)
- [frontend/web/app.py](../frontend/web/app.py): server-rendered HTML panel. It is a thin client of the REST API — upload, status, and download are delegated to `backend/api` via `frontend/clients/api_client.py`.

#### Command Line Interface (`frontend/cli/`)
- [frontend/cli/run.py](../frontend/cli/run.py): console-script entry point; it delegates to `frontend.run` so both commands start the same interfaces and share the process lock.

#### REST API (`backend/api/`)
- The standalone JSON API that all interfaces consume: job submission and status, download, history, and health. It owns the processing queue and the pipeline. The Telegram bot and the Web panel are clients of it. Full endpoint reference in [endpoints.md](endpoints.md).

#### AgentOS runtime (`frontend/agent_os.py`)
- An optional Agno runtime that exposes the Vision and Data agents for inspection (chat, sessions, memory, metrics, traces) via the AgentOS panel or agent-ui. It does not run the pipeline; see [endpoints.md](endpoints.md).

---

### 2. Canonical Document & Export Pipeline (`libs/core/src/acessilia_core/pipeline/`, `libs/core/src/acessilia_core/export/`)

- [libs/core/src/acessilia_core/pipeline/canonical_builder.py](../libs/core/src/acessilia_core/pipeline/canonical_builder.py): builds the canonical document and sections tree.
- `docstruct.types.CanonicalDocument` and `CanonicalSection` are deprecated compatibility dataclasses since 0.5.3 ([ADR 0024](adr/0024-legacy-canonical-type-deprecation.md)). The original classes and root reexports retain their constructors, fields, methods and pickle paths, with informational deprecation metadata and silent imports/construction. The pipeline uses builder-produced dictionaries described by the packaged schema; `CanonicalBlock` and other algorithm value objects remain active. Removing the legacy names requires a separate breaking-version decision and consumer migration.
- [docstruct.text.sanitize](../libs/docstruct/src/docstruct/text/sanitize.py): cleans raw text, removes prompt leaks and Markdown artifacts.
- [libs/core/src/acessilia_core/pipeline/validators.py](../libs/core/src/acessilia_core/pipeline/validators.py): validates canonical structure, heading hierarchy, links, and output text; `audit_canonical_document` classifies structural and accessibility issues as `BLOCKER` or `WARNING`.
- [docstruct.schemas](../libs/docstruct/src/docstruct/schemas/__init__.py) owns the packaged accessible-document JSON Schema. Its accessor returns a fresh dictionary from a fixed resource; the root schema is a generated byte-identical copy checked by the core contract test. `validate_against_schema(document, validator)` calls an injected engine. `jsonschema` is dev-only; [ADR 0023](adr/0023-packaged-canonical-schema.md) records the resource-read exception and API. Tests validate builder output, including children, and CI checks the installed wheel outside the checkout. Core 0.2.0 calls the injected API after normalization/audit and before profile selection or rendering; schema-invalid inputs now fail with a localized JSON Pointer/keyword diagnostic ([ADR 0026](adr/0026-strict-canonical-export-gate.md)). Pure serializer fallback, schema constraints and E1.0 goldens remain unchanged.
- [libs/core/src/acessilia_core/export/pandoc_exporter.py](../libs/core/src/acessilia_core/export/pandoc_exporter.py): single export coordinator for validation, filtering, AST build, and renderer dispatch; acts as a deterministic gatekeeper that halts export when the audit returns any `BLOCKER`.
- Format ownership ([ADR 0025](adr/0025-format-catalogue-ownership.md)): docstruct owns pure `FormatSpec` identity; `acessilia_core.export.catalog` owns frozen delivery metadata and SDK capability references; `backend.api.export_plan` owns worker order, flags, progress and failure policy. Downloads/web reuse MIME, labels and filenames. Produced, downloadable, legacy and internal roles differ: `pdf` remains download-only; `drbench_md` remains internal; ZIP remains packaging. Public wire labels, suffixes, filters, validation and archive order stay unchanged.
- [libs/core/src/acessilia_core/export/renderers/](../libs/core/src/acessilia_core/export/renderers/): renderers for TXT and HTML (DOCX and PDF/UA render on the Toolbox).
- [docstruct.export.walk](../libs/docstruct/src/docstruct/export/walk.py): shared section/child traversal and per-type dispatch for the pure TXT, HTML, Pandoc AST and benchmark Markdown serializers ([ADR 0022](adr/0022-export-walker-contract.md)). Format visitors own selection and rendering; public signatures and E1.0 golden outputs remain unchanged. TXT keeps its profile filter and current child formula-label policy. HTML collects blocks, applies its existing global profile/link filter, then renders with document-local TOC, table numbering and reserved IDs. Pandoc/Markdown add no profile filter. TXT/HTML/Pandoc omit only the first matching legacy title; Markdown omits every heading matching the section title. Behavior changes remain in #161.
- [libs/core/src/acessilia_core/export/exporters/](../libs/core/src/acessilia_core/export/exporters/): the export adapters called by the worker, including `audio_exporter.py`, which produces the MP3 via edge-tts, and `pdf_exporter.py`, which produces the PDF/UA, the only PDF. [libs/core/src/acessilia_core/toolbox/pdf_ua_audit.py](../libs/core/src/acessilia_core/toolbox/pdf_ua_audit.py) audits it with veraPDF on the Toolbox (`pdf.validate.pdf_ua`) for the result e-mail.

---

## Layering & Dependency Direction

The codebase follows a pragmatic layered architecture with a top-down flow: Interface → Orchestration → Extraction → Canonical Document → Output. Infrastructure services and shared tools support multiple layers but do not own business decisions. One controlled exception exists: the orchestrator coordinates both processing and infrastructure concerns (cache, history).

### Libraries and the Toolbox (`libs/`)

The heavy models run in a separate service, the [Acessilia Toolbox](https://github.com/A11yDevs/acessilia-toolbox). Between it and this core sit two libraries kept in `libs/`. Dependencies only point down:

| Layer | Package | Role | May depend on |
|---|---|---|---|
| 0 | `libs/docstruct` (`acessilia-docstruct`) | Pure document-structure algorithms (fusion, tables, reading order), no dependencies of its own | nothing |
| 1 | Toolbox (separate repository) | Heavy providers, artifact storage, capability execution over REST/MCP | docstruct |
| 2 | `libs/sdk` (`acessilia-sdk`) | Capability allowlist, HTTP transport, catalogue checks, artifact references, retries and failover; generic i18n infrastructure (locale parsing/normalization, negotiation, request context and catalog translation); configuration is passed in | the Toolbox's **published contract** (capability ids, versions, schemas), never its package |
| 3 | Core (`libs/core/src/acessilia_core`) | Agents, PDDL planning, obligations, policies | SDK, docstruct |

- **The core decides what to do and when; the SDK defines how to reach an operation; the Toolbox provides where and with which resources it runs.** Obligations, admissible methods and costs are the core's planning policy: the Toolbox reports what it found, and the core derives the obligations ([#138](https://github.com/A11yDevs/acessilia/pull/138)).
- **Operational capabilities run only in the Toolbox.** The production policy is `remote_only`: the core keeps no local fallback for Pandoc, TeX Live, veraPDF, PyMuPDF rendering, media inspection or OCR, and the Toolbox does not depend on the SDK ([ADR-0002](adr/0002-component-responsibilities.md), [ADR-0003](adr/0003-remote-only-operational-capabilities.md)).
- **Availability comes from Toolbox replicas** behind a load balancer that share the artifact store, with bounded SDK retries; the SDK's multi-endpoint failover is reserved for independent deployments ([ADR-0006](adr/0006-availability-and-failover.md)). Persisted artifacts travel as `ArtifactRef` references ([ADR-0015](adr/0015-artifact-reference-v1.md)).
- **One source of truth per contract:** docstruct owns the canonical document models; the Toolbox owns the operational API contracts; the SDK consumes them ([ADR-0004](adr/0004-single-source-of-truth-for-contracts.md)). Cross-component decisions are recorded in [docs/adr/](adr/README.md).
- **The Toolbox catalogue only restricts.** Methods that call the Toolbox are checked against the live catalogue before a document is planned (`TOOLBOX_AVAILABILITY_GATE`); a capability outside the SDK allowlist is never made available. See [toolbox_integration.md](toolbox_integration.md).
- **docstruct is distributed as a release wheel.** The core installs it from this checkout. The Toolbox pins the wheel of a `docstruct-vX.Y.Z` GitHub Release by URL and `#sha256=` ([Releases](../libs/docstruct/README.md#releases)). The SDK is not published yet; its consumers in this repository are the core, the service, the frontend and the benchmark scripts.
- **Enforced by tests:** `libs/docstruct/tests/test_purity.py` and `libs/sdk/tests/test_purity.py` import every module with the upper layers refused; `tests/test_architecture_layers.py` fails if `backend` imports the Toolbox package.

---

## Main Processing Flow

1. User submits a document via the REST API directly, or through the Telegram bot, Web panel, or CLI (which call the API).
2. The interface handler validates the file extension and size.
3. The file is saved and enqueued in `ProcessingQueue`.
4. The worker dequeues the task; `backend/service.py::process` registers it in `StateManager` and checks the processing cache.
5. On a cache miss, it runs the PDDL orchestrator (`PddlAccessibilityOrchestrator.execute()`):
   - Inspects the source media (`media.inspect`) and extracts the processing manifest through the Toolbox (`document.structure.extract`); a slide deck is extracted without dual-provider fusion and structured slide by slide.
   - Enriches pictures and tables, builds and validates a PDDL plan for the manifest's obligations, and executes it, replanning when a method fails.
   - Builds the canonical document from the executed manifest.
6. Canonical validators verify schema adherence, heading hierarchy, and output safety.
7. Renderers and export adapters build the output artifacts (TXT, DOCX, PDF/UA, HTML, MP3).
8. Output files are packaged and delivered to the user (via Telegram message, Web download link, or email).

---

## Interface Activation

The `ENABLED_INTERFACES` environment variable controls which surfaces start at boot (default `"api,telegram,web"`):
- `api`: the REST API (`backend/api`) on `API_PORT` (default 8000) — the pipeline and queue live here.
- `telegram`: the Telegram bot (a client of the API).
- `web`: the HTML Web panel (`frontend/web`) on `WEB_PORT` (default 8001), also a client of the API.

The AgentOS runtime is not part of `ENABLED_INTERFACES`; it is started separately with `python -m frontend.agent_os`.

---

## External Dependencies

- **Agno Framework:** multi-agent orchestration and unified multimodal LLM interface.
- **AI Providers:** Ollama API (local models like LLaVA/Qwen-VL), OpenRouter API (cloud models like Claude/GPT-4o), or the Toolbox VLM gateway, which relays the chats to a Toolbox VLM provider under its concurrency limit.
- **Processing Libraries:** edge-tts, aiogram, FastAPI.
- **One local executor remains,** the edge-tts audio exporter ([ADR-0003](adr/0003-remote-only-operational-capabilities.md), [acessilia-toolbox#73](https://github.com/A11yDevs/acessilia-toolbox/issues/73)); the others left with [#150](https://github.com/A11yDevs/acessilia/issues/150): the manifest is extracted only through `ToolboxManifestExtractor`, and PyMuPDF is a development dependency used by tests to build PDFs. `tests/test_architecture_layers.py` fails if `backend/` or `frontend/` imports an operational library (PyMuPDF, Pillow, OpenCV, Docling, pypdf, python-docx, RapidOCR, reportlab). Pandoc, TeX Live, veraPDF and the OCR and media libraries are no longer in the image, since DOCX and PDF/UA render only on the Toolbox; NumPy and OpenCV left the dependencies together with the Dr.DocBench experiment scripts (tag `drbench-2026-snapshot`); Pillow and pypdf left the runtime dependencies with reportlab and the local PDF renderer, and Pillow remains only in the `dev` extra, for the page images the Toolbox end-to-end tests send.

---

## Key Architectural Decisions

1. **Interface-independent domain:** the domain packages — `libs/core/src/acessilia_core` (manifest, planning, execution, pipeline, agents, Toolbox adapters, export and i18n), `backend/services`, `backend/config` and `backend/agents` (the job state) — have no dependency on interface frameworks (no aiogram, no FastAPI). The single exception is `backend/api`, which is the FastAPI layer that exposes the domain over HTTP; everything in `frontend/` is a client of that API. Keeping the boundary there means a new interface never requires touching the domain.
2. **Modular Multi-Agent Architecture:** Separates structural reading, visual description, data formatting, and text editing into distinct agents.
3. **Canonical Document Source of Truth:** All renderers consume the validated canonical document schema to guarantee screen reader compatibility.
