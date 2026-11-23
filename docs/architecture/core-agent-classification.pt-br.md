# Classificação: os agentes do Core (#735 fase 4, ADR-0029)

Inglês, versão normativa: [English version](core-agent-classification.md)

A [ADR-0029](../adr/0029-symbolic-core-every-step-planned.pt-br.md) separa um
Core agêntico de uma Toolbox passiva:

> **O Core é agêntico e ativo**: raciocina, planeja, delega, coordena,
> avalia e replaneja. **A Toolbox é operacional e passiva**: executa as
> capacidades que lhe pedem e devolve resultados, sem autonomia agêntica e
> sem responsabilidade por decisões de workflow.

Toda autonomia agêntica está no Core. Seus agentes assumem um de três
**papéis** permanentes, distinguidos pelo escopo da sua autoridade, não pela
tecnologia que usam:

| Papel | Especializado em | Responsabilidade | Escopo de planejamento |
|---|---|---|---|
| estratégico | objetivos globais | Objetivos, políticas, prioridades, coordenação global, avaliação dos resultados globais, a decisão de replanejar, a futura integração LLM + planejamento (#619) | o plano global |
| gerencial | domínio | Um objetivo delegado: sua decomposição, um subplano de domínio, delegar tarefas a agentes operacionais ou invocar capacidades diretamente, avaliação, replanejamento dentro do domínio, escalada ([#774](https://github.com/A11yDevs/acessilia/issues/774)) | um subplano de domínio |
| operacional | tarefa | Uma tarefa logicamente atômica com as capacidades autorizadas: escolher entre alternativas, observar resultados, recuperar falhas locais, escalar ao seu gerente | um plano local delimitado |

Uma tarefa operacional é atômica logicamente, não computacionalmente: o
agente pode usar várias capacidades, mas não planeja um domínio, não cria
agentes nem delega subplanos. Não há um agente por capacidade: uma tarefa sem
decisões adaptativas relevantes é uma capacidade que o agente gerencial
invoca diretamente.

Cada módulo também tem um **ciclo de vida**: `active` (parte permanente do
Core), `legacy` (em decomposição: suas operações viram capacidades não
agênticas da Toolbox, e qualquer decisão que ele tenha fica no Core) ou
`deprecated` (em aposentadoria). Um papel operacional é permanente; um ciclo
de vida legado não é. Nenhum agente vai para a Toolbox (veja
[Decomposição antes da migração](#decomposição-antes-da-migração)).

Esta página classifica todos os módulos de
`libs/core/src/acessilia_core/agents/`
([#768](https://github.com/A11yDevs/acessilia/issues/768)). A classificação
fica como dados em
[`tests/fixtures/core_agent_classification.json`](../../tests/fixtures/core_agent_classification.json),
e `tests/test_architecture_layers.py` mantém o diretório, os dados e esta
página alinhados.

## Resumo

Medido em `develop` no `a1a68a7b`.

- **8 agentes: 0 estratégicos, 0 gerenciais, 8 operacionais, todos
  `legacy`.** Isso fecha o indicador "Agentes do Core classificados" da #735
  (8/8). Nenhum deles é um agente operacional no sentido permanente: executam
  ou encapsulam operações destinadas à Toolbox e não tomam decisões
  adaptativas próprias (veja [Decomposição antes da migração](#decomposição-antes-da-migração)).
- **O escopo é o pacote `acessilia_core.agents`, não todos os agentes do
  Core.** `PlannerAgent` (`planning/`) e `ExecutorAgent` (`execution/`) ficam
  fora dele. Pela função são estratégicos, e estão listados em
  [Onde estão as funções estratégicas](#onde-estão-as-funções-estratégicas).
  O papel gerencial, e um agente operacional permanente, ainda não têm
  instâncias; os papéis existem para que possam ser introduzidos (#774) sem
  mudar esta política.
- **As funções estratégicas não estão em `agents/`.** Planejamento,
  coordenação, avaliação de estado e replanejamento ficam em `planning/`,
  `execution/` e `pipeline/` (veja [Onde estão as funções estratégicas](#onde-estão-as-funções-estratégicas)).
  Elas ficam no Core, e nenhuma é um agente deste diretório.
- **Só dois agentes chamam um modelo:** `VisionAgent` e `DataAgent`. Com
  `AI_CLIENT=toolbox` (ADR-0012), a chamada em si já passa pela Toolbox; os
  prompts, a validação da resposta, as novas tentativas e o cache de regiões
  ainda rodam no Core.
- **Os envelopes Agno não rodam em produção.** Seis agentes envolvem métodos
  determinísticos (`process`, `process_*`) num agente Agno (`build_agent`).
  Nenhum código de produção executa esse agente (`.agent.run`); o pipeline
  chama os métodos diretamente.
- **Quatro agentes não têm chamador no pipeline.** `AdjudicationAgent`,
  `OrderAdjudicationAgent`, `PageLevelAgent` e `TableSpecialistAgent` vieram
  com o trabalho do Dr.DocBench (#125). Só seus testes unitários e
  `tests/test_docs_pr125.py` os usam.

## Agentes

| Módulo | Papel, ciclo de vida | O que faz | Chamado por (pipeline) | Chama modelo | Destino |
|---|---|---|---|---|---|
| `agents/vision_agent` | operacional, legacy | Descrição de imagens e regiões, inspeção de páginas e regiões, leitura de fórmulas | `pipeline/enrichment/pictures`, `pipeline/enrichment/formulas`, `pipeline/handlers/inspection` | sim | Sua inferência vira capacidades não agênticas (descrição de imagem, inspeção de região, leitura de fórmula), com prompts, validação, novas tentativas e cache. As decisões sobre o que descrever ou inspecionar, e se inspecionar de novo, ficam no Core |
| `agents/data_agent` | operacional, legacy | Extração validada de tabelas e fórmulas de uma região | `pipeline/enrichment/tables` | sim | Sua inferência vira uma capacidade não agêntica de extração de tabelas e fórmulas. Os orçamentos de releitura e de novas tentativas do estágio de tabelas ficam no Core |
| `agents/informational_structural` | operacional, legacy | Extrai o documento pela Toolbox, funde os provedores e monta o manifesto de processamento | `pipeline/orchestrator` | não (só o envelope Agno) | A extração já é uma chamada à Toolbox. A fusão local e a montagem do manifesto viram uma capacidade composta de extração. Derivar as obrigações fica no Core (veja abaixo) |
| `agents/fusion_agent` | operacional, legacy | Fusão, auditoria, classificação, verso, junção final, guarda contra repetição, normalização e ordem de leitura determinísticas (`process_*`) | `pipeline/handlers/common`, para os handlers dos métodos do plano | não (só o envelope Agno) | Cada `process_*` vira uma capacidade com o método do plano que o usa, como parte da migração do [inventário do Docstruct](docstruct-import-inventory.pt-br.md). Qual deles roda continua sendo escolha do plano |
| `agents/adjudication_agent` | operacional, legacy | Roteamento de páginas entre provedores, decisões a partir da transcrição do VLM, o juiz pareado, o oráculo | nenhum | não (só o envelope Agno) | Não migra até um método do plano precisar dele (veja [Ainda em aberto](#ainda-em-aberto)) |
| `agents/order_adjudication_agent` | operacional, legacy | Interpreta e completa uma ordem de leitura do VLM; tau de Kendall | nenhum | não (só o envelope Agno) | Idem |
| `agents/page_level_agent` | operacional, legacy | Fusão e seleção de páginas inteiras, concordância de páginas, upscale e orientação | nenhum | não (só o envelope Agno) | Idem |
| `agents/table_specialist_agent` | operacional, legacy | Gera, compara e adjudica candidatos de tabela | nenhum | não (só o envelope Agno) | Idem |

## Módulos de apoio

| Módulo | Papel, ciclo de vida | O que é | Usado por | Destino |
|---|---|---|---|---|
| `agents/model_call_policy` | operacional, legacy | A margem de prazo das chamadas de modelo de visão e de dados | `vision_agent`, `data_agent` | Sai com esses agentes |
| `agents/prompt_tools` | operacional, legacy | Carrega e monta os prompts de visão e de região (`agents/prompts/`) | `vision_agent`, `data_agent` | Sai com esses agentes, com os prompts |
| `agents/output_schemas` | operacional, legacy | Contratos de saída validados dos agentes de visão e de dados | os dois agentes, o enriquecimento e o handler de inspeção | Sai com esses agentes; o contrato do resultado que o Core lê fica como contrato de capacidade |
| `agents/run_helpers` | operacional, legacy | Lê o resultado de uma execução Agno | `output_schemas` | Sai com `output_schemas` |
| `agents/_tool_mixins` | operacional, legacy | Corpos compartilhados dos envelopes Agno de seleção de página e junção final | `adjudication_agent`, `page_level_agent`, `fusion_agent` | Sai com esses agentes |
| `agents/agno_support` | infraestrutura, active | Monta agentes Agno quando a pilha opcional está instalada | os agentes acima, `planning/planner_agent`, `execution/executor` | Fica: o planejador e o executor o usam |
| `agents/ai_client` | infraestrutura, active | O cliente de modelo de cada `AI_CLIENT` (Ollama, OpenRouter, o gateway da Toolbox) | `vision_agent`, `data_agent`, `backend/api/routes/health` | Fica enquanto o Core fizer chamadas de modelo (ADR-0012); um LLM estratégico (#619) precisa dele |
| `agents/model_calls` | infraestrutura, active | A porta de execução da aplicação para chamadas de modelo síncronas | `pipeline/orchestrator`, os dois agentes, `backend/services/model_calls` | Fica enquanto o Core fizer chamadas de modelo |
| `agents/provider_breaker` | infraestrutura, active | Para de chamar um provedor que falha pelo resto de um job | `pipeline/orchestrator`, enriquecimento | Fica: é uma preocupação de coordenação do job; quando as chamadas forem capacidades, ele as protege |

## Onde estão as funções estratégicas

Estas são as funções estratégicas que a ADR-0029 mantém no Core. Nenhuma delas
está em `agents/`:

| Função | Onde |
|---|---|
| Montar o problema de planejamento: as obrigações de que um documento precisa | `manifest/builder` (`_derive_processing_needs`, `inspect_document_needs`) |
| Planejar | `planning/planner_agent`, por trás de `planning/engine` (`PlanningEngine`, #744) |
| Disponibilidade de capacidades como restrição do planejamento | `planning/toolbox_gate` |
| Executar e observar o plano | `execution/executor` (`ExecutorAgent`) |
| Coordenação e replanejamento limitado | `pipeline/orchestrator` (`_replan_until_done`) |
| Avaliar o resultado: obrigações em aberto, as críticas bloqueiam a entrega | `pipeline/obligations` |

A montagem do manifesto mistura os dois lados: a extração e a fusão são
operacionais, enquanto derivar as obrigações define o problema de
planejamento e fica no Core. A migração do `InformationalStructuralAgent`
mantém essa linha.

## Decomposição antes da migração

Um componente legado não migra inteiro. Suas responsabilidades são
separadas antes:

| Responsabilidade | Destino |
|---|---|
| Objetivos e planejamento | Core estratégico |
| Subplanejamento e escolha de estratégia | Core gerencial |
| Avaliação semântica e decisão de replanejar | Core estratégico ou gerencial, no escopo que a detém |
| Inferência de modelos | Toolbox |
| Algoritmos determinísticos de processamento | Toolbox |
| Validação técnica e transformação de resultados | Toolbox |
| Contratos e transporte | Core SDK e contratos compartilhados |

Nos oito agentes de hoje, a separação já está limpa. As decisões ficam nos
seus chamadores no Core: quais figuras recebem descrição
(`pipeline/enrichment/pictures`), os orçamentos do estágio de tabelas
(`pipeline/enrichment/tables`), a inspeção como método do plano
(`pipeline/handlers/inspection`) e qual `process_*` um método do plano
executa. O que os agentes contêm é operacional e vira capacidades. Uma
migração futura verifica isso de novo: uma decisão encontrada dentro de um
agente fica no Core.

Decompor um componente legado não exclui um agente operacional. Se uma
tarefa passar a precisar de autonomia (escolher entre reconhecedores, julgar
um resultado, tentar de novo dentro de um orçamento), um agente operacional
permanente no Core pode assumi-la, usando as capacidades que a migração
produziu. Por exemplo, ao tornar uma fórmula acessível:

- o agente estratégico define a obrigação;
- um gerente de matemática a decompõe em reconhecimento, validação,
  adjudicação se necessária, e MathML;
- um agente de reconhecimento escolhe entre os reconhecedores autorizados,
  avalia o resultado e tenta de novo dentro do seu orçamento;
- a Toolbox executa o OCR matemático, o reconhecimento por VLM, a validação
  de LaTeX e a conversão para MathML.

O gerente decide se é preciso mais adjudicação, se o resultado atende aos
critérios do domínio ou se o problema deve ser escalado. Se os três níveis
compensam é uma questão experimental (#774, #619).

## A migração, em ordem

1. **`VisionAgent` e `DataAgent`.** São os únicos agentes com modelo, e é
   neles que rodam a "descrição de imagens" e a "extração de tabelas e
   fórmulas" da ADR-0029. Cada uso vira uma capacidade não agêntica. O Core
   fica com a decisão de quando pedir uma e interpreta o resultado no
   contexto do plano.
2. **Os métodos `process_*` do `FusionAgent`**, por método do plano, com a
   migração do inventário do Docstruct.
3. **`InformationalStructuralAgent`.** Uma capacidade composta de extração
   devolve o documento fundido; o Core deriva as obrigações a partir dele.
4. **Os envelopes Agno.** Saem com seus agentes; nenhum roda em produção.

Cada passo segue os passos do
[inventário do Docstruct](docstruct-import-inventory.pt-br.md#como-uma-migração-diminui-a-allowlist):
uma capacidade equivalente, a chamada pelo Core SDK, um teste diferencial e a
remoção das fixações obsoletas.

## A guarda

`tests/test_architecture_layers.py` verifica que:

- todo módulo de `acessilia_core/agents/` está no fixture, e nenhuma entrada
  está obsoleta. Um agente novo chega classificado;
- o papel de um agente é estratégico, gerencial ou operacional, o de um
  módulo de apoio é operacional ou infraestrutura, e todo módulo tem um ciclo
  de vida (active, legacy ou deprecated);
- as duas páginas listam os módulos do fixture.

## Ainda em aberto

- **Os papéis gerencial e operacional.** Contratos de delegação e de tarefa
  (objetivo, entradas, restrições, capacidades autorizadas, orçamento,
  critérios de sucesso, resultado, escalada), agentes gerenciais, agentes
  operacionais permanentes, capacidades de apoio que calculam evidências sem
  decidir e a comparação entre um, dois e três níveis (HTN e PDDL) são
  pesquisa, na [#774](https://github.com/A11yDevs/acessilia/issues/774) e na
  #619.

- **Os quatro agentes sem chamador no pipeline.** Devem ir para as
  ferramentas de benchmark (Dr.DocBench, #125) fora do Core, ser
  aposentados, ou virar capacidades quando um método do plano precisar
  deles?
- **A infraestrutura depois da migração.** `ai_client` e `model_calls` ficam
  só para um LLM estratégico (#619), ou saem quando o Core não fizer nenhuma
  chamada de modelo própria?
- **Contratos de resultado e de decisão.** A ADR-0029 pede que os contratos
  distingam um resultado operacional de uma decisão estratégica. Os
  contratos de capacidade (ADR-0027) definem isso para cada agente migrado.
