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
| Enriquecimento | Quatro passos antes do planejamento, numa ordem fixa (abaixo); desde a 0.3.12, os passos 5 e 6 rodam dentro do plano (M2) | | Toolbox e os agentes de modelo do Core | `enriched`, por objeto, nos passos 1–4; o checkpoint de execução, por passo do plano, nos 5–6 |
| Planejamento | | Compila o problema a partir do manifesto enriquecido e planeja | — | `plan` |

Os passos de enriquecimento (`_enrich_before_planning` até o core 0.3.11;
desde a 0.3.12, os passos 5 e 6 rodam dentro do plano, como o método
`table-enrichment`, M2):

| Passo | Função | Chama | Efeito no manifesto |
|---|---|---|---|
| 1. Regiões de fórmula | `_classify_formula_regions` | Toolbox `pdf.render` (o recorte da fórmula); `VisionAgent` | confere os rótulos de fórmula do extrator. Um desenho é descrito uma vez e vira imagem, o que reconcilia suas obrigações (`reconcile_reclassified_element`); um candidato incerto vai para revisão humana |
| 2. Descrições de imagens | `_enrich_picture_descriptions` | `VisionAgent` | primeiro injeta uma imagem de página inteira para uma imagem raster isolada e anota a posse do texto visual, ambas a partir da inspeção de mídia; depois uma descrição por imagem |
| 3. Matemática inline | `_mark_inline_math` | Toolbox `document.text.spans` | marca a matemática na prosa |
| 4. LaTeX das fórmulas | `_enrich_formula_latex` | Toolbox `math.recognize`, `pdf.render` | separa os números de equação, depois o LaTeX de cada fórmula |
| 5. Estrutura das tabelas | `_enrich_table_structures` | `DataAgent` | uma AST estruturada por tabela |
| 6. Matemática inline das tabelas | `_mark_table_inline_math` | Toolbox `document.text.spans` | marca a matemática nas células (depois do passo 5, que pode substituir células) |

O que os passos compartilham não é uniforme:

| Recurso | Passos | Onde vive (core 0.3.12) |
|---|---|---|
| Breaker de provider | 1, 2, 4, 5 | o da execução, `RunPorts.services` (`run_breaker`), compartilhado com o método `table-enrichment` |
| Progresso por objeto (`on_progress`) | 1, 2, 4 | uma variável local, de `checkpoints.enrichment_progress`; o passo 5, dentro do plano, tem o checkpoint de execução do seu passo do plano |
| Cache de regiões | 1, 2, 4 | de `RunPorts` (`region_cache_for`) |
| Leitor de spans de texto (`_TextSpanReader`) | 3, 6 | o da execução, `RunPorts.services` (`run_text_spans`); não guarda manifesto |
| Mensagens de progresso | 1, 2, 4, 5 | o callback de status antes do planejamento; `RunServices.progress` dentro do plano |
| Inspeção de mídia | 2 | uma saída do bootstrap |
| Arquivo de origem | todos | o contexto da execução; o manifesto registra seu digest |

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

1. **Um plano não cria objetos; o replanejamento de descoberta só existe para
   acréscimos.** A classificação de fórmulas pode reclassificar um elemento e
   reconciliar suas obrigações, então depois dela as próximas ações dependem
   de obrigações que o problema não tinha.

   O executor já trata um caso. Depois de um handler bem-sucedido e validado,
   `_run_obligation_handler` chama `_select_discovered` (#594), que seleciona
   as obrigações que o handler acrescentou. Quando alguma continua
   insatisfeita, ele liga `replan_required`. O resto do plano ainda roda, e o
   relatório leva a flag a `_replan_until_done`, que replaneja com essas
   obrigações como raízes.

   O que falta:
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

   Não se encontrou dependência de dados entre a matemática inline da prosa e
   os passos de fórmula (eles leem elementos diferentes), entre imagens e
   tabelas, nem entre o LaTeX das fórmulas e as tabelas. Cada migração
   confirma isso para o seu passo.
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
   objetos, então **ficam no bootstrap**. O método de imagens migrado então
   não precisa da inspeção como entrada.
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
   `METHOD_TOOLBOX_REQUIREMENTS`.
7. **A retomada continua idempotente.** Hoje um passo pula os objetos que já
   terminou. Como método, o mesmo registro torna barato um passo do plano
   executado de novo, e o checkpoint de execução registra quais passos
   rodaram.
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

**O que o resultado significa.** O método tem sucesso quando a tentativa
coletiva rodou: o passo terminou para todos os alvos. Isso não afirma que todo
elemento está enriquecido. Cada elemento mantém seu próprio desfecho (para uma
tabela, `table_read_failure` com o motivo, inclusive o `admission_rejected` de
um executor de chamadas de modelo cheio, #590), e as obrigações por elemento
que dependem dela validam o seu elemento. Reprovar a obrigação inteira por um
elemento bloquearia os elementos utilizáveis. Por isso a mensagem do método
informa o que aconteceu com cada elemento, e ele só falha quando o passo lança
uma exceção.

**Limites, para o M0.** A obrigação é criada uma vez, antes do primeiro plano,
com os elementos conhecidos naquele momento, e os kinds por elemento que
dependem dela são uma lista fixa (`_AFTER_TABLE_ENRICHMENT`). Um elemento
acrescentado, removido ou retipado enquanto o plano roda não é reconciliado
com ela. Nenhum handler acrescenta ou retipa uma tabela hoje, mas o M0 (#832)
precisa reconciliar os alvos e as dependências de uma obrigação do documento,
e as próximas migrações precisam acrescentar seus kinds a essa lista.

## Ordem da migração

Cada passo é um pull request. Os nomes de métodos e kinds do M3 e do M4 são
propostas, decididas nos seus pull requests.

| PR | Passo | Obrigação e método | Papel | Requisitos de Toolbox | Muda obrigações enquanto o plano roda |
|---|---|---|---|---|---|
| M2 (feito, core 0.3.12) | Estrutura das tabelas e matemática inline das tabelas | `enrich-tables`, uma por documento com tabelas, método `table-enrichment`; `linearize-table` e `select-table-source` dependem dela. Depois da #170, o método chama `table.recognize`, cujos providers competem (`docling-table`, `mineru-table`, o VLM) | `transitional` (`DataAgent`) | nenhum declarado: suas chamadas à Toolbox (`pdf.render` para uma tabela lida de novo, `document.text.spans` para as marcas) são condicionais e se degradam por tabela, então não podem descartá-lo | não |
| M0 | Preparação do executor | Tratar obrigações removidas ou substituídas enquanto o plano roda: pular os passos de obrigações removidas, revalidar o plano remanescente e replanejar para as substitutas (critérios 4 e 5 da restrição 1) | — | — | — |
| M1 | Descrições de imagens | `describe-images`, uma por documento com imagens (ou com os visuais substitutos de um documento majoritariamente visual), método `picture-description`, que roda o passo com seu paralelismo e sua passada de retry; `describe-image` mantém o `vision-description`, que confere o resultado, e depende dela | `transitional` (`VisionAgent`) | os que o `VisionAgent` fizer, se houver | sim: uma descrição pode retipar uma imagem como fórmula, o que remove seu `describe-image` e acrescenta `verbalize-formula` |
| M3 | LaTeX das fórmulas | kind novo `recognize-formula`, método `formula-recognizer`, uma dependência de `verbalize-formula` e `normalize-formula` | novo, declarado | `math.recognize`, `pdf.render` | sim: o kind novo, por fórmula |
| M4 | Regiões de fórmula e matemática inline da prosa | kinds novos `classify-formula-region` (método `formula-region-classifier`) e `mark-inline-math` (método `inline-math-marker`) | novos: `transitional` (`VisionAgent`) e declarado | `pdf.render`; `document.text.spans` | sim: a reclassificação reconcilia obrigações |
| — | Bootstrap | Mantido e documentado como a baseline 0.3.0 | — | — | — |

O M2 veio primeiro porque não muda nenhuma obrigação enquanto o plano roda. O
M1 estava previsto primeiro, mas seu passo retipa elementos: uma imagem que o
modelo lê como fórmula vira fórmula, e a reconciliação remove o
`describe-image` da imagem e acrescenta `verbalize-formula`. Hoje o executor
só trata obrigações acrescentadas (`_select_discovered`), então o M1 espera o
M0. O M3 e o M4 também mudam obrigações e se apoiam no M0.

Cada PR:
- tira seu passo de `_enrich_before_planning`;
- atualiza `LOCAL_METHODS` e `METHOD_TOOLBOX_REQUIREMENTS`;
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
