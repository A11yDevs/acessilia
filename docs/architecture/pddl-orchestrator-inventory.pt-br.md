# Inventário do orquestrador PDDL

> A versão em inglês está em [pddl-orchestrator-inventory.md](pddl-orchestrator-inventory.md).

Esta é a Fase 2 do plano da [#402](https://github.com/A11yDevs/acessilia/issues/402) (o comentário "Plano complementar"). Ela classifica cada definição de topo de `backend/agents/pddl_orchestrator.py` por responsabilidade e propõe um destino para cada grupo: o core, o docstruct, o SDK ou a Toolbox. O código com responsabilidades misturadas fica marcado para ser decomposto antes. A Fase 3 migra os grupos um PR por vez, seguindo esta tabela. O orquestrador diminui porque perde responsabilidades que não são dele, e não porque é fatiado em arquivos. Essa era a abordagem da [#381](https://github.com/A11yDevs/acessilia/issues/381), agora em `status:blocked`.

Ele também cumpre as tarefas de inventário da [#365](https://github.com/A11yDevs/acessilia/issues/365), que a #381 absorveu:
- mapear os grupos e o estado que compartilham;
- verificar, para cada grupo, se é um algoritmo estrutural puro, que pertence ao docstruct ([ADR-0002](../adr/0002-component-responsibilities.pt-br.md));
- listar as maiores funções.

- **Retrato:** `acessilia` `develop` em `a5ae2a8e`. `backend/agents/pddl_orchestrator.py` tem **6.185 linhas**, e 192 definições de topo estão atribuídas aos grupos.
- **Como foi medido:** o arquivo foi analisado com `ast`. Cada função, classe e constante de topo pertence a um grupo, e nenhuma ficou sem grupo. A coluna "Depende de" lista os outros grupos cujos nomes o código do grupo cita; o estado que os grupos compartilham pelo manifesto está mapeado à parte, em "Estado compartilhado". Os grupos cobrem 5.599 linhas; o restante são imports, a docstring do módulo e linhas em branco.

## Regra de destino

Cada definição é classificada pelo que faz, e não pelo arquivo onde está nem por chamar ou não um agente ([ADR-0002](../adr/0002-component-responsibilities.pt-br.md), "Onde fica o código novo?").

| Se o código… | Destino | Base |
|---|---|---|
| decide o que fazer ou quando: política, plano, recuperação, degradação, fluxo, mensagens ao usuário | **core** | ADR-0002; constituição P2, P6 |
| é um algoritmo estrutural determinístico, sem I/O | **docstruct** | ADR-0002, [ADR-0009](../adr/0009-legacy-unicode-repair.pt-br.md), [ADR-0011](../adr/0011-inline-math-from-font-runs.pt-br.md) |
| diz como chegar a uma capacidade ou a um artefato: chamada de cliente, pedido de render, id de artefato | **SDK** | ADR-0002 (pergunta 4), [ADR-0005](../adr/0005-artifact-references.pt-br.md), [ADR-0015](../adr/0015-artifact-reference-v1.pt-br.md) |
| executa um modelo, OCR, VLM ou um renderizador | **Toolbox** | [ADR-0003](../adr/0003-remote-only-operational-capabilities.pt-br.md), [ADR-0012](../adr/0012-agents-reach-the-vlm-through-the-toolbox.pt-br.md) |
| mistura mais de uma dessas coisas | **decompor antes**, depois mover cada parte | Plano, princípio 1 |

**O docstruct trabalha com os próprios tipos.** As funções do orquestrador recebem os modelos Pydantic do core: `ManifestElement`, `ProcessingManifest`, `Obligation`. O docstruct não pode importá-los. Desde a [#203](https://github.com/A11yDevs/acessilia/issues/203), a parte de documento tem sua definição normativa em `docstruct.manifest` (`DocumentElement`, `BoundingBox`, `Provenance`), e os modelos do core são adaptadores sobre ela (veja o [inventário do modelo de manifesto](manifest-model-inventory.pt-br.md), decisão D1).

Então "docstruct", abaixo, quer dizer que o algoritmo se muda e passa a trabalhar com tipos do docstruct ou valores simples: caixas como tuplas, texto, linhas. Um adaptador pequeno no core mantém a assinatura atual, converte e chama o algoritmo. O adaptador é o que continua substituível pelos testes.

Nenhum grupo vai para a Toolbox: o orquestrador já não roda modelo nem renderizador localmente. A Fase 1 da #402 e a ADR-0003 removeram os últimos.

## Inventário

Os grupos têm as letras da análise que gerou esta tabela. "Linhas" é o intervalo das definições do grupo e "Tamanho", a soma dos comprimentos. "PT" conta as linhas com texto em português, que a guarda de idioma e a [#410](https://github.com/A11yDevs/acessilia/issues/410) acompanham quando elas se movem.

| Id | Grupo | Linhas | Tamanho | Depende de | PT | Destino |
|---|---|---|---|---|---|---|
| A | Ids de mensagens ao usuário (`MSG_*`) | 148–163 | 10 | — | 0 | core |
| B | Handlers de fórmula: MathML e fala | 166–286 | 115 | X | 11 | core (handler de execução) |
| C | Infraestrutura de fusão (`_run_extract_fused`, `_fusion_agent`) | 289–334 | 44 | — | 8 | core |
| D | Alvos compartilhados e geometria de elemento | 337–1409 | 93 | — | 1 | **decompor** |
| E | Handlers determinísticos simples | 392–594 | 195 | D, O, S | 12 | core (handlers de execução) |
| F | Reparo Unicode e sobreposições de negação | 599–957 | 334 | D | 2 | **decompor**: geometria para o docstruct |
| G | Renderização, inspeção de região e de página | 960–1327 | 350 | D | 0 | core, sobre o render que o SDK já tem; tipos de entrada aceitos para o SDK |
| H | Handlers de texto com o FusionAgent | 1330–1527 | 140 | C, D | 7 | core; `_tailjoin_position` para o docstruct |
| I | Escolha calibrada de provider | 1539–1979 | 410 | D, K | 12 | **decompor**: geometria de caixas para o docstruct |
| J | Juiz VLM por pares | 1984–2226 | 231 | D, G, I | 10 | **decompor**: leitura de `pB` para o SDK |
| K | Handlers de ordem e revisão, registro de handlers | 2229–2396 | 158 | C, D, E, F, G, H, I | 5 | core |
| L | Fusão com dois providers e com um | 2399–2680 | 274 | C, D, G | 16 | core |
| M | Erros e limites de páginas | 2683–2733 | 43 | — | 0 | core |
| N | `PddlAccessibilityOrchestrator` (pipeline, plano, executor) | 2736–3071 | 336 | B, J, K, L, M, O–V | 2 | core (orquestração) |
| O | Enriquecimento de figuras | 3079–4961 | 483 | G, U | 15 | **decompor**: heurísticas e geometria de recorte para o docstruct |
| P | Enriquecimento de fórmulas | 3339–4160 | 510 | G, O, U | 0 | **decompor**: ranking para o docstruct |
| Q | Matemática inline | 3424–3722 | 280 | F, G | 0 | **decompor**: geometria de spans para o docstruct, lotes de spans para o SDK |
| R | Triagem de mídia | 4163–4216 | 52 | — | 0 | core |
| S | Enriquecimento de tabelas e texto de tabela | 4288–4670 | 343 | G, O, U, X | 0 | **decompor**: leitura de linhas para o docstruct |
| T | Situação das obrigações e replanejamento | 4868–5059 | 144 | B, O, U | 0 | core |
| U | Progresso, rótulos de páginas, log de disponibilidade | 5031–5136 | 89 | — | 4 | core |
| V | Montagem do payload | 5139–5358 | 204 | A, T, W, X | 1 | core |
| W | Payload de página: números de página e timbre | 5361–5666 | 271 | A, D, X | 0 | **decompor**: regras de detecção para o docstruct |
| X | Blocos, listas, texto e AST de tabela | 5669–6180 | 488 | A | 0 | **decompor**: algoritmos de lista, texto e tabela para o docstruct |
| Z | Aliases legados (`PmvAccessibilityOrchestrator`, `build_pmv_structured_payload`) | 6184–6185 | 2 | N, V | 0 | remover (sem chamador) |

Os intervalos se sobrepõem quando as definições de um grupo estão espalhadas pelo arquivo. Por exemplo, `_element_role` e `_block_kind`, do grupo D, ficam perto da linha 1400, e as heurísticas puras do grupo O ficam depois do S.

### O que se move, grupo a grupo

Só aparecem os grupos marcados para decompor ou com uma parte para o docstruct ou o SDK. Os outros ficam inteiros no core.

- **D: alvos compartilhados e geometria de elemento.**
  - `_element_bbox` transforma um elemento do manifesto numa caixa com uma origem de coordenadas, usando `docstruct.geometry.is_bottom_left`. É um adaptador e fica no core.
  - `_element_role` e `_block_kind` são semântica de documento.
    - `_element_role` associa os tipos de mobiliário de página a papéis de fusão com a mesma tabela de `docstruct.fusion.noise.DECOR_TYPES`, então vai para lá, como `element_role`.
    - `_block_kind` fica no core por enquanto: `fusion.convert.classify_kind`, do docstruct, é uma quase duplicata que decide de outro jeito. Veja "Achados".
  - `_target_elements` e `_missing_obligation` leem obrigações, que são processo, então ficam no core.
- **F: reparo Unicode e sobreposições de negação.** A ADR-0009 já pôs a detecção e o reparo no docstruct (`docstruct.text.unicode_repair`). A geometria das sobreposições vai para `docstruct.text.negation_overlay`, que já tem `compose_negation`, `locate_in_grid` e `locate_in_text`: são `_vertical`, `_table_grid`, `_compose_in_host` e as tolerâncias de caixa. `_reattach_negation_overlays` e `_repair_table_cells` percorrem elementos do manifesto; viram adaptadores sobre funções do docstruct. O handler fica no core.
- **G: renderização, inspeção de região e de página.** O render em si já está no SDK: `ToolboxPdfClient.render` recebe um arquivo ou um artefato, uma página, um recorte e sua origem, confere a resposta e busca a imagem verificada. Não é preciso um binding novo de render.
  - `_toolbox_render` fica no core como o adaptador sobre esse método. Ele monta o cliente pela factory do core (e, portanto, com a configuração do core), confere se o tipo de mídia do manifesto bate com a extensão do arquivo e decide reenviar o arquivo quando o artefato armazenado sumiu. Isso é assunto do core.
  - O conjunto de entradas que o `pdf.render@2` aceita (`_RENDERABLE_MEDIA_TYPES`: PDF, PNG, JPEG) é conhecimento de contrato, então vai para o SDK ao lado do método de render, como uma constante que o adaptador confere: `acessilia_sdk.toolbox.clients.pdf.RENDER_MEDIA_TYPES`.
  - `_source_artifact_id` fica no core. Ele lê o manifesto (`extractor.configuration["artifact_id"]`) e decide ignorar um id que não se interpreta ou cujo digest não é o da origem. A interpretação de que ele depende já é o `ArtifactRef` do SDK.
  - `_save_region_artifact` grava evidência em `settings.data_dir`, então fica no core.
  - `_inspect_region` e `_inspect_page` chamam o `VisionAgent`, então ficam no core.
  - Os dois handlers ficam no core.
- **H: handlers de texto.** `_tailjoin_position` repetia, sobre os elementos do manifesto, `docstruct.fusion.tailjoin.page_number_position`, a regra que o builder aplica aos blocos de fusão. Agora chama essa função através de `_FurnitureView`, uma visão somente leitura que lê a caixa de um elemento só quando ele é mobiliário com número de página, como antes. Os handlers usam o `FusionAgent` e ficam no core.
- **I: escolha calibrada de provider.**
  - `_ordered_box`, `_iou` e `_pair_block` são geometria de caixas e vão para o docstruct, como `docstruct.fusion.similarity.ordered_box` e `pair_block`. `_iou` dá o mesmo valor que o `docstruct.fusion.similarity.iou` já existente para qualquer entrada, então é substituído por ele; veja "Achados". `_pair_block` fica no core como o adaptador que lê as caixas do elemento e dos candidatos; os limiares são política e ficam com ele.
  - `_page_number` e `_page_markdown` são pequenos auxiliares de documento.
  - `_load_secondary_extraction` lê um arquivo e confere o digest, então fica no core.
  - O par calibrado, as preferências e os limiares são política: core.
- **J: juiz VLM por pares.**
  - `_render_page_png` renderiza pelo adaptador do grupo G, então fica no core.
  - `_judge_probability` lê o `pB` da resposta do `document.adjudicate.page`, que o `ToolboxAdjudicateClient.judge_page` já documenta. Ler a resposta de uma capacidade é trabalho do SDK, como foram os formatos do `math.recognize` no #434, então vai para perto desse cliente. A movimentação mantém o comportamento atual: um `pB` ausente, não numérico ou fora do intervalo dá `None`. O que fazer com `None` continua sendo decisão do handler, no core. Passar a levantar erro seria uma mudança de comportamento à parte. Agora é `acessilia_sdk.toolbox.clients.adjudicate.page_judgement_probability`.
  - `_judge_page` é o wrapper síncrono do core sobre o `ToolboxAdjudicateClient`.
  - O handler (179 linhas, a quarta maior função) fica no core e é dividido lá. O passo 5 fez isso: `_judge_texts` dá os dois candidatos de uma página, `_judge_one_page` renderiza a página e lê a resposta do juiz, e `_judgement_result` registra os julgamentos e informa o resultado; o handler fica com o laço sobre as páginas (50 linhas, 22 delas de docstring).
- **O: enriquecimento de figuras.**
  - O fluxo, as novas tentativas e o disjuntor ficam no core (`_enrich_picture_descriptions`, com 197 linhas, e `_retry_failed`). O passo 5 a dividiu no core: `_pictures_to_describe` escolhe os elementos, `_fold_picture_description` incorpora uma resposta a um deles e `_retype_element` o torna fórmula ou figura; a função fica com o fluxo (109 linhas).
  - `_extract_picture_bytes`, `_picture_clip` e `_embedded_picture_bytes` (#386) misturam um render pelo adaptador do grupo G, geometria de recorte (docstruct) e um limite de tamanho (política do core). Foram separadas: `_picture_clip` é `docstruct.geometry.boxes.best_effort_clip`, e a decodificação do URI `data:` de `_embedded_picture_bytes` é `docstruct.data_uri.decode_data_uri`, que recebe do core os tipos aceitos e o limite de tamanho. `_extract_picture_bytes` fica com as chamadas de render e seus fallbacks (a página para uma caixa recusada ou uma lasca, nenhuma imagem para qualquer outra falha).
  - As heurísticas `_is_ocr_noise`, `_is_placeholder_text`, `_is_placeholder_visual_element` e `_has_meaningful_text` são testes puros de texto e de elemento, então vão para `docstruct.placeholders` (`is_ocr_noise`, `is_placeholder_text`, `is_placeholder_visual`, `has_meaningful_text`). `_is_mostly_visual_manifest` só lê os elementos, então também vai, como `is_mostly_visual`. Elas leem um elemento por um protocolo somente leitura que o `ManifestElement` do core satisfaz, então o core não precisa de adaptador.
  - `_inject_full_page_picture` altera o manifesto, então fica no core.
- **P: enriquecimento de fórmulas.**
  - `_formula_recognition_crop` renderiza pelo adaptador do grupo G e recorta (o docstruct cuida da geometria do recorte). Seu recorte é `docstruct.geometry.boxes.best_effort_clip` desde a #459; o que fica nele (o recorte salvo, o render, nenhum recorte para uma lasca) é do core.
  - `_ranked_formula_candidates` normaliza o LaTeX e ordena por confiança. É puro e vai para o docstruct, como `docstruct.text.latex.ranked_latex_candidates`. Sua normalização é `bare_latex`, a conservadora, que o core importa como `normalize_latex` (`backend/tools/formula_tools.py`), e não o `normalize_latex` do docstruct.
  - `_reclassify_formula_picture` e `_escalate_unresolved_formula` alteram o manifesto, então ficam no core.
  - `_enrich_formula_latex`, com 299 linhas a maior função do arquivo, fica no core e é dividida lá (#365). Agora fica com a seleção, a preparação e os logs de resumo (131 linhas, 61 delas de docstring). `_FormulaEnrichment` guarda o estado compartilhado de um documento e o `enrich_one`; `_MathRecognizer`, a sondagem de indisponibilidade, paga uma vez por documento; `_TextLayerGate`, o portão de concordância e o que ele recusou; `_first_agreeing_candidate`, `_formula_by_vision` e `_record_formula_recognition`, os três passos de uma fórmula.
- **Q: matemática inline.**
  - A geometria de spans vai para `docstruct.text.inline_math`, que já detecta e encaixa os trechos (ADR-0011): `_top_left_box`, `_detect_by_page` e `_element_span_lines`, que leem as caixas de um elemento como posições `(página, caixa)`. O teste de pertinência que elas dividem com `_claim_negation_overlay` é `docstruct.geometry.boxes.holds_point`. `_claim_negation_overlay` grava a reivindicação e acha a caixa da barra com o `_bbox` de F, e `_boxed_pages` lê os elementos do core, por isso os dois ficam no core.
  - `ToolboxPdfClient.text_spans` já lê o `document.text.spans` e confere a resposta. O que sobra são os lotes: `backend/tools/text_spans.fetch_text_spans` pede no máximo `TEXT_SPANS_MAX_PAGES` páginas por chamada, o que é transporte e vai para o SDK, como a paginação de datasets foi no #432. Agora é `ToolboxPdfClient.text_spans_by_page`; `fetch_text_spans` fica no core, ligando-o às configurações (o cliente, `toolbox_use_remote_cache`). O cache por documento do `_TextSpanReader`, e o registro de uma falha (`configuration["inline_math_detection"]`), ficam no core.
  - `_mark_inline_math`, `_mark_table_inline_math` e a checagem da configuração ficam no core.
- **S: enriquecimento de tabelas.**
  - `_rows_from_visual_table_text`, `_rows_from_pipe_table`, `_rows_from_delimited_lines`, `_looks_like_markdown_separator`, `_score_rows`, `_rows_look_like_placeholder` e `_table_ast_column_count` transformam texto em linhas, então vão para `docstruct.tables`.
  - As regras de releitura (`_table_reread_disqualified`, `_keep_misread_table`, tentativas e limiares) e `_enrich_table_structures`, que chama o `DataAgent`, ficam no core. O passo 5 a dividiu lá: `_tables_to_read` escolhe as tabelas e por que cada uma mal lida é lida de novo, `_read_table` faz as leituras, `_record_unread_table` registra uma tabela para a qual nenhuma leitura foi mantida e `_fold_table_reading` grava uma leitura mantida; a função fica com o fluxo (91 linhas).
- **W: números de página e timbre.**
  - As regras de detecção vão para o docstruct, ao lado de `docstruct.fusion.tailjoin.is_page_number`: `_is_decorated_page_number`, `_is_page_number_in_margin`, `_page_number_ids`, `_is_page_header_line`, `_is_beside` e `_letterhead_groups`.
  - `_letterhead_block` define o locale da requisição para a sua mensagem, então fica no core.
  - `_manifest_pages_to_payload` monta o payload do core, então fica no core.
- **X: blocos, listas, texto e AST de tabela.**
  - Estes são algoritmos de lista e de texto e vão para o docstruct: `_recover_empty_lettered_list_items` (130 linhas) e `_merge_list_blocks` se juntam a `docstruct.blocks.lists`; `_callout_titles` se junta a `docstruct.blocks.callouts`; `_render_text_from_blocks`, `_render_text_from_pages` e `_normalize_metadata_links` também vão para o docstruct.
  - `_table_ast_from_rows` e `_table_ast_from_metadata` se sobrepõem a `docstruct.tables.ast`; veja "Achados".
  - `_elements_to_blocks`, `_element_to_block` e `_text_kept_by_picture` transformam elementos do manifesto em blocos e usam as mensagens `MSG_*`. São adaptadores e ficam no core; a parte pura de `_element_to_block` (110 linhas) é separada antes.

### Maiores funções

São as funções que a #365 pediu para dividir, no tamanho atual. Todas ficam no core; a Fase 3 as divide depois que as partes puras saírem.

| Função | Grupo | Linhas |
|---|---|---|
| `PddlAccessibilityOrchestrator` (classe) | N | 336; só o `execute`, 198 (antes `executar`; dividido no passo 5: 81, com `_extract_structure`, `_enrich_before_planning`, `_replan_until_done` e `_check_unsatisfied`) |
| `_enrich_formula_latex` | P | 299 |
| `_enrich_picture_descriptions` | O | 197 |
| `_handle_vlm_pairwise_judge_method` | J | 179 |
| `_enrich_table_structures` | S | 179 |
| `build_pddl_structured_payload` | V | 134 |
| `_recover_empty_lettered_list_items` | X | 130 (vai para o docstruct) |

## Estado compartilhado

"Depende de" conta nomes, então não pega o acoplamento que passa pelo manifesto: um grupo grava uma chave ou um campo que outro grupo lê depois. Mover um lado sem o outro, ou trocar a ordem dos dois, muda o comportamento mesmo com todas as referências a nomes intactas. Este mapa foi medido com `ast` no mesmo retrato. Ele cobre:
- o `metadata["…"]` de elementos e obrigações, por subscrito, `.get`, `.setdefault`, `.pop` e `in`;
- o `extractor.configuration["…"]`;
- atribuições a campos de elementos e de obrigações.

Ele encontra 63 chaves, 17 delas gravadas ou lidas por mais de um grupo.

| Chave | Gravada por | Lida por | O que a ordem atual garante |
|---|---|---|---|
| `metadata["negation_overlay"]` | F, Q | F, Q, W | Q, antes do planejamento, reivindica uma barra de negação solta para matemática inline só se ninguém a reivindicou. F, na execução, pula barras reivindicadas e marca as que compõe. W deixa barras reivindicadas fora do payload. A reivindicação de Q, portanto, prevalece, e F é idempotente. |
| `metadata["vision_description_complete"]` | O, P | E, O, X | O a define numa descrição e a apaga quando registra uma falha. P a define quando uma região de fórmula se revela uma figura descrita. O handler de visão de E pula figuras completas, e X a usa para decidir qual texto de figura o payload mantém. |
| `metadata["vision_failure_reason"]` | O | E, O, V | O registra a causa e a nova tentativa dele a lê. O handler de E a lê. V a informa como degradação visível (`records_visual_failures`). |
| `metadata["vision_confidence" / "vision_elements" / "vision_language" / "vision_warnings"]` | O, P | — | Dois gravadores dos mesmos campos de descrição: O para figuras, P para o fallback de visão das fórmulas. Eles precisam manter um só formato. |
| `metadata["original_type"]` | K, O, P | — | Atribuída, e não definida uma vez só. Quando um elemento é reclassificado duas vezes, o último a gravar decide qual tipo original sobrevive, então a ordem faz parte do comportamento. |
| `metadata["src"]` | G, P | O | A inspeção de região e de página e o recorte de fórmula registram a origem da imagem; o enriquecimento de figuras a lê. |
| `metadata["table_ast"]` | S | E, F, I, Q, S | S a grava antes do planejamento. A passada de tabelas de Q roda depois de S, porque S pode substituir as células de uma tabela. E, F e I a leem na execução. |
| `metadata["table_read_failure"]` | S | S, V | S registra por que uma tabela não foi lida, e V a informa como degradação. |
| `metadata["mathml"]`, `metadata["verbalization"]`, `metadata["latex_normalized"]` | B, B, E | T | T considera uma fórmula legível a partir dessas chaves (`_formula_has_readable_content`), então a sua checagem de entrega depende de os handlers terem rodado antes. |
| `metadata["blank_page"]` | G | W | A inspeção de página marca páginas em branco, e o payload de página usa a marca. |
| `configuration["region_inspection_mode"]` | N | G | O pipeline escolhe o modo de inspeção, e os handlers de região e de página o leem. |
| `configuration["toolbox_provider"]` | (o extrator) | I, L | Gravada fora do orquestrador; a escolha de provider e a fusão a leem. |

**Campos de elementos e de obrigações.** Foram medidos pelo nome do atributo, então algumas ocorrências podem ser outros objetos com o mesmo atributo; leia como limite superior.
- `text` é gravado por E, F, G, H, I, L, O, P, Q e S;
- `type` por G, K, O e P;
- `raw_label` por G, O e P;
- `reading_order` por K e L;
- `page_number` por G, L, O e S;
- a lista `elements` por G, L e O;
- a lista `obligations` por O e P.

**Ordem do `execute`.** Antes do planejamento ele roda:
1. P classifica regiões de fórmula;
2. O descreve figuras;
3. Q marca matemática inline na prosa;
4. P reconhece fórmulas;
5. S lê tabelas;
6. Q marca matemática inline nas tabelas.

Os handlers do plano (B, E–L) vêm em seguida. As checagens de situação de T e o payload (V, W, X) vêm por último.

**Caracterização primeiro.** Antes de uma movimentação mexer num dos lados de uma chave compartilhada, um teste deve fixar o par de ponta a ponta num mesmo manifesto, e não cada lado sozinho:
- F, Q e W em `negation_overlay`;
- O, P, E e X em `vision_description_complete`;
- S antes de Q em `table_ast`;
- B e E antes de T nas chaves de fórmula legível;
- O e S até V nos registros de falha;
- K, O e P em `original_type`.

## Achados

1. **Quase duplicatas de funções do docstruct** (constituição P1). Unificá-las exige escolher um comportamento, então cada uma pede uma decisão própria, e não uma movimentação neutra:
   - `_table_ast_from_rows` contra `docstruct.tables.ast.table_ast_from_rows`. A versão do orquestrador devolve `{"body": []}` quando não há linhas e pula as que não são listas. A do docstruct devolve `None` e normaliza entradas mistas.
   - `_block_kind` contra `docstruct.fusion.convert.classify_kind`. As duas dão o `DiffBlock.kind` de um bloco. A versão do orquestrador lê só o tipo do elemento. A do docstruct também lê o texto e os sinônimos do tipo: um `title` é título lá e texto no core, e um parágrafo feito de um único trecho inline (`$x + y$`) é fórmula lá e texto no core. Mover `_block_kind` como está colocaria dois classificadores de tipo no docstruct. Escolher um muda os blocos que os handlers de fusão recebem, então isso precisa de uma decisão própria.
   - `_iou` contra `docstruct.geometry.intersection_area`. A interseção é a mesma; `_iou` acrescenta a união. **Resolvido sem mudança de comportamento:** `docstruct.fusion.similarity.iou` já calculava o mesmo valor para qualquer entrada (#402, Fase 3) e substituiu `_iou`.
2. **Aliases mortos.** Nenhum módulo, script ou teste usa `PmvAccessibilityOrchestrator` ou `build_pmv_structured_payload` (grupo Z). Podem sair num PR pequeno só para isso.
3. **Pontos de substituição dos testes.** Os testes substituem **20 nomes** no módulo do orquestrador:

   `VisionAgent` (10 arquivos), `_extract_picture_bytes` (9), `inspect_source_media` (9), `_enrich_picture_descriptions` (5), `_enrich_table_structures` (5), `DataAgent` (4), `_formula_recognition_crop` (3), `_run_extract_fused` (3), `toolbox_recognize_formula` (3), `_toolbox_render` (2), `_EMBEDDED_PICTURE_MAX_BYTES`, `_inspect_page`, `_judge_page`, `_manifest_pages_to_payload`, `_render_source_page`, `_save_region_artifact`, `asyncio`, `t`, `toolbox_convert_latex`, `toolbox_verbalize_latex` (1 cada).

   O código que busca esses nomes precisa continuar buscando pelo módulo que os testes substituem, ou os testes precisam passar a substituí-los no módulo onde o código agora mora. Este plano recomenda a segunda opção: os hooks injetados da #381 foram a origem das suas quatro inconsistências.
4. **As linhas em português se movem junto com o código.** Os grupos têm 106 linhas com texto em português, quase todas docstrings e mensagens de log em B, C, E, I, J, L e O. Cada movimentação precisa baixar a contagem do orquestrador em `tests/fixtures/portuguese_allowlist.json` pelas linhas que saem, e um arquivo novo não pode ganhar entrada na allowlist. Então as linhas movidas ou entram como exceção por caminho em `tests/test_no_portuguese.py` (texto para o usuário), ou são traduzidas no mesmo PR (docstrings). A #410 acompanha a tradução.
5. **Não sobrou operação local.** O orquestrador não importa nenhuma biblioteca operacional (`tests/test_architecture_layers.py`). Renderização, OCR, VLM e conversão passam todos pela Toolbox, então nada daqui vai para a Toolbox.

## Ordem da Fase 3

Cada passo é um PR sem mudança de comportamento. Os testes de caracterização vêm primeiro e rodam na `develop`. O core importa direto do novo lugar, sem bridge nem wrapper, e os testes substituem os nomes onde eles são buscados. As conferências de paridade nos casos 036 e 006 em staging acontecem ao fim de cada destino, com o cache de processamento desligado: a chave dele não inclui a revisão do código, então uma execução do branch leria a saída da `develop`.

1. **Remover os aliases mortos** (Z).
2. **docstruct, das folhas para dentro:**
   - os algoritmos de lista e texto do X;
   - as regras de detecção do W;
   - a leitura de linhas do S;
   - a geometria de sobreposição do F;
   - a geometria de spans do Q;
   - as heurísticas de texto do O, a geometria de caixas do I e `_tailjoin_position`;
   - `_element_role` e `_block_kind`.

   Cada um se move com seus testes para `libs/docstruct/tests` e deixa um adaptador no core onde a assinatura recebe modelos do core.
3. **SDK.** O render, a interpretação de artefatos e a chamada de text spans já existem no SDK, então este passo é pequeno e os reaproveita:
   - a leitura de text spans em lotes, a partir de `backend/tools/text_spans.fetch_text_spans`, como método do `ToolboxPdfClient`;
   - os tipos de entrada que o `pdf.render@2` aceita, a partir de `_RENDERABLE_MEDIA_TYPES`, como constante ao lado de `render`;
   - a leitura de `pB` do `document.adjudicate.page`, a partir de `_judge_probability`, ao lado do `ToolboxAdjudicateClient`.
4. **Decompor as funções mistas no core:** o `_extract_picture_bytes` do O, e o `_formula_recognition_crop` e o `_enrich_formula_latex` do P. As chamadas de render continuam passando pelo adaptador do grupo G.
5. **Dividir as maiores funções** da tabela acima, uma por PR.
6. **Reorganizar dentro do core** só o que ainda passar do limite de tamanho (decisão D4), por exemplo os handlers de execução em `backend/core/execution/handlers/`.
   - **Revisado depois do passo 5:** os módulos vão para `backend/core/pipeline/`, com a estrutura que o `acessilia_core.pipeline` teria pela [ADR-0016](../adr/0016-core-package.pt-br.md). Se essa ADR for aceita, levá-los para `libs/core` é uma troca de caminho, e o `backend/core` some com ela. Cada módulo fica abaixo de 900 linhas:

     ```text
     backend/core/pipeline/
       orchestrator.py   # a classe: a sequência do execute
       preflight.py      # inspeção de mídia, limites de página, apresentações (A, M)
       toolbox.py        # adaptadores: render, artefato de origem, juiz (G, J)
       payload.py        # build_pddl_structured_payload (V)
       enrichment/       # figuras (O), fórmulas (P), tabelas (S), matemática inline (Q), regiões (G)
       handlers/         # registro (K) e um módulo por grupo de handlers
     ```

   - **Ordem:** primeiro as folhas (payload, adaptadores), depois os handlers grupo a grupo, as etapas de enriquecimento e, por último, a classe. Cada pull request é neutro, com caracterização e teste diferencial. Os testes que substituem um nome em `pddl_orchestrator` (achado 3) passam para o módulo onde o nome agora está.
   - **O resto do core** (os agentes e seus prompts, a fusão, os adaptadores da Toolbox, os exportadores, as mensagens e seus catálogos) se reúne em `backend/core/` depois deste passo, seguindo o passo 2 do roteiro da [ADR-0016](../adr/0016-core-package.pt-br.md). Ali, um teste de fronteira precisa passar antes que os módulos vão para `libs/core`.
   - **Aguardam a [ADR-0017](../adr/0017-operational-sdk-and-agentic-core.pt-br.md)** (#470): o `toolbox.py` (render, artefato de origem, juiz) e a cadeia de fórmula de `enrichment/formulas`. O mecanismo deles pode ir para o SDK, então mudam de lugar quando a divisão for decidida. Os outros módulos da estrutura seguem como previsto. A primeira movimentação, `obligations.py` e `elements.py`, foi a #469 (mergeada). O `payload.py` veio na #472 (mergeada). Depois, os handlers mudam grupo a grupo: o `handlers/common.py` guarda os auxiliares que todos os handlers usam, e o `handlers/text.py`, os handlers que reparam texto sem modelo nem Toolbox (`norm-fix`, `unicode-repair`, `rep-guard`, `line-number-extractor`, `verse-chunker`, `tailjoin`, `deterministic-heading-repair`). Em seguida, o `handlers/content.py` guarda os handlers que conferem ou completam o conteúdo de um elemento (`vision-description`, `pandoc-table`, `pandoc-code`), e o `handlers/review.py`, o `human-review` terminal. O registro fica no orquestrador até o último grupo mudar. Os handlers que renderizam ou julgam pela Toolbox (`pymupdf-region`, `vision-page-inspection`, o juiz VLM, a fusão de dois providers) e os handlers de fórmula aguardam a ADR-0017.

As quase duplicatas do achado 1 são decisões de comportamento, cada uma num PR próprio (P8).

## Decisões a tomar

- **D1. Tipos das funções do docstruct.**
  - **A pergunta:** os algoritmos movidos devem receber o `DocumentElement` do docstruct ou valores simples (tuplas de caixa, strings, linhas)?
  - **Proposta:** valores simples para geometria e texto, e `DocumentElement` só onde o algoritmo precisa da estrutura do elemento. Isso mantém os adaptadores pequenos e não obriga o core a construir elementos do docstruct no caminho principal.
- **D2. As duas quase duplicatas.**
  - **A pergunta:** qual comportamento vale para o caso vazio de `table_ast_from_rows` (`None` ou um corpo vazio)? E o docstruct deve ganhar um `iou`?
  - **Proposta:** decidir cada uma com os testes dos chamadores, num PR de comportamento, depois das movimentações neutras.
- **D3. O que o passo do SDK acrescenta.**
  - **A pergunta:** o SDK precisa de um binding novo de render ou de text spans?
  - **Proposta:** não. `ToolboxPdfClient.render` e `ToolboxPdfClient.text_spans` já cobrem as chamadas, e o `ArtifactRef` cobre a interpretação de ids. O passo do SDK acrescenta só as três peças listadas no passo 3 da Fase 3, como métodos de cliente ou constantes. Compor várias chamadas numa função do SDK é o que a ADR A, na Fase 4, decide.
- **D4. Limite de tamanho de módulo.**
  - **A pergunta:** a #365 pediu um limite de tamanho de módulo combinado e conferido por um teste.
  - **Proposta:** 900 linhas para qualquer módulo em `backend/agents/` e `backend/core/`. Dois passam disso hoje: `pddl_orchestrator.py` (6.185) e `backend/core/manifest/builder.py` (1.205). Os dois entram na allowlist do teste com o tamanho atual, que só pode diminuir; o próximo maior é `backend/agents/vision_agent.py` (758).
  - **Ajustada depois do passo 5** (#402):
    - **Nenhum teste fazia a D4 valer ainda**, e o passo 5 aumentou o orquestrador de 5.531 para 5.823 linhas (#461–#466). Cada divisão encurtou a sua função, mas acrescentou assinaturas e docstrings. A allowlist começa com os tamanhos do dia em que o teste entrar.
    - **O teste entra com o passo 6**, antes da primeira movimentação: `tests/test_module_size.py`, com a allowlist em uma fixture.
    - **O que ele confere:**
      - um módulo do core acima de 900 linhas falha, a menos que esteja na lista. A varredura cobre os módulos do core onde eles estão hoje (`backend/agents/`, `backend/core/`, `backend/ai/`, `backend/pipeline/`, `backend/tools/`, `backend/export/`, `backend/adapters/` e os módulos de mensagens), e o `acessilia_core` quando a [ADR-0016](../adr/0016-core-package.pt-br.md) os mover;
      - um módulo da lista que cresce falha;
      - um módulo da lista que diminui falha até sua entrada ser reduzida, como faz a allowlist de português (`tests/test_no_portuguese.py`), para que o ganho fique registrado;
      - uma entrada com 900 ou menos é removida.
    - **O passo 6 leva os dois módulos da lista para baixo de 900.** O `builder.py` é dividido pelas próprias responsabilidades (montagem a partir do documento da Toolbox, ordem de leitura, necessidades de processamento, páginas sem estrutura) em pull requests próprios.
