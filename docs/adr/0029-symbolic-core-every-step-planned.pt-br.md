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
  planejador. Seu padrão é `observe`. Em `enforce`, ele remove métodos e o
  planejador "cai para métodos locais", que a ADR-0028 elimina.
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

- Todo passo **semanticamente relevante** de um job deve ser uma ação do
  domínio de planejamento: passos que mudam o documento ou decidem o workflow,
  como inspeção, extração, OCR, fusão de blocos, ordem de leitura, descrição
  de imagens, adjudicação, normalização matemática e exportação acessível. O
  orquestrador não pode rodar uma sequência fixa desses passos.
- Políticas de configuração continuam políticas do core, não ações. O limite
  de páginas (`DocumentConfig.max_pages`, verificado antes da extração) é uma
  delas: é uma verificação de admissão que rejeita o job com
  `DocumentTooLargeError`. Dos quatro estágios que hoje rodam antes do
  planejamento, inspeção, extração e enriquecimento viram ações; o limite de
  páginas continua política.
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
  problemas de fixture com o planejador interno. O Fast Downward continua
  opcional, como no código (o CI não o instala hoje): a comparação roda onde
  ele estiver instalado. Incluí-lo no CI é uma decisão separada.

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

### Agentes estratégicos ficam no core; agentes operacionais são capacidades

- Os agentes de `acessilia_core.agents` são classificados como estratégicos ou
  operacionais; a classificação está em
  [core-agent-classification.pt-br.md](../architecture/core-agent-classification.pt-br.md)
  (#768).
- **Agentes estratégicos ficam no core**: interpretar objetivos, decompor
  tarefas, escolher estratégias, coordenar subplanos, avaliar estado e
  objetivos, decidir replanejar e a futura integração LLM + planejamento da
  #619.
- **Agentes operacionais viram capacidades da Toolbox**: OCR e extração
  semântica, classificação documental, descrição de imagens, adjudicação
  visual, extração de tabelas e fórmulas, processamento multimodal.
- Com `AI_CLIENT=toolbox` (ADR-0012; as implantações de produção e staging),
  chamadas a modelos passam pela Toolbox, inclusive as de um agente
  estratégico. O padrão ainda é `ollama`, e `openrouter` continua suportado.
  Remover os modos diretos não é decidido aqui: emendaria a ADR-0012 e a
  configuração. O core interpreta os resultados dos modelos no contexto do
  plano. A Toolbox
  nunca decide objetivos globais nem replanejamento.
- Os contratos distinguem um resultado operacional de uma decisão estratégica.

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
  três estágios semânticos fixos viram ações, e depois os agentes operacionais viram
  capacidades. O ciclo fechado não espera pelas filas duráveis
  (#639): chamadas MCP síncronas bastam.
- Os indicadores de progresso são acompanhados na #735: estágios semânticos
  fora do plano (3: inspeção, extração, enriquecimento), métodos de plano que
  computam localmente (14 de 25, ADR-0028), agentes operacionais ainda no
  core.
- Trabalho decorrente, acompanhado na #735:
  - Toolbox: servir fragmentos PDDL por capacidade e por versão, gerados a
    partir de um snapshot do catálogo (REST e recursos MCP).
  - core: compor o domínio a partir desses fragmentos; a verificação de
    política do limite de páginas; a extensão do journal e o registro de
    resultados aplicados.
- Conformidade: as fixtures de planejamento no CI; um teste do orquestrador
  que verifica que todo passo de um job vem do plano;
  `tests/test_architecture_layers.py` para clientes de modelo no core.
