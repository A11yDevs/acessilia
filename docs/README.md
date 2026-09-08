# Acessilia Project Documentation

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](README.pt-br.md)

## Purpose
This documentation details the architecture of **Acessilia**, a document accessibility system that combines **deterministic planning** (PDDL-based task ordering and validation) with **Agno-coordinated multi-agent AI** for vision, data, and description tasks. Deterministic functions are the source of truth; LLMs provide interpretation and description.

The system runs in one of two pipeline engines, selected by the `PIPELINE_ENGINE` setting: `legacy` (the direct orchestrated pipeline, default) or `pddl` (the manifest → plan → execution flow). See [architecture.md](architecture.md).

---

## Navigation

1. [Architectural Constitution](constitution.md) — non-negotiable principles and quality rules.
2. [Architecture Specification](architecture.md) — layers, both pipeline engines, and processing flow.
3. [Design & Integration Patterns](patterns.md) — recurring patterns and their rationale.
4. [Use Cases](use_cases.md) — actors and user-facing operations.
5. [Endpoints & APIs](endpoints.md) — the REST API, the Web panel, and the AgentOS runtime.
6. [Automated Test Suite](../tests/README.md) — test strategy and coverage.
7. [Docker Compose](docker-compose.md) — local execution, GHCR images, staging and production update paths.
8. [Production systemd timer](producao-systemd.md) — production setup, promotion and rollback procedure.
9. [Internationalization (i18n)](i18n.md) — what is localized, where the locale strings files live, and step-by-step guides for adding strings, internationalizing a file, and adding a new locale.

---

## PDDL + Agno Architecture

The planning-based pipeline and its incorporation are documented separately:

1. [PMV — Agno, manifest, PDDL and nominal execution](pmv_agno_pddl.md) — the minimal cycle `document → manifest → PDDL plan → execution report → canonical document`, and how Agno coordinates the deterministic tools. (Brazilian Portuguese: [versão em pt-BR](pmv_agno_pddl.pt-br.md))
2. [PDDL + Agno incorporation plan](plano_incorporacao_pddl_agno.md) — the block-by-block plan used to bring the planning layer into the codebase. (Brazilian Portuguese: [plano em pt-BR](plano_incorporacao_pddl_agno.pt-br.md))

---

## UML Diagrams (PlantUML)

Each diagram is a visual aid; the linked description summarizes its content in text.

1. **Architecture & Multi-Agent Pipeline:** [architecture/architecture.puml](architecture/architecture.puml) — component and package structure of the backend/frontend pipeline.
2. **Processing Sequence:** [sequence/document_processing_sequence.puml](sequence/document_processing_sequence.puml) — step-by-step flow of a document conversion, including the parallel vision/data agents.
3. **Task State Machine:** [state_machine/task_state_machine.puml](state_machine/task_state_machine.puml) — lifecycle of a processing task (processing, done, error, cancelled).
4. **Use Cases:** [use_cases/use_cases.puml](use_cases/use_cases.puml) — actors and the main user-facing operations.

---

## Covered Scope

- **`backend/`** — Interface-agnostic business logic.
  - `core/` — the planning layer: `manifest/` (Informational-Structural extraction via Docling/PyMuPDF → `processing-manifest.json`), `planning/` (PlannerAgent → PDDL problem and `nominal-plan.json`), `execution/` (Executor via Agno Workflow → `execution-report.json`).
  - `agents/` — the pipeline agents (`ReaderAgent`, `VisionAgent`, `DataAgent`, `EditorAgent`) and the legacy and PDDL orchestrators.
  - `api/` — the standalone REST API (jobs, download, history, health).
  - `pipeline/` + `export/` — canonical document construction, validation, and format renderers.
  - `ai/`, `services/`, `tools/` — Agno model registry and prompts, infrastructure services (cache, queue, history, cleanup, email, tokens), and shared utilities.
- **`frontend/`** — Clients of the API: Telegram bot (`frontend/telegram/`), Web panel (`frontend/web/`), CLI (`frontend/cli/`), the shared `frontend/clients/api_client.py`, and the AgentOS runtime (`frontend/agent_os.py`).
- **`infra/`** — Dockerfile and Docker Compose configurations.
- **`tests/`** — Unit and integration test suite (`pytest`).

---

## Traceability Matrix

- **Use Cases to Implementation:** [use_cases.md](use_cases.md)
- **Design & Evolution Patterns:** [patterns.md](patterns.md)
- **Test Strategy & Coverage:** [../tests/README.md](../tests/README.md)
