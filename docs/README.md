# a11y-devs-describer Project Documentation

## Purpose
This documentation describes the project architecture, modules, classes, use cases, and principles aligned with the current codebase.

## Navigation
1. [Architectural Constitution](constitution.md)
2. [Architecture](architecture.md)
3. [Design and Integration Patterns](patterns.md)
4. [Tests](tests.md)
5. [Use Cases](use_cases.md)
6. [Modules](modules.md)
7. [Classes](classes.md)

## UML Diagrams (PlantUML)
1. Use cases: [docs/use_cases/use_cases.puml](use_cases/use_cases.puml)
2. Architecture: [docs/architecture/architecture.puml](architecture/architecture.puml)
3. Processing sequence: [docs/sequence/document_processing_sequence.puml](sequence/document_processing_sequence.puml)
4. Task state machine: [docs/state_machine/task_state_machine.puml](state_machine/task_state_machine.puml)

## Covered Scope
- Main Telegram bot runtime (aiogram) and startup flow.
- File processing flow, orchestration, and fallback behavior.
- AI agent, OpenCode/OpenRouter clients, and prompts.
- SQLite persistence for history and filesystem cache.
- Export pipeline for accessible TXT, DOCX, and PDF.
- Validations, middlewares, status tracking, and image/PDF/text utilities.
- Operational, debug, extraction scripts, and automated tests.

## Traceability Matrix
- Use cases to implementation: [use_cases.md](use_cases.md)
- Implementation by module: [modules.md](modules.md)
- Objects and responsibilities: [classes.md](classes.md)
- Test strategy and coverage: [tests.md](tests.md)

## Key Decisions Observed in Code
- The project supports cross-platform temporary directories using tempfile/gettempdir configuration.
- The active AI client is selected through AI_CLIENT (opencode by default).
- There is a conditional browser client branch in the agent that depends on a module not present in the current repository. This is documented as a technical risk in patterns.md and modules.md.
