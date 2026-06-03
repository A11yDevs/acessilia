# a11y-devs-describer Project Documentation

## Purpose
This documentation describes the modular architecture: an interface-agnostic **core/** package containing all business logic, and **interfaces/** containing pluggable front-ends (Telegram bot, Web panel).

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
- **core/** — Interface-agnostic orchestrator, AI clients (Ollama/OpenRouter), state manager, cache, history, queue, email service, utilities (logger, validators, image processing, text processing), and thin exporter wrappers.
- **interfaces/telegram/** — aiogram Bot/Dispatcher, handlers, middlewares, adapters (status tracker, file service), and AI prompts.
- **interfaces/web/** — FastAPI application with upload form and email delivery.
- **pipeline/** — Canonical document pipeline (builder, sanitizer, structure parser, validators, verbosity manager, Pandoc AST builder).
- **exporters/** — Export coordinator and format-specific renderers (TXT, DOCX, PDF, HTML).
- **renderers/** — Deterministic format renderers.
- **filters/** — Profile-based block filtering and audit stripping.
- **config/** — Centralized settings with environment variable bindings.
- **tests/** — Automated tests for pipeline, validators, renderers, and AI client.

## Traceability Matrix
- Use cases to implementation: [use_cases.md](use_cases.md)
- Implementation by module: [modules.md](modules.md)
- Objects and responsibilities: [classes.md](classes.md)
- Test strategy and coverage: [tests.md](tests.md)

## Key Decisions Observed in Code
- The canonical accessible document is the source of truth for exports and validations.
- **core/** has zero dependencies on any interface-specific library (no aiogram, no FastAPI).
- Each interface in **interfaces/** imports only from **core/**, never from another interface.
- `ENABLED_INTERFACES` environment variable controls which front-ends start at runtime.
- Output formats are rendered from the canonical document through deterministic format-specific renderers.
- Temporary directories, cache and history paths remain centralized in config/settings.py.
