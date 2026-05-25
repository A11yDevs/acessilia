# Tests

## Purpose
Document the automated tests available in the repository, what they validate, and which runtime behavior they cover.

## Test stack
1. [pytest](../requirements.txt)
2. [pytest-asyncio](../requirements.txt)
3. [respx](../requirements.txt)

## Current coverage

## 1. Validators
- File: [tests/test_validators.py](../tests/test_validators.py)
- Scope:
  - allowed extensions
  - file size limits
  - combined file validation
- Covered code:
  - [bot/utils/validators.py](../bot/utils/validators.py)
  - indirectly [config/settings.py](../config/settings.py)

## 2. Exporters
- File: [tests/test_exporters.py](../tests/test_exporters.py)
- Scope:
  - TXT export
  - DOCX export
  - PDF export
  - empty text export
- Covered code:
  - [bot/exporters/txt_exporter.py](../bot/exporters/txt_exporter.py)
  - [bot/exporters/docx_exporter.py](../bot/exporters/docx_exporter.py)
  - [bot/exporters/pdf_exporter.py](../bot/exporters/pdf_exporter.py)

## 3. OpenRouter client
- File: [tests/test_openrouter_client.py](../tests/test_openrouter_client.py)
- Scope:
  - successful multimodal request
  - retry after rate limit (429)
  - missing API key error
- Covered code:
  - [bot/clients/openrouter.py](../bot/clients/openrouter.py)
  - [config/settings.py](../config/settings.py)

## Test design principles already present
1. Unit tests are isolated and fast.
2. Temporary directories are used for filesystem outputs.
3. Network calls are mocked with HTTP-level fakes.
4. Async flows are validated with pytest-asyncio.

## Coverage gaps
1. No direct tests yet for [bot/agente_mestre.py](../bot/agente_mestre.py).
2. No direct tests yet for [bot/agents/agente_unico.py](../bot/agents/agente_unico.py).
3. No direct tests yet for [bot/handlers/document.py](../bot/handlers/document.py).
4. No direct tests yet for [bot/handlers/start.py](../bot/handlers/start.py).
5. No direct tests yet for [bot/services/cache.py](../bot/services/cache.py), [bot/services/history_service.py](../bot/services/history_service.py), or [bot/services/queue_service.py](../bot/services/queue_service.py).

## Recommended next tests
1. Conversion pipeline happy path with mocked AI client.
2. Fallback path when the AI client raises an exception.
3. Task cancellation flow via state_manager.
4. Telegram handler integration for document uploads.
5. Cache hit/miss behavior for file and page caches.

## How to run
```bash
pytest tests/
```

## Related documentation
- [Architecture](architecture.md)
- [Use Cases](use_cases.md)
- [Modules](modules.md)