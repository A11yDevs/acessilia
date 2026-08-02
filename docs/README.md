# Acessília Project Documentation

## Purpose
This documentation details the architecture of **Acessília**, a modular multi-agent system powered by the **Agno Framework** for document accessibility.

---

## Navigation

1. [Architectural Constitution](constitution.md)
2. [Architecture Specification](architecture.md)
3. [Design & Integration Patterns](patterns.md)
4. [Use Cases](use_cases.md)
5. [Automated Test Suite](../tests/README.md)

---

## UML Diagrams (PlantUML)

Each diagram is a visual aid; the linked description summarizes its content in text.

1. **Architecture & Multi-Agent Pipeline:** [architecture/architecture.puml](architecture/architecture.puml) — component and package structure of the backend/frontend pipeline.
2. **Processing Sequence:** [sequence/document_processing_sequence.puml](sequence/document_processing_sequence.puml) — step-by-step flow of a document conversion, including the parallel vision/data agents.
3. **Task State Machine:** [state_machine/task_state_machine.puml](state_machine/task_state_machine.puml) — lifecycle of a processing task (processing, done, error, cancelled).
4. **Use Cases:** [use_cases/use_cases.puml](use_cases/use_cases.puml) — actors and the main user-facing operations.

---

## Covered Scope

- **`backend/`** — Interface-agnostic business logic, Agno multi-agent pipeline (`ReaderAgent`, `VisionAgent`, `DataAgent`, `EditorAgent`), `AccessibilityOrchestrator`, AI client setup (`get_agno_model`), services (cache, history, queue, email, tokens), canonical document pipeline, export renderers, and utilities.
- **`frontend/`** — Pluggable interfaces: Telegram bot (`frontend/telegram/`), FastAPI Web UI & API (`frontend/web/`), and CLI (`frontend/cli/`).
- **`infra/`** — Dockerfile and Docker Compose configurations.
- **`tests/`** — Unit and integration test suite (`pytest`).

---

## Traceability Matrix

- **Use Cases to Implementation:** [use_cases.md](use_cases.md)
- **Design & Evolution Patterns:** [patterns.md](patterns.md)
- **Test Strategy & Coverage:** [../tests/README.md](../tests/README.md)
