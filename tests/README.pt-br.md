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

O Core mantém cinco canônicos históricos (`001`, `004`, `005`, `007`, `008`)
em `tests/fixtures/pipeline-comparison/`, da revisão
`9ed07b28aeddb69721228f2dd66de6f9794c0001` do Dataset e do schema `1.0.0`.
O teste offline verifica os canônicos sem a Toolbox. O teste de fumaça com o
Dataset fixado e o E2E de comparação verificam o hash das entradas
correspondentes no checkout do Dataset.

Os leitores de matemática e apresentação usam o contrato
`references/manifest.csv` do Dataset (schema `1.2.0`). A CI confere a revisão
de consumo fixada em
`c436966d4fd051a2287273e471b4a3565d64a27a` com um teste de fumaça que valida o
manifesto, seletores, schemas, contagens e os dois casos sem Toolbox. A revisão
e o digest esperados ficam em
[`scripts/bench/dataset.lock.json`](../scripts/bench/dataset.lock.json).

Para uso local, `--dataset` e `ACESSILIA_TEST_DATASET_DIR` continuam aceitando
qualquer diretório compatível, inclusive uma árvore exportada sem `.git`. Um
`references/manifest.csv` novo e válido tem precedência sobre o layout legado;
manifesto novo inválido ou referência obrigatória ausente gera erro, sem
fallback para arquivos antigos. Para executar o E2E de matemática com a
revisão fixada, clone o Dataset em `tests/dataset` ou aponte a variável de
ambiente para essa revisão:

```bash
git clone https://github.com/A11yDevs/acessilia-dataset.git tests/dataset
git -C tests/dataset checkout c436966d4fd051a2287273e471b4a3565d64a27a

ACESSILIA_TEST_DATASET_DIR="$PWD/tests/dataset" uv run pytest -m e2e -v
```

O comparador histórico é uma heurística sobre o schema canônico `1.0.0`, não
uma prova estrutural nem de fidelidade do conteúdo. O protocolo atual não conta
blocos canônicos `math` como fórmulas, não lê células de `table_ast` ao extrair
texto e usa similaridade de conjuntos de palavras com tolerâncias na contagem
de blocos. Mudanças nesse protocolo precisam de versão e regressões próprias;
a simples movimentação das fixtures não deve regenerá-las.

Artefatos gerados ficam juntos no diretório de cada execução em `var/bench/`.
Incluem snapshots disponíveis, scorecards, revisão e digest efetivos do
Dataset, seleção, protocolo e configuração. A retenção é controlada pelo
operador: não há limpeza automática nem exportação para observabilidade. Os
artefatos podem conter documentos de origem e respostas de modelos; aplique a
política de armazenamento correspondente aos dados.

## Documentação relacionada
- [Arquitetura](../docs/architecture.md)
- [Contratos de avaliação do benchmark](../docs/benchmark-evaluations.md)
- [Pipeline PDDL + Agno](../docs/pmv_agno_pddl.md)
- [Internacionalização (i18n)](../docs/i18n.pt-br.md) — veja a suíte de testes de internacionalização em [test_i18n.py](test_i18n.py)
