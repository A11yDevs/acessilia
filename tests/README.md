# Automated Test Suite

A suíte unitária do projeto: pipeline canônico, motor PDDL, API e exporters. Tudo rápido e isolado — arquivos vão para diretórios temporários, rede e chamadas de LLM são mockadas, e fluxos async rodam com `pytest-asyncio`.

Pela constitution, o portão é o container: os testes precisam passar no Docker (equivalente à produção) antes do merge. A execução nativa é verificação secundária.

## Rodar

```bash
# Nativo
poetry run pytest

# Um arquivo só
poetry run pytest tests/test_pddl_planning.py

# Container (o portão — estágio `test` do infra/Dockerfile)
docker build -f infra/Dockerfile --target test -t acessilia:test-docling .
docker run --rm -v "$PWD:/app" -w /app acessilia:test-docling pytest tests/
```

## Fixtures

`fixtures/` tem PDFs e imagens de exemplo, usados tanto pelos testes quanto pelo cenário de carga e pelos benchmarks em `scripts/`.

## Documentação relacionada
- [Architecture](../docs/architecture.md)
- [PDDL + Agno pipeline](../docs/pmv_agno_pddl.md)
