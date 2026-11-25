# Suíte Automatizada de Testes (tests)

Também disponível em **inglês (EUA)**: [English version](README.md)

A suíte de testes unitários do projeto cobre o pipeline canônico, o motor PDDL, a API e os exportadores. Tudo é rápido e isolado: arquivos vão para diretórios temporários; chamadas de rede e de LLM são simuladas (mock), e os fluxos assíncronos rodam com `pytest-asyncio`.

O gate de merge é o CI, que executa as suítes principal, da biblioteca do core,
da docstruct e do SDK no Python 3.12, no ambiente do `uv.lock` da raiz. Jobs adicionais testam as
bibliotecas isoladamente a partir dos próprios locks. A imagem de produção
carrega dependências de runtime e passa por verificações de build, inicialização
e saúde da API por smoke tests antes da publicação. Veja a
[estratégia de testes da constituição](../docs/constitution.pt-br.md#3-regras-de-qualidade-arquitetural).

As regressões da issue #342 cobrem continuações de listas após parágrafos e tabelas com numeração explicitamente consecutiva. O scorecard separa sequências quando o grupo de origem muda sem numeração de continuação correspondente, a numeração reinicia explicitamente, muda de estilo, pula um número, cruza títulos ou páginas ou encontra blocos diferentes de parágrafos, tabelas ou fórmulas. Blocos adjacentes antigos sem metadados de grupo mantêm seu agrupamento. TXT/MP3 continuam usando a fala enriquecida conforme o ADR-0011; use as expectativas atuais do dataset, que aceitam o sinal negativo falado.

## Execução

O fluxo local suportado está descrito em [docs/testing.pt-br.md](../docs/testing.pt-br.md):

```bash
# Tudo o que a CI executa, sem E2E (suíte principal, docstruct, SDK e libs/core)
make test-all

# Um arquivo ou um node id
make test-file F=tests/test_pddl_planning.py

# Reexecuta os testes que falharam na última vez
make test-failed
```

Os comandos equivalentes do pytest:

```bash
# Nativa
uv run pytest

# Apenas um arquivo
uv run pytest tests/test_pddl_planning.py
```

## Fixtures

`fixtures/` guarda os PDFs e imagens de exemplo, usados tanto pelos testes quanto pelos cenários de carga e benchmarks em `scripts/`. `fixtures/failures/` guarda documentos corrompidos inertes usados por `test_job_failure_e2e.py` para reproduzir a falha do pipeline e o e-mail de falha; veja o [README](fixtures/failures/README.md). Não há flag de debug envolvida: os arquivos vivem apenas na árvore de testes.

## Compatibilidade de tipos canônicos legados

A compatibilidade E1.3 é coberta por
`libs/docstruct/tests/test_legacy_canonical_types.py`: metadados de descontinuação,
identidade dos reexports da raiz, compatibilidade de construtores/campos, defaults,
estado serializado, leitura de pickle anterior à descontinuação (0.5.2) e imports/
construção em processo novo tratando warnings como erros. Esses testes também
rodam contra o wheel instalado. As suítes existentes de tipos e caracterização
dos exports mantêm sua cobertura. Veja o
[ADR 0024](../docs/adr/0024-legacy-canonical-type-deprecation.pt-br.md).

## Contrato de schema canônico

O contrato de schema canônico é conferido separadamente:
`libs/docstruct/tests/test_schema_validation.py` cobre o draft empacotado,
validador injetado, propagação de falhas e saída do builder incluindo filhos;
`libs/core/tests/test_canonical_schema_contract.py` confere a cópia da raiz, o builder do
core e a aceitação preservada de tipos personalizados no export. A CI também
valida o schema do wheel instalado fora do checkout. `jsonschema` é apenas dev
na docstruct; os guards de runtime com biblioteca padrão e de infraestrutura
continuam rodando, com a exceção do recurso fixo registrada no ADR 0023.

Regenerar/conferir o schema histórico da raiz após editar a fonte do pacote:

```bash
uv run python scripts/sync_accessible_document_schema.py
uv run python scripts/sync_accessible_document_schema.py --check
```

O Core 0.2.0 valida após normalização/auditoria e antes do perfil.
`libs/core/tests/test_export_schema_gate.py` verifica 68 resultados antes/depois, normalização,
filhos/blocos filtrados, ausência de efeitos do renderer em chamadas diretas
ao Core e diagnóstico localizado. O teste do worker observa criação do
diretório antes do export, rejeição e remoção posterior, além de histórico
de erro e ausência de token. Veja o
[corpus de compatibilidade](fixtures/export_schema_gate/README.pt-br.md) e a [API de schema](../libs/docstruct/README.pt-br.md#schema-canônico-docstructschemas-docstructvalidation).

## Caracterização dos exports

A linha de base de paridade dos exports da #371 fica em
[`fixtures/export_snapshots/`](fixtures/export_snapshots/README.pt-br.md).
`libs/docstruct/tests/test_export_characterization.py` congela as quatro APIs
puras de export, suas políticas atuais de omissão/filtro e os dois destinos
Pandoc. Executa nativamente, contra o wheel isolado e em contêiner de CI travado
pelo lock. Manter seus arquivos de referência inalterados durante a extração/
migração do walker.

`test_export_walk.py` verifica a travessia E1.6, despacho por tipo, fallback,
seleção e metadados dos contextos. Para a E1.7, `test_export_walk_parity.py`
observa todas as 30 chamadas caracterizadas usando o walker de produção e
verifica a renderização pelos onze callbacks e fallback explícito. Substitui as
antigas trocas de travessia feitas apenas nos testes. Preserva também a rejeição
existente de tipos de bloco não hasháveis em TXT/HTML/Pandoc, sua aceitação no
Markdown e a filtragem antes da rejeição. O gate de referência inalterado ainda
verifica saída exata e políticas distintas de títulos/rótulos nos filhos.
Esses testes rodam no mesmo contêiner travado. Veja a
[API do walker](../libs/docstruct/README.pt-br.md#walker-de-exportação-docstructexportwalk).

## Fixtures diferenciais da saída canônica

[`differential/`](differential/README.pt-br.md) roda documentos inteiros pelo
caminho do backend contra um Toolbox determinístico, em processo, e compara
cada documento canônico com referências gravadas no core antes de cada
migração da #640 (#849). `test_differential_canonical.py` roda na suíte
normal; uma diferença que uma release posterior fez de propósito é declarada
junto da sua referência.

## Testes end-to-end

Os testes marcados com `-m e2e` ficam fora da CI e precisam de um ambiente real:

```bash
# Somente Toolbox (suíte existente)
TOOLBOX_BASE_URL=https://toolbox.example/toolbox \
TOOLBOX_API_KEY="$TOOLBOX_API_KEY" \
uv run pytest -m e2e -v --timeout=900

# Também o core implantado (tests/test_core_api_e2e.py)
CORE_BASE_URL=https://core.example/api/v1 \
CORE_EXPECT_BUILD_INFO=1 \
uv run pytest -m e2e -v --timeout=900
```

`--timeout=900` substitui o limite global de 180 segundos da suíte: operações
E2E podem levar até 300 segundos e uma espera de job do core, até 600. O job
agendado de E2E usa o mesmo valor. O caso do deck completo é a exceção: usa
`CORE_SLIDE_TIMEOUT` (padrão 3600 s) e se marca para essa espera mais 600 s.

O workflow `Scheduled test monitoring` roda a suíte E2E semanalmente quando as
variáveis do repositório `TOOLBOX_BASE_URL` ou `CORE_BASE_URL` estão
configuradas. Ele usa o secret opcional `TOOLBOX_API_KEY` e a variável
`CORE_EXPECT_BUILD_INFO`; o corpus opcional do dataset não é clonado ali, então
esses casos são pulados. O E2E é uma validação agendada, não um portão de merge.

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
- `test_slide_case_e2e.py` lê o `input/presentation-reference/` auditado
  (o deck 006, issue #615) e envia a cópia byte-idêntica em
  `fixtures/presentations/`. É um caso manual/slow: use
  `CORE_SLIDE_CASE=1` para rodá-lo. O teste fixa a revisão do dataset
  `8e51a1f` por hash dos arquivos e `CORE_SLIDE_TIMEOUT` (padrão 3600 s)
  limita a espera; cada execução grava saídas, scorecards e `run.json` em um
  diretório exclusivo em `var/bench/slides/e2e/`.

Para rodar esses casos contra um clone mantido no checkout principal:

```bash
git clone https://github.com/A11yDevs/acessilia-dataset.git tests/dataset
git -C tests/dataset archive origin/feat/036-velocidade-instantanea \
    input/math-reference | tar -x -C tests/dataset

ACESSILIA_TEST_DATASET_DIR="$PWD/tests/dataset" uv run pytest -m e2e -v
```

## Documentação relacionada
- [Fluxo local de testes](../docs/testing.pt-br.md) — comandos `make`, tempos de linha de base e timeouts
- [Arquitetura](../docs/architecture.md)
- [Pipeline PDDL + Agno](../docs/pddl_pipeline.pt-br.md)
- [Internacionalização (i18n)](../docs/i18n.pt-br.md) — veja a suíte de testes de internacionalização em [test_i18n.py](test_i18n.py)

## Compatibilidade do catálogo de formatos

`test_export_catalog.py` fixa identidades, labels da API, MIME types, nomes,
papéis de entrega distintos, referências ao SDK e plano do worker em E1.9.
`test_download_token_service.py` verifica arquivos existentes, incluindo PDF
legado, nos dois idiomas. `test_web_panel.py` exclui entradas internas e
experimentais dos formatos oferecidos. Regressões do worker cobrem falhas
obrigatórias de TXT/HTML/ZIP, falhas opcionais de benchmark/remotos/áudio, flags,
ordem de formatos concluídos e de entradas do pacote.
`libs/docstruct/tests/test_format_spec.py` também roda contra o wheel isolado.
Os goldens E1.0 permanecem iguais. Veja o
[ADR 0025](../docs/adr/0025-format-catalogue-ownership.pt-br.md).
