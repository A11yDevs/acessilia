# Inventário: contratos estruturais e fronteiras operacionais (#470, fase 1)

Também disponível em **inglês (EUA)**: [English version](operational-boundaries-inventory.md)

A [#470](https://github.com/A11yDevs/acessilia/issues/470) propõe fazer do
docstruct o núcleo estrutural portável do ecossistema e permitir que o SDK
ofereça operações e workflows determinísticos, não só transporte. A fase 1 dela
pede um diagnóstico antes de qualquer decisão. Esta página registra o que o
código e as ADRs já resolvem e o que continua em aberto. A medição foi feita na
develop em 8d7465e4 (a Toolbox nas refs da seção dela, abaixo), com uma varredura de AST que inclui os imports dentro de
funções. A [ADR-0017](../adr/0017-operational-sdk-and-agentic-core.pt-br.md)
parte daqui.

## O que já está decidido e verificado

Boa parte da #470 repete a [ADR-0002](../adr/0002-component-responsibilities.pt-br.md),
que já foi aceita:

| Princípio da #470 | Onde já vale |
|---|---|
| P1, portabilidade (só a biblioteca padrão, aceleradores opcionais protegidos) | Tabela e conformidade da ADR-0002; o `libs/docstruct/tests/test_purity.py` confere que o `pyproject.toml` não declara dependência de execução, que todo outro import é um acelerador listado atrás de `except ImportError` e que todo módulo é importado num interpretador que recusa tudo fora da biblioteca padrão. O único acelerador é o `rapidfuzz`, em `evaluation/metrics/text_ed.py`. A alternativa A da #470, portanto, já está em vigor. |
| P2, contratos estruturais compartilhados | [ADR-0007](../adr/0007-manifest-model-and-mathml-conversion.pt-br.md) e #203: o `docstruct.manifest` é o modelo normativo do documento. Os modelos pydantic do core e da Toolbox ficam só como modelos de transporte 1.1.0, conferidos contra o `docstruct.manifest.field_specs` em testes de contrato. |
| P3, independência de infraestrutura | **Em parte.** A tabela da ADR-0002 enuncia a regra. O `test_purity.py` confere dependências e imports, mas permite toda a biblioteca padrão: um módulo que lê `os.environ` ou um arquivo ao ser importado ainda passa, como a revisão da #471 reproduziu. A parte de rede, ambiente, arquivos e subprocessos ainda não é testada. |
| Direção das dependências, sem ciclos | A ADR-0002 já permite **SDK → docstruct** e oferece "acesso em processo aos algoritmos puros do docstruct" pelo SDK. O `test_purity.py` do SDK mantém as dependências dele "dentro do `httpx` e do docstruct". |
| P7, uma implementação por algoritmo estrutural | ADR-0002 e #203; o `tests/test_docstruct_bridges.py` falha com uma nova cópia de um algoritmo já ligado ao docstruct. |
| A Toolbox não importa o core nem o SDK | O `tests/unit/test_architecture.py` da Toolbox. Fora dele, `acessilia_sdk` e `backend` aparecem só em um teste entre projetos (`tests/cross_project/test_core_storage_outage.py`). |

## O que difere entre as ADRs e o código

- **O SDK não usa o docstruct, e o job isolado do CI o proíbe.** A ADR-0002
  permite a dependência, mas o `libs/sdk/pyproject.toml` declara só o `httpx`.
  O job `SDK alone` recusa o `docstruct` junto com o `backend`, a Toolbox, o
  Agno e o FastAPI. Se o SDK compuser algoritmos do docstruct (#470, P5), a
  dependência e esse job mudam.
- **A Toolbox e o core concordam sobre o docstruct só por convenção.** Cada
  branch da Toolbox fixa o wheel de release do docstruct pelo SHA-256, e as
  versões fixadas batem com os branches do core:

  | Branch | Core (`libs/docstruct`) | Toolbox (`pyproject.toml`) |
  |---|---|---|
  | `main` | 0.4.0 (cac215df) | `docstruct-v0.4.0` (e77869be) |
  | `develop` | 0.5.0 (b6ca0ecf) | `docstruct-v0.5.0` (77c7df7c), desde o db866c60 da acessilia-toolbox (2026-11-02) |

  Então não há divergência hoje. Mas nada confere se uma release do docstruct
  e a versão fixada pela Toolbox andam juntas, nem se os dois ainda concordam
  sobre os modelos compartilhados: é o risco da P8 da #470.
- **O docstruct não tem job de instalação isolada.** O `test_purity.py` recusa
  imports fora da biblioteca padrão num subprocesso, mas nenhum job de CI
  instala o docstruct sozinho num ambiente limpo, como o `SDK alone` faz com o
  SDK.
- **A independência de infraestrutura do docstruct não é testada.** Veja a P3
  acima. Um job de instalação isolada também não a pegaria: é preciso um teste
  de que nenhum módulo lê o ambiente ou arquivos, abre sockets ou inicia
  subprocessos.

## Algoritmos estruturais: core e docstruct

19 funções têm o mesmo nome no core e no docstruct. 15 são adaptadores que
chamam o docstruct, então não há duplicação nelas:
- `pipeline/canonical_builder.py`, `pipeline/validators.py` e
  `pipeline/table_ast.py`;
- `refine_reading_order` e `is_unstructured_page_placeholder` no builder do
  manifesto;
- `_pair_block`, `_letterhead_groups`, `_recover_empty_lettered_list_items` e
  `_implicit_product_variables` do orquestrador;
- `wrap_latex`.

O resto, com as duplicações já registradas:

| Core | docstruct | Achado |
|---|---|---|
| `_table_ast_from_rows` (orquestrador) | `docstruct.tables.ast.table_ast_from_rows` | Quase duplicata com comportamento diferente: `{"body": []}` contra `None` sem linhas. Registrada no inventário do orquestrador; unificar é uma decisão de comportamento. |
| `_block_kind` (orquestrador) | `docstruct.fusion.convert.classify_kind` | Quase duplicata com comportamento diferente. Registrada no inventário do orquestrador. |
| `_area` (`backend/core/manifest/slides.py`) | `docstruct.fusion.similarity.area` | O mesmo cálculo, para uma caixa presente. |
| `_overlaps`, `_union_area` (`slides.py`) | nenhuma | Geometria pura de caixas; candidatas ao docstruct. (O `_overlaps` do docstruct compara trechos de texto, não caixas.) |
| `decide` (`planning/toolbox_gate.py`) | `docstruct.fusion.adjudication.decide` | Só o nome é igual; não têm relação. |
| agrupamento de callouts (builder de normalização da Toolbox) | `docstruct.regions.grouping` | Desvio conhecido da ADR-0002 ([acessilia-toolbox#72](https://github.com/A11yDevs/acessilia-toolbox/issues/72)). |

## Operações determinísticas no core

Pela P4 da #470, estes são mecanismos que o core executa com parâmetros
explícitos, ao lado da política que decide quando e sobre o quê. São
candidatos a operações do SDK, com a parte da decisão ficando no core:

| Operação | Hoje | Mecanismo (candidato ao SDK) | Decisão (fica no core) |
|---|---|---|---|
| Cadeia de fórmula | `_formula_recognition_crop`, `toolbox_math_tools`, o enriquecimento de fórmulas | renderizar uma região e depois `math.recognize`, `math.convert` e `math.verbalize` em sequência | quais fórmulas, o portão de concordância com a camada de texto, o fallback da visão, o disjuntor |
| Juiz de página | `_render_page_png`, `_judge_page`, `_judge_one_page` | renderizar uma página e depois `document.adjudicate.page`, lendo o `pB` | quais páginas, o limiar, se troca |
| Inspeção de mídia | `backend/tools/media_inspect.py` | `media.inspect` | o que uma apresentação ou um limite de páginas significa para o job |
| Auditoria PDF/UA | `backend/tools/pdf_ua_audit.py` | `pdf.validate.pdf_ua` | o que uma auditoria reprovada faz com o job |
| Text spans | `backend/tools/text_spans.py` | já é `ToolboxPdfClient.text_spans_by_page` (#455) | quais páginas, o cache por documento |
| Exportação Pandoc | `backend/export/pandoc_exporter.py` | `document.export.pdf_ua`, `document.export.docx` | qual perfil, quais formatos |

## Em aberto, para a ADR-0017 e as seguintes

- Quais dessas operações viram operações do SDK, e em que ordem. A cadeia de
  fórmula é a prova de conceito que a #402 e a #470 citam.
- Qual é a API pública estável do docstruct.
- Como uma mudança do docstruct chega à Toolbox, e como os dois são conferidos
  um contra o outro.
- Se o SDK deve executar um contrato de plano operacional. A #470 registra o
  risco de o SDK virar um segundo orquestrador.
