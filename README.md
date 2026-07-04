# Bot Acess

**Bot‑Acess** is an open‑source project that extracts, classifies and makes documents (PDF, DOCX, TXT, etc.) accessible using LLMs (Ollama, OpenRouter) and a modular pipeline.

## Architecture (modular)

- **core** – domain logic (agents, AI clients, services, utilities, pipeline).
- **adapters** – concrete implementations that adapt the domain to external tools (exporters, renderers, filters).
- **interfaces** – entry points (Web UI via FastAPI, Telegram bot, CLI).
- **tests** – unit‑test suite covering most modules.

The project now follows a *Domain → Application → Interface* layering, making it easier to:
- Replace the LLM client (add new providers).
- Add new export formats (just implement ``AbstractExporter``).
- Swap the web framework or add a new interface without touching core logic.

## Installation

```bash
# using Poetry (recommended)
poetry install
poetry run bot-acess   # runs the CLI / starts enabled interfaces
```

## Running

- **CLI**: `poetry run bot-acess`
- **Web**: enable `web` in `ENABLED_INTERFACES` and visit `http://localhost:8000`.
- **Telegram**: enable `telegram` and provide a valid `BOT_TOKEN`.

## Contributing

1. Fork the repository.
2. Create a feature branch.
3. Write tests for new functionality.
4. Run `pytest` – ensure coverage stays high.
5. Submit a pull request.

## License

MIT © 2024‑2026 AAIF (Agentic AI Foundation)
