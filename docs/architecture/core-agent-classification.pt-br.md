# Classificação: os agentes do Core (#735 fase 4, ADR-0029)

Inglês, versão normativa: [English version](core-agent-classification.md)

A [ADR-0029](../adr/0029-symbolic-core-every-step-planned.pt-br.md) classifica
os agentes de `acessilia_core.agents` como estratégicos ou operacionais:

- **Agentes estratégicos ficam no Core.** Interpretam objetivos, decompõem
  tarefas, escolhem estratégias, coordenam subplanos, avaliam estado e
  objetivos, decidem replanejar e recebem a futura integração LLM +
  planejamento (#619).
- **Agentes operacionais viram capacidades da Toolbox.** Fazem OCR e
  extração semântica, classificação de documentos, descrição de imagens,
  adjudicação visual, extração de tabelas e fórmulas e processamento
  multimodal.

Esta página classifica todos os módulos de
`libs/core/src/acessilia_core/agents/`
([#768](https://github.com/A11yDevs/acessilia/issues/768)). A classificação
fica como dados em
[`tests/fixtures/core_agent_classification.json`](../../tests/fixtures/core_agent_classification.json),
e `tests/test_architecture_layers.py` mantém o diretório, os dados e esta
página alinhados.

## Resumo

Medido em `develop` no `a1a68a7b`.

- **8 agentes: 0 estratégicos, 8 operacionais.** Isso fecha o indicador
  "Agentes do Core classificados" da #735 (8/8).
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

| Módulo | Classe | O que faz | Chamado por (pipeline) | Chama modelo | Destino |
|---|---|---|---|---|---|
| `agents/vision_agent` | operacional | Descrição de imagens e regiões, inspeção de páginas e regiões, leitura de fórmulas | `pipeline/enrichment/pictures`, `pipeline/enrichment/formulas`, `pipeline/handlers/inspection` | sim | Uma capacidade da Toolbox com modelo para cada uso (descrição de imagem, inspeção de região, leitura de fórmula), com seus prompts, validação, novas tentativas e cache |
| `agents/data_agent` | operacional | Extração validada de tabelas e fórmulas de uma região | `pipeline/enrichment/tables` | sim | Uma capacidade da Toolbox com modelo para extração de tabelas e fórmulas |
| `agents/informational_structural` | operacional | Extrai o documento pela Toolbox, funde os provedores e monta o manifesto de processamento | `pipeline/orchestrator` | não (só o envelope Agno) | A extração já é uma chamada à Toolbox. A fusão local e a montagem do manifesto viram uma capacidade composta de extração. Derivar as obrigações fica no Core (veja abaixo) |
| `agents/fusion_agent` | operacional | Fusão, auditoria, classificação, verso, junção final, guarda contra repetição, normalização e ordem de leitura determinísticas (`process_*`) | `pipeline/handlers/common`, para os handlers dos métodos do plano | não (só o envelope Agno) | Cada `process_*` sai com o método do plano que o usa, como parte da migração do [inventário do Docstruct](docstruct-import-inventory.pt-br.md) |
| `agents/adjudication_agent` | operacional | Roteamento de páginas entre provedores, decisões a partir da transcrição do VLM, o juiz pareado, o oráculo | nenhum | não (só o envelope Agno) | Não migra até um método do plano precisar dele (veja [Ainda em aberto](#ainda-em-aberto)) |
| `agents/order_adjudication_agent` | operacional | Interpreta e completa uma ordem de leitura do VLM; tau de Kendall | nenhum | não (só o envelope Agno) | Idem |
| `agents/page_level_agent` | operacional | Fusão e seleção de páginas inteiras, concordância de páginas, upscale e orientação | nenhum | não (só o envelope Agno) | Idem |
| `agents/table_specialist_agent` | operacional | Gera, compara e adjudica candidatos de tabela | nenhum | não (só o envelope Agno) | Idem |

## Módulos de apoio

| Módulo | Classe | O que é | Usado por | Destino |
|---|---|---|---|---|
| `agents/model_call_policy` | operacional | A margem de prazo das chamadas de modelo de visão e de dados | `vision_agent`, `data_agent` | Sai com esses agentes |
| `agents/prompt_tools` | operacional | Carrega e monta os prompts de visão e de região (`agents/prompts/`) | `vision_agent`, `data_agent` | Sai com esses agentes, com os prompts |
| `agents/output_schemas` | operacional | Contratos de saída validados dos agentes de visão e de dados | os dois agentes, o enriquecimento e o handler de inspeção | Sai com esses agentes; o contrato do resultado que o Core lê fica como contrato de capacidade |
| `agents/run_helpers` | operacional | Lê o resultado de uma execução Agno | `output_schemas` | Sai com `output_schemas` |
| `agents/agno_support` | infraestrutura | Monta agentes Agno quando a pilha opcional está instalada | os agentes acima, `planning/planner_agent`, `execution/executor` | Fica: o planejador e o executor o usam |
| `agents/ai_client` | infraestrutura | O cliente de modelo de cada `AI_CLIENT` (Ollama, OpenRouter, o gateway da Toolbox) | `vision_agent`, `data_agent`, `backend/api/routes/health` | Fica enquanto o Core fizer chamadas de modelo (ADR-0012); um LLM estratégico (#619) precisa dele |
| `agents/model_calls` | infraestrutura | A porta de execução da aplicação para chamadas de modelo síncronas | `pipeline/orchestrator`, os dois agentes, `backend/services/model_calls` | Fica enquanto o Core fizer chamadas de modelo |
| `agents/provider_breaker` | infraestrutura | Para de chamar um provedor que falha pelo resto de um job | `pipeline/orchestrator`, enriquecimento | Fica: é uma preocupação de coordenação do job; quando as chamadas forem capacidades, ele as protege |

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

## A migração, em ordem

1. **`VisionAgent` e `DataAgent`.** São os únicos agentes com modelo, e é
   neles que rodam a "descrição de imagens" e a "extração de tabelas e
   fórmulas" da ADR-0029. Cada uso vira uma capacidade. O Core fica com a
   decisão de quando pedir uma e interpreta o resultado no contexto do plano.
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
- um agente é estratégico ou operacional, e um módulo de apoio é operacional
  ou infraestrutura;
- as duas páginas listam os módulos do fixture.

## Ainda em aberto

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
