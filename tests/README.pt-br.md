# Suíte Automatizada de Testes (tests)

Também disponível em **inglês (EUA)**: [English version](README.md)

A suíte de testes unitários do projeto cobre o pipeline canônico, o motor PDDL, a API e os exportadores. Tudo é rápido e isolado: arquivos vão para diretórios temporários; chamadas de rede e de LLM são simuladas (mock), e os fluxos assíncronos rodam com `pytest-asyncio`.

Por constituição, o portão é o container: os testes devem passar dentro do Docker (equivalente à produção) antes de um merge. A execução nativa é a verificação secundária.

As regressões da issue #342 cobrem continuações de listas após parágrafos e tabelas com numeração explicitamente consecutiva. O scorecard separa sequências quando o grupo de origem muda sem numeração de continuação correspondente, a numeração reinicia explicitamente, muda de estilo, pula um número, cruza títulos ou páginas ou encontra blocos diferentes de parágrafos, tabelas ou fórmulas. Blocos adjacentes antigos sem metadados de grupo mantêm seu agrupamento. TXT/MP3 continuam usando a fala enriquecida conforme o ADR-0011; use as expectativas atuais do dataset, que aceitam o sinal negativo falado.

## Execução

```bash
# Nativa
uv run pytest

# Apenas um arquivo
uv run pytest tests/test_pddl_planning.py

# Container (o portão — o estágio `test` de infra/Dockerfile)
docker build -f infra/Dockerfile --target test -t acessilia:test-docling .
docker run --rm -v "$PWD:/app" -w /app acessilia:test-docling pytest tests/
```

## Fixtures

`fixtures/` guarda os PDFs e imagens de exemplo, usados tanto pelos testes quanto pelos cenários de carga e benchmarks em `scripts/`. `fixtures/failures/` guarda documentos corrompidos inertes usados por `test_job_failure_e2e.py` para reproduzir a falha do pipeline e o e-mail de falha; veja o [README](fixtures/failures/README.md). Não há flag de debug envolvida: os arquivos vivem apenas na árvore de testes.

## Testes end-to-end

Os testes marcados com `-m e2e` ficam fora da CI e precisam de um ambiente real:

```bash
# Somente Toolbox (suíte existente)
TOOLBOX_BASE_URL=https://toolbox.example/toolbox \
TOOLBOX_API_KEY="$TOOLBOX_API_KEY" \
uv run pytest -m e2e -v

# Também o core implantado (tests/test_core_api_e2e.py)
CORE_BASE_URL=https://core.example/api/v1 \
CORE_EXPECT_BUILD_INFO=1 \
uv run pytest -m e2e -v
```

O `tests/test_core_api_e2e.py` só é pulado enquanto `CORE_BASE_URL` não estiver
definido. Depois de definido, um core inalcançável ou um `/health` doente
reprovam a execução: uma suíte pulada não pode passar durante uma indisponibilidade
real. Um job que não chega a estado terminal é cancelado ao fim da espera.

Alguns testes E2E usam o corpus opcional do
[A11yDevs/acessilia-dataset](https://github.com/A11yDevs/acessilia-dataset).
Ele é um clone separado, ignorado pelo Git, colocado em `tests/dataset/`; use
`ACESSILIA_TEST_DATASET_DIR` para apontar para outro diretório sem copiar o
corpus para o checkout.

- `test_compare_pipelines_e2e.py` lê `input/00{1,4,5,7,8}.*` e
  `intermediate/canonical-document/*.json`; sem o clone, os 25 casos
  baseados em referência são pulados.
- `test_math_case_e2e.py` lê `input/math-reference/` do branch
  `feat/036-velocidade-instantanea` do dataset; ele não está na `main`.

Para rodar esses casos contra um clone mantido no checkout principal:

```bash
git clone https://github.com/A11yDevs/acessilia-dataset.git tests/dataset
git -C tests/dataset archive origin/feat/036-velocidade-instantanea \
    input/math-reference | tar -x -C tests/dataset

ACESSILIA_TEST_DATASET_DIR="$PWD/tests/dataset" uv run pytest -m e2e -v
```

## Documentação relacionada
- [Arquitetura](../docs/architecture.md)
- [Pipeline PDDL + Agno](../docs/pmv_agno_pddl.md)
- [Internacionalização (i18n)](../docs/i18n.pt-br.md) — veja a suíte de testes de internacionalização em [test_i18n.py](test_i18n.py)
