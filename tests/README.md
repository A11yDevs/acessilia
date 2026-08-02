# Automated Test Suite

## Purpose
Document the automated test suite for Acessília, what each test module validates, and how to execute tests locally or inside Docker containers.

---

## Test Stack
1. **pytest**: test runner framework.
2. **pytest-asyncio**: async test execution support.
3. **respx**: HTTP request mocking for external API calls (OpenRouter / Ollama).

---

## Suite Structure & Coverage

| Test File | Target Module / Area | Validation Scope |
|---|---|---|
| `tests/test_audit_validation.py` | `backend/services/history_service.py` & audit logs | Schema validation of audit records and processing metadata. |
| `tests/test_canonical_pipeline.py` | `backend/pipeline/canonical_builder.py` | Building canonical document structures from extracted blocks. |
| `tests/test_exporters.py` | `backend/export/` & renderers | End-to-end export generation for TXT, DOCX, PDF, HTML. |
| `tests/test_pandoc_filters.py` | `backend/export/pandoc_exporter.py` | Output profile block filtering and audit data stripping. |
| `tests/test_pipeline_validation.py` | `backend/pipeline/validators.py` | Heading hierarchy, schema integrity, and output safety checks. |
| `tests/test_renderers.py` | `backend/export/renderers/` | Format-specific renderers output correctness. |
| `tests/test_structure_parser.py` | `backend/pipeline/structure_parser.py` | Parsing raw text and Markdown into structured canonical blocks. |
| `tests/test_validators.py` | `backend/tools/validators.py` | File extension, size limits, and input safety rules. |

---

## Execution Instructions

### Via Docker Container (Recommended)
```bash
docker exec -it acessilia-instance pytest
```

### Direct Local Execution (With Poetry)
```bash
poetry run pytest
```

---

## Test Design Principles
1. **Speed & Isolation:** Unit tests run quickly without requiring real external LLM API keys.
2. **HTTP Mocking:** External AI calls are mocked at the HTTP layer using `respx`.
3. **Temporary Filesystem:** Fixtures generate temporary directories for outputs, ensuring clean test runs.
4. **Async Execution:** Asynchronous workflow methods are tested via `pytest.mark.asyncio`.
