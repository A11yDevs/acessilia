# Estágios pré-planejamento como ações planejadas (#640, PR 2)

Inglês, versão normativa: [English version](workflow-actions.md)

A [ADR-0029](../adr/0029-symbolic-core-every-step-planned.pt-br.md) torna todo
passo semanticamente relevante de um job uma ação do domínio de planejamento.
Hoje o orquestrador roda quatro estágios antes de planejar. Deles, inspeção,
extração e enriquecimento precisam virar ações; o limite de páginas continua
uma política de admissão. Esta página é o desenho dessa migração: o que cada
estágio faz hoje, as restrições que uma migração precisa respeitar e a ordem
dos pull requests. Ela não muda código. As propostas abaixo estão abertas à
revisão (veja [Questões abertas](#questões-abertas)).

## Hoje

`PddlAccessibilityOrchestrator._execute` (`pipeline/orchestrator.py`) roda, em
ordem:

| Estágio | O que faz | Chama | Escreve | Checkpoint |
|---|---|---|---|---|
| Inspeção de mídia | Lê os fatos de mídia do arquivo; um deck de slides é estruturado de outro jeito | Toolbox `media.inspect` | a inspeção e a configuração de mídia | `media` |
| Limite de páginas | Recusa um documento acima de `DocumentConfig.max_pages` (`DocumentTooLargeError`) | — | — | — |
| Extração | Monta o manifesto: elementos, depois as obrigações derivadas dos seus tipos | Toolbox `document.structure.extract` (um ou dois providers) | o manifesto | `manifest` |
| Enriquecimento | Seis passos, numa ordem fixa (abaixo) | Toolbox e os agentes de modelo do Core | o manifesto, passo a passo | `enriched`, por objeto |
| Planejamento | Compila o problema a partir do manifesto enriquecido e planeja | — | o plano | `plan` |

Os seis passos de enriquecimento (`_enrich_before_planning`) compartilham um
breaker de provider, um cache de regiões e um registro de progresso por
objeto:

| Passo | Função | Chama | Efeito no manifesto |
|---|---|---|---|
| 1. Regiões de fórmula | `_classify_formula_regions` | Toolbox `pdf.render` (o recorte da fórmula); `VisionAgent` | pode mudar o tipo de um elemento e então reconcilia suas obrigações (`reconcile_reclassified_element`) |
| 2. Descrições de imagens | `_enrich_picture_descriptions` | `VisionAgent` | uma descrição por imagem |
| 3. Matemática inline | `_mark_inline_math` | Toolbox `document.text.spans` | marca a matemática na prosa |
| 4. LaTeX das fórmulas | `_enrich_formula_latex` | Toolbox `math.recognize`, `pdf.render` | o LaTeX de cada fórmula |
| 5. Estrutura das tabelas | `_enrich_table_structures` | `DataAgent` | uma AST estruturada por tabela |
| 6. Matemática inline das tabelas | `_mark_table_inline_math` | Toolbox `document.text.spans` | marca a matemática nas células (depois do passo 5, que pode substituir células) |

O plano então trabalha sobre o que o enriquecimento produziu. Alguns métodos
só conferem esse trabalho: `vision-description` confere as descrições e
`pandoc-table` confere a AST da tabela. Os dois estão classificados como
`validation` em `toolbox_gate.LOCAL_METHODS` (#801).

## A observação central

O domínio já tem uma ação operacional genérica, `execute-obligation(o, m)`.
Um método é um jeito de satisfazer uma obrigação, e o executor roda o handler
do método. Então **um passo vira uma ação ao virar o método de uma
obrigação**: o planejador passa a escolhê-lo, ordená-lo por `depends-on`,
contar seu custo, descartá-lo pelos fatos do catálogo (domínio 2.4) e
replanejar quando ele falha. Nada disso precisa de um novo esquema de ação. A
migração do enriquecimento **não muda o domínio**. Inspeção e extração
precisam de uma mudança no manifesto (abaixo), e possivelmente de nenhuma no
domínio.

## Restrições

1. **Um plano não cria objetos.** A extração cria os elementos e suas
   obrigações, e a classificação de fórmulas pode mudar o tipo de um elemento
   e, com ele, suas obrigações. Depois de uma ação assim, as próximas dependem
   de objetos que o problema não tinha. O ciclo fechado resolve isso: roda a
   ação, observa o novo estado, replaneja. O replanejamento é limitado
   (`max_replans`), então uma ação que cria objetos não pode contar como falha
   para esse limite.
2. **A ordem vira dependência.** A ordem fixa do enriquecimento vira
   `depends-on` entre obrigações do mesmo elemento:
   - a classificação de fórmulas vem antes da descrição de uma imagem que ela
     pode reclassificar;
   - o reconhecimento do LaTeX vem antes de `verbalize-formula` e
     `normalize-formula`;
   - a estrutura da tabela vem antes da matemática inline da tabela.
3. **A infraestrutura fica fora do domínio.** O breaker de provider, o cache de
   regiões, o progresso por objeto e os checkpoints são assunto do runtime
   (ADR-0029). Os handlers chegam a eles pelo contexto da execução
   (`RunPorts`), não por fatos.
4. **Os handlers são síncronos.** `MethodHandler` é
   `(manifest, obligation_id) -> MethodResult`; os passos de enriquecimento são
   assíncronos. Um handler migrado os chama por
   `acessilia_sdk.runtime.run_sync`, como o `dual-provider-fusion` já faz.
5. **Chamadas de modelo ainda não são capacidades.** `VisionAgent` e
   `DataAgent` são os agentes de modelo do Core
   ([classificação](core-agent-classification.pt-br.md)). Levar um passo para
   um método o torna planejado, mas a chamada de modelo continua no Core. Esse
   método fica como `transitional` em `LOCAL_METHODS` até a chamada virar uma
   capacidade (#804, #640 PR 4), e até lá o gate não consegue conferi-lo. As
   chamadas à Toolbox que um passo faz (`math.recognize`, `pdf.render`,
   `document.text.spans`) são declaradas em `METHOD_TOOLBOX_REQUIREMENTS`
   quando o passo vira método.
6. **A retomada continua idempotente.** Hoje um passo pula os objetos que já
   terminou. Como método, o mesmo registro torna barato um passo do plano
   executado de novo, e o checkpoint de execução registra quais passos
   rodaram.
7. **Equivalência primeiro.** Cada migração mantém um teste diferencial do
   manifesto final em documentos de fixture, antes e depois (ADR-0028).

## Ordem da migração

Cada passo é um pull request, do menos ao mais estrutural:

| PR | Passo | Obrigação e método | Domínio | Manifesto |
|---|---|---|---|---|
| M1 | Descrições de imagens | `describe-image`: `vision-description` produz a descrição em vez de conferi-la | — | — |
| M2 | Estrutura das tabelas e matemática inline das tabelas | `linearize-table`: `pandoc-table` lê a estrutura e marca a matemática | — | — |
| M3 | LaTeX das fórmulas | Um kind novo, `recognize-formula`, antes de `verbalize-formula` e `normalize-formula` | — | kind novo |
| M4 | Regiões de fórmula e matemática inline | Kinds novos por região candidata e por bloco de prosa. Uma reclassificação cria obrigações, então o ciclo replaneja | — | kinds novos |
| M5 | Inspeção e extração | Obrigações do job, `inspect-media` e `extract-structure`, sobre um manifesto semente que existe antes da extração | possivelmente nenhuma | um estado semente (versão do schema) |

O M1 é o menor. A obrigação e o método existem, o papel do método passa de
`validation` para `transitional`, e só a chamada pré-planejamento muda de
lugar. O M5 é o maior. Ele precisa de um manifesto que exista antes dos seus
elementos, e é o passo em que o planejamento hierárquico (#774) é a
alternativa.

Cada PR:
- tira seu passo de `_enrich_before_planning` (ou de `_execute`, no M5);
- atualiza `LOCAL_METHODS` e `METHOD_TOOLBOX_REQUIREMENTS`;
- acrescenta o teste diferencial e o caso de fixture do Fast Downward (o job
  de CI da #790);
- atualiza esta página.

## Questões abertas

- **M5: manifesto semente ou um problema separado do job.** Um manifesto
  semente mantém um problema e um ciclo, mas muda o schema do manifesto. Um
  problema do job que planeja inspeção e extração e depois passa para o
  problema do documento é planejamento hierárquico (#774).
- **Replanejamentos que criam objetos.** Eles devem contar para
  `max_replans`? A proposta é que não: contar só os replanejamentos que seguem
  uma falha, e dar aos que criam objetos um limite próprio.
- **Custos** dos novos métodos e kinds, para que o planejador os ordene como o
  enriquecimento faz hoje quando nada falha.
- **O breaker compartilhado** hoje cobre todos os passos de um documento. Como
  serviço da execução, ele mantém esse escopo; confirmar isso evita que uma
  indisponibilidade de provider vire uma falha por obrigação.

## Fora do escopo

- Compor o domínio a partir dos fragmentos da Toolbox. Isso espera a decisão
  aberta da ADR-0029, "Fragmentos por versão", que os donos da Toolbox
  precisam aceitar.
- Tirar o modo `observe` do gate (#809).
- Transformar os agentes de modelo em capacidades (#804, #640 PR 4).
