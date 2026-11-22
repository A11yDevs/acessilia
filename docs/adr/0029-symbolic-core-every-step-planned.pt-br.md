# 0029. Um core simbólico: todo passo do processamento é planejado

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

A Toolbox já publica o lado semântico das suas capacidades: predicados, ações
por capacidade e fragmentos de domínio (`/planning/domain-fragments`, recursos
MCP `acessilia://...`; ver `docs/pddl.md` da Toolbox). Ela não é dona do
planejamento. A #632 (PR 2) proíbe um compilador genérico MCP → PDDL, e a #640
trata a composição de fragmentos como experimental.

## Decisão

### Todo passo é uma ação

- Todo passo de um job (inspeção, limite de páginas, extração, enriquecimento,
  fusão, ordenação, julgamento, exportação) deve ser uma ação do domínio de
  planejamento. O orquestrador não pode rodar uma sequência fixa de estágios.
- Uma ação operacional deve estar ligada a uma capacidade da Toolbox, por id e
  versão exata, invocada pelo cliente genérico (ADR-0027). As demais ações são
  só simbólicas: registrar estado, `human-review`, concluir o job.

### O domínio é composto de fragmentos versionados

- O domínio efetivo é formado pelas ações de workflow do core mais os
  fragmentos PDDL que a Toolbox publica para as capacidades do snapshot do
  catálogo.
- Os fragmentos são curados e versionados junto com sua capacidade. A
  composição verifica nomes e tipos; não traduz schemas de tools em PDDL (sem
  compilador genérico, #632).
- O CI deve fazer o parsing do domínio composto e resolver um conjunto de
  problemas de fixture com o planejador interno e o Fast Downward.

### Estado, disponibilidade e falha

- O problema é compilado a partir do estado observado: os fatos do manifesto,
  as obrigações, os resultados já registrados e um snapshot do catálogo.
- A disponibilidade de capacidades e providers são predicados do problema. O
  `toolbox_gate` fica reduzido a relatório.
- Um problema insolúvel é um resultado explícito: o job falha com a causa, ou
  uma ação `human-review` é planejada. Nunca é uma degradação silenciosa.
- Um resultado de capacidade atualiza o estado simbólico uma vez por
  `operation_id`, pelo journal da ADR-0020. Um resultado duplicado ou atrasado
  é ignorado.
- O replanejamento continua no core e continua limitado.

### Decisões são simbólicas; modelos são capacidades

- O core decide só por planejamento e políticas simbólicas.
- Chamadas a modelos são capacidades (o VLM já passa pela Toolbox, ADR-0012).
  Suas saídas são observações às quais o plano reage.
- Os agentes de `acessilia_core.agents` são migrados para capacidades da
  Toolbox ou para ações de adjudicação cujo resultado é observado.

### Planejador e coordenação são separados

- Uma interface `PlanningEngine` (#632, PR 3) separa o planejador da
  coordenação do workflow. O planejador interno e o Fast Downward continuam
  intercambiáveis atrás dela, e a comparação entre eles continua rodando.

## Consequências

- O plano explica o job inteiro; disponibilidade, alternativas e becos sem
  saída vêm do domínio, e não de caminhos no código. Esse é o baseline
  simbólico para a #619.
- O domínio cresce com o catálogo. A curadoria dos fragmentos, os custos das
  ações e as fixtures de planejamento no CI o mantêm tratável.
- A migração é incremental e segue a ADR-0028, método a método. Depois os
  quatro estágios fixos viram ações, e depois os agentes viram capacidades ou
  ações de adjudicação. O ciclo fechado não espera pelas filas duráveis
  (#639): chamadas MCP síncronas bastam.
- Os indicadores de progresso são acompanhados na #735: estágios fora do plano
  (4), métodos sem vínculo com capacidade (cerca de 20 de 25), agentes no core.
- Conformidade: as fixtures de planejamento no CI; um teste do orquestrador
  que verifica que todo passo de um job vem do plano;
  `tests/test_architecture_layers.py` para clientes de modelo no core.
