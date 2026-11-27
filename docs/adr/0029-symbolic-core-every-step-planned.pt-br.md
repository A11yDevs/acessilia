# 0029. O core planeja e coordena: todo passo semântico do workflow é planejado

Também disponível em **inglês (EUA)**: [English version](0029-symbolic-core-every-step-planned.md)

- **Status:** Proposto
- **Data:** 2026-11-22
- **Componentes:** core, Toolbox
- **Issues:** [#735](https://github.com/A11yDevs/acessilia/issues/735), [#640](https://github.com/A11yDevs/acessilia/issues/640), [#632](https://github.com/A11yDevs/acessilia/issues/632), [#619](https://github.com/A11yDevs/acessilia/issues/619)
- **Baseia-se em:** [ADR-0020](0020-job-resumption-and-operation-journal.pt-br.md), [ADR-0027](0027-mcp-core-toolbox-contract.pt-br.md), [ADR-0028](0028-operational-execution-in-the-toolbox.pt-br.md)

## Contexto

O core já planeja com PDDL em ciclo fechado: `PddlProblemCompiler`,
`PlannerAgent`, `NominalPlan`, `ExecutorAgent` e replanejamento limitado por
`max_replans` (#640). Mas o plano cobre só parte de um job. Medido em
`develop` (`46f2fe7e`):

- `domain_v2.3.pddl` tem **3 ações genéricas**: `start-job`,
  `execute-obligation` e `complete-job`. O planejador ordena obrigações; não
  modela capacidades, suas pré-condições nem seus efeitos.
- `PddlAccessibilityOrchestrator.execute` roda **quatro estágios em sequência
  fixa, antes de planejar**: inspeção de mídia, limite de páginas, extração
  estrutural e os estágios de enriquecimento.
- Qual método satisfaz uma obrigação é decidido pelo registro de métodos
  (`METHOD_HANDLERS`), não pelo domínio.
- A disponibilidade de capacidades é aplicada pelo `toolbox_gate` fora do
  planejador. No momento desta medição seu padrão era `observe` (removido na
  [#809](https://github.com/A11yDevs/acessilia/issues/809)); em `enforce` ele
  removia métodos e o planejador "caía para métodos locais", que a ADR-0028
  elimina.
- Agentes em `acessilia_core.agents` (fusão, adjudicação, visão, especialista
  em tabelas, nível de página) tomam decisões e chamam modelos a partir do
  core.

A Toolbox já publica parte do lado semântico das suas capacidades:
`GET /v1/planning/domain` (um domínio monolítico, gerado a partir da versão
mais recente de cada capacidade), `GET /v1/planning/capabilities/{id}` e
`GET /v1/planning/predicates`, e os recursos MCP
`acessilia://planning/domain` e `acessilia://planning/capabilities/{id}`.
Fragmentos por capacidade (`/planning/domain-fragments`) aparecem no
`docs/pddl.md` da Toolbox só como algo que ela *pode* expor. A Toolbox não é
dona do planejamento. A #632 (PR 2) proíbe um compilador genérico MCP → PDDL,
e a #640 trata a composição de fragmentos como experimental.

## Decisão

### O que é o core

- O core é responsável pelo planejamento, pelo raciocínio, pela coordenação e
  pelo estado lógico dos workflows. Não executa capacidades operacionais nem
  algoritmos de processamento documental (ADR-0028).
- Ele continua computando o que o planejamento e a coordenação exigem:
  compilar problemas, compor e validar domínios, manter o estado lógico e o
  journal, verificar efeitos observados, aplicar políticas, correlacionar
  resultados e replanejar. Isso não é computação documental.

### Todo passo semântico é uma ação

- O core planeja os passos semânticos de transformação e acessibilização do
  documento posteriores à aquisição do estado inicial: passos que mudam o
  documento ou decidem o workflow, como OCR, fusão de blocos, ordem de
  leitura, descrição de imagens, adjudicação, normalização matemática e
  exportação acessível. O orquestrador não pode rodar uma sequência fixa
  desses passos.
- Uma fase explícita de **bootstrap** pode realizar a inspeção de mídia e a
  extração estrutural inicial necessárias à formulação do primeiro problema
  PDDL, sob política e coordenação do core e com execução operacional na
  Toolbox. Ela é a baseline da 0.3.0: o enriquecimento que hoje roda antes do
  planejamento migra para ações planejadas
  (`docs/architecture/workflow-actions.pt-br.md`), e a eventual incorporação
  do próprio bootstrap ao planejamento é uma investigação posterior (#816).
- Políticas de configuração continuam políticas do core, não ações. O limite
  de páginas (`DocumentConfig.max_pages`, verificado antes e depois da
  extração) é uma delas: é uma verificação de admissão que rejeita o job com
  `DocumentTooLargeError`.
- A infraestrutura fica fora do domínio e pertence ao runtime: retries HTTP,
  renovação de credenciais, serialização, persistência operacional,
  confirmação de mensagens em filas, health checks, transporte e recuperação
  de artefatos.
- Uma capacidade composta pode executar várias operações internas como uma só
  ação. Seus passos internos não são ações PDDL.
- Uma ação operacional deve estar ligada a uma capacidade da Toolbox, por id e
  versão exata, invocada pelo cliente genérico (ADR-0027). As demais ações são
  só simbólicas: registrar estado, `human-review`, concluir o job.

### O domínio é composto de fragmentos versionados

- O domínio efetivo é formado pelas ações de workflow do core mais os
  fragmentos PDDL das capacidades **e versões** do snapshot do catálogo. A
  Toolbox deve servir fragmentos por capacidade e por versão, gerados a partir
  de um snapshot; o domínio monolítico gerado das versões mais recentes não
  consegue atender a um plano que fixa uma versão anterior.
- Os fragmentos são curados e versionados junto com sua capacidade. A
  composição verifica nomes e tipos; não traduz schemas de tools em PDDL (sem
  compilador genérico, #632).
- O CI deve fazer o parsing do domínio composto e resolver um conjunto de
  problemas de fixture com o planejador interno e com o Fast Downward. O Fast
  Downward continua opcional em tempo de execução, como no código. Conferi-lo
  no CI ficou em aberto aqui; essa subdecisão está tomada, enquanto esta ADR
  continua Proposta. Desde a #790, um job roda os dois backends sobre o
  domínio atual, único (2.4), com o Fast Downward de uma imagem fixada. A
  parte do domínio composto está **pendente**: suas fixtures chegam com os
  fragmentos (#640, PR 2), e o mesmo job passa a cobri-las.

### Estado, disponibilidade e falha

- O problema é compilado a partir do estado observado: os fatos do manifesto,
  as obrigações, os resultados já registrados e um snapshot do catálogo.
- A disponibilidade de capacidades e providers são predicados do problema. O
  `toolbox_gate` fica reduzido a relatório.
- Um problema insolúvel é um resultado explícito, nunca uma degradação
  silenciosa: o job termina **escalado**, com a causa registrada. Hoje o
  `human-review` faz exatamente isso (seu handler registra a escalada e
  retorna `success=False`), e continua terminal: o job não pausa à espera de
  uma pessoa. Pausar e retomar após uma decisão humana exige estado durável de
  workflow e fica para uma ADR posterior.
- Um resultado de capacidade atualiza o estado simbólico uma vez por
  `operation_id`. O journal da ADR-0020 guarda só identidade, "(task_id, slot
  lógico) → operation_id", para os slots de upload e extração. Por isso esta
  ADR o estende:
  - os slots do journal passam a cobrir toda chamada de capacidade do plano;
  - o checkpoint `execution` guarda um **registro de resultados aplicados**, o
    conjunto de `operation_id`s cujo resultado já foi aplicado ao estado
    simbólico.

  Um resultado cujo `operation_id` já está nesse registro, ou que não pertence
  ao passo atual do plano, é ignorado.
- O replanejamento continua no core e continua limitado.

### O core é agêntico; a Toolbox é passiva

- **O core é agêntico e ativo**: raciocina, planeja, delega, coordena,
  avalia e replaneja. **A Toolbox é operacional e passiva**: executa as
  capacidades que lhe pedem e devolve resultados, sem autonomia agêntica e
  sem responsabilidade por decisões de workflow.
- A Toolbox pode conter capacidades atômicas e compostas, algoritmos do
  docstruct, inferência de modelos, prompts, adaptadores, validação e
  processamento de resultados, workers, filas, caches e recuperação
  operacional, e composição determinística de operações. Uma capacidade
  composta pode manter controle operacional interno. A Toolbox não contém
  agentes autônomos, planejadores de objetivos ou subobjetivos, coordenação
  agêntica de workflows, replanejamento semântico nem decisões estratégicas
  ou gerenciais.
- **Toda autonomia agêntica está no core.** Seus agentes assumem um de três
  papéis permanentes, distinguidos pelo escopo da sua autoridade, não pela
  tecnologia que usam (um LLM, um planejador simbólico ou regras
  determinísticas):

  | Papel | Especializado em | Responsabilidade | Escopo de planejamento |
  |---|---|---|---|
  | estratégico | objetivos globais | Objetivos, políticas e prioridades; coordenação global; avaliação dos resultados globais; a decisão de replanejar; a futura integração LLM + planejamento da #619 | o plano global |
  | gerencial | domínio | Decompor um objetivo delegado; um subplano de domínio; delegar tarefas a agentes operacionais ou invocar capacidades diretamente; avaliar resultados; replanejar dentro do domínio; escalar o que excede sua autoridade | um subplano de domínio |
  | operacional | tarefa | Concluir uma tarefa logicamente atômica com as capacidades autorizadas: escolher entre alternativas, observar resultados, recuperar falhas locais, escalar ao seu gerente | um plano local delimitado |

- **Uma tarefa operacional é atômica logicamente, não computacionalmente.**
  Tem um objetivo verificável, entradas e saídas contratadas, capacidades
  autorizadas, autonomia delimitada, orçamento de recursos, critérios de
  conclusão e condições de escalada. O agente pode usar várias capacidades.
  Ele não redefine objetivos de domínio, não muda políticas, não coordena
  outros subplanos, não cria agentes nem delega subplanos (uma primeira
  fronteira, que a #774 pode rever).
- **Não há um agente por capacidade.** Uma tarefa que uma capacidade executa
  sem decisões adaptativas relevantes é invocada diretamente pelo agente
  gerencial. Um agente operacional se justifica pela necessidade de
  autonomia: escolher entre alternativas, avaliar resultados ou recuperar
  falhas. Nem todo workflow usa os três níveis; a hierarquia efetiva segue a
  complexidade da tarefa.
- **Evidência não é autoridade.** Agentes gerenciais e operacionais podem
  usar capacidades de apoio (comparar candidatos, ordenar estratégias,
  estimar custos, verificar restrições, reunir evidências de consistência ou
  de conclusão). Elas calculam evidências; a decisão de aceitar uma
  alternativa, mudar um subplano ou considerar um objetivo satisfeito fica
  com o agente responsável no core. Uma capacidade de apoio fica numa
  biblioteca pura do core quando é um mecanismo de planejamento ou
  coordenação, e na Toolbox quando é processamento operacional.
- **Papel e ciclo de vida são separados.** Um agente operacional genuíno
  pode ser parte permanente do core. Os módulos existentes de
  `acessilia_core.agents` são componentes operacionais **legados**: executam
  ou encapsulam operações destinadas à Toolbox (OCR e extração semântica,
  classificação documental, descrição de imagens, adjudicação visual,
  extração de tabelas e fórmulas, processamento multimodal).
- **Nenhum agente vai para a Toolbox.** Um componente legado é decomposto
  por responsabilidade antes de migrar. Inferência de modelos, algoritmos
  determinísticos, validação técnica e transformação de resultados viram
  capacidades não agênticas. Definir objetivos e planejar fica com o core
  estratégico. Subplanejar e escolher a estratégia fica com o core
  gerencial. Avaliação semântica e a decisão de replanejar ficam no core, no
  escopo do agente que as detém. Contratos e transporte pertencem ao core
  SDK e aos contratos compartilhados. Por exemplo, a inferência de um agente
  de visão vira capacidade, enquanto a decisão de inspecionar de novo fica
  no core.
- **O planejamento hierárquico continua possível.** O planejamento não
  precisa ser monolítico. O plano global pode delegar objetivos de domínio a
  agentes gerenciais que planejam subplanos, e a delegação pode ser recursiva
  com limites explícitos de profundidade, custo, tempo e autoridade.
  Contratos de delegação, os agentes gerenciais e a comparação entre
  planejamento hierárquico e monolítico (HTN incluída) são direções de
  pesquisa acompanhadas na
  [#774](https://github.com/A11yDevs/acessilia/issues/774) e na #619, não
  decisões tomadas aqui. A #774 compara um nível (o agente estratégico
  invoca capacidades), dois níveis (estratégico e gerencial) e três níveis
  (com agentes operacionais). Todo passo semântico continua planejado, em
  algum nível da hierarquia, e o core estratégico mantém o estado lógico
  global; os demais agentes relatam resultados e evidências, sem atualizá-lo
  de forma conflitante.
- A classificação dos agentes existentes está em
  [core-agent-classification.pt-br.md](../architecture/core-agent-classification.pt-br.md)
  (#768).
- Com `AI_CLIENT=toolbox` (ADR-0012; as implantações de produção e staging),
  chamadas a modelos passam pela Toolbox, inclusive as de um agente
  estratégico. O padrão ainda é `ollama`, e `openrouter` continua suportado.
  Remover os modos diretos não é decidido aqui: emendaria a ADR-0012 e a
  configuração. O core interpreta os resultados dos modelos no contexto do
  plano. A Toolbox
  nunca decide objetivos globais nem replanejamento.
- Os contratos distinguem o resultado de uma capacidade, e a evidência que ele
  traz, da decisão de um agente.

### Planejador e coordenação são separados

- Uma interface `PlanningEngine` (#632, PR 3) separa o planejador da
  coordenação do workflow. O planejador interno e o Fast Downward continuam
  intercambiáveis atrás dela, e a comparação entre eles continua rodando.

## Decisões em aberto

Esta ADR continua `Proposto` até que estes pontos sejam fechados na revisão:

- **Fragmentos por versão.** Os donos da Toolbox aceitam servir fragmentos
  por capacidade e por versão a partir de um snapshot do catálogo.
- **Registro de resultados aplicados.** A extensão do journal da ADR-0020 e do
  checkpoint `execution` é revisada junto com a versão de schema de checkpoint
  de que precisa.
- **Revisão entre componentes.** Os donos da Toolbox revisam o contrato de
  planejamento (processo de ADR, passo 5). Depois disso, um pull request
  seguinte define `Aceito`.

## Consequências

- O plano explica todo passo semântico do job; disponibilidade, alternativas e
  becos sem saída vêm do domínio, e não de caminhos no código. Manter a
  infraestrutura fora do domínio o mantém pequeno. Esse é o baseline
  simbólico para a #619.
- O domínio cresce com o catálogo. A curadoria dos fragmentos, os custos das
  ações e as fixtures de planejamento no CI o mantêm tratável.
- A migração é incremental e segue a ADR-0028, método a método. Depois os
  passos de enriquecimento viram ações enquanto o bootstrap continua fixo (a
  #816 decide se ele entra no plano), e depois as responsabilidades
  operacionais dos agentes legados viram capacidades não agênticas. O ciclo fechado não espera pelas filas duráveis
  (#639): chamadas MCP síncronas bastam.
- Os indicadores de progresso são acompanhados na #735: passos de
  enriquecimento fora do plano (6, `docs/architecture/workflow-actions.pt-br.md`;
  o bootstrap fica fora por desenho), métodos de plano que
  computam localmente (14 de 25, ADR-0028), agentes operacionais ainda no
  core.
- Trabalho decorrente, acompanhado na #735:
  - Toolbox: servir fragmentos PDDL por capacidade e por versão, gerados a
    partir de um snapshot do catálogo (REST e recursos MCP).
  - core: compor o domínio a partir desses fragmentos; a verificação de
    política do limite de páginas; a extensão do journal e o registro de
    resultados aplicados.
  - core: a camada gerencial, contratos de delegação e planejamento
    hierárquico, como pesquisa (#774, #619).
- Conformidade: as fixtures de planejamento no CI; um teste do orquestrador
  que verifica que todo passo de um job vem do plano;
  `tests/test_architecture_layers.py` para clientes de modelo no core e para
  a classificação de todo módulo de `acessilia_core.agents` (papel e ciclo de
  vida).
