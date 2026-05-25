# a11y-devs-describer Project Documentation

## Purpose
This documentation describes the current canonical document architecture, the modular pipeline, the deterministic renderers, and the operational runtime around the Telegram bot.

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
3. Layers: [docs/architecture/layers.puml](architecture/layers.puml)
4. Processing sequence: [docs/sequence/document_processing_sequence.puml](sequence/document_processing_sequence.puml)
5. Task state machine: [docs/state_machine/task_state_machine.puml](state_machine/task_state_machine.puml)

## Covered Scope
- Main Telegram bot runtime (aiogram) and startup flow.
- File processing flow, orchestration, hybrid extraction, and fallback behavior.
- Canonical JSON document model, schema validation, and Pandoc-style AST build step.
- Hybrid extraction agent (PyMuPDF local-first + AI vision when needed), OpenCode/OpenRouter clients, and prompts.
- SQLite persistence for history and filesystem cache.
- Export pipeline for accessible TXT, DOCX, PDF, and HTML.
- Deterministic renderers and output profiles.
- Validations, middlewares, status tracking, and image/PDF/text utilities.
- Operational, debug, extraction scripts, and automated tests.

## Traceability Matrix
- Use cases to implementation: [use_cases.md](use_cases.md)
- Implementation by module: [modules.md](modules.md)
- Objects and responsibilities: [classes.md](classes.md)
- Test strategy and coverage: [tests.md](tests.md)

## Key Decisions Observed in Code
- The canonical accessible document is the source of truth for exports and validations.
- Output formats are rendered from the canonical document through deterministic format-specific renderers.
- Output profiles control verbosity and audit metadata inclusion per format.
- Temporary directories, cache and history paths remain centralized in config/settings.py.
