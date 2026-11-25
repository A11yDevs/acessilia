# Changelog do Core

Inglês, versão normativa: [English version](CHANGELOG.md).

## 0.3.22 — uma descoberta é atendida depois de esgotado o orçamento de falhas (#842)

Uma execução com um passo falho e uma descoberta era um replanejamento de
falha; com `max_replans` esgotado o laço parava, e uma obrigação crítica que
a execução encontrou fazia o job falhar por causa de uma falha independente e
não crítica.
- Com `max_replans` esgotado, essa execução agora é um replanejamento de
  descoberta, dentro de `max_discovery_replans` e da guarda de assinatura,
  só para o trabalho que nenhuma falha toca (`_discovered_roots`: nunca
  tentado e sem obrigação aberta e já tentada entre as suas dependências). As
  obrigações que falharam e as suas dependentes ficam fora dessa rodada e de
  todas as seguintes, então as suas alternativas nunca rodam; o orçamento de
  descobertas não é um caminho em volta do de falhas. `_replan_allowed`
  virou `_replan_kind` (`failure`, `discovery` ou parar); os contadores e a
  assinatura são salvos com o plano como antes.
- Testes: uma descoberta crítica ao lado de uma falha independente é atendida
  e o trabalho que falhou não é tentado de novo, nessa rodada nem numa
  seguinte; uma descoberta que depende do trabalho que falhou ainda faz o job
  falhar; as raízes e os tipos isoladamente.

## 0.3.21 — o manifesto entregue é validado (#844)

O laço de replanejamento revalidava o grafo de obrigações (referências e DAG)
só antes de um replanejamento (#832, M0). Uma execução que concluía sem ele
entregava o que um handler deixou: uma obrigação satisfeita apontando para
uma obrigação que ele removeu chegava ao payload, e uma dependente esgotada
(sem método restante, então sem replanejamento) falhava com o resumo das
não satisfeitas em vez da causa.
- `_check_unsatisfied` roda primeiro `validate_delivered_manifest`, qualquer
  que seja o status da execução, dry runs incluídos: o round trip que uma
  retomada faz (`ProcessingManifest.model_validate`), então uma execução
  nunca entrega o que a sua própria retomada rejeitaria. Além das
  referências e do DAG, ele checa as predecessoras das obrigações satisfeitas
  e as contagens do resumo. Falha com a mensagem do manifesto; um manifesto
  válido é entregue como antes.
- Uma fixture de teste que acrescentava uma página sem a sua contagem
  (`test_unstructured_pages.py`) foi corrigida.
- Testes: uma dependente satisfeita e uma esgotada de uma obrigação removida,
  um ciclo, uma obrigação satisfeita esperando por uma esgotada, uma remoção
  que religa a sua dependente (com o que é entregue) e um dry run.

## 0.3.20 — a matemática inline da prosa é uma ação planejada (#640, M4b)

Até a 0.3.19 o orquestrador marcava a matemática inline da prosa antes do
planejamento, e de novo numa passada depois da execução sobre os blocos que
o plano acrescentou (#599). Agora um PDF com prosa a marcar ganha uma
obrigação `mark-inline-math`, satisfeita pelo método `inline-math-marker`,
que acha cada trecho de matemática pelas fontes da camada de texto e o
escreve como `$…$`, com o leitor de spans da execução. Todo passo de
enriquecimento, menos a preparação das imagens, agora roda dentro do plano.
- **A passada depois da execução acabou.** Um bloco que o plano acrescenta
  (um parágrafo do `rescue-omitted`) ganha o passo pela reconciliação. Uma
  execução que terminou e deixou trabalho para os passos do documento
  replaneja para ele, como uma descoberta, com o job concluído reaberto para
  esse replanejamento. Esse gatilho serve a todo passo do documento, não só
  à matemática inline. Uma tabela adotada do provedor secundário é marcada
  como `inline_math_stale` onde suas células mudam, e o passo a marca de
  novo.
- **As conversões de fórmula esperam por ela.** `verbalize-formula` e
  `normalize-formula` leem as variáveis que as marcas da prosa dão, então
  dependem de `mark-inline-math` embora não compartilhem elemento: um
  `DocumentStep` pode declarar `waiting_kinds`, uma dependência declarada
  mínima (declarar predecessores em geral é a #865). Quando o passo marca um
  bloco depois que uma conversão já rodou (um replanejamento), ele descarta
  essa conversão, para que o build canônico a refaça com as variáveis
  finais. Antes de qualquer conversão rodar, nada é descartado, então uma
  conversão que o extrator deu fica.
- Ela vem por último em `DOCUMENT_STEPS`: compartilha um parágrafo com as
  descrições (um documento majoritariamente visual) e uma tabela obsoleta
  com o enriquecimento de tabelas, e roda depois dos dois.
- O passo não é crítico: um bloco que ficou sem marcas mantém o texto do
  extrator, como com a detecção desligada. Ele é `transitional` (a detecção
  roda no core, `docstruct`), com `document.text.spans` como chamada
  opcional (#848). Com a detecção desligada, ou outro formato, ele não muda
  nada; sua mensagem nomeia a detecção (`fonts`, `off`, `unavailable`).
- Antes do planejamento a execução só prepara as imagens, sem mensagem de
  progresso própria; cada método anuncia seu passo dentro do plano.
- Testes: a obrigação e seus alvos, as conversões esperando por ela (também
  no Fast Downward), o método e sua mensagem, a invalidação só depois de uma
  conversão, uma tabela obsoleta, uma execução concluída com um bloco
  acrescentado (replanejada) ou sem nada novo, o bloco
  restaurado pelo `execute` e o `document.text.spans` opcional.
- **Da revisão do #867:**
  - Um job só é reaberto quando o seu replanejamento é permitido. Com o
    orçamento de descobertas gasto, o trabalho que uma execução concluída
    deixou é julgado como em qualquer execução: uma obrigação crítica falha
    o job em vez de sair em silêncio, e um refinamento deixa um aviso,
    mantendo o job concluído.
  - Uma tabela marcada obsoleta de novo depois de o passo marcá-la entra
    numa obrigação nova (`DocumentStep.renewed`); uma esgotada ainda a
    cobre.
  - Um bloco de prosa sem caixas que já traz `$…$` (um parágrafo resgatado)
    entra no passo, que o pesa para a invalidação, como fazia a passada da
    #599; com a detecção desligada, o passo é planejado também para isso.
  - Uma `mark-inline-math` esgotada não segura mais as conversões que
    esperavam por ela (`DocumentStep.critical=False`).
  - O status da detecção dos dois passos vem de um helper só
    (`inline_math_detection_status`), e a documentação (ADR-0011,
    `workflow-actions`, o inventário) descreve o passo planejado.

## 0.3.19 — a classificação de regiões de fórmula é uma ação planejada (#640, M4a)

Até a 0.3.18 o orquestrador conferia os rótulos de fórmula do extrator antes
do planejamento. Agora um documento com regiões de fórmula a conferir ganha
uma obrigação `classify-formula-regions`, satisfeita pelo método
`formula-region-classifier`, que roda o mesmo passo dentro do plano: o
modelo de visão pergunta se cada recorte de fórmula sem LaTeX contém
matemática, um desenho ou algo que ele não consegue dizer, com seu
paralelismo, o breaker e o cache de regiões da execução.
- **Do documento,** como M1–M3, não uma por região como proposto antes.
  Ela tem como alvo, numa fonte que pode ser renderizada, as fórmulas sem
  marcação LaTeX que nenhuma classificação decidiu. A seleção e a execução
  compartilham `formulas_needing_classification`. Um elemento que as
  descrições transformaram em fórmula (uma imagem, ou um visual substituto
  de um documento majoritariamente visual) não é classificado: as
  descrições rodavam depois dela antes do planejamento, então ele nunca
  era, e uma segunda resposta poderia lê-lo como desenho e descartar a
  fórmula que elas deram. Uma classificação que não teve resposta
  (`unclassified`) é tentada de novo quando o passo roda de novo, como nos
  outros passos compostos; `math` e `unresolved` são decisões.
- **Ela compartilha as fórmulas com o LaTeX das fórmulas (M3),** que deve
  vir depois dela. `DOCUMENT_STEPS` lista a classificação primeiro, então
  `recognize-formulas` depende de `classify-formula-regions` nas fórmulas
  que compartilham, assim como as obrigações das próprias fórmulas. A
  política entre os passos do documento agora é: dois passos só
  compartilham elementos quando o primeiro precisa rodar antes do segundo,
  na ordem de `DOCUMENT_STEPS`.
- **Correção:** `reconcile_document_steps` reconcilia as arestas mais uma
  vez depois que as obrigações de todos os passos existem. A passada de um
  passo só liga as obrigações que existem então, então a aresta do
  reconhecimento para a classificação, criada numa passada posterior,
  esperava a próxima reconciliação, e o primeiro plano podia rodá-los em
  qualquer ordem.
- **Ela muda obrigações.** Um desenho vira imagem descrita (as obrigações de
  fórmula trocadas por `describe-image`); uma região incerta vai para
  revisão humana (`verbalize-formula` fica só com `human-review`,
  `normalize-formula` é retirada). O executor pula os passos que mudaram e
  replaneja (M0).
- A mensagem do método conta as regiões achadas como matemática, os
  desenhos, as enviadas para revisão humana, as decididas antes desta
  tentativa (um passo retomado) e o motivo de cada uma que ficou sem
  classificação. O passo se anuncia com uma mensagem própria,
  `STAGE_CLASSIFYING_FORMULA_REGIONS`. Cada região classificada é gravada no checkpoint
  de execução (#836). Ele é `transitional` (sua chamada de modelo é o
  `VisionAgent` do core), com `pdf.render` como chamada opcional (#848).
- Antes do planejamento a execução agora só prepara as imagens e marca a
  matemática inline da prosa, anunciada como `STAGE_MARKING_INLINE_MATH`
  (nova).
- O M4 foi dividido em dois pull requests: a matemática inline da prosa
  (M4b) vem em seguida.
- Testes: a obrigação e seus alvos, a ordem com o reconhecimento (também no
  Fast Downward), a mensagem do método, um desenho e uma região incerta no
  executor e de ponta a ponta, um visual substituto lido como fórmula de
  ponta a ponta (não classificado de novo), uma queda no meio do passo e
  uma queda depois que a classificação mudou obrigações, o `pdf.render`
  opcional e um teste diferencial dos elementos antes e depois.

## 0.3.18 — o plano de redução vem do SDK (#636)

A recuperação de contexto do payload de visão não repete mais a regra do SDK
sobre quando vale a pena reduzir uma imagem. O `toolbox/vision_payload` agora
consulta `acessilia_sdk.toolbox.clients.pdf.plan_downscale` — a mesma decisão
pura que o `downscale_image` do SDK executa —, então o core pula exatamente as
imagens que o render não reduziria, antes de criar um cliente. O comportamento
não muda: um `scale` inválido, bytes desconhecidos e uma imagem não reduzível
continuam devolvendo `None` sem tocar a Toolbox, e uma falha da Toolbox
continua devolvendo `None` depois de fechar o cliente. O core deixa de
importar `docstruct.imaging` e passa a exigir o SDK 0.7.

## 0.3.17 — checkpoints dentro de uma ação composta (#836)

As descrições de imagens (M1), o LaTeX das fórmulas (M3) e o enriquecimento
de tabelas (M2) são cada um uma ação planejada sobre muitos elementos. Para
o planejador cada uma é atômica; a persistência dela não é mais. Até agora
uma queda no meio de uma delas retomava o passo inteiro, pagando de novo as
chamadas de modelo dos objetos já terminados. Agora:
- **Depois de cada objeto terminado** o método grava o manifesto que está
  enriquecendo no checkpoint de execução da execução, como `step_progress`
  ao lado do último passo terminado: o `on_progress` da etapa, agrupado como
  antes do planejamento (uma escrita por vez, o manifesto mais recente),
  serializado no laço de eventos da etapa. Ele passa pelo
  `RunServices.step_checkpoint`, que o orquestrador liga ao seu checkpoint
  de execução; sem fase de checkpoint nova.
- **Uma execução retomada do mesmo plano** recomeça esse passo dele
  (`resumed_manifest`), e os filtros por objeto do passo pulam o que foi
  feito: uma imagem descrita, uma tabela lida, uma fórmula reconhecida. O
  progresso de um passo que o plano não roda em seguida nunca é usado, e o
  próximo passo terminado o descarta.
- **O que o passo interrompido encontrou é mantido.** As obrigações que os
  objetos terminados dele acrescentaram (uma imagem lida como fórmula ganha
  `verbalize-formula`) são selecionadas na restauração, como o executor faz
  quando um handler retorna, então o replanejamento as planeja; do contrário
  um job retomado poderia terminar sem elas. Isso também cobre uma queda
  depois que o handler retornou, antes de o checkpoint do passo ser gravado.
- **Uma segunda queda mantém o progresso da retomada.** O checkpoint de
  execução de uma execução retomada parte do snapshot que ela retomou, então
  o progresso do primeiro passo dela também é gravado.
- A recuperação coletiva (um breaker, uma passada de retry) e as mensagens
  de progresso (`RunServices.progress`) não mudam.
- Testes: quedas no meio do passo com imagens, muitas tabelas e fórmulas
  retomam só com o que o progresso salvo deixou (em que objeto a queda cai
  depende do timing, então os testes conferem esse contrato, não uma lista
  fixa); uma segunda queda no mesmo passo; uma queda depois de uma imagem
  lida como fórmula, no meio do passo e entre o handler e o checkpoint do
  passo.

## 0.3.16 — capacidades opcionais do Toolbox (#848)

As chamadas de um método ao Toolbox agora são de três tipos:
- **obrigatórias** (`METHOD_TOOLBOX_REQUIREMENTS`): a falta de uma exclui o
  método, como antes;
- **opcionais** (`METHOD_OPTIONAL_CAPABILITIES`, novo): a falta de uma
  degrada o método por elemento, então nunca o exclui;
- nenhuma: o método roda só no core.

`picture-description` (`pdf.render`), `formula-recognizer`
(`math.recognize`, `pdf.render`) e `table-enrichment` (`pdf.render`,
`document.text.spans`) declaram suas chamadas opcionais; até agora o gate não
as registrava. Um snapshot que não tem uma delas informa o método em
`degraded_methods`, ao lado de `optional`, nos metadados de disponibilidade
que a saída leva e num aviso de log, tanto em `observe` quanto em
`enforce`. Os fatos do catálogo e o plano não mudam, e os métodos degradam
como antes. Sem snapshot nada é informado como degradado (o `catalog_error`
diz por quê). Um documento cujas únicas chamadas ao Toolbox são opcionais
agora tem o catálogo lido. Um checkpoint de plano de antes não restaura
chamadas opcionais. Onde um método vive (o papel em `LOCAL_METHODS`)
continua uma dimensão separada.
- O relatório é por método, não por documento: um método é listado quando o
  catálogo não tem uma chamada opcional que ele *pode* fazer, mesmo que este
  documento nunca a faça (uma imagem de DOCX traz os próprios bytes). O log
  diz "may run degraded"; informar só as degradações reais é a #859.
- **Correção:** chamadas obrigatórias e opcionais resolvem um provider
  configurado vazio para o padrão do registro, como o cliente faz. No
  `enforce`, um `TOOLBOX_PDF_PROVIDER` vazio excluía um método que o cliente
  roda.
- `evaluate` lê `methods` uma só vez, então um gerador não perde mais as
  checagens obrigatórias.
- `docs/toolbox_integration.md` (EN/PT) explica onde declarar uma chamada.

## 0.3.15 — o LaTeX das fórmulas é uma ação planejada (#640, M3, #846)

Até a 0.3.14 o orquestrador lia o LaTeX das fórmulas antes do planejamento.
Agora um documento com fórmulas a reconhecer, ou rótulos de equação a
separar, ganha uma obrigação `recognize-formulas`, satisfeita pelo método
`formula-recognizer`, que roda o mesmo passo dentro do plano: separa os
rótulos de equação e depois lê o LaTeX das fórmulas sem ele, primeiro o
`math.recognize` e o modelo de visão como alternativa, com seu paralelismo,
o breaker e o cache de regiões da execução.
- **Uma obrigação para o documento,** como as imagens (M1) e as tabelas
  (M2), e não uma por fórmula como proposto antes: o passo compartilha um
  breaker, uma sondagem do `math.recognize` por obrigação (uma segunda, para
  fórmulas encontradas durante o plano, sonda de novo) e seu paralelismo no
  documento inteiro. Ela tem como alvo as fórmulas com um rótulo a separar e, numa
  fonte que pode ser renderizada, as sem LaTeX que nenhum reconhecimento
  registrou. `verbalize-formula` e `normalize-formula` dependem dela, assim
  como as obrigações de página de uma página com fórmula. É o terceiro
  `DocumentStep`, e não compartilha elemento com os outros dois.
- **A lacuna do M1 está fechada (#846).** Uma imagem que as descrições leem
  como fórmula ganha o passo no replanejamento, pela reconciliação, então o
  seu `verbalize-formula` vê o rótulo da equação separado, como antes do
  planejamento até a 0.3.13. O teste que fixava a lacuna foi invertido:
  `test_a_picture_read_as_a_formula_gets_the_formula_steps`. O alcance é o
  que o passo fazia: uma fórmula cujo texto do modelo não tem marcação
  LaTeX é lida pelo `math.recognize` antes da verbalização; o LaTeX que o
  modelo já deu não é lido de novo (uma segunda leitura independente é a
  #852).
- **Uma política para seleção e execução.** Os alvos da obrigação e o
  trabalho do passo compartilham `formulas_needing_number_separation` e
  `formulas_needing_recognition`, então uma fórmula selecionada só para
  separar o rótulo não é lida de novo, nem tem o registro de reconhecimento
  sobrescrito.
- **Ele pode mudar obrigações.** Uma fórmula que a alternativa de visão lê
  como imagem vira imagem, então as suas obrigações de fórmula são trocadas
  por um `describe-image`; o executor as pula e replaneja (M0).
- O método tem sucesso quando o passo rodou para todas as fórmulas da
  obrigação; uma que ficou sem LaTeX mantém o texto e o motivo
  (`formula_recognition_failure`). A mensagem conta as fórmulas reconhecidas
  por método, os rótulos separados, as lidas como imagem e o motivo de cada
  uma que ficou como estava. O passo se anuncia uma vez (o método; a etapa
  não repete mais `STAGE_ENRICHING_FORMULAS`). Uma fórmula cujo recorte não
  pôde ser feito agora registra o motivo (`crop_unavailable`, que os avisos
  entregues contam como o de uma imagem e que tira a execução do cache, ou
  `no_page`), em vez de ficar sem mudança em silêncio.
- Os três passos do documento não compartilham elemento, então a ordem
  deles é o desempate do planejador; numa indisponibilidade parcial do
  provider, o que roda primeiro gasta primeiro o orçamento do breaker
  compartilhado (#853).
- `formula-recognizer` é `transitional` em `LOCAL_METHODS` (sua alternativa
  é o `VisionAgent` do core) e não declara requisito do Toolbox: o
  `math.recognize` degrada para a alternativa e o `pdf.render` por fórmula
  (#848).
- Antes do planejamento a execução agora classifica regiões de fórmula,
  prepara as imagens e marca a matemática inline da prosa. Um checkpoint de
  enriquecimento da 0.3.14 já leu suas fórmulas e não ganha obrigação.
- Testes: a obrigação e seus alvos, a ordem no plano (também no Fast
  Downward), a mensagem e o escopo do método, uma fórmula lida como imagem,
  o fluxo de ponta a ponta imagem → fórmula → rótulo → verbalização e um
  teste diferencial dos elementos antes e depois da migração.

## 0.3.14 — as descrições de imagens são uma ação planejada (#640, M1)

Até a 0.3.13 o orquestrador descrevia as imagens antes do planejamento.
Agora um documento com imagens a descrever ganha uma obrigação
`describe-images`, satisfeita pelo método `picture-description`, que roda o
mesmo passo dentro do plano: o modelo de visão, com seu paralelismo, o
breaker e o cache de regiões da execução, uma passada de retry e a anotação
de posse de novo depois das descrições.
- **Uma obrigação para o documento.** Ela tem como alvo as imagens ainda não
  descritas; sem imagens, num documento majoritariamente visual, seus
  visuais substitutos, ou o primeiro elemento de um documento de uma
  página, como o passo os escolhia, mas nunca uma fórmula nem uma tabela:
  os candidatos e os elementos que o passo mantém compartilham um só teste
  (`is_describable`), então ele nunca pega um que depois deixaria de lado,
  nem retipa uma fórmula ou uma tabela como imagem. Os dois passos do
  documento não compartilham elemento, então nenhum depende do outro; como
  proteção, as arestas entre eles seguem `DOCUMENT_STEPS` (a de um passo
  pode depender da de um anterior, nunca da de um posterior), então não
  fazem ciclo. O método descreve os alvos da sua obrigação ainda
  descritíveis e não descritos, sejam quais forem os candidatos quando ele
  roda, então nunca tem sucesso sem tentá-los; um alvo que agora é lido por
  outro passo é informado como `not_describable`. O `describe-image` de
  cada imagem mantém o `vision-description`, que confere o resultado, e depende dela, assim como
  as obrigações de página de uma página com imagem. A única alternativa é
  `human-review`. O método tem sucesso quando o passo rodou para todas as
  imagens; uma imagem que ficou sem descrição mantém o motivo
  (`vision_failure_reason`), e o seu `describe-image` a valida. A mensagem
  conta as imagens descritas, lidas como fórmula, já descritas e o motivo de
  cada uma que ficou sem descrição.
- **Ela muda obrigações enquanto o plano roda.** Uma imagem que o modelo lê
  como fórmula vira fórmula, então o seu `describe-image` é trocado por
  `verbalize-formula`; um visual substituto que ele descreve vira imagem com
  `describe-image`. O executor pula o passo trocado e replaneja para as
  novas, dentro de `max_discovery_replans` (M0).
- **O que fica antes do planejamento.** O que deriva da inspeção de mídia: a
  imagem de página inteira injetada e a primeira anotação de posse
  (`_prepare_pictures`), para que as obrigações do plano incluam as da
  imagem injetada. O método anota de novo com a inspeção que o orquestrador
  entrega aos serviços da execução (`RunServices.media_inspection`; gravar
  no manifesto os fatos de que ele precisa é a #847), e não injeta de novo
  a imagem de página inteira. A
  mensagem de progresso antes do planejamento agora é a das fórmulas
  (`STAGE_ENRICHING_FORMULAS`); o método anuncia as descrições dentro do
  plano.
- **Uma regra para os dois passos do documento.** As regras da 0.3.13 para o
  enriquecimento de tabelas (cobrir, deixar de lado os alvos perdidos,
  reconciliar as arestas, selecionar uma obrigação nova antes de um
  replanejamento) vão para `pipeline/document_obligations.py` e valem para
  os dois passos (`DocumentStep`, `reconcile_document_steps`).
  `add_table_enrichment_obligation` e as constantes de tabela mantêm os
  nomes.
- **Lacuna conhecida até o M3.** O passo de LaTeX das fórmulas roda antes do
  planejamento, então não vê mais uma imagem que o modelo lê como fórmula:
  essa fórmula fica com o LaTeX do modelo, sem a segunda leitura do
  reconhecedor nem a separação do número da equação. O M3 (#846) torna o
  reconhecimento uma obrigação da própria fórmula; fechar a lacuna é
  condição da release 0.3.0, e um teste a fixa, falhando quando o M3 a
  fechar.
- Um manifesto com todas as imagens descritas, como um checkpoint de
  enriquecimento da 0.3.13, não ganha `describe-images`, então uma retomada
  não descreve nada de novo antes do primeiro plano; a reconciliação de um
  replanejamento dá uma obrigação às imagens que ficaram sem descrição,
  tentadas no replanejamento que a execução já faria. Os candidatos são escolhidos antes de deixar de
  lado os já descritos, então um documento com todas as imagens descritas
  não passa mais para os seus visuais substitutos, como o passo fazia numa
  retomada.
- `picture-description` é `transitional` em `LOCAL_METHODS` (sua chamada de
  modelo é o `VisionAgent` do core) e não declara requisito do Toolbox: o
  recorte por `pdf.render` é por imagem e degrada para `crop_unavailable`.
- Testes: a obrigação, a ordem no plano (também no Fast Downward), o escopo
  e a mensagem do método, uma imagem lida como fórmula replanejada de ponta
  a ponta, a retomada de um checkpoint da 0.3.13 e um teste diferencial dos
  elementos antes e depois da migração.

## 0.3.13 — o executor trata obrigações que uma execução muda (#832, M0 da #640)

Uma reclassificação durante o plano, como uma imagem que o modelo de visão lê
como fórmula, remove as obrigações antigas do elemento e acrescenta novas. O
executor já selecionava as acrescentadas (#594). Agora ele trata também o
resto, para que o M1 (as descrições de imagens como ação planejada) possa vir:
- **Pulado, não falho.** O passo de uma obrigação que esta execução removeu
  ou substituiu fica `skipped`, com o motivo (`EXE_OBLIGATION_REMOVED`). O
  mesmo vale para o passo de uma obrigação que agora depende de uma obrigação
  aberta que este plano não executa antes dele: uma encontrada durante a
  execução, ou uma planejada e ainda não executada
  (`EXE_OBLIGATION_WAITS_FOR_OPEN`). O replanejamento ordena as duas. O
  `complete-job` fica `skipped`, não mais `failed`, enquanto toda obrigação
  aberta foi encontrada ou adiada por esta execução
  (`EXE_DISCOVERED_OBLIGATIONS_OPEN`, que as agrupa por kind). Uma que o
  plano executou e deixou aberta continua sendo falha.
- **Obsoleta sob o mesmo id.** O passo de uma obrigação mudada sob o mesmo
  id (outro kind, alvos de outros tipos, ou o método do passo que deixou de
  ser admissível) também fica `skipped` (`EXE_OBLIGATION_CHANGED`), e o
  replanejamento decide de novo. Um redirecionamento que mantém os tipos
  (uma divisão ou uma junção) não é mudança.
- **Uma remoção religa.** Um handler que remove uma obrigação precisa religar
  as dependentes dela à substituta, como faz a reconciliação; o manifesto
  recusa uma dependência pendurada. O executor relata uma que ficou
  pendurada pelo nome (`EXE_DEPENDENCY_REMOVED`), em vez de um `KeyError`.
  Antes de a guarda de descoberta ler o estado, o orquestrador recheca as
  referências de obrigação e o DAG do manifesto que a execução mudou, então
  uma referência pendurada deixada por um handler em qualquer ponto do grafo
  faz o job falhar com a mensagem do manifesto, em vez de um `KeyError` da
  guarda. As mensagens das checagens do grafo (alvos, dependências e
  artefatos inexistentes, autodependência, ciclo) seguem o idioma, como as
  do executor.
- `skipped` já era um status de passo do relatório de execução, então o
  contrato não muda. Uma execução em que só as obrigações mudaram não tem
  passo `failed`.
- **Limite próprio.** Depois de uma execução sem passo falho, o orquestrador
  replaneja com um limite próprio, `max_discovery_replans`, separado de
  `max_replans`, que continua contando as falhas. É uma opção do construtor
  (valores negativos contam como 0), que o serviço lê de
  `PDDL_MAX_DISCOVERY_REPLANS` (padrão 3). Um valor diferente do padrão entra
  nas identidades do checkpoint e do cache, então o padrão mantém as da
  0.3.12. Ele para quando um replanejamento partiria do estado de
  planejamento de que o anterior partiu (`planning_signature`, tomada depois
  da reconciliação: alvos, dependências, status e métodos tentados, não só
  ids). O contador e a assinatura são salvos com o checkpoint de plano
  (`discoveries`, `previous_signature`) e restaurados na retomada; um
  checkpoint sem eles retoma como antes.
- **A falha tem precedência.** Uma execução com passo falho e descoberta é
  um replanejamento de falha, então o orçamento de descobertas nunca
  contorna `max_replans`. Com ele esgotado, uma obrigação crítica deixada
  aberta faz o job falhar. Atender a descoberta sem tentar de novo o
  trabalho que falhou é a #842.
- **Obrigações do documento reconciliadas.** `add_table_enrichment_obligation`
  também roda antes de cada replanejamento:
  - uma tabela nova entra no enriquecimento aberto, ou ganha um novo
    (`obligation-enrich-tables-2`) quando os existentes estão fechados:
    satisfeitos, ou esgotados (`failed`), que não são planejados de novo.
    Antes de um replanejamento o novo já vem selecionado, então o
    replanejamento o agenda;
  - um enriquecimento deixa de lado as tabelas que o documento perdeu, e um
    que fica sem tabelas é removido junto com as dependências dele
    (`target_ids` não pode ficar vazio);
  - toda obrigação aberta cujos alvos incluem uma tabela depende do
    enriquecimento aberto daquela tabela, e uma aresta para um
    enriquecimento, aberto ou fechado, com o qual não compartilha mais
    tabela é removida. É uma regra sobre alvos, no lugar da lista da 0.3.12:
    além de `linearize-table` e `select-table-source`, ordena as obrigações
    de página de uma página com tabela depois da leitura, como na 0.3.11, ao
    custo de serializá-las atrás dela. Uma aresta para um fechado fica
    enquanto o alvo que a justificou ficar, então um enriquecimento esgotado
    não bloqueia uma dependente redirecionada para outra tabela.
- **O enriquecimento de tabelas se restringe aos seus alvos.**
  `_tables_to_read`, `_enrich_table_structures` e `_mark_table_inline_math`
  recebem `targets`, então um segundo enriquecimento lê e marca só as
  próprias tabelas, e a mensagem dele conta só elas.
- `_plan_progress` e `_thread_status` vão para `pipeline/progress.py`.

## 0.3.12 — o enriquecimento de tabelas é uma ação planejada (#640, M2)

Os dois passos de tabela que rodavam antes do planejamento passam para dentro
do plano (`docs/architecture/workflow-actions.pt-br.md`):
- ler, com o `DataAgent`, as tabelas sem estrutura utilizável ou
  embaralhadas;
- marcar a matemática inline das células a partir da camada de texto.

Um documento com tabelas ganha uma obrigação `enrich-tables`, que tem como
alvo todas as suas tabelas e é satisfeita pelo método `table-enrichment`. Esse
método roda os dois passos como antes: um breaker, uma passada de retry e um
leitor de spans para o documento inteiro. As obrigações `linearize-table` das
tabelas e, no modo dual, `select-table-source` dependem dela, então o plano lê
antes de linearizar ou escolher a fonte, como antes. Um método por tabela foi
descartado: ele esperaria a passada de retry uma vez por tabela que falhasse e
perderia a recuperação das tabelas lidas depois da abertura do breaker.

- `RunPorts.services` (`RunServices`) guarda a infraestrutura que os estágios
  e os métodos de uma execução compartilham, uma execução de um documento:
  `run_breaker`, `run_text_spans` e `progress`. O leitor de spans não guarda
  manifesto; um passo que não consegue ler a camada de texto grava
  `inline_math_detection = unavailable` no manifesto que enriquece, inclusive
  na cópia do executor.
- **O que o resultado do método significa:** a tentativa coletiva rodou. Cada
  tabela mantém seu próprio desfecho (`table_read_failure`: `model_failed`,
  `admission_rejected`, `crop_unavailable`), e seu `linearize-table` a
  valida. A mensagem informa quantas tabelas precisavam de leitura, quantas
  ganharam estrutura, o que ficou e por quê, e o estado da matemática inline
  (`fonts`, `unavailable` ou `off`). Uma rejeição de admissão (#590) é mantida
  e continua poupando o breaker dentro do plano.
- `table-enrichment` é `transitional` em `LOCAL_METHODS`: a mesma computação,
  mudada de lugar. Suas chamadas à Toolbox são condicionais, então não são
  requisitos.
- Um rótulo de localização sobre mais de cinco páginas dá a contagem e o
  intervalo ("12 páginas, de 1 a 12"), para que o passo sobre todas as tabelas
  não liste todas elas.
- Um caso de fixture do Fast Downward confere a nova ordem nos dois
  planejadores.

O que muda, de forma observável:
- O progresso continua: dentro do plano, o método informa "Enriquecendo as
  tabelas com OCR" e "Reconhecendo a tabela N de M" pelo
  `RunServices.progress` da execução, depois da mensagem do próprio passo do
  executor.
- Num documento com tabelas, o plano tem um passo a mais, e seus
  `problem_sha256` e `plan_id` mudam.
- O checkpoint do manifesto é salvo depois dos quatro passos de enriquecimento
  antes do planejamento, não seis. Dentro do plano, o checkpoint de execução
  cobre o passo inteiro, então uma queda no meio dele lê de novo as tabelas que
  já tinha lido naquela tentativa (follow-up: #836).
- Um passo que lança exceção não derruba mais o job na hora. Como qualquer
  método, ele registra uma tentativa falha, o planejador replaneja com
  `human-review` e o job então falha nessa obrigação crítica (com
  `PDDL_MAX_REPLANS`, mais uma execução).
- Um job retomado de um checkpoint de enriquecimento da 0.3.11 já tem as
  tabelas enriquecidas e não ganha a obrigação; um retomado de uma fase
  anterior ganha.

As descrições de imagens (M1) esperam uma preparação do executor (M0): uma
descrição pode retipar uma imagem como fórmula, o que remove uma obrigação
enquanto o plano roda.

## 0.3.11 — fatos de catálogo ligados à versão exata da capacidade

Os fatos de requisito nomeiam cada capacidade na versão exata de contrato que o
cliente do SDK chama, `capability_id@versão` (por exemplo `math.convert@1`,
símbolo PDDL `math-convert-1`). Essa também é a versão que a conferência do
catálogo exige (#640, PR 2). `toolbox_gate.capability_ref` monta a referência a
partir do registro do SDK; uma capacidade fora da allowlist mantém o id simples.

Os passos do plano não mudam, nem em `observe` nem em `enforce`. O problema de
um documento com métodos da Toolbox nomeia as versões, então seus
`problem_sha256` e `plan_id` mudam. Um job retomado mantém o checkpoint de plano
que tem, e os requisitos sem versão desse checkpoint continuam como estão nos
seus replanejamentos.

O `observe` continua o padrão; tirá-lo é um passo posterior, depois que os logs
de produção mostrarem que não há falsos "would remove" (#809).

## 0.3.10 — os métodos de fórmula declaram seus requisitos de Toolbox

`mathml` e `latex-verbalizer` chamam a Toolbox (`math.convert` e
`math.verbalize`, pelo provider de transformação de fórmulas), mas não estavam
em `METHOD_TOOLBOX_REQUIREMENTS`, então o gate de disponibilidade nunca os
conferia (#789). Agora estão declarados:
- em `observe` os passos do plano não mudam. O problema de um documento com
  obrigações de fórmula ganha os fatos `requires` delas, então seus
  `problem_sha256` e `plan_id` mudam; um job retomado mantém o checkpoint de
  plano que tem;
- em `enforce`, um catálogo sem eles descarta os dois métodos: uma obrigação
  `verbalize-formula` cai para `human-review`, e uma `normalize-formula` para
  `latex-normalizer`.

Todo outro método sem requisitos de Toolbox está classificado em
`planning/toolbox_gate.py`:
- `LOCAL_METHODS` associa cada um a um papel e um motivo. Os papéis são
  `transitional` (computação documental ainda no Core, que a ADR-0028 leva
  para a Toolbox, #804), `validation` (confere trabalho feito antes do
  planejamento) e `symbolic` (`human-review`);
- `NEVER_AVAILABLE_METHODS` guarda `table-specialist`, que tem custo mas não
  tem handler.

Testes falham para um método, com custo ou handler, que não esteja declarado
nem classificado, e o conjunto transitório só encolhe.

## 0.3.9 — o catálogo da Toolbox como fatos de planejamento (domínio 2.4)

A ADR-0029 torna a disponibilidade de capacidades e providers predicado do
problema de planejamento (#640, PR 1). O domínio PDDL vai para **2.4**:
- tipos `capability` e `provider`;
- fatos `(requires m c p)` e `(offered c p)`;
- um `(runnable m)` derivado: o método está `available` (o Core tem um
  handler) e o catálogo oferece todo requisito.

`execute-obligation` passa a exigir `runnable` no lugar de `available`. O
domínio 2.3 continua distribuído.

`PddlProblemCompiler.compile`, `PlannerAgent` e `PlanningProblem` recebem um
`catalogue` (`CatalogueFacts`). O gate de disponibilidade o monta a partir do
snapshot do catálogo (`AvailabilityDecision.catalogue_facts()`):
- em `observe`, todo requisito é oferecido, então o catálogo fica visível no
  problema e os planos não mudam. Esses fatos são presumidos, não observados:
  o metadado do gate diz `offered_source: assumed` e lista os métodos que o
  snapshot descarta (`assumed_runnable_methods`); `off` não acrescenta fatos
  de catálogo;
- em `enforce`, o snapshot decide o que é oferecido, e sem snapshot nada é
  (falha fechada). O gate não exclui mais métodos pelo nome
  (`unavailable_methods` fica vazio), e os mesmos métodos são excluídos pelos
  fatos.

Os requisitos e os pares oferecidos da decisão são salvos com o checkpoint
do plano (`AvailabilityDecision.from_metadata`, que substitui o
`_availability_from` do orquestrador), então um replanejamento depois de um
reinício vê o mesmo catálogo. Um checkpoint anterior à 2.4 mantém sua própria
lista de métodos excluídos.

A identidade do checkpoint de planejamento passa a incluir os hashes do
domínio. O executor recusa um plano feito com outro domínio, então, depois
deste deploy, um job retomado planeja de novo em vez de falhar.
Um job retomado reutiliza a decisão de catálogo do checkpoint de plano e não
lê o catálogo de novo (revalidação na retomada: #640, PR 3).

Os símbolos PDDL são únicos no problema inteiro: valores de tipos diferentes
que se normalizam igual (um método e um provider chamados `docling`) recebem
símbolos distintos, e o validador recusa um objeto declarado duas vezes.

O planejador interno é testado com o domínio 2.4. O Fast Downward 26.6 foi
conferido localmente e concorda com ele; o CI ainda não o roda (#790).
`tests/test_fast_downward_domain.py` compara os dois backends. Ele leva o
marcador `fast_downward`, fora da seleção por padrão porque o CI recusa testes
pulados: rode-o com `-m fast_downward` e `ACESSILIA_FAST_DOWNWARD` definido.

## 0.3.8 — o compilador PDDL recusa dependências cíclicas e desconhecidas

O modelo do manifesto recusa dependências cíclicas e desconhecidas entre
obrigações, mas um replanejamento altera o manifesto no lugar. Antes, o
compilador deixava as duas passarem:
- um ciclo compilava, e só o planejador interno o recusava, ao ordenar; o
  Fast Downward apenas não encontrava plano;
- uma dependência desconhecida levantava um `KeyError` cru.

O `PddlProblemCompiler` agora recusa as duas antes de qualquer planejador
rodar, com um `ValueError` que nomeia o ciclo ou a obrigação ausente (#783).
A verificação cobre o fecho selecionado: um ciclo abaixo de uma raiz nomeia só
o ciclo, e uma dependência desconhecida nomeia a obrigação que a tem. O modelo e
o compilador compartilham um percurso (`acessilia_core.manifest.dependencies`),
então reportam o mesmo ciclo; a mensagem do modelo agora também o nomeia.

## 0.3.7 — uma interface de motor de planejamento

Os planos padrão não mudam. `acessilia_core.planning.engine` cria a interface
entre o planejamento e a coordenação do workflow (#632, PR 3; ADR-0029):
- `PlanningProblem` (manifesto, raízes selecionadas, métodos indisponíveis);
- `PlanningResult` (plano, problema compilado, comparação opcional);
- o protocolo `PlanningEngine`;
- `PddlPlanningEngine`, o adaptador sobre o `PlannerAgent`.

O adaptador agora concentra a escolha do backend (`internal`,
`fast-downward`, `both`), que antes ficava no orquestrador. O
`PddlAccessibilityOrchestrator` planeja por `planning_engine`: um motor passado
ao construtor ou, por padrão, um `PddlPlanningEngine` montado a partir das suas
opções de backend a cada chamada de planejamento. Assim, um teste pode
substituir o planejador por um fake.

O contrato do motor:
- `plan` é síncrono e o motor não guarda estado entre chamadas; a propriedade
  aceita atribuição e rejeita um objeto que não segue o protocolo.
- Um motor tem uma `identity`. O `mode` do relatório é `pddl-<identity>`, que
  para o motor padrão é `pddl-<backend>`, como antes. A identidade de um motor
  injetado também entra na identidade do checkpoint de planejamento, então um
  job retomado com outro motor planeja de novo. Os checkpoints do motor padrão
  mantêm sua identidade.
- O coordenador rejeita um resultado cujo plano não confere com o hash do
  problema compilado.
- `PlanningProblem` e `PlanningResult` são imutáveis só superficialmente:
  compartilham o manifesto e o plano (#751).

Duas mudanças menores:
- O `PlannerAgent` é construído no primeiro uso, então um orquestrador com motor
  injetado não carrega o domínio PDDL para ele.
- A regra do plano preferido no modo both agora é `PlannerAgent.preferred`,
  compartilhada com o caminho da CLI; a mensagem de erro da CLI passa a ser a
  do catálogo.

Os padrões `DEFAULT_PLANNER_BACKEND` e `DEFAULT_FAST_DOWNWARD_SEARCH` ficam em
`planning.models`.

## 0.3.6 — descrições canônicas para os schemas PDDL

As descrições dos schemas PDDL agora usam as constantes canônicas em inglês em
vez do lookup do locale ativo, então gerar os schemas é determinístico
independentemente do locale do servidor. Os schemas de execution report,
nominal plan e planning comparison foram regenerados com essas descrições; suas
versões e estruturas não mudam. Os três msgids de descrição de schema foram
removidos dos catálogos de tradução porque são texto canônico de schema, não
strings localizadas. Um teste na raiz agora confere os quatro schemas
versionados contra seus geradores, nos dois locales suportados (#737).

## 0.3.5 — um único writer para os arquivos JSON Schema

Sem mudança de comportamento. As quatro funções `write_*_schema` agora delegam
para `acessilia_core.schema_files.write_schema`, que concentra a criação do
diretório pai e a formatação JSON em UTF-8 (#656).

## 0.3.4 — findings estruturados renderizados pelo SDK

Sem mudança de comportamento. `acessilia_core.pipeline.validators` renderiza
seus findings `(msgid, kwargs)` por
`acessilia_sdk.i18n.translation.resolve_findings` em vez de manter o loop de
formatação no Core. O core agora exige `acessilia-sdk>=0.6,<0.7` (#656).

## 0.3.3 — metadados de timeout da Toolbox pelo SDK

Sem mudança de comportamento. O Core lê os timeout keys próprios dos clientes
por `acessilia_sdk.toolbox.clients.client_timeout_keys()` em vez de introspectar
os internos do módulo de clientes do SDK; `TIMEOUT_KEYS` continua o nome público
do Core usado pela configuração do serviço. O core agora exige
`acessilia-sdk>=0.5,<0.6` (#656).

## 0.3.2 — reexportações da docstruct em formula_tools depreciadas

Sem mudança de comportamento para consumidores migrados; os nomes antigos agora
emitem `DeprecationWarning`. `acessilia_core.formula_tools` mantém `wrap_latex`
e `label_spoken_formula`. Importe os substitutos de `docstruct.text.latex`:
`bare_latex` para `normalize_latex` e `ensure_math_delimiters` para o nome
homônimo. Os consumidores do repositório foram migrados, e os nomes de
compatibilidade ficam até uma versão incompatível posterior removê-los (#656).

## 0.3.1 — reexportações da docstruct depreciadas nas bridges do pipeline

Sem mudança de comportamento. `acessilia_core.pipeline.table_ast` e
`acessilia_core.pipeline.validators` mantêm suas funções localizadas, mas as
funções puras e os msgids da docstruct que eles reexportavam agora emitem
`DeprecationWarning`; importe de `docstruct.tables.ast` e
`docstruct.validation`. Os consumidores do repositório foram migrados, e os
nomes de compatibilidade ficam até uma versão incompatível posterior removê-los
(#656).

## 0.3.0 — o adaptador da Toolbox não reexporta mais o SDK

**Mudança incompatível** para quem importava nomes do SDK por
`acessilia_core.toolbox.toolbox_client`. Importe `PROVIDER_DEFAULTS`, os erros
`Toolbox*`, `ToolboxCapabilityClient`, `auth_headers`, `execute_capability` e
`require_capability` de `acessilia_sdk.toolbox`.

O comportamento em runtime não muda. O adaptador do Core agora só mapeia a
`ToolboxConfig` da execução para a configuração de cliente do SDK e constrói
clientes, então o Core não atua mais como fachada do SDK (#656).

## 0.2.6 — infraestrutura de i18n pelo SDK

Sem mudança de comportamento. A infraestrutura genérica de i18n agora vive em
`acessilia_sdk.i18n` (#712): parsing e normalização de locales, negociação,
contexto de requisição por tarefa, compilação de catálogo e lookup
gettext/plural. O core mantém seus catálogos, ids de mensagem, políticas de
locale e a API pública de tradução `t()`/`n()`. A fachada temporária
`acessilia_core.i18n.parse_locales` foi removida; os nomes existentes
`set_request_locale`/`reset_request_locale` permanecem como reexportações de
compatibilidade, e código novo deve importá-los do SDK. O core agora exige
`acessilia-sdk>=0.4,<0.5`. O novo piso também cobre as APIs do SDK que o Core
0.2.5 já consumia -- fusão dual, downscale/validação de render e `run_sync` --
que o SDK publica na 0.4.0; os metadados do 0.2.5 ainda apontavam para 0.3.x.

## 0.2.5 — fusão dual, downscale, validação de render e bridge sync/async via SDK e docstruct

Sem mudança de comportamento, exceto dois casos-limite menores descritos
abaixo. O core passa a delegar a extração com dois provedores, a
fusão/roteamento puro de payloads, a redução de escala de imagens, a
pré-validação de mídia renderizável e os bridges síncrono/assíncrono ao
`acessilia-sdk` e ao `acessilia-docstruct` (#612):

- `pipeline/fusion.py`: `extract_fused` delega para
  `acessilia_sdk.operations.fusion.extract_dual_fused` (preservando os logs de
  falhas por provedor e fallback de artefato via `DualFusionUnavailable`),
  enquanto `fuse_extraction_payloads` e `apply_page_routes` delegam para
  `docstruct.fusion.payload.fuse_extraction_payloads` e `route_pages`
  (preservando os logs de páginas roteadas e ausentes).
- `toolbox/vision_payload.py`: `downscale_image` delega a renderização para
  `acessilia_sdk.toolbox.clients.pdf.downscale_image`, mantendo no core o ciclo
  de vida do cliente com `ToolboxConfig`, o log localizado e o retorno `None`.
- `pipeline/toolbox.py` e `pipeline/judge.py`: substituem `_check_renderable`
  por `acessilia_sdk.toolbox.clients.pdf.check_renderable`.
- `pipeline/handlers/inspection.py` e `pipeline/handlers/fusion.py`: substituem
  os bridges síncrono/assíncrono duplicados por `acessilia_sdk.runtime.run_sync`.

Casos-limite menores:

- O `ValueError` de divergência de tipo de mídia em `check_renderable` passa a
  dizer `Source is <declared> but would be sent as <extension>` (sem o trecho
  `"in the manifest"`).
- `vision_payload.downscale_image` com `scale` não positivo ou não finito passa
  a devolver `None` sem construir cliente da Toolbox, em vez de renderizar uma
  imagem de 1 px.

O core passa a exigir `acessilia-docstruct>=0.5.8,<0.6` (#612).

## 0.2.4 — primitivas estruturais do docstruct 0.5.7

Sem mudança de comportamento, exceto um caso-limite mais estrito. As
implementações duplicadas do core passam a chamar o `acessilia-docstruct`
diretamente (#612): as verificações de tabela e o `DataOutput.table_ast`
(`docstruct.tables.structured`), a detecção e o reparo da hierarquia de
títulos (`docstruct.sections`), a ordenação pelo esqueleto
(`docstruct.fusion.skeleton`, mesmo limiar de 0.5), os helpers de caixa dos
slides (`docstruct.geometry.boxes`), a inspeção de cabeçalhos PNG/JPEG
(`docstruct.imaging`) e o `is_legitimate_text` (`docstruct.fusion.noise`).

O caso-limite mais estrito: um `table_ast` cujo `rowspan`/`colspan` traz um
booleano JSON sobrevivia ao `isinstance(span, int)`; o normalizador estrito o
descarta. Caracterizado em `libs/core/tests/test_docstruct_057_adoption.py`.

O core passa a exigir o docstruct 0.5.7 ou mais novo (#612).

## 0.2.3 — o juiz de página pela operação do SDK

O método `vlm-pairwise-judge` renderiza a página e consulta o juiz pela
operação do juiz de página do SDK (`acessilia_sdk.operations.page_judge`,
#470). O core mantém as suas decisões: a conferência da fonte, quais páginas, o
aviso de truncamento, o limiar e o que cada falha significa. As requisições,
as escolhas e as mensagens de falha não mudam, exceto num caso. Uma resposta
cujo documento não é um objeto (null, lista, texto, número, booleano) levantava
`AttributeError` para fora do método; agora faz o método falhar como uma
resposta sem `pB` válido.

## 0.2.2 — AST de tabela a partir das linhas, pelo docstruct

O construtor do payload e o preenchimento de tabelas montam o AST de uma tabela
a partir das linhas com o `docstruct.tables.ast.table_ast_from_rows`, em vez da
cópia do core (#470). Nas entradas do core, listas de células, as duas só
diferem nas linhas em que todas as células estão em branco: o docstruct as deixa de fora e devolve `None` quando não sobra
nenhuma. A única entrada que chega a isso é uma tabela cujo texto é só espaço
em branco e que não tem um AST de tabela aproveitável: o bloco dela no payload
passa a ter `table_ast: None` em vez de um AST de uma célula vazia. A tabela do
documento canônico e as exportações não mudam.

## 0.2.1 — geometria de caixas dos slides vinda do docstruct

Sem mudança de comportamento. O layout de slides (`manifest/slides.py`) usa a
geometria de caixas do docstruct em vez das suas próprias cópias:
`boxes_overlap` e `union_area`, novas em `docstruct.geometry.boxes`, e
`docstruct.fusion.similarity.area`. O core passa a exigir o docstruct 0.5.6 ou
mais novo (#470).

## 0.2.0 — validação canônica estrita na exportação

**Mudança incompatível de validação:** TXT, HTML, DOCX e PDF/UA exigem que o
documento normalizado inteiro corresponda ao schema empacotado do docstruct,
após a auditoria existente e antes da seleção de perfil. Tipos customizados,
IDs de bloco/seção ausentes e valores inválidos antes aceitos passam a gerar
`ValueError` localizado antes do renderer. Falhas de auditoria têm precedência.

Antes de adotar 0.2.0, construa árvores com `docstruct.canonical` ou forneça
todos os IDs/campos necessários. Corrija valores inválidos; represente semântica
customizada com um dos onze tipos suportados e metadados. Blocos customizados
em nível filtrado pelo TXT não contornam o gate. Células numéricas continuam
convertidas em texto pelo sanitizador; extensões de metadados são válidas.
Texto/Markdown continuam passando pelo builder.

Mappings persistidos/em cache, incluindo jobs retomados, são conferidos ao
exportar. Artefatos existentes e tokens não são revalidados.

Serializadores puros, fallback, schema, contratos do SDK, perfis, nomes e
downloads legados não mudam. Não há nova flag ou fallback. Veja o
[ADR 0026](../../docs/adr/0026-strict-canonical-export-gate.pt-br.md) e o
[corpus de compatibilidade](../../tests/fixtures/export_schema_gate/README.pt-br.md).
