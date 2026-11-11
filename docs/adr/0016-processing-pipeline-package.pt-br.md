# 0016. O pipeline de processamento como um pacote próprio

Também disponível em **inglês (EUA)**: [English version](0016-processing-pipeline-package.md)

- **Status:** Proposto
- **Data:** 2026-11-11
- **Componentes:** core
- **Issues:** [#402](https://github.com/A11yDevs/acessilia/issues/402), [#365](https://github.com/A11yDevs/acessilia/issues/365)

## Contexto

O core (`backend/`) guarda duas coisas que mudam por motivos diferentes:

- **O pipeline de processamento**: o manifesto, o planejamento e a execução
  (`backend/core`), o orquestrador PDDL com seus handlers e etapas de
  enriquecimento (`backend/agents/pddl_orchestrator.py`), os agentes de visão
  e de dados (`backend/agents`, `backend/ai`), a fusão dupla
  (`backend/pipeline`), os adaptadores da Toolbox (`backend/tools`) e as
  mensagens (`backend/i18n`, `log_messages`, `stage_messages`).
- **O serviço em volta dele**: a API (`backend/api`, FastAPI), os jobs, o
  estado e os caches (`backend/services`), os exportadores (`backend/export`)
  e a configuração do ambiente (`backend/config`).

A única forma de rodar o pipeline é por dentro do `backend`, então um
benchmark, um script ou outro front-end carrega o serviço inteiro. O SDK já
permite que um script chegue à Toolbox sem o core (#402, fase 1); nada permite
rodar o pipeline sem o serviço.

Medido na develop em fd7f7152:

- **As dependências de framework já estão do lado certo.** O FastAPI é
  importado só em `backend/api`; o Agno só em três arquivos de
  `backend/agents` (`vision_agent.py`, `data_agent.py`, `output_schemas.py`);
  `backend/core` não importa nenhum dos dois.
- **O pipeline chega ao serviço em dois pontos.**
  - `backend.config`: 31 imports, e 55 chaves diferentes do `settings` lidas
    em 101 pontos. Só o orquestrador lê 12 chaves.
  - `backend.services`, em três lugares:
    - `run_blocking` (`blocking.py`);
    - o cache de regiões da visão (`get_cached_bytes`, `set_cache_bytes`,
      `options_cache_key`);
    - `processing_cache_configuration` e `_file_hash`, lidos pelo payload e
      pelo extrator da Toolbox.
- **O serviço chega ao pipeline** por `backend/service.py`
  (`PddlAccessibilityOrchestrator`), e pelas mensagens e ferramentas usadas na
  API, nos serviços e nos exportadores.
- **Tamanho.** O `pddl_orchestrator.py` tem 5.770 linhas (5.823 com a #466) e o
  `backend/core/manifest/builder.py`, 1.205. O passo 6 da fase 3 da #402
  reorganiza o orquestrador em módulos, que é o momento de escolher onde eles
  ficam.

Opções consideradas:

1. **Reorganizar no lugar**, em `backend/core`, mantendo o pipeline dentro do
   serviço. O código fica organizado, mas o acoplamento com a configuração do
   ambiente continua implícito, e todo uso do pipeline continua carregando o
   serviço.
2. **Um pacote do pipeline** (`libs/pipeline`), do qual o serviço depende, com
   a configuração passada de forma explícita, como o SDK recebe o
   `ToolboxClientConfig`.
3. **Dividir o repositório inteiro** em um repositório do serviço e um do
   pipeline. Vai além do que o problema pede; a opção 2 pode levar a isso
   depois, se surgir um segundo serviço.

## Decisão

Proposta: a opção 2. As regras abaixo são o que a ADR tornaria obrigatório; as
perguntas em aberto no fim precisam de resposta antes que ela seja aceita.

- **O pipeline é um pacote**, `libs/pipeline`, com os módulos que transformam
  um arquivo de origem em um documento canônico: manifesto, planejamento,
  execução, orquestrador, handlers, enriquecimento, agentes, fusão,
  adaptadores da Toolbox e mensagens.
- **Direção das dependências:**

  ```text
  backend (serviço) ──▶ pipeline ──▶ SDK ──▶ docstruct
                           └──────────────▶ docstruct
  ```

  O pipeline não pode importar o serviço (`backend`). O SDK e o docstruct não
  podem importar o pipeline.
- **A configuração é explícita.** O pipeline não pode ler o ambiente nem um
  `settings` global. Ele recebe um objeto de configuração montado por quem o
  chama; o serviço o monta a partir do seu ambiente, como já monta o
  `ToolboxClientConfig` do SDK.
- **O estado do serviço é injetado.** Os caches de regiões e de processamento,
  e a forma de rodar chamadas bloqueantes, chegam ao pipeline como argumentos
  que seguem um protocolo declarado pelo pipeline. O pipeline não é dono do
  armazenamento do serviço.
- **A mudança é gradual e neutra**, uma responsabilidade por pull request,
  como na fase 3 da #402:
  1. **O passo 6 da fase 3** reorganiza o orquestrador em
     `backend/core/pipeline/`, com a estrutura de módulos que o pacote terá
     (veja [o inventário](../architecture/pddl-orchestrator-inventory.pt-br.md)).
     Extrair o pacote depois é então uma troca de caminho, não uma segunda
     reorganização.
  2. As leituras do `settings` são trocadas pelo objeto de configuração, uma
     etapa por vez.
  3. Os caches e o `run_blocking` passam a ser injetados.
  4. A pasta vira `libs/pipeline`, com uma verificação de instalação e import
     no CI, como o job isolado do SDK.
- **Evidência para aceitar esta ADR:** uma prova de conceito em que uma etapa
  de enriquecimento, por exemplo a das estruturas de tabela, roda a partir de
  um script com um objeto de configuração explícito, sem importar o FastAPI nem
  o `backend.config`, e devolve o mesmo manifesto que o serviço para a mesma
  entrada.

## Consequências

- **Fica mais fácil:**
  - benchmarks e scripts rodam o pipeline inteiro sem o serviço;
  - o serviço fica só com a entrega: a API, os jobs, os caches e os
    exportadores;
  - a fronteira vira uma dependência de pacote, que um teste confere, como o
    `libs/sdk/tests/test_purity.py` confere a do SDK.
- **Fica mais difícil:**
  - cada etapa que lê o `settings` muda de assinatura (101 leituras);
  - os testes que alteram atributos do `settings` passam a montar uma
    configuração;
  - o pacote depende do Agno por causa dos agentes.
- **Desvios que permanecem** até que os passos acima terminem:
  - o pipeline continua lendo o `settings`;
  - os caches continuam em `backend/services`.
- **Perguntas em aberto**, a responder antes de aceitar esta ADR:
  - **Os exportadores pertencem ao pipeline ou ao serviço?** Eles usam o
    `backend.pipeline` quatro vezes, e produzem o que o serviço entrega.
  - **Os agentes ficam no pacote do pipeline ou formam um pacote próprio?** Um
    pacote próprio manteria o Agno longe de quem só planeja ou executa.
  - **Os catálogos de mensagens vão com o pipeline ou são injetados?** A API
    também os usa, então movê-los faz o serviço depender dos catálogos do
    pipeline.
  - **Qual é o nome do pacote?**
- **Conformidade:**
  - um teste de que o pacote do pipeline não importa nada do `backend`;
  - um teste de que ele não lê o ambiente;
  - um job de instalação isolada no CI.

  Até lá, o passo 6 é conferido pelo limite de tamanho de módulo (decisão D4
  do inventário).
