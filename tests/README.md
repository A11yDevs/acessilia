# Automated Test Suite (tests)

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](README.pt-br.md)

The project's unit test suite covers the canonical pipeline, PDDL engine, API and exporters. Everything is fast and isolated: files go to temporary directories; network and LLM calls are mocked, and async flows run with `pytest-asyncio`.

By constitution, the gate is the container: tests must pass inside Docker (production equivalent) before a merge. The native run is secondary verification.

## Running

```bash
# Native
poetry run pytest

# A single file only
poetry run pytest tests/test_pddl_planning.py

# Container (the gate — the `test` stage of infra/Dockerfile)
docker build -f infra/Dockerfile --target test -t acessilia:test-docling .
docker run --rm -v "$PWD:/app" -w /app acessilia:test-docling pytest tests/
```

## Fixtures

`fixtures/` holds sample PDFs and images, used both by the tests and by the load scenarios and benchmarks in `scripts/`.

## Related documentation
- [Architecture](../docs/architecture.md)
- [PDDL + Agno pipeline](../docs/pmv_agno_pddl.md)
- [Internationalization (i18n)](../docs/i18n.md) — see the internationalization test suite in [test_i18n.py](test_i18n.py)
