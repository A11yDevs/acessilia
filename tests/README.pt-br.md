# Suíte Automatizada de Testes (tests)

Também disponível em **inglês (EUA)**: [English version](README.md)

A suíte de testes unitários do projeto cobre o pipeline canônico, o motor PDDL, a API e os exportadores. Tudo é rápido e isolado: arquivos vão para diretórios temporários; chamadas de rede e de LLM são simuladas (mock), e os fluxos assíncronos rodam com `pytest-asyncio`.

Por constituição, o portão é o container: os testes devem passar dentro do Docker (equivalente à produção) antes de um merge. A execução nativa é a verificação secundária.

## Execução

```bash
# Nativa
poetry run pytest

# Apenas um arquivo
poetry run pytest tests/test_pddl_planning.py

# Container (o portão — o estágio `test` de infra/Dockerfile)
docker build -f infra/Dockerfile --target test -t acessilia:test-docling .
docker run --rm -v "$PWD:/app" -w /app acessilia:test-docling pytest tests/
```

## Fixtures

`fixtures/` guarda os PDFs e imagens de exemplo, usados tanto pelos testes quanto pelos cenários de carga e benchmarks em `scripts/`.

## Documentação relacionada
- [Arquitetura](../docs/architecture.md)
- [Pipeline PDDL + Agno](../docs/pmv_agno_pddl.md)
- [Internacionalização (i18n)](../docs/i18n.pt-br.md) — veja a suíte de testes de internacionalização em [test_i18n.py](test_i18n.py)
