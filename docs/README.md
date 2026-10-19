# Acessilia Project Documentation

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](README.pt-br.md)

## Purpose
This documentation details the architecture of **Acessilia**, a document accessibility system that combines **deterministic planning** (PDDL-based task ordering and validation) with **Agno-coordinated multi-agent AI** for vision, data, and description tasks. Deterministic functions are the source of truth; LLMs provide interpretation and description.

The system runs the `pddl` pipeline engine (the manifest → plan → execution flow), selected by the `PIPELINE_ENGINE` setting, whose default is `pddl`. The former `legacy` engine is disabled: `backend/service.py` accepts only `pddl` (the old `pmv` alias is normalized to it) and refuses any other value; its code has been removed. See [architecture.md](architecture.md).

---

## Navigation

1. [Architectural Constitution](constitution.md) — non-negotiable principles and quality rules, including the ecosystem principles P1–P9 (section 7) that divide the work between the core, the SDK, docstruct and the Toolbox.
2. [Architecture Specification](architecture.md) — layers, the PDDL pipeline engine, and processing flow.
3. [Design & Integration Patterns](patterns.md) — recurring patterns and their rationale.
4. [Use Cases](use_cases.md) — actors and user-facing operations.
5. [Endpoints & APIs](endpoints.md) — the REST API, the Web panel, and the AgentOS runtime.
6. [Automated Test Suite](../tests/README.md) — test strategy and coverage.
7. [Docker Compose](docker-compose.md) — local execution, GHCR images, staging and production update paths.
8. [Production systemd timer](producao-systemd.md) — production setup, promotion and rollback procedure.
9. [Internationalization (i18n)](i18n.md) — what is localized, where the locale strings files live, and step-by-step guides for adding strings, internationalizing a file, and adding a new locale.
10. [Benchmark harness](bench.md) — run and score the core on Dr.DocBench (and other datasets) with `python -m scripts.bench`.
11. [Dr.DocBench benchmark](drbench.md) — structure-extraction provider benchmark (Docling vs MinerU), metrics and results.
12. [Toolbox tool integration](toolbox_integration.md) — how to integrate a new Toolbox tool into the core: HTTP contract, libraries vs. Toolbox capabilities, and the two integration scenarios. (Brazilian Portuguese: [versão em pt-BR](toolbox_integration.pt-br.md))
13. [Architecture Decision Records](adr/README.md) — cross-component decisions (responsibilities, remote-only execution, contracts, artifact references, availability, the manifest model and MathML conversion) and how to propose a new one. (Brazilian Portuguese: [versão em pt-BR](adr/README.pt-br.md))
14. [Architecture audit, October 2026](architecture/audit-2026-10.md) — what is still implemented twice across the components, the remaining operational dependencies, the architectural guards and the initial metrics, with an owner and a destination for each finding. (Brazilian Portuguese: [versão em pt-BR](architecture/audit-2026-10.pt-br.md))

---

## PDDL + Agno Architecture

The planning-based pipeline and its incorporation are documented separately:

1. [PMV — Agno, manifest, PDDL and nominal execution](pmv_agno_pddl.md) — the minimal cycle `document → manifest → PDDL plan → execution report → canonical document`, and how Agno coordinates the deterministic tools. (Brazilian Portuguese: [versão em pt-BR](pmv_agno_pddl.pt-br.md))
2. [PDDL + Agno incorporation plan](plano_incorporacao_pddl_agno.md) — the block-by-block plan used to bring the planning layer into the codebase. (Brazilian Portuguese: [plano em pt-BR](plano_incorporacao_pddl_agno.pt-br.md))
3. [docstruct Algorithms](docstruct_algorithms.md) — how the deterministic algorithms work (multi-provider fusion / Tree Differ, canonical audit, region classification, re-inference) and how the agents invoke them. (Brazilian Portuguese: [algoritmos em pt-BR](docstruct_algorithms.pt-br.md))
4. [XY-cut reading order for multi-column pages](reading_order_xycut.md) — optional fusion step that fixes the reading order on multi-column pages: the problem, the gates, how to enable it, the small-batch Dr.DocBench experiment and its limitations. (Brazilian Portuguese: [XY-cut em pt-BR](reading_order_xycut.pt-br.md))

---

## UML Diagrams (PlantUML)

Each diagram is a visual aid; the linked description summarizes its content in text.

1. **Architecture:** [architecture/architecture.puml](architecture/architecture.puml) — components of the PDDL engine, the frontends, and the Toolbox and AI services they call.
2. **Processing Sequence:** [sequence/document_processing_sequence.puml](sequence/document_processing_sequence.puml) — step-by-step flow of a document conversion: manifest extraction on the Toolbox, planning, plan execution and export.
3. **Task State Machine:** [state_machine/task_state_machine.puml](state_machine/task_state_machine.puml) — lifecycle of a processing task (processing, done, error, cancelled).
4. **Use Cases:** [use_cases/use_cases.puml](use_cases/use_cases.puml) — actors and the main user-facing operations.

---

## Covered Scope

- **`backend/`** — Interface-agnostic business logic.
  - `core/` — the planning layer: `manifest/` (Informational-Structural extraction through the Toolbox → `processing-manifest.json`), `planning/` (PlannerAgent → PDDL problem and `nominal-plan.json`), `execution/` (Executor via Agno Workflow → `execution-report.json`).
  - `agents/` — the PDDL orchestrator and the agents it uses (`VisionAgent`, `DataAgent`).
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
