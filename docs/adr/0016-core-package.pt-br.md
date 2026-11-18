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
    (`backend/core/pipeline/`, para onde o passo 6 da #402 os moveu a partir
    do `backend/agents/pddl_orchestrator.py`);
  - os agentes (`backend/agents`, `backend/ai`, `backend/core/agents`);
  - a fusão dupla (`backend/core/pipeline/fusion.py`, que o passo 2 reuniu a partir
    do `backend/pipeline`) e os exportadores (`backend/core/export`, que o passo 2 reuniu a partir do
    `backend/export`; os envelopes
    sem uso de `backend/adapters` foram removidos no passo 2);
  - os adaptadores da Toolbox (`backend/core/toolbox`, com os auxiliares
    `backend/core/logger.py` e `backend/core/formula_tools.py`; o passo 2 os reuniu a
    partir do `backend/tools`);
  - as mensagens (`backend/core/i18n`, com o `log_messages`, o `stage_messages` e os
    catálogos, que o passo 2 reuniu a partir de `backend/i18n.py`,
    `backend/log_messages.py`, `backend/stage_messages.py` e `backend/locales`).
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
- **As outras bibliotecas que o core importa**, contadas com uma varredura de
  AST que inclui os imports dentro de funções:
  - pydantic e loguru;
  - Babel (`backend/core/i18n/__init__.py`);
  - jsonschema (`backend/core/manifest/schema.py`);
  - rapidfuzz (`backend/core/pipeline/fusion.py`);
  - edge-tts (`backend/core/export/exporters/audio_exporter.py`). É o executor
    local que a [ADR-0003](0003-remote-only-operational-capabilities.pt-br.md)
    registra como desvio conhecido
    ([acessilia-toolbox#73](https://github.com/A11yDevs/acessilia-toolbox/issues/73)).
- **O core importa o frontend.** O `backend/core/planning/models.py` e o
  `backend/core/execution/models.py` pegam descrições de schema e mensagens de
  validação de `frontend.telegram.messages`. Sem o `frontend` instalado, os
  dois levantam `ImportError`. (Resolvido no passo 2: essas mensagens agora
  ficam em `backend/core/planning/messages.py` e `backend/core/execution/messages.py`.)
- **O core chega ao serviço em dois pontos.**
  - `backend.config`: 34 imports, e 59 chaves diferentes do `settings` lidas
    em 107 pontos. Só o orquestrador lê 12 chaves, e os exportadores, 3.
  - `backend.services`, em quatro imports, vindos de três lugares:
    - `run_blocking` (`blocking.py`; passou para o core no passo 4);
    - o cache de regiões da visão (`get_cached_bytes`, `set_cache_bytes`,
      `options_cache_key`; no passo 4 o core o recebe como porta, e o
      `options_cache_key` passou para o core);
    - `processing_cache_configuration` e `_file_hash`, lidos pelo payload e
      pelo extrator da Toolbox (no passo 3 o core deixou de importar esses
      dois, que ficam no serviço: ele monta as suas identidades em
      `backend/core/run_identity.py`, #544).

    Imports acrescentados depois deste inventário: os checkpoints do job
    (`job_checkpoint`) e o id do job (`operation_context`) no orquestrador,
    que passam pela porta `JobCheckpoints` no passo 4, e o registro de
    operações remotas (`operation_registry`, `operation_context`) no extrator
    da Toolbox, que passa pela porta `RemoteOperations` no passo 4. Desde
    então o core não importa nada de `backend.services`, o que o
    `tests/test_run_ports.py` confere.
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
3. **Colocar o core no SDK.** Rejeitada. O SDK não toma decisões (ADR-0002).
   A [ADR-0017](0017-operational-sdk-and-agentic-core.pt-br.md) o amplia do
   transporte para operações determinísticas, mas não para decisões. A
   instalação-base dele continua leve: o `httpx`, e o docstruct quando ele
   compuser algoritmos do docstruct (garantido pelo
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
    ports.py       # protocolos que o serviço implementa: caches, checkpoints, operações
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
  | `backend/core/pipeline` (o orquestrador era `backend/agents/pddl_orchestrator.py` até o passo 6 da #402 movê-lo; o `backend/pipeline` se reuniu ali no passo 2) | `acessilia_core.pipeline` |
  | `backend/core/agents` (reunidos no passo 2 a partir de `backend/agents/{vision_agent,data_agent,output_schemas,provider_breaker,run_helpers}.py`, do `backend/ai` e do `backend/core/agno_support.py`, com a carga de prompts do `backend/tools`) | `acessilia_core.agents` |
  | `backend/core/toolbox`, `backend/core/logger.py`, `backend/core/formula_tools.py` (reunidos a partir do `backend/tools` no passo 2; a carga de prompts foi com os agentes) | `acessilia_core.toolbox` e auxiliares |
  | `backend/core/export` (reunido a partir do `backend/export` no passo 2; o `backend/adapters`, sem uso, foi removido) | `acessilia_core.export` |
  | `backend/core/i18n` (reunido no passo 2 a partir de `backend/i18n.py`, `log_messages.py`, `stage_messages.py` e `locales/`) | `acessilia_core.i18n` |

- **O que fica no `backend/`, o serviço:**
  - a API e o worker;
  - os jobs, a fila, o histórico, o e-mail, os tokens de download e a limpeza;
  - os caches, que implementam os `ports` do core;
  - o estado do job (`state_manager`);
  - o filtro de log de acesso e a validação de upload (`backend/services`, vindos
    do `backend/tools` no passo 2, com os nomes de arquivo de saída);
  - o `config/settings.py`, que lê o ambiente e monta o `CoreConfig`.
- **Direção das dependências:**

  ```text
  backend (serviço) ──▶ acessilia_core ──▶ SDK ──▶ docstruct
                              └────────────────▶ docstruct
  ```

  - O `acessilia_core` pode importar a biblioteca padrão, o SDK, o docstruct, o
    Agno, o pydantic, o loguru, o Babel, o jsonschema e o rapidfuzz. São as
    bibliotecas que ele importa hoje.
  - O edge-tts é permitido só como o desvio que a ADR-0003 registra. Ele sai
    quando a exportação de áudio virar uma capacidade da Toolbox. A mudança
    neutra não o substitui, nem a nenhuma outra implementação.
  - Não pode importar o `backend`, o `frontend` nem o FastAPI, e não pode ler
    o ambiente.
  - O SDK e o docstruct não podem importá-lo.
- **A configuração é explícita.** O core recebe um `CoreConfig` montado por
  quem o chama. O serviço o monta a partir do seu ambiente, como já monta o
  `ToolboxClientConfig` do SDK.
- **O estado do serviço é injetado.** O cache de regiões, os checkpoints do
  job e o registro de operações remotas chegam a cada execução num único
  objeto `RunPorts`, cujos membros seguem os protocolos de
  `acessilia_core.ports`; o serviço o monta para o job. O core não é dono do
  armazenamento do serviço. O cache de processamento é só do serviço: ele
  envolve a execução, e o core só lhe dá a identidade da execução
  (`run_identity`). O `run_blocking`, um auxiliar sem estado feito só com a
  biblioteca padrão, pertence ao core, e o serviço o importa de lá (emenda
  do passo 4).
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
     | `backend/pipeline` | `backend/core/pipeline/` (feito) | |
     | `backend/agents/{vision_agent,data_agent,output_schemas,provider_breaker,run_helpers}.py`, `backend/ai`, `backend/core/agents`, `backend/core/agno_support.py` | `backend/core/agents/` (feito: o `ai_client`, o `agno_support` e o `prompt_tools` com eles) | `backend/ai/prompts/` (10 prompts) → `backend/core/agents/prompts/` (feito) |
     | `backend/tools` (adaptadores da Toolbox, ferramentas de fórmula e de código, carga de prompts, logger) | `backend/core/toolbox/` e auxiliares (feito: os adaptadores para `backend/core/toolbox/`, `logger` e `formula_tools` para `backend/core/`, o `validators`, o `access_log_filter` e o `filenames` do serviço para `backend/services/`; o `code_tools`, morto, foi removido; o `prompt_tools` foi com os agentes) | |
     | `backend/export` (`backend/adapters`: removido, nada o importava) | `backend/core/export/` (feito) | |
     | `backend/i18n.py`, `log_messages.py`, `stage_messages.py` | `backend/core/i18n/` (feito) | `backend/locales/` (os catálogos `.po`) → `backend/core/i18n/locales/` |

     O estado do job (`backend/agents/state_manager.py`) fica no serviço.

     As mensagens que o core pega de `frontend.telegram.messages` (as
     descrições de schema e as mensagens de validação de `planning/models.py`
     e `execution/models.py`) vão para as mensagens do core no mesmo passo. Se
     o frontend ainda as usar, passa a importá-las do core. Feito: os 18 msgids
     foram para o `planning/messages.py` e o `execution/messages.py`, e o
     frontend não os usava.

     **As operações que podem ir para o SDK ficam onde estão** até que a
     [ADR-0017](0017-operational-sdk-and-agentic-core.pt-br.md) decida a
     divisão delas em mecanismo (SDK) e política (core), para que não mudem
     de lugar duas vezes. São o juiz de página, os adaptadores da Toolbox do core
     (então em `backend/tools`, hoje em `backend/core/toolbox`) e a cadeia de fórmula (a ligação do core com o render não
     fica retida; veja a ADR-0017); o
     [inventário da #470](../architecture/operational-boundaries-inventory.pt-br.md)
     os lista. O que ficar no core depois da divisão (a política, e a ligação
     do `CoreConfig` aos parâmetros de cada operação) se reúne aqui em
     seguida. A ADR-0017 foi aceita em 2026-11-13: a política da cadeia de
     fórmula foi para o `backend/core/pipeline/` (#513, #515), e o juiz de
     página foi para lá inteiro, com a divisão com o SDK deixada para depois. Os adaptadores
     da Toolbox foram inteiros para o `backend/core/toolbox/` no passo 2, também
     com a divisão com o SDK deixada para depois.
  3. As leituras do `settings` são trocadas pelo `CoreConfig`, uma etapa por
     vez. Feito: o `backend/core/config.py` define o `CoreConfig` como
     grupos congelados (Toolbox, modelos, visão, fusão, documento, exportação,
     caminhos), o serviço o monta em `backend/config/core_config.py`, e o
     orquestrador monta um por execução até que cada etapa receba o seu grupo.
     Já passou para ele o grupo `document` (primeiro o limite de páginas,
     depois a matemática inline, o reparo de Unicode legado, as opções de
     slides e o limiar de concordância das fórmulas), o grupo `export`, que o
     worker captura uma vez por job e passa aos exportadores, o grupo
     `fusion` e o grupo `vision` (a concorrência das etapas, o limiar do
     disjuntor, a espera da nova tentativa, a revisão de tabelas e o cache
     de regiões, além do DPI da inspeção de páginas). O grupo `toolbox`
     passa em três pull requests: o gate de planejamento e o seu catálogo
     (feito; o cache do catálogo é compartilhado pelas execuções com o mesmo
     endpoint, chave e tempos), depois as chaves de ativação e as opções do
     extrator (feito: inspeção de mídia, validação de PDF, cache remoto,
     armazenamento de artefatos, timeout da extração e os providers primário
     e de matemática; cada função que chama a fábrica de clientes recebe a
     `ToolboxConfig` da execução), depois a fábrica de clientes e quem a
     chama (feito: `make_toolbox_client(cls, toolbox)`). O grupo `models`
     também foi feito: `get_agno_model(models, toolbox)` e
     `active_model_name(models)`, e o `VisionAgent` e o `DataAgent` recebem a
     `ModelConfig` da execução, dada pelas etapas e pelos handlers de
     inspeção. O grupo `paths` fecha os grupos: a evidência de fusão do
     extrator e os artefatos dos handlers de fusão e de inspeção são gravados
     no `PathsConfig.data_dir` da execução, então o core não lê nenhuma
     configuração de uma execução; e os grupos de configuração estão feitos.
     Depois, uma execução exige a sua config e o seu runner de chamadas de
     modelo (`execute(..., config=, model_calls=)`, e `ports=` desde o passo
     4), o serviço monta uma config
     por job e as exportações e a auditoria do worker a reutilizam, e as
     ferramentas Agno sem execução recebem a config com que o agente foi
     construído: as pontes saíram. Em seguida, a chave do cache de
     processamento e o reaproveitamento da fusão passam a ser montados a partir
     da config da execução (#544): o `backend/core/run_identity.py` classifica
     cada campo do `CoreConfig` como parte ou não da identidade do documento
     processado, e o serviço acrescenta as suas opções. Por último, a preparação do
     processo é passada no início dele: o
     `backend/config/process_setup.py::setup_process` dá ao logger o
     `LOG_LEVEL` e o `LOGS_DIR`, e aos catálogos o `I18N_LOCALES_ACTIVE`
     (`i18n.configure_locales`), então o `backend/core` não lê nenhuma
     configuração nem importa nada de `backend.config`, o que o
     `tests/test_core_config.py` confere. Os handlers de método que leem a config declaram um parâmetro
     `config` (os handlers de fusão de dois providers e de provider único, os
     de inspeção de região e de página, os de fórmula, `mathml` e
     `latex-verbalizer`, e o do juiz VLM), e cada execução vincula a sua config
     a eles (`bind_run`) numa cópia do registro.
  4. Os caches e o `run_blocking` passam a ser injetados pelos `ports`.
     Feito, em três pull requests:
     - **O cache de regiões e o `run_blocking` (feito).** O
       `backend/core/ports.py` define o `RegionCache` e o `RunPorts`, com um
       no-op para execuções fora do serviço (`RunPorts.none()`). O
       `execute(..., ports=)` é obrigatório, como `config` e `model_calls`. As
       etapas recebem o cache de regiões da execução, ou `None` quando a config
       o desliga, e os handlers que declaram `ports` os recebem (`bind_run`,
       que substitui o `bind_config`). O serviço implementa a porta sobre o seu
       cache em arquivos (`ContentCache`). O `run_blocking` e o
       `options_cache_key` passaram para o core.
     - **Os checkpoints do job e o id do job (feito).** O
       `RunPorts.checkpoints` é o `JobCheckpoints` do job (`load`, `save`,
       `remove` por fase, e o `job_id` para o log), ou `None` fora de um job,
       que não grava nem retoma nada. Os nomes das fases são do core
       (`CHECKPOINT_PHASES`). O serviço vincula o `FileJobCheckpoints` ao id
       da tarefa do job, e o orquestrador não lê mais o id do job.
     - **O registro de operações remotas (feito).** O `RunPorts.operations`
       é o `RemoteOperations` do job (`begin` de uma chamada de um
       `OperationKind`, `finish` dela, e o `job_id` que a rotula), ou `None`
       fora de um job, cujas chamadas não são registradas nem rotuladas. A
       execução o passa ao extrator; o serviço vincula o `JobOperations` ao id
       da tarefa. O core e o serviço não leem mais o id do job da variável de
       contexto do serviço, então o `backend/services/operation_context.py`
       (`task_context`, `current_task_id`) saiu. O SDK mantém a sua: o
       extrator abre o `operation_context(job_id, operation_id)` em volta de
       cada chamada, e os clientes a leem por `current_operation()` para
       enviar os cabeçalhos da ADR-0019.

     O core não importa nada de `backend.services`, incluindo os imports
     dentro de funções, o que o `tests/test_run_ports.py` confere.
  5. **Um teste de fronteira** confere o `backend/core/`, incluindo os imports
     dentro de funções:
     - ele não importa nada do `backend` fora do `backend/core`, nem nada do
       `frontend`;
     - os outros imports são só as bibliotecas permitidas acima, com o
       edge-tts na allowlist do teste e uma referência à acessilia-toolbox#73;
     - ele não lê variáveis de ambiente.

     Ele precisa passar antes da extração. Feito: o
     `tests/test_core_boundary.py` confere as três regras, impede que a
     allowlist de bibliotecas cresça (uma biblioteca que o core deixa de
     importar sai dela), restringe o edge-tts ao exportador de áudio e
     confere que o SDK e o docstruct não importam o core. A varredura segue
     apelidos (`import os as o`) e pega `expanduser`/`expandvars` em qualquer
     receptor. Restavam duas leituras do ambiente, e as duas saíram:
     - o locale do servidor, que o `t()` negociava a partir de `LOCALE`,
       `LANGUAGE`, `LC_ALL` e `LANG` a cada chamada. Agora o serviço o
       negocia uma vez na inicialização (`setup_process`, com a
       `negotiate_server_locale`) e o passa aos catálogos
       (`configure_server_locale`). Um processo que não faz essa preparação
       usa `en_US`;
     - o `expanduser` (`HOME`) nos caminhos do sandbox do planejador, por
       onde um caminho da home não passaria de qualquer jeito.

     O `tempfile` respeita o `TMPDIR` dentro da biblioteca padrão; isso não
     é o core lendo o seu ambiente, então o teste o permite.
  6. **A extração**, em três pull requests:
     - **Recursos preparados no lugar (feito).** Dois recursos eram
       localizados pelo caminho do próprio módulo, o que um pacote instalado
       quebra. Os catálogos de tradução compilavam o `messages.mo` ao lado
       dos `.po` na importação, e um pacote somente leitura deixava toda
       mensagem em inglês: agora eles são compilados em memória, no primeiro
       uso. O sandbox do planejador era `<repo>/temp/pddl-sandbox`, quatro
       pastas acima do módulo: o `PlannerAgent(sandbox_dir=)` agora o recebe
       de quem o chama (`PathsConfig.data_dir / "pddl-sandbox"`), e as suas
       ferramentas de arquivo se recusam a rodar sem ele. O `plan` e o
       `compare`, que o pipeline chama, trabalham em memória e não precisam
       dele.
     - **A mudança e a renomeação dos imports (feito).** O `backend/core`
       agora é o pacote `acessilia_core` em `libs/core/src/acessilia_core`
       (`libs/core/pyproject.toml`, versão 0.1.0), instalado editável como o
       SDK e o docstruct, e todo import de `backend.core` virou
       `acessilia_core`, sem ponte. Os passos acima citam o `backend/core`
       como ele era quando foram feitos. O teste de fronteira agora varre o
       pacote, que pode importar a si mesmo mas nada do `backend`; as
       guardas que varriam o `backend/` varrem o pacote também, e o teste de
       pureza do SDK e os jobs de CI de isolamento das duas bibliotecas
       também recusam o `acessilia_core`.
     - **A instalação limpa, o seu teste de fumaça e a prova de conceito
       (feito).** O job de CI `core-isolated` instala o `libs/core` a partir
       do seu próprio lock, como wheel, confere que nem o serviço, nem os
       front-ends, nem o FastAPI podem ser importados, roda o teste de
       fronteira sobre o código-fonte e roda o
       `libs/core/tests/test_smoke.py` a partir de uma pasta fora do
       checkout: ele carrega o domínio PDDL, todo arquivo de prompt que os
       carregadores citam e os dois catálogos, e planeja e executa um
       manifesto de fixture (dry run). Cada tipo de dado do pacote deixado
       fora da wheel o faz falhar. A prova de conceito é o
       `libs/core/examples/table_stage.py`: a etapa de estrutura de tabelas
       roda com um `CoreConfig` explícito e um runner de chamadas de modelo
       do próprio script, também nesse job, onde o serviço não está
       instalado; o `tests/test_core_standalone_table_stage.py` confere que
       ela devolve o mesmo manifesto que o serviço para a mesma entrada e não
       carrega nem o `backend` nem o FastAPI.

     Os testes ficam em `tests/`; só o teste de fronteira e o de fumaça vão
     para `libs/core/tests`. Quando os três estiverem feitos:

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
    API pública do SDK" (ADR B da #402, hoje a
    [ADR-0018](0018-core-uses-sdk-public-api.pt-br.md)) é conferida sobre
    `backend/`, `scripts/` e `tests/` hoje, e vale na fronteira do pacote depois
    da extração.
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
  - os módulos do core continuam dentro do `backend/`;
  - a exportação de áudio continua sintetizando localmente com o edge-tts até
    a acessilia-toolbox#73 (ADR-0003).
- **Conformidade:**
  - antes da extração, o teste de fronteira do passo 5;
  - depois dela, um teste de que o `acessilia_core` não importa nada do
    `backend` nem do `frontend`, importa só as bibliotecas permitidas e não lê
    variáveis de ambiente;
  - o job de instalação isolada, com o smoke de planejamento e execução
    (passo 6).

  Até lá, o passo 6 é conferido pelo limite de tamanho de módulo (decisão D4
  do inventário).
