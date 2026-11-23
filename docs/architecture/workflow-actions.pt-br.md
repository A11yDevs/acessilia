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
| Enriquecimento | Seis passos, numa ordem fixa (abaixo) | | Toolbox e os agentes de modelo do Core | `enriched`, por objeto |
| Planejamento | | Compila o problema a partir do manifesto enriquecido e planeja | — | `plan` |

Os passos de enriquecimento (`_enrich_before_planning`):

| Passo | Função | Chama | Efeito no manifesto |
|---|---|---|---|
| 1. Regiões de fórmula | `_classify_formula_regions` | Toolbox `pdf.render` (o recorte da fórmula); `VisionAgent` | confere os rótulos de fórmula do extrator. Um desenho é descrito uma vez e vira imagem, o que reconcilia suas obrigações (`reconcile_reclassified_element`); um candidato incerto vai para revisão humana |
| 2. Descrições de imagens | `_enrich_picture_descriptions` | `VisionAgent` | primeiro injeta uma imagem de página inteira para uma imagem raster isolada e anota a posse do texto visual, ambas a partir da inspeção de mídia; depois uma descrição por imagem |
| 3. Matemática inline | `_mark_inline_math` | Toolbox `document.text.spans` | marca a matemática na prosa |
| 4. LaTeX das fórmulas | `_enrich_formula_latex` | Toolbox `math.recognize`, `pdf.render` | separa os números de equação, depois o LaTeX de cada fórmula |
| 5. Estrutura das tabelas | `_enrich_table_structures` | `DataAgent` | uma AST estruturada por tabela |
| 6. Matemática inline das tabelas | `_mark_table_inline_math` | Toolbox `document.text.spans` | marca a matemática nas células (depois do passo 5, que pode substituir células) |

O que os passos compartilham não é uniforme:

| Recurso | Passos | Onde vive hoje |
|---|---|---|
| Breaker de provider | 1, 2, 4, 5 | uma variável local de `_enrich_before_planning` |
| Progresso por objeto (`on_progress`) | 1, 2, 4, 5 | uma variável local, de `checkpoints.enrichment_progress` |
| Cache de regiões | 1, 2, 4 | de `RunPorts` (`region_cache_for`) |
| Leitor de spans de texto (`_TextSpanReader`) | 3, 6 | uma variável local |
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
    pipeline que a Toolbox configura, `table_mode`).
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
| 5. Estrutura das tabelas | tabelas sem estrutura utilizável, ou embaralhadas (`TABLE_VISUAL_REVIEW`) | a estrutura do TableFormer é mantida quando é utilizável |

A migração precisa manter essas condições: **uma obrigação só existe onde sua
condição vale**. Do contrário, o plano mandaria para um provider
especializado um objeto que o bootstrap já tratou bem. As condições também
são onde as detecções do bootstrap são conferidas. Conferir um rótulo, a forma
de uma tabela ou um reconhecimento contra a camada de texto decide o
workflow, então pertence ao plano.

Dois pontos sobre a configuração do bootstrap, a confirmar com a Toolbox:
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
  leitor de tabelas. Se isso corresponde à intenção do desenho é decisão da
  Toolbox.

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

1. **Um plano não cria objetos, e hoje nada replaneja depois de um sucesso.**
   A classificação de fórmulas pode reclassificar um elemento e reconciliar
   suas obrigações, então depois dela as próximas ações dependem de obrigações
   que o problema não tinha. O ciclo atual não trata isso:
   `_replan_until_done` só itera enquanto `execution_report.replan_required`, e
   o executor liga essa flag depois de uma falha com alternativas, nunca
   depois de um passo bem-sucedido. Uma migração que cria obrigações (M3, M4)
   precisa de um gatilho novo. A proposta é um **replanejamento de
   descoberta**. Depois que um plano roda, o coordenador compara as obrigações
   de antes e de depois. As obrigações novas e insatisfeitas viram as raízes de
   um replanejamento, que:
   - é contado por um limite próprio, não por `max_replans`, que continua
     contando falhas;
   - é salvo com `save_plan`, como qualquer replanejamento;
   - descarta o checkpoint de execução, como hoje.

   A alternativa é uma flag em `MethodResult` ("o estado mudou, replaneje").
   Ela é mais explícita, mas muda o contrato do resultado.
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

## Ordem da migração

Cada passo é um pull request, do menos ao mais estrutural. Os nomes de
métodos e kinds do M3 e do M4 são propostas, decididas nos seus pull
requests.

| PR | Passo | Obrigação e método | Mudança de papel | Requisitos de Toolbox | Cria obrigações |
|---|---|---|---|---|---|
| M1 | Descrições de imagens | `describe-image`: `vision-description` produz a descrição em vez de conferi-la | `validation` → `transitional` (`VisionAgent`) | os que o `VisionAgent` fizer, se houver | não |
| M2 | Estrutura das tabelas e matemática inline das tabelas | `linearize-table`: `pandoc-table` lê a estrutura (`DataAgent`) e marca a matemática das células | `validation` → `transitional` (`DataAgent`) | `document.text.spans` | não |
| M3 | LaTeX das fórmulas | kind novo `recognize-formula`, método `formula-recognizer`, uma dependência de `verbalize-formula` e `normalize-formula` | novo, declarado | `math.recognize`, `pdf.render` | sim: o kind novo, por fórmula |
| M4 | Regiões de fórmula e matemática inline da prosa | kinds novos `classify-formula-region` (método `formula-region-classifier`) e `mark-inline-math` (método `inline-math-marker`) | novos: `transitional` (`VisionAgent`) e declarado | `pdf.render`; `document.text.spans` | sim: a reclassificação reconcilia obrigações |
| — | Bootstrap | Mantido e documentado como a baseline 0.3.0 | — | — | — |

O M1 e o M2 não criam obrigações e não precisam nem do replanejamento de
descoberta nem de mudança no manifesto, então vêm primeiro. O M3 e o M4
acrescentam kinds e dependem do replanejamento de descoberta (restrição 1),
então o gatilho chega com o M3.

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

- **A configuração do bootstrap:** se o core deve declarar as opções de
  pipeline das quais depende (os enriquecimentos do Docling desligados, o
  reconhecimento de fórmulas e tabelas do MinerU) e registrar as efetivas no
  manifesto, em vez de depender dos padrões da Toolbox.

- **O replanejamento de descoberta:** a comparação no coordenador ou uma flag
  em `MethodResult`, e o seu limite.
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
