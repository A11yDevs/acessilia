# Algoritmos de docstruct — Fusão, Auditoria, Classificação e Re-inferência

Também disponível em **inglês (EUA)**: [English version](docstruct_algorithms.md)

Este documento explica como funcionam os algoritmos determinísticos por trás
da biblioteca `docstruct` e como os agentes de Acessilia os invocam. É o
companheiro de [`libs/docstruct/README.md`](../../libs/docstruct/README.md)
(API pública) e de [`pmv_agno_pddl.md`](pmv_agno_pddl.md) (orquestração PDDL).

## Escopo

A biblioteca `docstruct` (`libs/docstruct/`) é um núcleo **puro** de
processamento estrutural de documentos: nenhuma função toca a rede, o sistema
de arquivos, subprocessos, configuração, o logger ou i18n dinâmico. É a única
fonte de verdade para os algoritmos descritos aqui. O backend (`backend/`)
fornece as pontes de I/O, configuração e i18n, e os agentes Agno expõem os
algoritmos como ferramentas.

```
backend (agentes Agno, PDDL, I/O, configuração, i18n)
   │  depende de
   ▼
docstruct (algoritmos puros)
```

---

## 1. Fusão multi-provider (Tree Differ)

### 1.1 Objetivo

Dois providers de extração de estrutura (por padrão **Docling** e **MinerU**)
produzem listas de blocos independentes para o mesmo documento. Cada provider
é bom em coisas distintas: Docling é forte em ordem de leitura e títulos;
MinerU é forte em qualidade de texto e extração de fórmulas. A fusão os
combina em uma única sequência de blocos de maior qualidade.

### 1.2 Pipeline (`backend/pipeline/fusion.py`)

`extract_fused()` orquestra os dois providers e chama o puro
`docstruct.fusion.merge_blocks()`:

1. Extrai com o provider **primário** (por padrão `docling`).
2. Extrai com o provider **secundário** (por padrão `mineru`), em paralelo.
3. Converte o payload de cada provider em blocos canônicos (com bbox).
4. Agrupa os blocos por página.
5. Para cada página, chama `merge_blocks(D, M, policy)` onde `D` = blocos de
   Docling e `M` = blocos de MinerU.
6. Serializa os blocos fundidos em markdown.

**Fallback:** se o provider secundário falha, `extract_fused` usa
silenciosamente só o primário. O handler PDDL `dual-provider-fusion` trata
isso como **falha** (ver [§5](#5-como-os-agentes-invocam-os-algoritmos))
porque a semântica dual planejada não foi realmente executada.

### 1.3 O Tree Differ (`docstruct.fusion.differ.merge_blocks`)

`merge_blocks(D, M, policy)` é a porta do Tree Differ v2 da PR #98
(Dr.DocBench). É executado em etapas:

#### Etapa A — Pré-processamento (redução de ruído)

- **Rebaixamento de fórmulas** (`formula_text`): as fórmulas sem operador
  matemático são rebaixadas a texto simples.
- **Supressão de regiões** (`suppress_regions`): o texto de Docling que cai
  dentro de uma tabela/figura de MinerU é suprimido (a menos que a página
  quase não tenha texto).
- **Decor-tail** (`decor_tail`): cabeçalhos/rodapés e números de página são
  separados e movidos para o fim da página.
- **Filtro de lixo** (`junk_filter`): os blocos que parecem lixo (p. ex.
  tokens soltos) são descartados.
- **Fusão de linhas** (`fuse_lines`): as sequências de linhas consecutivas são
  fundidas.
- **Re-fusão de parágrafos** (`merge_paragraphs`): os parágrafos divididos são
  reagrupados.

#### Etapa B — Alinhamento Húngaro

O passo central de pareamento. Constrói-se uma matriz de custos em que cada
célula é:

```
cost(i, j) = (1 - λ) * (1 - sim(texto_i, texto_j)) + λ * (1 - IoU(caixa_i, caixa_j))
```

- `sim(texto)` é uma similaridade de texto (sobreposição de tokens).
- `IoU(caixa)` é a interseção-sobre-união das duas caixas delimitadoras.
- `λ = policy.align_lambda` (por padrão `0.5`) pondera texto vs geometria.

Uma atribuição pura **Kuhn–Munkres** (Húngara) (`_hungarian.py`, O(n³), sem
scipy) encontra o pareamento um-para-um de custo mínimo. Os pares cujo custo
supera `policy.align_tau` (por padrão `0.6`) ficam **sem pareamento**.

#### Etapa C — Esqueleto de ordem de leitura

A ordem de leitura segue o provider B (**MinerU**). Para cada bloco de
MinerU:

- se pareou com um bloco de Docling, o texto é escolhido com `_pick_text`
  (ver abaixo);
- se é unilateral (sem pareamento), mantém-se o próprio texto.

#### Etapa D — Inserção de blocos Docling unilaterais

Os blocos de Docling que não parearam são inseridos junto ao seu **vizinho
geometricamente mais próximo** no esqueleto de MinerU (acima ou abaixo, de
acordo com o centro vertical). Os blocos de texto curtos (`len < min_len`) são
descartados, e os blocos que "engolem" vários blocos de MinerU também são
descartados (`pick_guard`).

#### Etapa E — Seleção de texto (`_pick_text`)

Para um par pareado, o texto é escolhido conforme `policy.text_pick`:

- `docling` → sempre Docling;
- `mineru` → sempre MinerU;
- `auto` (por padrão) → MinerU vence no corpo, a menos que tenha truncado o
  texto ou tenha pior qualidade de OCR; Docling vence quando é
  significativamente mais longo ou quando MinerU engoliu colunas.

### 1.4 `FusionPolicy`

`FusionPolicy` é um dataclass congelado com **defaults conservadores e
neutros**. Os presets ajustados ao benchmark (`drbench_v12`, `drbench_v13`)
são classmethods nomeados, nunca defaults, porque foram sobreajustados ao
split dev (gap dev→test ≈ −6).

---

## 2. Auditoria do documento canônico

### 2.1 Objetivo

Validar um documento canônico e coletar achados estruturados para que os
renderers e consumidores posteriores possam confiar em sua estrutura.

### 2.2 `validate_canonical_document`

Verifica os invariantes estruturais de um documento canônico:

- campos obrigatórios (`schema_version`, `id`, `title`, `language`, `sections`);
- ids de bloco duplicados;
- hierarquia de títulos (exatamente um H1, sem níveis pulados, o primeiro
  título é H1);
- vazamentos de prompt e markdown solto no texto de parágrafos;
- consistência de indentação de código;
- estrutura de tabelas (linhas, colunas, células, `table_ast`);
- links internos quebrados.

### 2.3 `audit_canonical_document`

Executa a validação base mais uma auditoria de acessibilidade e agrupa os
achados por severidade:

| Severidade | Significado |
|---|---|
| `BLOCKER` | Falhas estruturais (erros de validação base, seções ausentes). |
| `WARNING` | Achados de acessibilidade (imagens sem alt-text, tabelas sem cabeçalhos explícitos). |

Os achados são retornados como tuplas `(msgid, kwargs)` — o msgid canônico é
a única fonte de verdade; o backend o resolve por meio de seu catálogo i18n.

---

## 3. Classificação de regiões

### 3.1 Objetivo

Classificar uma região de página em uma categoria de processamento para que o
pipeline saiba como tratá-la (visão, OCR, linearização de tabelas,
verbalização de fórmulas, ou ignorar).

### 3.2 `classify_region`

`docstruct.regions.classify.classify_region(region)` mapeia uma `Region` a uma
categoria:

| Tipo de região | Classificações possíveis |
|---|---|
| `image` | `embedded_image` (confiança alta + bytes), `unknown` (grande), `ignore` |
| `table` | `table` (tem texto ou é grande), `ignore` |
| `formula` | `formula` (grande), `ignore` |
| `text` | `text_clean`, `text_scanned`, `code_block`, `list_block`, `unknown`, `ignore` |
| `unknown` | `unknown` (grande), `ignore` |

As regiões de Docling vêm pré-classificadas e são mapeadas por meio de
`DOCLING_CLASSIFICATION`.

### 3.3 `region_needs_vision`

Retorna `True` para as categorias que exigem uma passada de visão/LLM:
`text_scanned`, `embedded_image`, `unknown`, `table`, `formula`.

### 3.4 `needs_reinfer`

A ferramenta `FusionAgent.needs_reinfer` classifica a região e informa se ela
precisa de re-inferência (visão ou correção de orientação). É o portão
determinístico que decide se uma passada de LLM é necessária.

---

## 4. O `FusionAgent` (envelope de ferramentas Agno)

`backend/core/agents/fusion_agent.py` expõe os algoritmos como ferramentas
Agno, seguindo o padrão `InformationalStructuralAgent`: cada capacidade tem
um método `process_*` puro (testável sem Agno) mais um envelope JSON fino.

| Ferramenta | Núcleo determinístico | Propósito |
|---|---|---|
| `fuse_providers` | `process_fuse_providers` → `extract_fused` | Fundir dois providers de toolbox. |
| `audit_document` | `process_audit_document` → `audit_canonical_document` | Auditar um documento canônico. |
| `classify_block` | `process_classify_block` → `classify_region` | Classificar uma região. |
| `needs_reinfer` | `process_needs_reinfer` → `classify_region` + `region_needs_vision` | Decidir se uma região precisa de re-inferência. |

**Nota de design:** os envelopes de ferramentas intencionalmente **não**
serializam `image_bytes` — reconstruem uma `Region` com `image_bytes=None`.
Payloads binários não devem cruzar os limites das chamadas de ferramentas.
Para decisões multimodais futuras, passe uma referência persistente
(`artifact_id` / `image_ref` / `crop_path` / URI de object-storage) em vez de
bytes crus.

---

## 5. Como os agentes invocam os algoritmos

### 5.1 Fusão dirigida por PDDL (`dual-provider-fusion`)

O planejador PDDL pode selecionar o método `dual-provider-fusion` para uma
obrigação. O fluxo é:

```
Plano PDDL
   │  seleciona dual-provider-fusion
   ▼
ExecutorAgent (Agno Workflow)
   │  chama o handler registrado
   ▼
_handle_dual_provider_fusion_method (backend/agents/pddl_orchestrator.py)
   │  chama extract_fused()
   ▼
backend.pipeline.fusion.extract_fused
   │  extrai com docling + mineru (em paralelo)
   ▼
docstruct.fusion.merge_blocks (Tree Differ)
   │  devolve blocos markdown fundidos
   ▼
o handler persiste o payload em data_dir/artifacts/fusion/<obligation_id>.json
   │  devolve MethodResult(artifacts=[fusion_artifact])
   ▼
ExecutorAgent incorpora o artefato ao manifesto
   e associa seu id à tentativa executada (proveniência)
```

O handler é **estrito**: se só um provider participou (o fallback
single-provider dentro de `extract_fused`), a ação `dual-provider-fusion`
planejada é tratada como **falha**, registrando `(tried ...)` e permitindo
replanejamento para um método single-provider. Isso mantém a semântica
planejada alinhada com o que realmente foi executado.

### 5.2 Invocação direta de ferramentas

As ferramentas do `FusionAgent` também podem ser invocadas diretamente (p. ex.
por um agente LLM ou pelo runtime AgentOS) para fundir, auditar, classificar
ou decidir re-inferência sem passar pelo planejador PDDL.

---

## 6. Documentação relacionada

- [libs/docstruct/README.md](../../libs/docstruct/README.md) — API pública.
- [pmv_agno_pddl.md](pmv_agno_pddl.md) — orquestração PDDL e o método
  `dual-provider-fusion`.
- [architecture.md](architecture.md) — arquitetura do sistema.
- [patterns.md](patterns.md) — padrões de design (padrão 12: agente de fusão
  determinístico).
- [drbench.md](drbench.md) — o benchmark Dr.DocBench que motivou o Tree Differ.
