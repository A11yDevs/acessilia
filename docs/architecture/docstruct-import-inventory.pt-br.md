# Inventário: os imports do Docstruct no Core (#735 fase 4, ADR-0028)

Inglês, versão normativa: [English version](docstruct-import-inventory.md)

A [ADR-0028](../adr/0028-operational-execution-in-the-toolbox.pt-br.md) tira
toda a computação documental do processo do Core. A migração começa por este
inventário: cada módulo `docstruct.*` importado pelo Core
(`libs/core/src/acessilia_core`) e por `backend/`, classificado como
contrato, algoritmo, validação, política ou operação. A revisão da
classificação decide quais módulos continuam na allowlist, uma das decisões
em aberto da ADR ([#758](https://github.com/A11yDevs/acessilia/issues/758)).

A classificação fica como dados em
[`tests/fixtures/docstruct_import_allowlist.json`](../../tests/fixtures/docstruct_import_allowlist.json),
e `tests/test_architecture_layers.py` mantém o código, os dados e esta página
alinhados (veja [A guarda](#a-guarda)).

## Resumo

Medido em `develop` no `82424b34`, com uma varredura AST que inclui imports
dentro de funções e instruções `import docstruct.x` (a mesma da guarda); os
números abaixo foram remedidos depois que a #636 removeu o último import
direto de `docstruct.imaging` no Core (`toolbox/vision_payload` agora pede o
plano de redução ao SDK).

- **49 arquivos** importam **56 módulos** do Docstruct.
- **44 arquivos** importam computação (algoritmo ou operação): os 43 da
  ADR-0028, mais `pipeline/judge` e `pipeline/handlers/judge` (que importam
  `docstruct.fusion.judge`, classificado aqui como algoritmo), menos
  `toolbox/vision_payload`, cujo último import direto a #636 removeu (veja
  [A regra de classificação](#a-regra-de-classificação)).
- **5 arquivos** importam só contratos, validação ou política:
  - só contrato: `export/catalog`, `manifest/document_adapter`,
    `manifest/models`;
  - só validação: `pipeline/validators`;
  - só política: `manifest/toolbox_extractor`.
- A ADR-0028 conta 46 arquivos no `46f2fe7e`. A mesma varredura encontra 50
  ali, os mesmos arquivos do `82424b34`: a diferença está na contagem, e
  nenhum arquivo passou a importar o Docstruct desde então.

| Classe | Módulos | O que é | Destino |
|---|---|---|---|
| contrato | 2 | Modelos, mensagens e schemas de interoperabilidade | Importável em qualquer lugar, até a ADR de contratos decidir onde ficam |
| validação | 1 | Verificação de um documento contra um schema ou regras | Transitória, fixada: a validação de schema fica perto da camada de interoperabilidade; a auditoria do documento vira capacidade |
| política | 2 | Regras de decisão que o Core usa para coordenar | Transitória, fixada: a parte estratégica vai para o Core (ADR-0029); os parâmetros dos algoritmos ficam com a Toolbox |
| operação | 10 | Composições: montagem canônica, renderização de exportação, fusão de payloads, especialista de tabelas | Uma capacidade composta da Toolbox, por trás de uma ação planejada |
| algoritmo | 41 | Algoritmos estruturais sobre o conteúdo do documento e os tipos internos a eles | Uma capacidade atômica da Toolbox, migrada com o método do plano ou o agente que a usa |

Toda classe, exceto contrato, é fixada: cada importador e cada nome que ele
importa ficam listados, e a lista só diminui.

## A regra de classificação

> Módulos mistos são classificados pela sua responsabilidade mais
> operacional. Um módulo não é classificado como contrato ou política só por
> conter alguns símbolos de contrato ou de política: enquanto também contiver
> algoritmos documentais, fica fixado até que as partes sejam separadas
> fisicamente.

Contrato é a única classe não fixada, por isso é mantida estreita: um módulo
é contrato quando dois componentes o trocam, não por ser uma dataclass pura
ou não ter dependência externa. A guarda fixa o conjunto de módulos de
contrato no próprio teste, então ampliá-lo é uma mudança revisada no teste.

## As classes

- **Contrato.** Modelos, constantes e mensagens que dois componentes trocam:
  - `docstruct.export.formats.FormatSpec`, os registros de identidade dos
    formatos;
  - `docstruct.manifest`, o modelo normativo do manifesto (ADR-0007). É um
    contrato **transitório**: também verifica invariantes e adapta payloads,
    e depende de `docstruct.geometry.boxes` (`OrientedBox`) e de
    `docstruct.validation` (`Finding`). A ADR de contratos separa os modelos
    e schemas desses algoritmos e mantém uma única fonte de verdade.
- **Validação.** `docstruct.validation`, **transitória** e fixada. Reúne duas
  coisas diferentes:
  - `validate_against_schema` verifica um documento contra um schema de
    interoperabilidade; fica perto da camada de interoperabilidade;
  - `audit_canonical_document` inspeciona a estrutura, a semântica e a
    acessibilidade do documento processado; vira uma capacidade da Toolbox
    (por exemplo `document.audit.*`).

  O módulo inteiro não recebe uma allowlist permanente.
- **Política.** Regras de decisão, **transitórias** e fixadas:
  - `profiles.verbosity_for_mode`, o exemplo da ADR-0028;
  - `policy.FusionPolicy`, que mistura política de workflow com os
    parâmetros dos algoritmos (veja [Política estratégica e configuração operacional](#política-estratégica-e-configuração-operacional)).
- **Operação.** Uma composição de algoritmos com um resultado no nível do
  documento:
  - `canonical`, o construtor canônico;
  - os oito módulos `export.*`, exceto `formats`. A ADR-0028 classifica a
    renderização de exportação como computação por trás de uma ação
    planejada;
  - `fusion.payload`, a fusão entre provedores e o roteamento de páginas;
  - `fusion.table_specialist`, geração, comparação e adjudicação.
- **Algoritmo.** Todo o resto: fusão, ordem de leitura, geometria, tabelas,
  texto, matemática, reparo de Unicode, imagens e texto visual, e os tipos
  internos a eles. Pela regra acima, isso inclui três módulos que têm alguma
  política ou tipos:
  - `docstruct.types`: `Region` carrega dados de processamento
    (`image_bytes`), ao lado de `CanonicalBlock`, `BlockPairing`,
    `OrientationResult` e tipos legados de documento. Só os tipos realmente
    compartilhados vão depois para o pacote de contratos;
  - `docstruct.regions.classify`: `region_needs_vision` e
    `region_prompt_key` encaminham uma região, mas `classify_region` calcula
    sobre geometria, densidade de texto e confiança;
  - `docstruct.fusion.judge`: `should_judge` decide se o juiz VLM é
    consultado, mas `debias`, `p2_from_logprobs` e `decide_pair` normalizam
    probabilidades, corrigem viés e comparam candidatos.

  Em cada caso, a computação vai para a Toolbox. O Core fica com a decisão
  de quando pedir uma capacidade, a partir das evidências que a Toolbox
  devolve.

## Política estratégica e configuração operacional

O `FusionPolicy` reúne os dois tipos de ajuste:

| Tipo | O que decide | Campos, por exemplo |
|---|---|---|
| Política de workflow (Core) | Quais passos rodam e que evidência pedir | `page_judge` (consultar o juiz VLM), `text_pick` (de quem preferir o texto), `upscale`, `orientation_reinfer` |
| Configuração operacional (Toolbox) | Como um algoritmo roda | `align_tau`, `align_lambda`, `xycut_min_balance`, `tailjoin_k`, `rep_max_n`, a calibração `pic_*` e `merge_*` |

Levar a classe inteira para o Core faria o Core depender dos parâmetros
internos da Toolbox. A política estratégica pertence ao Core (ADR-0029); os
parâmetros dos algoritmos ficam com a Toolbox, por trás das capacidades.
Até a classe ser dividida fisicamente, mantendo a compatibilidade durante a
migração, ela fica fixada aos importadores atuais.

## Módulos mistos

Pela regra de classificação, um módulo tem uma única classe: a mais
operacional das suas partes. Alguns
módulos também trazem vocabulário ou tipos que, por natureza, são contratos;
a ADR de contratos decide se eles vão para um pacote de contratos:

- `docstruct.placeholders`: `UNSTRUCTURED_PAGE_FLAG` e
  `UNSTRUCTURED_PAGE_LABEL` são vocabulário; `has_meaningful_text`,
  `is_mostly_visual` e `is_placeholder_visual` são algoritmos.
- `docstruct.geometry`: `OrientedBox` e `ReadingItem` são tipos;
  `order_reading_items`, `reading_role`, `union` e `is_bottom_left` são
  algoritmos.
- `docstruct.geometry.boxes`: `PageBox` é um tipo; o resto são algoritmos.
- `docstruct.tables.ast`: `TABLE_SECTIONS` e as mensagens `MSG_TABLE_TEXT_*`
  são vocabulário; os construtores da AST e a linearização são algoritmos.
- `docstruct.fusion.judge` e `docstruct.regions.classify`: veja a classe
  algoritmo acima.
- `docstruct.imaging.policy` é classificado como **algoritmo**, apesar do
  nome: `upscale_factor` e `decide_orientation` definem os parâmetros do
  processamento de imagem do agente de página e vão com ele.
- `docstruct.fusion.types` **não** é contrato: sua docstring diz que é
  interno ao fusor e não é uma API pública estável.

## Onde está a computação

Os importadores se agrupam pela parte do Core que executa a computação. Esta
é a ordem que a migração pode seguir, por método do plano ou por agente
(ADR-0028):

| Parte do Core | Arquivos | O que sai |
|---|---|---|
| Agentes operacionais (`agents/*`) | fusion, page-level, adjudication, order adjudication, table specialist, vision, prompt tools, output schemas | Fusão, ordem de leitura, protocolo de adjudicação, guarda contra repetição, especialista de tabelas. Saem com os agentes classificados como operacionais (#735, linha dos agentes) |
| Handlers dos métodos do plano (`pipeline/handlers/*`) | text, content, formula, structure, order, rescue, unicode repair, inspection, fusion, judge | Uma capacidade por método, a migração por método da ADR-0028 |
| Enriquecimento (`pipeline/enrichment/*`) | common, formulas, inline math, pictures, tables | Recorte de imagem, fórmulas e matemática inline, contexto de figuras, recuperação de tabelas. São também os estágios semânticos que a ADR-0029 planeja |
| Montagem do payload e do documento canônico | `pipeline/payload`, `pipeline/canonical_builder`, `pipeline/elements`, `pipeline/obligations` | Montagem canônica e texto das páginas: a composição por trás da exportação acessível |
| Exportação acessível (`export/*`) | renderers, exporters, exportador Pandoc, markers, catalog | Renderização, por trás da capacidade de exportação (`document.export.*`) |
| Construção do manifesto (`manifest/*`) | builder, detectores de layout e texto, slides | Ordem de leitura, junção final, verso e normalização durante a construção do manifesto |
| Coordenação e fronteira | `pipeline/fusion`, `pipeline/secondary`, `pipeline/toolbox`, `pipeline/judge`, `manifest/toolbox_extractor` | Fusão de payloads, recorte de regiões e o limiar do juiz; a política de fusão é política |
| Shims de compatibilidade | `pipeline/table_ast`, `formula_tools`, `pipeline/validators` | Reexportações mantidas para imports antigos (`import docstruct.x`); saem quando seus chamadores saírem |
| Serviço (`backend/service.py`) | `backend/service` | `merge_broken_paragraphs` (algoritmo) e `verbosity_for_mode` (política) |

## Módulos
| Módulo | Classe | Nomes que o Core importa | Quem importa |
|---|---|---|---|
| `docstruct.export.formats` | contrato | `FormatSpec` | `export/catalog` |
| `docstruct.manifest` | contrato | `MSG_CHAR_RANGE_REVERSED`, `MSG_DUPLICATE_ELEMENT_IDS`, `MSG_DUPLICATE_PAGE_NUMBERS`, `MSG_ELEMENT_UNKNOWN_PAGE`, `MSG_PAGE_DUPLICATE_ELEMENT_IDS`, `MSG_PAGE_UNKNOWN_ELEMENTS`, `MSG_PARENT_CYCLE`, `MSG_PARENT_REF_MISMATCH`, `MSG_PROVENANCE_UNKNOWN_PAGE`, `MSG_SELF_PARENT`, `MSG_UNKNOWN_PARENT`, `StructuredDocument`, `document_invariant_findings`, `structured_document_from_payload`, `structured_document_to_payload` | `manifest/document_adapter`, `manifest/models` |
| `docstruct.validation` | validação | módulo, `FindingTuple`, `audit_canonical_document`, `validate_against_schema` | `agents/fusion_agent`, `export/pandoc_exporter`, `pipeline/validators` |
| `docstruct.policy` | política | `FusionPolicy` | `manifest/toolbox_extractor`, `pipeline/fusion`, `pipeline/handlers/fusion` |
| `docstruct.profiles` | política | `verbosity_for_mode` | `backend/service` |
| `docstruct.canonical` | operação | `MathEnricher`, `_enrich_math_blocks`, `build_canonical_document`, `sanitize_canonical_document` | `pipeline/canonical_builder` |
| `docstruct.export.filters` | operação | `strip_internal_audit_blocks` | `export/pandoc_exporter` |
| `docstruct.export.html` | operação | `HtmlLabels`, `_all_blocks`, `_collect_section`, `_render_block`, `_render_html_table_row`, `document_to_html` | `export/renderers/html_renderer` |
| `docstruct.export.markdown` | operação | `document_to_markdown` | `export/exporters/drbench_md_exporter` |
| `docstruct.export.markers` | operação | `wrap_object_markers` | `export/markers` |
| `docstruct.export.page_text` | operação | `blocks_text`, `pages_text` | `pipeline/payload` |
| `docstruct.export.pandoc_ast` | operação | `build_pandoc_ast`, `count_math_nodes`, `degrade_math_to_text`, `unconverted_math_indices` | `export/pandoc_exporter` |
| `docstruct.export.txt` | operação | `_render_block`, `_render_section`, `document_to_txt_lines` | `export/renderers/txt_renderer` |
| `docstruct.fusion.payload` | operação | `fuse_extraction_payloads`, `normalize_element_ids`, `route_pages` | `manifest/builder`, `pipeline/fusion` |
| `docstruct.fusion.table_specialist` | operação | `build_candidates`, `extract_table`, `is_valid_table`, `medoid_index`, `norm_table`, `select_greedy`, `select_table` | `agents/table_specialist_agent` |
| `docstruct.blocks.callouts` | algoritmo | `callout_titles`, `dedupe_callout_titles` | `pipeline/payload` |
| `docstruct.blocks.lists` | algoritmo | `marker_numbering`, `merge_list_blocks`, `recover_empty_lettered_list_items` | `pipeline/elements`, `pipeline/payload` |
| `docstruct.data_uri` | algoritmo | `decode_data_uri` | `pipeline/enrichment/common` |
| `docstruct.fusion.adjudication` | algoritmo | `clean_transcription`, `decide`, `decide_v0`, `decide_v1`, `filter_decision` | `agents/adjudication_agent`, `pipeline/handlers/fusion` |
| `docstruct.fusion.hf_end` | algoritmo | `move_hf_to_end` | `agents/fusion_agent`, `agents/page_level_agent` |
| `docstruct.fusion.judge` | algoritmo | `DEFAULT_NEW_THR`, `decide_pair`, `should_judge` | `agents/adjudication_agent`, `pipeline/handlers/judge`, `pipeline/judge` |
| `docstruct.fusion.line_numbers` | algoritmo | `extract_line_numbers` | `agents/fusion_agent`, `manifest/detectors/layout` |
| `docstruct.fusion.noise` | algoritmo | `PAGE_NUMBER_MARGIN`, `element_role`, `is_bare_page_number`, `is_decorated_page_number`, `is_legitimate_text`, `is_page_number_in_margin`, `select_page_numbers` | `pipeline/handlers/rescue`, `pipeline/handlers/text`, `pipeline/payload` |
| `docstruct.fusion.oracle` | algoritmo | `oracle_page` | `agents/adjudication_agent` |
| `docstruct.fusion.page_select` | algoritmo | `fuse`, `page_agreement`, `page_norm`, `select_by_agreement`, `swap_low_agreement_pages` | `agents/adjudication_agent`, `agents/page_level_agent` |
| `docstruct.fusion.repetition` | algoritmo | `collapse`, `guard_page` | `agents/fusion_agent`, `agents/vision_agent` |
| `docstruct.fusion.similarity` | algoritmo | `area`, `is_duplicate`, `ordered_box`, `pair_block` | `manifest/slides`, `pipeline/handlers/rescue`, `pipeline/secondary` |
| `docstruct.fusion.skeleton` | algoritmo | `DEFAULT_MIN_SKELETON_MATCH`, `skeleton_reading_order` | `pipeline/handlers/order` |
| `docstruct.fusion.tailjoin` | algoritmo | `join_tail`, `page_number_position`, `tailjoin3` | `agents/fusion_agent`, `agents/page_level_agent`, `manifest/detectors/layout`, `pipeline/handlers/text` |
| `docstruct.fusion.types` | algoritmo | `DiffBlock` | `agents/fusion_agent`, `manifest/detectors/layout` |
| `docstruct.fusion.verse` | algoritmo | `split_box_rows`, `verse_blocks` | `agents/fusion_agent`, `manifest/detectors/layout`, `pipeline/handlers/structure` |
| `docstruct.fusion.xycut` | algoritmo | `xycut_order` | `agents/fusion_agent`, `agents/order_adjudication_agent`, `manifest/detectors/layout` |
| `docstruct.geometry` | algoritmo | `OrientedBox`, `ReadingItem`, `is_bottom_left`, `order_reading_items`, `reading_role`, `union` | `manifest/builder`, `manifest/detectors/types`, `manifest/slides`, `pipeline/elements`, `pipeline/payload`, `pipeline/secondary` |
| `docstruct.geometry.boxes` | algoritmo | `PageBox`, `best_effort_clip`, `box_contains_center`, `box_distance`, `boxes_overlap`, `boxes_side_by_side`, `downward_edges`, `expand_box`, `holds_point`, `spans_horizontally`, `union_area` | `manifest/slides`, `pipeline/enrichment/common`, `pipeline/enrichment/inline_math`, `pipeline/handlers/unicode_repair`, `pipeline/toolbox` |
| `docstruct.imaging.policy` | algoritmo | `decide_orientation`, `upscale_factor` | `agents/page_level_agent` |
| `docstruct.placeholders` | algoritmo | `UNSTRUCTURED_PAGE_FLAG`, `UNSTRUCTURED_PAGE_LABEL`, `has_meaningful_text`, `is_mostly_visual`, `is_placeholder_visual`, `is_unstructured_page_placeholder` | `manifest/builder`, `pipeline/enrichment/pictures`, `pipeline/handlers/content`, `pipeline/payload` |
| `docstruct.regions.classify` | algoritmo | `classify_region`, `region_needs_vision`, `region_prompt_key` | `agents/fusion_agent`, `agents/vision_agent` |
| `docstruct.regions.letterhead` | algoritmo | `PlacedItem`, `letterhead_groups` | `pipeline/payload` |
| `docstruct.sections` | algoritmo | `find_heading_gaps`, `repair_heading_levels` | `manifest/builder`, `pipeline/handlers/text` |
| `docstruct.tables.ast` | algoritmo | módulo, `TABLE_SECTIONS`, `analyze_table_complexity`, `linearize_table_for_text`, `raw_rows_from_table_ast`, `table_ast_column_count`, `table_ast_from_rows` | `manifest/detectors/text`, `pipeline/elements`, `pipeline/enrichment/inline_math`, `pipeline/enrichment/tables`, `pipeline/handlers/content`, `pipeline/handlers/fusion`, `pipeline/handlers/unicode_repair`, `pipeline/table_ast` |
| `docstruct.tables.garble` | algoritmo | `table_garble_reason` | `pipeline/enrichment/tables` |
| `docstruct.tables.structured` | algoritmo | `normalize_strict_table_ast`, `table_ast_from_structured_rows`, `table_ast_has_structured_content` | `agents/output_schemas`, `pipeline/elements` |
| `docstruct.tables.text_rows` | algoritmo | `rows_from_visual_table_text` | `pipeline/enrichment/tables` |
| `docstruct.text.code_reflow` | algoritmo | `normalize_code_text` | `pipeline/elements`, `pipeline/handlers/content` |
| `docstruct.text.equations` | algoritmo | `preserve_equation_number`, `split_equation_number` | `manifest/builder`, `pipeline/enrichment/formulas` |
| `docstruct.text.implicit_products` | algoritmo | `implicit_product_variables`, `mark_implicit_products` | `pipeline/handlers/formula` |
| `docstruct.text.inline_math` | algoritmo | `Placement`, `assign_runs_to_cells`, `detect_inline_math_by_page`, `splice_inline_math`, `top_left_box` | `pipeline/enrichment/inline_math` |
| `docstruct.text.latex` | algoritmo | módulo, `bare_latex`, `has_latex_markup`, `latex_text_agreement`, `normalize_latex` | `agents/fusion_agent`, `formula_tools`, `manifest/builder`, `manifest/detectors/text`, `pipeline/canonical_builder`, `pipeline/enrichment/formulas`, `pipeline/handlers/formula`, `pipeline/handlers/inspection`, `pipeline/handlers/unicode_repair`, `pipeline/obligations` |
| `docstruct.text.math_spans` | algoritmo | `block_prose`, `inline_math_sources` | `pipeline/handlers/formula` |
| `docstruct.text.named_operators` | algoritmo | `normalize_named_operators`, `speak_named_operators` | `pipeline/handlers/formula` |
| `docstruct.text.negation_overlay` | algoritmo | `compose_in_grid`, `compose_in_text`, `is_detached_overlay` | `pipeline/enrichment/inline_math`, `pipeline/handlers/unicode_repair` |
| `docstruct.text.norm_fix` | algoritmo | `norm_fix` | `agents/fusion_agent`, `manifest/detectors/text`, `pipeline/handlers/text` |
| `docstruct.text.paragraphs` | algoritmo | `merge_broken_paragraphs` | `backend/service` |
| `docstruct.text.unicode_repair` | algoritmo | `Detection`, `UnicodeRepairContext`, `detect_legacy_unicode`, `repair_legacy_unicode` | `manifest/detectors/text`, `pipeline/handlers/unicode_repair` |
| `docstruct.types` | algoritmo | `Region` | `agents/fusion_agent` |
| `docstruct.visual_text` | algoritmo | `TextOwnership`, `analyze_visual_text_ownership`, `bound_surrounding_items`, `collect_picture_context`, `deduplicate_picture_description`, `is_confirmed_logo_description`, `is_document_artifact`, `is_scene_artifact`, `scene_text_residue` | `agents/prompt_tools`, `pipeline/enrichment/pictures`, `pipeline/payload` |

## O SDK, para informação

O SDK importa seis módulos do Docstruct. Os cinco computacionais são o "5"
dos indicadores da #735:

- `docstruct.manifest` (contrato), em `toolbox/results/layout`;
- `docstruct.geometry.boxes` e `docstruct.text.latex`, em
  `operations/formula`;
- `docstruct.fusion.payload` e `docstruct.policy`, em `operations/fusion`;
- `docstruct.imaging`, em `toolbox/clients/pdf`.

Suas operações vão com o runtime operacional para a Toolbox (#735 fase 1,
ADR-0028). O `tests/test_purity.py` do próprio SDK guarda suas dependências,
então esta página não as fixa.

## A guarda

Os testes em `tests/test_architecture_layers.py` leem o fixture:

- **Classificado e fixado.** Todo módulo do Docstruct que o Core ou
  `backend/` importam precisa estar no fixture. Um módulo de contrato pode
  ser importado por qualquer arquivo. Os demais listam os arquivos que os
  importam e os nomes que cada arquivo importa. Para
  `import docstruct.x as m`, os nomes são os `m.attr` que o arquivo lê, e `*`
  marca qualquer outro uso de `m`. Um arquivo novo, ou um nome novo num
  import existente, falha: ele deve chamar uma capacidade da Toolbox.
- **Só diminui.** Um módulo, arquivo ou nome que não é mais importado falha
  até ser removido, então cada migração tira suas linhas do fixture, e o
  último importador de um módulo tira sua linha desta página.
- **Classes fechadas.** As classes são as cinco acima, e o conjunto de
  módulos de contrato fica fixado no teste: reclassificar um módulo
  computacional como contrato muda o teste, não só o fixture.
- **Os casos da própria guarda.** Testes sintéticos verificam um nome novo
  num import existente, um importador novo, um módulo sem classificação,
  fixações obsoletas e a resolução de aliases de módulo.
- **Alinhado com esta página.** As linhas de módulos da tabela acima, nos
  dois idiomas, precisam ser os módulos do fixture.

### Exceções transitórias: `*`

Dois shims de compatibilidade leem seu módulo do Docstruct dinamicamente, com
`getattr(module, name)` sobre uma tupla de nomes depreciados, então suas
fixações têm `*` e não restringem quais atributos eles leem:

- `pipeline/table_ast` (`docstruct.tables.ast`, `_DEPRECATED_NAMES`);
- `pipeline/validators` (`docstruct.validation`).

São transitórias: cada uma sai quando seus nomes depreciados não tiverem mais
chamadores, ou quando as chamadas por trás dela virarem capacidades da
Toolbox. Um `*` novo é uma fixação nova, então a guarda o recusa como
qualquer outra.

### Entre commits

Os testes comparam o código com o fixture, então um pull request que mude os
dois juntos ainda passaria por eles. O workflow `docstruct allowlist`
([#764](https://github.com/A11yDevs/acessilia/issues/764)) também compara o
fixture com o da branch base (`scripts/check_docstruct_allowlist.py`). Ele
falha quando um pull request acrescenta um módulo, um importador ou um nome,
ou reclassifica um módulo como contrato. Trocar um `*` por nomes, remoções e
mudanças entre classes fixadas passam. Ele falha fechado: uma ref base que não
resolve, ou um fixture base que não pode ser lido, reprova a verificação. Só
um commit base que comprovadamente não tem o fixture não tem o que comparar.

### Exceções

Uma fixação nova é uma decisão arquitetural, não um atalho de revisão. O
rótulo `architecture-exception` transforma a falha da verificação num aviso;
ele não substitui a revisão arquitetural. Um pull request que o usa:

- vincula a ADR ou a issue de decisão que autoriza a exceção;
- nomeia os módulos, arquivos e nomes que acrescenta;
- diz se a exceção é temporária ou permanente, por quê, e quando sai, se
  temporária;
- é aprovado por um mantenedor responsável pela arquitetura.

CODEOWNERS ou uma verificação automática da aprovação podem reforçar isso
depois.

## Indicadores

A baseline deste inventário, para a #735 acompanhar enquanto a migração
avança:

| Indicador | Baseline (`82424b34`) | Meta |
|---|---|---|
| Módulos do Docstruct importados diretamente | 57 | só os módulos de contrato |
| Arquivos que importam computação (algoritmo ou operação) | 45 | 0 |
| Exceções `*` fixadas | 2 | 0 |
| Imports fora da allowlist | 0 | 0 |
| Exceções novas sem decisão arquitetural | 0 | 0 |

## Como uma migração diminui a allowlist

Cada migração, por método do plano ou por agente (ADR-0028):

1. disponibiliza uma capacidade equivalente na Toolbox;
2. troca a computação local por uma chamada pelo Core SDK;
3. preserva os contratos e a equivalência funcional;
4. acrescenta um teste diferencial de regressão;
5. remove do fixture os arquivos e nomes obsoletos e, quando o último
   importador de um módulo sai, sua linha desta página;
6. remede o resumo acima, que acompanha o código; os indicadores mantêm a
   linha de base do `82424b34`.

Uma capacidade segue a semântica dos métodos do plano e dos agentes. Nem
toda função utilitária vira uma chamada remota: algoritmos de baixo nível
são compostos dentro do runtime da Toolbox, o que reduz a latência e mantém
o planejamento PDDL simples.

## Ainda em aberto

A classificação em si foi decidida na revisão do #760. Restam:

- **Divisões físicas.** Quando `docstruct.validation` (validação de schema e
  auditoria do documento), `FusionPolicy` (política de workflow e
  configuração operacional), `docstruct.fusion.judge` e
  `docstruct.regions.classify` são divididos, e em quais pull requests.
- **Vocabulário e o manifesto.** Quais tipos e vocabulário dos módulos
  mistos e de `docstruct.manifest` vão para o pacote de contratos que a ADR
  de contratos avalia.
- **Shims.** Os três shims de compatibilidade saem com o último chamador, ou
  antes?
