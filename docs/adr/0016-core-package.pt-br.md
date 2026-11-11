# 0016. O core como um pacote próprio, `acessilia_core`

Também disponível em **inglês (EUA)**: [English version](0016-core-package.md)

- **Status:** Proposto
- **Data:** 2026-11-11
- **Componentes:** core
- **Issues:** [#402](https://github.com/A11yDevs/acessilia/issues/402), [#365](https://github.com/A11yDevs/acessilia/issues/365)

## Contexto

A [ADR-0002](0002-component-responsibilities.pt-br.md) nomeia quatro
componentes: o core, o SDK, o docstruct e a Toolbox. O core é o que decide:
política, fluxo, planos e o que um job entrega. No código, porém, o core não é
um componente próprio. Ele está espalhado por `backend/`, ao lado do serviço
que o executa. O `backend/` mistura duas coisas que mudam por motivos
diferentes:

- **O core**:
  - o manifesto, o planejamento e a execução (`backend/core`);
  - o orquestrador PDDL, com seus handlers e etapas de enriquecimento
    (`backend/agents/pddl_orchestrator.py`);
  - os agentes (`backend/agents`, `backend/ai`, `backend/core/agents`);
  - a fusão dupla (`backend/pipeline`) e os exportadores (`backend/export`,
    `backend/adapters`);
  - os adaptadores da Toolbox (`backend/tools`);
  - as mensagens (`backend/i18n`, `log_messages`, `stage_messages`).
- **O serviço em volta dele**: a API e o worker (`backend/api`, FastAPI), os
  jobs, o histórico, o e-mail, os tokens de download e os caches
  (`backend/services`), o estado do job (`backend/agents/state_manager.py`) e
  a configuração do ambiente (`backend/config`).

A única forma de rodar o core é por dentro do `backend`, então um benchmark,
um script ou outro front-end carrega o serviço inteiro. O SDK já permite que um
script chegue à Toolbox sem o core (#402, fase 1). Nada permite rodar o core
sem o serviço.

Medido na develop em fd7f7152, sobre os módulos listados acima como core
(cerca de 18 mil linhas):

- **O FastAPI já está do lado do serviço.** Ele é importado só em
  `backend/api`, no topo do módulo ou dentro de uma função.
- **O Agno está no core, não só nos seus agentes.**
  - No topo do módulo: três arquivos de `backend/agents` (`vision_agent.py`,
    `data_agent.py`, `output_schemas.py`).
  - Dentro de funções:
    - `backend/core/agno_support.py` importa `agno.agent`, `agno.tools` e
      `agno.workflow`; o executor, o planejador e os seis agentes de
      `backend/core/agents` o usam;
    - `backend/ai/models/ai_client.py` importa as três classes de modelo do
      Agno.
  - **Planejar e executar precisam do Agno em tempo de execução.** O
    `ExecutorAgent.execute` sempre monta um workflow do Agno
    (`build_workflow`), e o `require_workflow_classes` levanta `RuntimeError`
    quando o Agno falta, mesmo para um plano sem passos.
- **O core chega ao serviço em dois pontos.**
  - `backend.config`: 34 imports, e 59 chaves diferentes do `settings` lidas
    em 107 pontos. Só o orquestrador lê 12 chaves, e os exportadores, 3.
  - `backend.services`, em quatro imports, vindos de três lugares:
    - `run_blocking` (`blocking.py`);
    - o cache de regiões da visão (`get_cached_bytes`, `set_cache_bytes`,
      `options_cache_key`);
    - `processing_cache_configuration` e `_file_hash`, lidos pelo payload e
      pelo extrator da Toolbox.
- **O serviço chega ao core** por `backend/service.py`
  (`PddlAccessibilityOrchestrator`), por `backend/api/worker.py` (os
  exportadores) e pela API e pelos serviços (as mensagens e as ferramentas).
- **Tamanho.** O `pddl_orchestrator.py` tem 5.770 linhas (5.823 com a #466), e
  o `backend/core/manifest/builder.py`, 1.205. O passo 6 da fase 3 da #402
  reorganiza o orquestrador em módulos, que é o momento de escolher onde eles
  ficam.

Opções consideradas:

1. **Reorganizar no lugar**, dentro do `backend/`. O código fica organizado,
   mas o acoplamento com o ambiente continua implícito, e todo uso do core
   continua carregando o serviço.
2. **O core como um pacote próprio** (`libs/core`, `acessilia_core`), do qual o
   serviço depende. A configuração é passada de forma explícita, como o SDK
   recebe o `ToolboxClientConfig`.
3. **Colocar o core no SDK.** Rejeitada. O SDK é transporte, tem o `httpx` como
   única dependência e não toma decisões (ADR-0002; garantido pelo
   `libs/sdk/tests/test_purity.py` e pelo job isolado do SDK). O core decide, e
   depende do Agno.
4. **Dividir o repositório** em um repositório do serviço e um do core. Vai
   além do que o problema pede; a opção 2 pode levar a isso depois.

## Decisão

Proposta: a opção 2.

- **O core é um pacote, `acessilia_core`, em `libs/core`.** A estrutura:

  ```text
  libs/core/src/acessilia_core/
    config.py      # CoreConfig: a configuração do core, explícita
    ports.py       # protocolos que o serviço implementa: caches, chamadas bloqueantes
    manifest/      # modelos, schema, builder, extrator da Toolbox, slides
    planning/      # domínio, planejador, processador PDDL, porta da Toolbox, comparação
    execution/     # executor, modelos, mensagens
    pipeline/      # orquestrador, pré-voo, payload, enrichment/, handlers/,
                   #   fusão, construtor canônico
    agents/        # visão, dados e os outros agentes do core, seus schemas,
                   #   o disjuntor de provider e a fábrica do modelo
    toolbox/       # adaptadores sobre o SDK: cliente a partir do CoreConfig,
                   #   matemática, inspeção de mídia, text spans, render, juiz
    export/        # exportadores e renderizadores
    i18n/          # t(), os catálogos, as mensagens de log e de etapa
  ```

  | Hoje | Vai para |
  |---|---|
  | `backend/core/{manifest,planning,execution}` | `acessilia_core.{manifest,planning,execution}` |
  | `backend/agents/pddl_orchestrator.py`, `backend/pipeline` | `acessilia_core.pipeline` |
  | `backend/agents/{vision_agent,data_agent,output_schemas,provider_breaker,run_helpers}.py`, `backend/ai`, `backend/core/agents` | `acessilia_core.agents` |
  | `backend/tools` (os adaptadores da Toolbox, ferramentas de fórmula e de código, prompts, logger) | `acessilia_core.toolbox` e auxiliares |
  | `backend/export`, `backend/adapters` | `acessilia_core.export` |
  | `backend/i18n.py`, `log_messages.py`, `stage_messages.py`, `locales/` | `acessilia_core.i18n` |

- **O que fica no `backend/`, o serviço:**
  - a API e o worker;
  - os jobs, a fila, o histórico, o e-mail, os tokens de download e a limpeza;
  - os caches, que implementam os `ports` do core;
  - o estado do job (`state_manager`);
  - o filtro de log de acesso e a validação de upload;
  - o `config/settings.py`, que lê o ambiente e monta o `CoreConfig`.
- **Direção das dependências:**

  ```text
  backend (serviço) ──▶ acessilia_core ──▶ SDK ──▶ docstruct
                              └────────────────▶ docstruct
  ```

  - O `acessilia_core` pode importar o SDK, o docstruct, o Agno, o pydantic e o
    loguru.
  - Não pode importar o `backend` nem o FastAPI, e não pode ler o ambiente.
  - O SDK e o docstruct não podem importá-lo.
- **A configuração é explícita.** O core recebe um `CoreConfig` montado por
  quem o chama. O serviço o monta a partir do seu ambiente, como já monta o
  `ToolboxClientConfig` do SDK.
- **O estado do serviço é injetado.** Os caches de regiões e de processamento,
  e a forma de rodar chamadas bloqueantes, chegam ao core como argumentos que
  seguem os protocolos de `acessilia_core.ports`. O core não é dono do
  armazenamento do serviço.
- **O Agno é uma dependência obrigatória**, por enquanto. Os agentes
  precisam dele, e o planejamento e a execução também: o executor roda todo
  plano como um workflow do Agno. Tornar o Agno opcional exigiria mais do que
  levar os agentes para um pacote próprio: a execução precisaria de um caminho
  que não monta o workflow. Isso fica para depois.
- **A mudança é gradual e neutra**, uma responsabilidade por pull request, como
  na fase 3 da #402. Todos os módulos do core se reúnem antes em
  `backend/core/`, com a estrutura do pacote, para que a extração seja só uma
  troca de caminho. A extração vem por último:
  1. **O passo 6 da fase 3** reorganiza o orquestrador em
     `backend/core/pipeline/`, com a estrutura que o `acessilia_core.pipeline`
     terá (veja [o inventário](../architecture/pddl-orchestrator-inventory.pt-br.md)).
  2. **O resto do core se reúne em `backend/core/`**, um grupo por pull
     request. Cada recurso vai junto com o código que o carrega.

     | Hoje | Reúne-se em | Recursos que vão junto |
     |---|---|---|
     | `backend/core/{manifest,planning,execution}` | já está no lugar | `planning/domains/`: os domínios PDDL e suas descrições |
     | `backend/pipeline` | `backend/core/pipeline/` | |
     | `backend/agents/{vision_agent,data_agent,output_schemas,provider_breaker,run_helpers}.py`, `backend/ai`, `backend/core/agents`, `backend/core/agno_support.py` | `backend/core/agents/` | `backend/ai/prompts/` (10 prompts) → `backend/core/agents/prompts/` |
     | `backend/tools` (adaptadores da Toolbox, ferramentas de fórmula e de código, carga de prompts, logger) | `backend/core/toolbox/` e auxiliares | |
     | `backend/export`, `backend/adapters` | `backend/core/export/` | |
     | `backend/i18n.py`, `log_messages.py`, `stage_messages.py` | `backend/core/i18n/` | `backend/locales/` (os catálogos `.po`) → `backend/core/i18n/locales/` |

     O estado do job (`backend/agents/state_manager.py`) fica no serviço.
  3. As leituras do `settings` são trocadas pelo `CoreConfig`, uma etapa por
     vez.
  4. Os caches e o `run_blocking` passam a ser injetados pelos `ports`.
  5. **Um teste de fronteira** confere o `backend/core/`: ele não importa nada
     do `backend` fora do `backend/core`, nem nada além do SDK, do docstruct,
     do Agno, do pydantic, do loguru e da biblioteca padrão; e não lê
     variáveis de ambiente. Ele precisa passar antes da extração.
  6. **A extração:**
     - os módulos vão para `libs/core`, e o `backend/core` some;
     - os domínios PDDL, os prompts e os catálogos são declarados como dados
       do pacote;
     - um job de CI instala o pacote em um ambiente limpo, fora do checkout, e
       roda um smoke a partir dali: ele planeja e executa um manifesto de
       fixture (dry run), carregando o domínio PDDL, um prompt e os dois
       catálogos. Só importar os módulos não carregaria esses recursos.
- **Evidência para aceitar esta ADR:** uma prova de conceito em que uma etapa
  de enriquecimento (por exemplo, a das estruturas de tabela) roda a partir de
  um script com um `CoreConfig` explícito, sem importar o FastAPI nem o
  `backend.config`, e devolve o mesmo manifesto que o serviço para a mesma
  entrada.

## Consequências

- **Fica mais fácil:**
  - benchmarks e scripts rodam o core inteiro sem o serviço;
  - o serviço fica só com a entrega: a API, os jobs e os caches;
  - a fronteira do core vira uma dependência de pacote, que um teste confere,
    como o `libs/sdk/tests/test_purity.py` confere a do SDK;
  - os recursos que o core carrega (domínios PDDL, prompts, catálogos) ficam
    junto com o código que os carrega;
  - a palavra "core" das ADRs passa a nomear um pacote. "O core depende só da
    API pública do SDK" (ADR B da #402) passa a ser conferível na fronteira do
    pacote.
- **Fica mais difícil:**
  - cada etapa que lê o `settings` muda de assinatura (107 leituras);
  - os caminhos dos módulos que o serviço e os testes importam mudam duas
    vezes: ao se reunirem em `backend/core/` e na extração;
  - os testes que alteram atributos do `settings` passam a montar um
    `CoreConfig`;
  - o serviço depende dos catálogos de mensagens do core, já que a API também
    os usa;
  - até o passo 4, "o core" na documentação designa tanto o futuro pacote
    quanto a pasta `backend/core`.
- **Desvios que permanecem** até que os passos acima terminem:
  - o core continua lendo o `settings`;
  - os caches continuam em `backend/services`;
  - os módulos do core continuam dentro do `backend/`.
- **Conformidade:**
  - antes da extração, o teste de fronteira do passo 5;
  - depois dela, um teste de que o `acessilia_core` não importa nada do
    `backend` e não lê variáveis de ambiente;
  - o job de instalação isolada, com o smoke de planejamento e execução
    (passo 6).

  Até lá, o passo 6 é conferido pelo limite de tamanho de módulo (decisão D4
  do inventário).
