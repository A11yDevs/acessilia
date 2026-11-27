# Enriquecimento como ações planejadas, depois do bootstrap (#640, PR 2)

Inglês, versão normativa: [English version](workflow-actions.md)

A [ADR-0029](../adr/0029-symbolic-core-every-step-planned.pt-br.md) torna os
passos semânticos de um job ações do domínio de planejamento. Para a baseline
0.3.0, ela distingue duas fases:

1. **Bootstrap**, que adquire o estado inicial: inspeção de mídia, limite de
   páginas e a extração estrutural inicial. Juntas, elas produzem o manifesto
   a partir do qual o Core formula as obrigações e os objetos do primeiro
   problema. O Core mantém a política de admissão e coordena a fase; a Toolbox
   executa as operações e devolve observações. Uma extração inicial fixa é uma
   limitação deliberada da baseline: por exemplo, o plano ainda não escolhe os
   providers da extração.
2. **Planejamento em ciclo fechado**, a partir do manifesto. O Core planeja,
   observa e replaneja. Os passos de enriquecimento, que hoje rodam antes do
   planejamento, migram para ações planejadas.

Esta página desenha a migração da segunda fase: o que roda hoje, as
restrições que uma migração precisa respeitar e a ordem dos pull requests.
Ela não muda código. Se o próprio bootstrap deve ser planejado é uma
investigação da 0.4.0
([#816](https://github.com/A11yDevs/acessilia/issues/816)).

## Hoje

`PddlAccessibilityOrchestrator._execute` (`pipeline/orchestrator.py`) roda, em
ordem:

| Fase | Estágio | O que faz | Chama | Checkpoint |
|---|---|---|---|---|
| Bootstrap | Inspeção de mídia | Lê os fatos de mídia do arquivo; um deck de slides é estruturado de outro jeito | Toolbox `media.inspect` | `media` |
| Bootstrap | Limite de páginas, antes da extração | Recusa um documento acima de `DocumentConfig.max_pages` pela contagem de páginas da inspeção (`DocumentTooLargeError`) | — | — |
| Bootstrap | Extração | Monta o manifesto: elementos, depois as obrigações derivadas dos seus tipos | Toolbox `document.structure.extract` (um ou dois providers) | `manifest` |
| Bootstrap | Limite de páginas, depois da extração | Confere o limite de novo contra a estrutura extraída | — | — |
| Enriquecimento | Passos antes do planejamento, numa ordem fixa (abaixo); desde a 0.3.12, os passos 5 e 6 rodam dentro do plano (M2), desde a 0.3.14 as descrições do passo 2 (M1), desde a 0.3.15 o passo 4 (M3), desde a 0.3.19 o passo 1 (M4a), e desde a 0.3.20 o passo 3 (M4b): antes do planejamento resta só a preparação do passo 2 | | Toolbox e os agentes de modelo do Core | `enriched` na preparação do passo 2; o checkpoint de execução, por passo do plano, no resto |
| Planejamento | | Compila o problema a partir do manifesto enriquecido e planeja | — | `plan` |

Os passos de enriquecimento (`_enrich_before_planning` até o core 0.3.11;
desde a 0.3.12, os passos 5 e 6 rodam dentro do plano, como o método
`table-enrichment`, M2; desde a 0.3.14, as descrições do passo 2, como o
método `picture-description`, M1; desde a 0.3.15, o passo 4, como o método
`formula-recognizer`, M3; desde a 0.3.19, o passo 1, como o método
`formula-region-classifier`, M4a; desde a 0.3.20, o passo 3, como o método
`inline-math-marker`, M4b):

| Passo | Função | Chama | Efeito no manifesto |
|---|---|---|---|
| 1. Regiões de fórmula | `_classify_formula_regions`, dentro do plano desde a 0.3.19 | Toolbox `pdf.render` (o recorte da fórmula); `VisionAgent` | confere os rótulos de fórmula do extrator. Um desenho é descrito uma vez e vira imagem, o que reconcilia suas obrigações (`reconcile_reclassified_element`); um candidato incerto vai para revisão humana |
| 2. Descrições de imagens | `_prepare_pictures` antes do planejamento; `_enrich_picture_descriptions` dentro do plano desde a 0.3.14 | `VisionAgent` | primeiro injeta uma imagem de página inteira para uma imagem raster isolada e anota a posse do texto visual, ambas a partir da inspeção de mídia (essas ficam antes do planejamento); depois uma descrição por imagem, e a posse anotada de novo |
| 3. Matemática inline | `_mark_inline_math` (dentro do plano desde a 0.3.20, `_enrich_inline_math`) | Toolbox `document.text.spans` | marca a matemática na prosa |
| 4. LaTeX das fórmulas | `_enrich_formula_latex`, dentro do plano desde a 0.3.15 | Toolbox `math.recognize`, `pdf.render`; `VisionAgent` como alternativa | separa os números de equação, depois o LaTeX de cada fórmula |
| 5. Estrutura das tabelas | `_enrich_table_structures` | `DataAgent` | uma AST estruturada por tabela |
| 6. Matemática inline das tabelas | `_mark_table_inline_math` | Toolbox `document.text.spans` | marca a matemática nas células (depois do passo 5, que pode substituir células) |

O que os passos compartilham não é uniforme:

| Recurso | Passos | Onde vive (core 0.3.12) |
|---|---|---|
| Breaker de provider | 1, 2, 4, 5 | o da execução, `RunPorts.services` (`run_breaker`), compartilhado com os métodos `formula-region-classifier`, `picture-description`, `formula-recognizer` e `table-enrichment`. A ordem deles é o desempate do planejador, então numa indisponibilidade parcial o passo que o plano roda primeiro gasta primeiro o orçamento do breaker (#853) |
| Progresso por objeto (`on_progress`) | 1, 2, 4 | uma variável local, de `checkpoints.enrichment_progress`; os passos 1, 2, 4 e 5, dentro do plano, gravam o manifesto que estão enriquecendo depois de cada objeto no checkpoint de execução (`step_progress`, #836), e uma queda no meio do passo retoma dele |
| Cache de regiões | 1, 2, 4 | de `RunPorts` (`region_cache_for`) |
| Leitor de spans de texto (`_TextSpanReader`) | 3, 6 | o da execução, `RunPorts.services` (`run_text_spans`), compartilhado pelos métodos `inline-math-marker` e `table-enrichment`; não guarda manifesto |
| Mensagens de progresso | 1–6 | `RunServices.progress`, dentro do plano: cada método anuncia seu passo |
| Inspeção de mídia | 2 | uma saída do bootstrap; dentro do plano, `RunServices.media_inspection`, que o orquestrador preenche ao carregar ou fazer a inspeção |
| Arquivo de origem | todos | o contexto da execução; o manifesto registra seu digest |

Até o core 0.3.19, os passos 3 e 6 também rodavam uma vez depois da
execução, antes do build canônico, sobre o manifesto executado (#599): o
`rescue-omitted` acrescenta blocos enquanto o plano roda, e o build canônico
só converte os spans que o manifesto carrega. Desde a 0.3.20 (M4b) essa
passada não existe mais. Um bloco que o plano acrescenta ganha a obrigação
`mark-inline-math` pela reconciliação, e uma execução que terminou com esse
trabalho replaneja para ele, como uma descoberta, com o job reaberto para
esse replanejamento. Uma tabela adotada do provedor secundário é marcada como
`inline_math_stale`, e o mesmo passo a marca de novo. Quando o passo marca um
bloco depois que uma conversão de fórmula já rodou, ele descarta essa
conversão, para que o build canônico a refaça com as variáveis finais.

O plano então trabalha sobre o que o enriquecimento produziu. Alguns métodos
só conferem esse trabalho: `vision-description` confere as descrições e
`pandoc-table` confere a AST da tabela. Os dois são `validation` em
`toolbox_gate.LOCAL_METHODS` (#804).

## O que o bootstrap extrai

A extração do bootstrap é rica. Os providers de estrutura detectam e rotulam
os objetos da página, e os passos de enriquecimento complementam e conferem
essa saída; não a refazem.

- **Docling**, o provider primário (`TOOLBOX_PROVIDER=docling`, com
  `FUSION_MODE=single` por padrão), roda:
  - a detecção de layout, com um rótulo e uma caixa por objeto: texto,
    títulos, listas, tabelas, imagens, fórmulas, código, legendas, notas de
    rodapé, cabeçalhos e rodapés de página;
  - a ordem de leitura;
  - OCR;
  - a estrutura das tabelas, com o TableFormer `accurate` (a única opção de
    pipeline que a Toolbox configura, `table_mode`). A ADR-0030 leva o
    reconhecimento de tabelas para a capacidade especializada,
    `table.recognize`, quando Docling e MinerU forem providers dela
    ([acessilia-toolbox#170](https://github.com/A11yDevs/acessilia-toolbox/issues/170)).
- **Os enriquecimentos opcionais do Docling ficam desligados por desenho**:
  enriquecimento de fórmulas (`do_formula_enrichment`), descrição e
  classificação de imagens, e enriquecimento de código. Providers mais
  especializados fazem esse trabalho, com resultado melhor:
  - LaTeX das fórmulas: `math.recognize` (PP-FormulaNet), com o modelo de
    visão como alternativa;
  - descrições de imagens: o modelo de visão;
  - MathML e matemática falada: `math.convert` e `math.verbalize`
    (`math-speech`).
- **MinerU**, o provider secundário em `FUSION_MODE=dual`, detecta fórmulas
  (em destaque e inline), tabelas (em HTML), gráficos, legendas, código e
  notas de rodapé.

Então cada passo de enriquecimento é **condicionado ao que o bootstrap deixou
faltando ou duvidoso**:

| Passo | Roda sobre | Porque |
|---|---|---|
| 1. Regiões de fórmula | os rótulos de fórmula do extrator | uma detecção pode rotular um desenho como fórmula: o rótulo é uma observação a conferir |
| 2. Descrições de imagens | imagens sem descrição | o extrator não descreve imagens |
| 3. Matemática inline | prosa da camada de texto | o Docling não informa região de fórmula inline num PDF tipografado |
| 4. LaTeX das fórmulas | fórmulas sem marcação LaTeX (`has_latex_markup`) | o enriquecimento de fórmulas do Docling está desligado; um reconhecimento precisa concordar com a camada de texto, quando houver |
| 5. Estrutura das tabelas | tabelas sem estrutura utilizável, ou embaralhadas (`TABLE_VISUAL_REVIEW`) | a estrutura do TableFormer é mantida quando é utilizável. Depois da #170 a extração entrega as tabelas como regiões, e a condição vira "toda tabela sem estrutura reconhecida válida": uma região, uma estrutura suspeita ou uma leitura que falhou. Uma estrutura válida é reaproveitada, também na retomada (ADR-0030) |

A migração precisa manter essas condições: **uma obrigação só existe onde sua
condição vale**. Do contrário, o plano mandaria para um provider
especializado um objeto que o bootstrap já tratou bem. As condições também
são onde as detecções do bootstrap são conferidas. Conferir um rótulo, a forma
de uma tabela ou um reconhecimento contra a camada de texto decide o
workflow, então pertence ao plano.

A política é a ADR-0030 (proposta no #819): as suítes de estrutura ficam
estruturais, e o que mais oferecerem é usado por capacidade, como um provider
que compete com os outros. Dois pontos da configuração atual ainda não
correspondem a ela:
- **A intenção do desenho só é garantida pelos padrões da Toolbox.** O core
  manda para `document.structure.extract` só o idioma e a flag de cache, e
  nenhuma opção de pipeline. Os plugins desligados estão desligados por causa
  do registro de providers da Toolbox e dos padrões dos providers, que nem o
  core nem o manifesto veem. O adaptador do Docling registra em
  `extractor.configuration` só os parâmetros da requisição, não os do
  registro (`table_mode`).
- **O reconhecimento de fórmulas e tabelas do MinerU está ligado por padrão.**
  O adaptador do MinerU 2.1 da Toolbox (`main`, release 0.2.0) manda
  `formula_enable=true` e `table_enable=true`, a menos que se peça o
  contrário; o `develop` passa para o MinerU 4.0.12 com `--tier basic`. No
  modo dual, uma fórmula fundida que vem do MinerU com LaTeX, ou uma tabela
  que vem com HTML, passa pela condição e assim pula o PP-FormulaNet ou o
  leitor de tabelas. Pela ADR-0030, o reconhecimento de fórmulas sai da
  capacidade de estrutura
  ([acessilia-toolbox#169](https://github.com/A11yDevs/acessilia-toolbox/issues/169)),
  e o de tabelas também, quando `table.recognize` tiver os reconhecedores do
  Docling e do MinerU como providers (#170).

## A observação central

O domínio já tem uma ação operacional genérica, `execute-obligation(o, m)`.
Um método é um jeito de satisfazer uma obrigação, e o executor roda o handler
do método. Então **um passo vira uma ação ao virar o método de uma
obrigação**: o planejador passa a escolhê-lo, ordená-lo por `depends-on`,
contar seu custo, descartá-lo pelos fatos do catálogo (domínio 2.4) e
replanejar quando ele falha. Nada disso precisa de um novo esquema de ação, e
kinds novos de obrigação são objetos que o compilador emite a partir do
manifesto. **A migração do enriquecimento não muda o domínio.**

## Restrições

1. **Um plano não cria objetos; obrigações mudam durante o plano.** A
   classificação de fórmulas pode reclassificar um elemento e reconciliar suas
   obrigações, então depois dela as próximas ações dependem de obrigações que
   o problema não tinha: acrescentadas, e também removidas, substituídas ou
   religadas.

   Antes do M0 o executor tratava só os acréscimos. Depois de um handler bem-sucedido e validado,
   `_run_obligation_handler` chama `_select_discovered` (#594), que seleciona
   as obrigações que o handler acrescentou. Quando alguma continua
   insatisfeita, ele liga `replan_required`. O resto do plano ainda roda, e o
   relatório leva a flag a `_replan_until_done`, que replaneja com essas
   obrigações como raízes.

   O que faltava (atendido pelo M0, abaixo):
   - o sinal de descoberta divide o orçamento `max_replans` com a recuperação
     de falhas, e o relatório não diz por que pede um replanejamento;
   - ele só vê obrigações **acrescentadas**, não as outras mudanças
     semânticas: uma obrigação tornada inaplicável, removida ou substituída
     por uma reclassificação, ou uma dependência alterada;
   - o resto do plano roda mesmo que uma mudança tenha invalidado alguns dos
     seus passos.

   O M3 e o M4 evoluem esse mecanismo; não acrescentam um segundo. Seus
   critérios:
   1. **Reaproveitar o gatilho:** partir de `_select_discovered` e do fluxo de
      `replan_required`.
   2. **Distinguir os motivos:** descoberta ou mudança de estado versus falha
      operacional, tanto no relatório (para a observabilidade) quanto no
      orçamento.
   3. **Separar os limites:** `max_replans` continua contando a recuperação de
      falhas; uma proteção própria impede expansão ou reclassificação sem
      progresso, para que não haja ciclos.
   4. **Cobrir mais que acréscimos:** detectar quando uma reclassificação
      torna obrigações existentes inaplicáveis, muda dependências ou exige
      obrigações novas.
   5. **Revalidar o plano remanescente:** não executar passos baseados em
      tipos ou obrigações que uma mudança relevante do manifesto tornou
      obsoletos.
   6. **Preservar a persistência e a retomada:** `save_plan`, a substituição do
      checkpoint de execução como hoje, e testes de idempotência.
   7. **Testar os cenários:** sucesso que cria obrigação, sucesso que
      reclassifica um elemento, falha com alternativa, retomada a partir de
      checkpoint e a proteção contra replanejamento cíclico.

   Uma flag em `MethodResult` ("o estado mudou, replaneje") continua em
   discussão, como evolução do contrato existente.

   **Atendido no core 0.3.13 (M0, #832).**
   - O gatilho é o existente, `_select_discovered` e `replan_required` (1).
   - O relatório distingue os motivos sem mudar o schema. Um passo que a
     mudança tornou obsoleto fica `skipped` com o motivo (`skipped` já era um
     status de passo), então uma execução em que nada falhou não tem passo
     `failed`. O orquestrador conta esse replanejamento à parte e registra o
     motivo no log (2).
   - `max_replans` conta as falhas e `max_discovery_replans` o resto. Um
     replanejamento de descoberta cujo estado de planejamento é aquele de que
     o anterior partiu não roda (3). O estado é `planning_signature`, tomado
     depois da reconciliação: kind, alvos, dependências, status e métodos
     tentados de cada obrigação replanejável, então os mesmos ids com outros
     alvos ou dependências são progresso. Ele fica no checkpoint de plano
     (`previous_signature`), então uma retomada mantém a guarda; um checkpoint
     sem ele retoma como antes.
   - Uma execução com falha e descoberta é um replanejamento de falha
     enquanto `max_replans` dura: o orçamento de descobertas nunca contorna o
     de falhas. Desde o core 0.3.22 (#842), com `max_replans` esgotado, a
     execução ainda pode ser um replanejamento de descoberta, dentro de
     `max_discovery_replans` e da guarda de assinatura, mas só para o
     trabalho que nenhuma falha toca (`_discovered_roots`): nunca tentado e
     sem obrigação aberta e já tentada entre as suas dependências. As
     obrigações que falharam e o que espera por elas ficam fora dessa rodada
     e de todas as seguintes, então as suas alternativas nunca rodam. Ficar
     fora de um plano não é ser cancelada: o executor preserva `selected`
     como meta do job. O escopo do plano é `NominalPlan.selected_obligations`;
     `complete-job` confere esse escopo e as metas recém-descobertas. A entrega
     julga todas as metas abertas. Trabalho excluído recebe `deferred_reason`
     quando conhecido (ADR-0031). Uma obrigação crítica deixada aberta, encontrada,
     falha ou à espera de trabalho falho, ainda faz o job falhar em vez de
     ser entregue em silêncio, e um refinamento é entregue com aviso e sem
     cache.
   - Obrigações removidas, substituídas e religadas estão cobertas (4). Um
     passo cuja obrigação agora depende de uma obrigação aberta que este plano
     não executa antes dele (encontrada durante a execução, ou planejada e
     ainda não executada) espera o replanejamento. Uma remoção precisa religar
     as dependentes da obrigação removida (`_rewire_removed_dependencies`); o
     manifesto recusa uma dependência pendurada, e o executor relata uma como
     bug do handler. Antes de a guarda ler o estado, as referências de
     obrigação e o DAG do manifesto que a execução mudou são rechecados, então
     uma referência pendurada deixada por um handler faz o job falhar com a
     mensagem do manifesto, nomeando a obrigação e a dependência ausente, em
     vez de um `KeyError`. Desde o core 0.3.21 (#844), o manifesto que uma
     execução entrega passa por todas as checagens que uma retomada faz,
     qualquer que seja o status da execução, dry runs incluídos
     (`validate_delivered_manifest` em `_check_unsatisfied`): uma execução
     que concluiu, ou terminou sem replanejamento, não entrega mais uma
     referência pendurada, um ciclo, uma obrigação satisfeita esperando por
     uma aberta, ou contagens desatualizadas.
   - `PDDL_MAX_DISCOVERY_REPLANS` (padrão 3) define o limite separado; um
     valor diferente do padrão entra nas identidades do checkpoint e do
     cache.
   - Os passos que elas tornam obsoletos são pulados, não executados (5). Isso
     inclui uma obrigação mudada sob o mesmo id: outro kind, alvos de outros
     tipos, outro conjunto de alvos, ou o método do passo que deixou de ser
     admissível. O executor compara cada passo com o que tornava o método
     aplicável no manifesto do plano. Desde o core 0.3.23 (#843) isso inclui
     os ids dos alvos. `remap_references` (`handlers/structure.py`) registra o
     mapeamento de cada divisão e junção no manifesto de trabalho, em ordem; o
     executor os compõe sobre os alvos planejados e compara o resultado com os
     atuais (`_retargeted`). Uma divisão ou junção sozinha não é mudança e não
     gasta replanejamento de descoberta; qualquer outra coisa é, qualquer que
     seja a forma: um elemento trocado ou acrescentado, novo ou preexistente,
     ou um removido sem junção. O checkpoint de execução salva o registro para
     uma retomada (um anterior à 0.3.23 não o tem, e uma divisão antes dele
     custa um replanejamento). Uma divisão ou junção ainda pode tornar o passo
     obsoleto por outro motivo (tipos, método, dependências). Os ids são
     únicos num manifesto; um liberado por uma remoção pode voltar num plano
     seguinte. Mudanças do conteúdo dos elementos sob o mesmo tipo não são
     comparadas (revisões de elementos são a #840).
   - O contador de descobertas fica no checkpoint de plano, e os pulos derivam
     dos manifestos do plano e do checkpoint, então uma retomada não precisa
     de mais nada (6).
   - `tests/test_changed_obligations.py` e
     `tests/test_changed_obligations_semantics.py` têm os cenários (7),
     incluindo uma reclassificação dentro de um handler real, uma falha com
     alternativa, uma falha ao lado de uma descoberta, e a retomada do
     contador de descobertas e da guarda.
2. **A ordem causal vira dependência, nunca custo.** Custos escolhem entre
   alternativas; não podem impor uma ordem tecnicamente obrigatória. A ordem
   fixa vira `depends-on` entre obrigações do mesmo elemento:
   - a classificação de fórmulas vem antes da descrição de um candidato que
     ela reclassifica como imagem, e antes do LaTeX de um candidato que ela
     mantém ou deixa sem classificação. Toda obrigação que sua reconciliação
     cria também vem depois dela;
   - o LaTeX da fórmula vem antes de `verbalize-formula` e
     `normalize-formula`;
   - a estrutura da tabela vem antes da matemática inline da tabela.

   Não se encontrou dependência de dados por elemento entre a matemática
   inline da prosa e os passos de fórmula (eles leem elementos diferentes),
   entre imagens e tabelas, nem entre o LaTeX das fórmulas e as tabelas. Cada
   migração confirma isso para o seu passo. O M4b revê isso para as
   conversões de fórmula: elas leem as variáveis que as marcas da prosa dão,
   uma dependência através do documento, não de um elemento compartilhado
   (abaixo).

   **M1 (core 0.3.14).** As descrições agora rodam depois dos passos 3 e 4.
   A matemática inline da prosa lê parágrafos, itens de lista, legendas e
   notas de rodapé, e seu teste de sobreposição só reconhece texto feito de
   barras de negação, não o de uma imagem. O LaTeX das fórmulas lê fórmulas,
   então não vê mais uma imagem que o modelo lê como fórmula: essa fórmula
   fica com o LaTeX do modelo, sem a segunda leitura do reconhecedor nem a
   separação do número da equação. Essa lacuna durou uma versão: o M3 (core
   0.3.15, #846) torna o LaTeX das fórmulas uma obrigação do documento, que
   a reconciliação dá a uma fórmula encontrada durante o plano, então o
   `verbalize-formula` dela espera por ela
   (`test_a_picture_read_as_a_formula_gets_the_formula_steps`).

   **M3 (core 0.3.15).** O LaTeX das fórmulas agora roda dentro do plano,
   depois da matemática inline da prosa, que lê outros elementos, e sem
   ordem com as imagens e as tabelas, que pegam outros elementos (fórmulas
   nunca são descritas, nem são tabelas). `verbalize-formula` e
   `normalize-formula` dependem dele, assim como as obrigações de página de
   uma página com fórmula: a ordem de antes do planejamento.

   O que o M3 restaura para uma fórmula encontrada durante o plano (#846) é
   o que o passo fazia: o rótulo da equação separado e, quando o texto do
   modelo não tem marcação LaTeX, uma leitura. O LaTeX que o modelo já deu
   não é lido de novo, como antes; uma segunda leitura independente é
   pesquisa (#852). A seleção do passo e a sua execução compartilham uma só
   política (`formulas_needing_number_separation`,
   `formulas_needing_recognition`), então uma fórmula selecionada só pelo
   rótulo não é lida de novo. Dentro do passo a estratégia continua fixa
   (`math.recognize`, depois a alternativa de visão); o plano escolhe, ordena
   e contabiliza o passo, não essa estratégia. A indisponibilidade do
   `math.recognize` é paga uma vez por obrigação: uma segunda, para fórmulas
   encontradas durante o plano, sonda de novo. Uma fórmula cujo recorte não
   pôde ser feito registra o motivo (`crop_unavailable`, `no_page`), como uma
   imagem.

   Entre passos do documento que pegam outros elementos não há
   dependência, e os custos são iguais, então o planejador desempata
   (`DOCUMENT_STEPS` é a ordem da reconciliação, não a do plano).

   **M4a (core 0.3.19).** A classificação de regiões de fórmula roda dentro
   do plano. Ela compartilha as fórmulas com o LaTeX das fórmulas, que deve
   vir depois dela (a classificação decide se uma região é matemática),
   então `recognize-formulas` depende de `classify-formula-regions` nas
   fórmulas que eles compartilham: `DOCUMENT_STEPS` lista a classificação
   primeiro, e a regra de arestas o segue. Um elemento que as descrições
   transformaram em fórmula (uma imagem ou um visual substituto) não é
   classificado: as descrições rodavam depois da classificação antes do
   planejamento, então ele nunca era, e uma segunda resposta poderia
   descartar a fórmula que elas deram. Uma classificação que não teve
   resposta (`unclassified`) é tentada de novo quando o passo roda de novo,
   como nos outros passos compostos; `math` e `unresolved` são decisões. Uma
   fórmula compartilhada faz o lote inteiro do reconhecimento esperar o lote
   da classificação: o custo da granularidade de documento, aceito para a
   0.3.0 (sublotes são pesquisa da #619).

   **M4b (core 0.3.20).** A matemática inline da prosa roda dentro do plano,
   como a obrigação do documento `mark-inline-math`. As conversões de fórmula
   (`verbalize-formula`, `normalize-formula`) leem as variáveis que suas
   marcas dão, então esperam por ela embora não compartilhem elemento: o
   passo as declara como `waiting_kinds`, uma dependência declarada mínima (a
   #865 propõe predecessores em geral). Ela compartilha um parágrafo com as
   descrições (um documento majoritariamente visual) e uma tabela obsoleta
   com o enriquecimento de tabelas, e vem depois dos dois. Ela não chama
   modelo, então o breaker de visão não a ordena; os passos que compartilham
   esse breaker (descrições, classificação e LaTeX das fórmulas, tabelas) só
   são ordenados por ele operacionalmente, numa indisponibilidade parcial do
   provider; isso está documentado, não imposto (#853).

   A revisão do #867 corrigiu quatro pontos desse desenho:
   - *Uma tabela obsoleta marcada de novo.* Uma obrigação satisfeita não
     cobre um elemento cujo resultado a execução invalidou depois
     (`DocumentStep.renewed`): uma tabela marcada `inline_math_stale` depois
     de o passo marcá-la entra numa obrigação nova. Uma obrigação esgotada
     ainda a cobre, então uma tentativa degradada não é reaberta para sempre.
   - *Evidência que a detecção não lê.* Um bloco de prosa sem caixas que já
     traz `$…$` (um parágrafo resgatado) também entra no passo: o passo não
     marca nada nele, mas o pesa para descartar as conversões feitas antes
     dele, como fazia a passada depois da execução da #599. Com
     `INLINE_MATH_DETECTION=off` o passo ainda é planejado pelo mesmo motivo,
     não marca nada e informa `detection: off`.
   - *Um passo não crítico.* `mark-inline-math` é não crítica
     (`DocumentStep.critical=False`): quando ela se esgota, as conversões que
     esperavam por ela perdem essa aresta e rodam sem as suas variáveis, em
     vez de ficarem fora do replanejamento e falharem o job.
   - *O trabalho que uma execução concluída deixa.* Encontrá-lo não reabre o
     job: o laço de replanejamento o reabre, só quando o replanejamento é
     permitido. Com o orçamento de descobertas gasto, o job mantém o seu
     status, e `_check_unsatisfied` julga o que foi encontrado como em
     qualquer execução: uma obrigação crítica falha o job, um refinamento
     deixa um aviso.

   Quando o passo descarta uma conversão, a obrigação `verbalize-formula` ou
   `normalize-formula` continua `satisfied`: o método dela rodou e a sua
   evidência vale. A construção canônica regenera `mathml` e `verbalization`
   a partir do manifesto final (`_enrich_math_blocks`, com o enriquecedor
   matemático da execução: as mesmas conversões do Toolbox, e as variáveis
   de todas as fórmulas e trechos inline); sem elas a fórmula mantém o seu
   LaTeX, como quando os métodos planejados degradam. A regeneração é uma projeção do
   manifesto final, não uma nova decisão semântica, então fica fora do
   plano. Reabrir as obrigações em vez disso, com invalidação seletiva e
   proveniência, é a #871.
3. **A infraestrutura fica fora do domínio** (ADR-0029). O cache de regiões já
   está em `RunPorts`. O breaker, o gancho de progresso e o leitor de spans de
   texto são variáveis locais hoje. A proposta é torná-los um **serviço de
   enriquecimento** por execução, no contexto da execução e montado pelo
   orquestrador, para que o breaker mantenha seu escopo de documento inteiro.
   Do contrário, uma indisponibilidade de provider viraria uma falha por
   obrigação.
4. **As entradas dos estágios vêm do manifesto, não de portas novas.** Os
   handlers chegam ao arquivo de origem pelo manifesto
   (`_verify_source_digest`), como o `pymupdf-region` faz. As duas partes do
   passo 2 que leem a inspeção de mídia, a injeção da imagem de página
   inteira e a anotação de posse, derivam de fatos do bootstrap e criam
   objetos, então **ficam no bootstrap**. O método de imagens (M1) anota a
   posse de novo depois de retipar elementos, como o passo fazia, então lê a
   inspeção que o orquestrador entrega aos serviços da execução
   (`RunServices.media_inspection`); o planejador nunca a lê. Gravar no
   manifesto, tipados, os dois fatos de que ele precisa é a #847. Dentro do
   plano o método não injeta de novo a imagem de página inteira: essa parte
   estrutural continua sendo do bootstrap.
5. **Os handlers são síncronos.** `MethodHandler` é
   `(manifest, obligation_id) -> MethodResult`; os passos são assíncronos. Um
   handler migrado os chama por `acessilia_sdk.runtime.run_sync`, como o
   `dual-provider-fusion` faz. O executor roda numa thread de trabalho
   (`run_blocking`), onde o `run_sync` inicia seu próprio loop.
6. **Chamadas de modelo ainda não são capacidades.** `VisionAgent` e
   `DataAgent` são os agentes de modelo do Core
   ([classificação](core-agent-classification.pt-br.md)). Levar um passo para
   um método o torna planejado, mas a chamada de modelo continua no Core. Esse
   método fica `transitional` em `LOCAL_METHODS` até a chamada virar uma
   capacidade (#804, #640 PR 4). Até lá o gate não consegue conferir a
   chamada de modelo; as chamadas à Toolbox que o passo faz são declaradas em
   `METHOD_TOOLBOX_REQUIREMENTS` quando a falta de uma exclui o método, ou em
   `METHOD_OPTIONAL_CAPABILITIES` quando a falta de uma só o degrada por
   elemento (#848). O gate informa uma chamada opcional ausente como
   `degraded_methods` nos metadados de disponibilidade e no log, e nunca
   exclui o método; o papel dele em `LOCAL_METHODS` (onde a implementação
   vive) é uma dimensão separada.
7. **A retomada continua idempotente.** Hoje um passo pula os objetos que já
   terminou. Como método, o mesmo registro torna barato um passo do plano
   executado de novo, e o checkpoint de execução registra quais passos
   rodaram.

   **Dentro de uma ação composta (#836).** A atomicidade do planejador não é
   a granularidade da persistência. Um método composto
   (`picture-description`, `formula-recognizer`, `table-enrichment`) grava o
   manifesto que está enriquecendo depois de cada objeto terminado, agrupado
   como antes do planejamento, no checkpoint de execução, como
   `step_progress` ao lado do último passo terminado (pelo
   `RunServices.step_checkpoint`; sem fase nova). Uma execução retomada do
   mesmo plano recomeça esse passo dele, e os filtros por objeto do passo
   (`vision_description_complete`, a estrutura de uma tabela, o registro de
   reconhecimento de uma fórmula) pulam os objetos já feitos, então as
   chamadas de modelo que eles custam não são pagas de novo. As obrigações
   que os objetos terminados do passo interrompido acrescentaram (uma imagem
   lida como fórmula ganha `verbalize-formula`) são selecionadas na
   restauração, como o executor faria quando o handler retornasse, então o
   replanejamento as planeja. O checkpoint de uma execução retomada parte do
   snapshot que ela retomou, então uma segunda queda no mesmo passo também
   mantém o progresso da retomada. O progresso de um passo que o plano não
   roda em seguida nunca é usado, e o próximo passo terminado o descarta. A recuperação coletiva continua do passo: um
   breaker, uma passada de retry. As mensagens de progresso passam pelo
   `RunServices.progress`, ligadas ao job.
8. **Equivalência primeiro.** Cada migração mantém um teste diferencial do
   manifesto final em documentos de fixture, antes e depois (ADR-0028).

## Obrigações do documento

A primeira migração mostrou que um passo nem sempre vira um método por
elemento sem perder comportamento. O passo de tabelas lê as tabelas com um
breaker de provider, faz uma passada de retry para o documento inteiro (espera
`VISION_RETRY_PASS_DELAY_SECONDS` uma vez e, com o breaker aberto, deixa passar
uma chamada de teste, que recupera todas as tabelas se o provider voltou) e
informa seu progresso. Por tabela, cada tabela que falhasse esperaria sozinha,
e as tabelas depois da abertura do breaker perderiam a recuperação. A descrição
de imagens, além disso, roda em paralelo (`vision.concurrency`), enquanto o
executor roda um passo por vez.

Então um passo que trabalha sobre o documento inteiro vira **uma obrigação do
documento**:
- ela tem como alvos todos os elementos sobre os quais o passo trabalha;
- seu método roda o passo como antes, com o breaker e o leitor de spans da
  execução (`RunPorts.services`);
- as obrigações por elemento que precisam do resultado dela dependem dela.

O planejador continua escolhendo-a, ordenando-a, contando seu custo,
descartando-a pelos fatos do catálogo e replanejando quando ela falha. A
ADR-0029 permite uma ação composta assim: seus passos internos não são ações
PDDL. A obrigação é criada quando o manifesto é enriquecido, antes do primeiro
plano, e só quando o documento tem os elementos sobre os quais o passo
trabalha. Essa é a sua condição; o método mantém as condições por elemento do
passo.

Cinco passos são planejados assim, cada um um `DocumentStep` de
`pipeline/document_obligations.py`, que guarda as regras abaixo uma vez para
todos:

| Passo | Tipo e método | Alvos | Sai dos alvos | Dependem dela |
|---|---|---|---|---|
| Enriquecimento de tabelas (M2, 0.3.12) | `enrich-tables`, `table-enrichment` | todas as tabelas | um elemento que deixou de ser tabela | `linearize-table`, `select-table-source` e as obrigações de página de uma página com tabela |
| Matemática inline da prosa (M4b, 0.3.20) | `mark-inline-math`, `inline-math-marker` | num PDF, a prosa (parágrafos, itens de lista, legendas, notas de rodapé) com caixas e texto que nenhuma detecção marcou, e as tabelas cujas marcas ficaram obsoletas (`inline_math_stale`) | um elemento que deixou de ser prosa ou tabela | as obrigações de página de uma página com esse elemento e, quais forem seus alvos, `verbalize-formula` e `normalize-formula` (`waiting_kinds`) |
| Classificação de regiões de fórmula (M4a, 0.3.19) | `classify-formula-regions`, `formula-region-classifier` | numa fonte que pode ser renderizada, as fórmulas sem marcação LaTeX que nenhuma classificação decidiu, menos uma que as descrições transformaram em fórmula | um elemento que deixou de ser fórmula (um desenho que ela descreveu é imagem) | `recognize-formulas` (eles compartilham a fórmula), `verbalize-formula`, `normalize-formula` e as obrigações de página de uma página com fórmula |
| LaTeX das fórmulas (M3, 0.3.15) | `recognize-formulas`, `formula-recognizer` | as fórmulas com um rótulo de equação a separar e, numa fonte que pode ser renderizada, as sem LaTeX que nenhum reconhecimento registrou | um elemento que deixou de ser fórmula (o reconhecimento o leu como imagem) | `verbalize-formula`, `normalize-formula` e as obrigações de página de uma página com fórmula |
| Descrições de imagens (M1, 0.3.14) | `describe-images`, `picture-description` | as imagens ainda não descritas; sem imagens, num documento majoritariamente visual, seus visuais substitutos, ou o primeiro elemento de um documento de uma página; nunca uma fórmula nem uma tabela | um elemento que virou fórmula ou tabela | `describe-image` e as obrigações de página de uma página com imagem |

Um manifesto com todas as imagens descritas (um checkpoint de enriquecimento
da 0.3.13) não ganha `describe-images`. Os candidatos são escolhidos antes de
deixar de lado os já descritos, então um documento com todas as imagens
descritas não passa mais para os seus visuais substitutos, como o passo
antes do planejamento fazia numa retomada. Os candidatos e os elementos que
o passo mantém compartilham um só teste (`is_describable`), então o passo
nunca pega um elemento que depois deixaria de lado. Uma fórmula ou uma
tabela, que a alternativa de uma página pegava, fica para os seus próprios
passos e nunca é retipada como imagem.

**Entre os passos** a política é explícita: dois passos só compartilham
elementos quando o primeiro precisa rodar antes do segundo, e
`DOCUMENT_STEPS` os lista nessa ordem; as arestas a seguem (a obrigação de
um passo pode depender da de um passo anterior que compartilha um elemento,
nunca da de um posterior), então nunca fazem ciclo. Antes da revisão da
#845 as descrições e as tabelas podiam compartilhar a tabela de um documento
de uma página, e a regra de alvos, aplicada por cada passo, fazia um
depender do outro. Hoje a classificação de regiões de fórmula e o LaTeX das
fórmulas compartilham fórmulas (M4a), e a matemática inline compartilha um
parágrafo com as descrições e uma tabela obsoleta com o enriquecimento de
tabelas (M4b); em cada par o primeiro roda antes. Além dos alvos, um passo
pode declarar `waiting_kinds`: kinds de obrigação que esperam por ele quais
forem seus alvos (M4b: as conversões de fórmula). As arestas são reconciliadas mais
uma vez depois que as obrigações de todos os passos existem, então o
primeiro plano já ordena dois passos que compartilham um elemento.

**O plano decide os alvos.** O método descreve os alvos da sua obrigação
que ainda são descritíveis e não estão descritos, sejam quais forem os
candidatos quando ele roda (um visual substituto continua alvo depois que
aparece uma imagem), então ele nunca tem sucesso sem tentar o trabalho para
o qual foi planejado. Um alvo que agora é lido por outro passo é informado
como `not_describable`.

**Retomar um checkpoint antigo.** Um checkpoint de enriquecimento da 0.3.13
é retomado como está: suas imagens foram descritas, ou ficaram com um motivo
de falha, antes do planejamento, então ele não ganha `describe-images`. A
reconciliação de um replanejamento dá uma obrigação às que ficaram sem
descrição, então o replanejamento que a execução já faria as tenta mais uma
vez.

**O que o resultado significa.** O método tem sucesso quando a tentativa
coletiva rodou: o passo terminou para todos os alvos. Isso não afirma que todo
elemento está enriquecido. Cada elemento mantém seu próprio desfecho (para uma
tabela, `table_read_failure` com o motivo, inclusive o `admission_rejected` de
um executor de chamadas de modelo cheio, #590), e as obrigações por elemento
que dependem dela validam o seu elemento. Reprovar a obrigação inteira por um
elemento bloquearia os elementos utilizáveis. Por isso a mensagem do método
informa o que aconteceu com cada elemento, e ele só falha quando o passo lança
uma exceção.

**Reconciliada antes de cada plano (M0, #832).**
`reconcile_document_steps` roda quando o manifesto é enriquecido e de novo
antes de cada replanejamento, para cada passo. As regras estão escritas aqui
para as tabelas; são as mesmas para as imagens:
- uma tabela que nenhum enriquecimento cobre entra no aberto; quando os
  existentes estão fechados, as tabelas novas ganham um novo
  (`obligation-enrich-tables-2`, …). Reabrir um satisfeito deixaria
  obrigações satisfeitas esperando por uma aberta, e um esgotado (`failed`)
  não é planejado de novo, então uma tabela que entrasse nele nunca seria
  lida;
- um enriquecimento deixa de lado as tabelas que o documento perdeu, e um que
  fica sem tabelas é removido junto com as dependências dele (um
  `target_ids` vazio é inválido). O passo que removeu um elemento remove ou
  redireciona as obrigações do próprio elemento e os `element_ids` da página;
- toda obrigação aberta cujos alvos incluem uma tabela depende do
  enriquecimento aberto daquela tabela, e só desses: uma aresta para um
  enriquecimento, aberto ou fechado, que não compartilha mais tabela com ela
  (o enriquecimento perdeu a tabela, ou a obrigação foi redirecionada) é
  removida. Só esta regra cria arestas para uma obrigação `enrich-tables`,
  então as arestas que ela remove são dela; uma aresta para um fechado fica
  enquanto o alvo que a justificou ficar. De outro modo, uma aresta para um
  enriquecimento esgotado bloquearia as dependentes de serem replanejadas;
- a regra é sobre alvos, não uma lista de kinds: além de `linearize-table` e
  `select-table-source`, ordena as obrigações de página
  (`refine-reading-order`, `fuse-providers`, `adjudicate-page`) de uma página
  com tabela, cujos alvos são os elementos da página. É a ordem do 0.3.11, em
  que as tabelas eram lidas antes do planejamento, ao custo de serializar
  essas obrigações de página atrás da leitura. Um passo futuro que precise
  rodar antes da leitura não é um que esta regra deva ordenar; ele precisa de
  uma exclusão na regra.

**Restrito aos seus alvos.** O método lê e marca só as tabelas da sua
obrigação (`targets` em `_tables_to_read`, `_enrich_table_structures` e
`_mark_table_inline_math`), então um segundo enriquecimento nunca relê nem
altera uma tabela de um anterior, mesmo uma ainda elegível para leitura, e a
mensagem dele conta só as próprias tabelas. O breaker, o leitor de spans e o
progresso continuam sendo os da execução. O método de imagens se restringe às
suas imagens do mesmo jeito (`targets` em `_enrich_picture_descriptions`).

**As descrições de imagens mudam obrigações (M1).** Uma imagem que o modelo
lê como fórmula vira fórmula: a reconciliação do elemento troca o seu
`describe-image` por `verbalize-formula`, e o visual substituto que o modelo
descreve vira uma imagem com `describe-image`. O executor pula o passo da
obrigação trocada e replaneja para as novas (M0). A mensagem do método conta
as imagens descritas, as lidas como fórmula, as já descritas e o motivo de
cada uma que ficou sem descrição.

## Ordem da migração

Cada passo é um pull request; o M4 são dois (M4a, M4b), porque seus dois
passos são independentes.

| PR | Passo | Obrigação e método | Papel | Requisitos de Toolbox | Muda obrigações enquanto o plano roda |
|---|---|---|---|---|---|
| M2 (feito, core 0.3.12) | Estrutura das tabelas e matemática inline das tabelas | `enrich-tables`, uma por documento com tabelas, método `table-enrichment`; `linearize-table` e `select-table-source` dependem dela. Depois da #170, o método chama `table.recognize`, cujos providers competem (`docling-table`, `mineru-table`, o VLM) | `transitional` (`DataAgent`) | opcionais (#848): `pdf.render` para uma tabela lida de novo e `document.text.spans` para as marcas se degradam por tabela, então nunca o excluem | não |
| M0 (feito, core 0.3.13) | Preparação do executor | O executor pula, e registra como `skipped` com o motivo, o passo de uma obrigação que esta execução removeu ou substituiu, e o de uma que agora espera uma obrigação aberta que o plano não executa antes dele. O `complete-job` é pulado enquanto toda obrigação aberta foi encontrada ou adiada; uma que o plano executou e deixou aberta é falha. O orquestrador replaneja depois de uma execução assim com um limite próprio (`max_discovery_replans`), separado de `max_replans`, e para quando um replanejamento partiria do mesmo estado de planejamento. O passo de uma obrigação mudada sob o mesmo id também é pulado. As obrigações do documento são reconciliadas antes de cada replanejamento, e o enriquecimento de tabelas se restringe aos seus alvos | — | — | — |
| M1 (feito, core 0.3.14) | Descrições de imagens | `describe-images`, uma por documento com imagens a descrever (ou com os visuais substitutos de um documento majoritariamente visual), método `picture-description`, que roda o passo com seu paralelismo e sua passada de retry; `describe-image` mantém o `vision-description`, que confere o resultado, e depende dela. A imagem injetada e a primeira anotação de posse ficam antes do planejamento | `transitional` (`VisionAgent`) | opcional (#848): `pdf.render` para o recorte de uma imagem degrada para `crop_unavailable` | sim: uma descrição pode retipar uma imagem como fórmula, o que remove seu `describe-image` e acrescenta `verbalize-formula` |
| M3 (feito, core 0.3.15) | LaTeX das fórmulas | `recognize-formulas`, uma por documento com fórmulas a reconhecer ou rótulos de equação a separar, método `formula-recognizer`, que roda o passo com seu paralelismo; `verbalize-formula` e `normalize-formula` dependem dela. Uma obrigação do documento, como no M1 e no M2, não uma por fórmula como proposto antes: o passo compartilha um breaker, uma sondagem do `math.recognize` por obrigação e seu paralelismo no documento inteiro | `transitional` (`VisionAgent`, a alternativa) | opcionais (#848): o `math.recognize` degrada para a alternativa de visão e o `pdf.render` por fórmula, então nunca o excluem | sim: a alternativa pode ler uma fórmula como imagem, o que troca suas obrigações de fórmula por `describe-image`; e uma fórmula que as descrições encontram ganha o passo no replanejamento |
| M4a (feito, core 0.3.19) | Regiões de fórmula | `classify-formula-regions`, uma por documento com regiões de fórmula a conferir, método `formula-region-classifier`, que roda o passo com seu paralelismo; `recognize-formulas` depende dela nas fórmulas que compartilham. Do documento, como M1–M3, não uma por região como proposto antes (`classify-formula-region`) | `transitional` (`VisionAgent`) | opcional (#848): `pdf.render` para o recorte de uma região | sim: um desenho vira imagem descrita (as obrigações de fórmula trocadas por `describe-image`), e uma região incerta vai para revisão humana (`verbalize-formula` fica só com `human-review`, `normalize-formula` é retirada) |
| M4b (feito, core 0.3.20) | Matemática inline da prosa | `mark-inline-math`, uma por PDF com prosa a marcar, método `inline-math-marker`; `verbalize-formula` e `normalize-formula` esperam por ela (`waiting_kinds`). Substitui a passada pós-execução da #599: um bloco que o plano acrescenta a ganha num replanejamento, que uma execução concluída agora faz para esse trabalho | `transitional` (a detecção roda no core, `docstruct`) | opcional (#848): `document.text.spans` | sim: um bloco que o plano acrescenta, e uma tabela adotada do provedor secundário, ganham o passo no replanejamento |
| — | Bootstrap | Mantido e documentado como a baseline 0.3.0 | — | — | — |

O M2 veio primeiro porque não muda nenhuma obrigação enquanto o plano roda. O
M1 estava previsto primeiro, mas seu passo retipa elementos: uma imagem que o
modelo lê como fórmula vira fórmula, e a reconciliação remove o
`describe-image` da imagem e acrescenta `verbalize-formula`. O executor então
só tratava obrigações acrescentadas (`_select_discovered`), então o M1 esperou
o M0 e veio depois dele, no core 0.3.14. O M3 veio na 0.3.15 e fechou a
lacuna que o M1 deixou para uma fórmula encontrada durante o plano (#846). O
M4a veio na 0.3.19 e o M4b na 0.3.20: todo passo de enriquecimento, menos a
preparação das imagens, agora roda dentro do plano.

Cada PR:
- tira seu passo de `_enrich_before_planning`;
- atualiza `LOCAL_METHODS`, `METHOD_TOOLBOX_REQUIREMENTS` e
  `METHOD_OPTIONAL_CAPABILITIES`;
- acrescenta o teste diferencial e um caso de fixture do Fast Downward (o job
  de CI da #790);
- atualiza esta página.

## O bootstrap

O bootstrap continua uma fase fixa e auditável na 0.3.0:
- a inspeção de mídia;
- o limite de páginas antes e depois da extração;
- a extração inicial;
- a injeção de imagem e a anotação de posse que derivam da inspeção.

Encapsulá-lo numa capacidade composta da Toolbox (por exemplo
`document.bootstrap@1`, que devolveria os fatos de mídia, a contagem de
páginas e uma referência versionada à estrutura inicial) é uma opção, não uma
exigência. Só vale a pena se compor `media.inspect` e
`document.structure.extract` de fato simplificar o fluxo, e mesmo assim a
Toolbox não formularia obrigações nem o problema. Planejar o próprio
bootstrap é a #816 (0.4.0).

## Questões abertas

- **A configuração do bootstrap:** a ADR-0030 torna explícitas e
  registradas as opções das quais o core depende. Quando a Toolbox as
  informar (#169), o manifesto as guarda como proveniência.

- **O replanejamento de descoberta:** como o sinal existente de
  `_select_discovered` informa seu motivo e ganha um limite próprio, e se uma
  flag em `MethodResult` vale a mudança de contrato.
- **Custos** dos novos métodos, para que, quando nada falha, o planejador
  escolha os mesmos métodos que o enriquecimento roda hoje. A ordem em si vem
  de `depends-on`.
- **O serviço de enriquecimento:** sua forma no contexto da execução, e a
  confirmação de que o breaker mantém o escopo de documento inteiro.
- **Sobreposição entre M1 e M4:** a classificação de fórmulas já descreve um
  desenho que ela reclassifica. Quando os dois forem métodos, a descrição deve
  ser feita uma vez só, pelo `vision-description`.

## Fora do escopo

- Planejar o bootstrap: #816 (0.4.0).
- Compor o domínio a partir dos fragmentos da Toolbox. Isso espera a decisão
  aberta da ADR-0029, "Fragmentos por versão", que os donos da Toolbox
  precisam aceitar.
- Tirar o modo `observe` do gate (#809).
- Transformar os agentes de modelo em capacidades (#804, #640 PR 4).
