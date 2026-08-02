# Acessília Project Documentation

## Purpose
This documentation details the architecture of **Acessília**, a modular multi-agent system powered by the **Agno Framework** for document accessibility.

---

## Navigation

1. [Architectural Constitution](constitution.md)
2. [Architecture Specification](architecture.md)
3. [Design & Integration Patterns](patterns.md)
4. [Use Cases](use_cases.md)
5. [Modules Overview](modules.md)
6. [Classes Catalog](classes.md)
7. [Automated Test Suite](../tests/README.md)

---

## UML Diagrams (PlantUML)

1. **Architecture & Multi-Agent Pipeline:** [docs/architecture/architecture.puml](architecture/architecture.puml)
2. **Layered Architecture:** [docs/architecture/layers.puml](architecture/layers.puml)
3. **Processing Sequence (Gather & Agents):** [docs/sequence/document_processing_sequence.puml](sequence/document_processing_sequence.puml)
4. **Task State Machine:** [docs/state_machine/task_state_machine.puml](state_machine/task_state_machine.puml)
5. **Use Cases:** [docs/use_cases/use_cases.puml](use_cases/use_cases.puml)

---

## Covered Scope

- **`backend/`** — Interface-agnostic business logic, Agno multi-agent pipeline (`ReaderAgent`, `VisionAgent`, `DataAgent`, `EditorAgent`), `AccessibilityOrchestrator`, AI client setup (`get_agno_model`), services (cache, history, queue, email, tokens), canonical document pipeline, export renderers, and utilities.
- **`frontend/`** — Pluggable interfaces: Telegram bot (`frontend/telegram/`), FastAPI Web UI & API (`frontend/web/`), and CLI (`frontend/cli/`).
- **`infra/`** — Dockerfile and Docker Compose configurations.
- **`tests/`** — Unit and integration test suite (`pytest`).

---

## Traceability Matrix

- **Use Cases to Implementation:** [use_cases.md](use_cases.md)
- **Implementation by Module:** [modules.md](modules.md)
- **Objects and Responsibilities:** [classes.md](classes.md)
- **Design & Evolution Patterns:** [patterns.md](patterns.md)
- **Test Strategy & Coverage:** [../tests/README.md](../tests/README.md)
