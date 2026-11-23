# 0028. Toda computação documental roda na Toolbox

Também disponível em **inglês (EUA)**: [English version](0028-operational-execution-in-the-toolbox.md)

- **Status:** Proposto
- **Data:** 2026-11-22
- **Componentes:** core, SDK, docstruct, Toolbox
- **Issues:** [#735](https://github.com/A11yDevs/acessilia/issues/735), [#632](https://github.com/A11yDevs/acessilia/issues/632), [#639](https://github.com/A11yDevs/acessilia/issues/639), relacionada: [#656](https://github.com/A11yDevs/acessilia/issues/656)
- **Emenda, se aceita:** [ADR-0002](0002-component-responsibilities.pt-br.md) (a linha do SDK, "acesso em processo aos algoritmos puros do docstruct", e o diagrama de dependências), [ADR-0017](0017-operational-sdk-and-agentic-core.pt-br.md) (operações executadas pelo chamador), [ADR-0003](0003-remote-only-operational-capabilities.pt-br.md) (o que "operacional" abrange) e os princípios P2, P3 e 5 da [constituição](../constitution.pt-br.md)

## Contexto

A ADR-0003 envia para a Toolbox o que precisa de "uma ferramenta externa, um
modelo ou infraestrutura especializada", e o princípio 5 da constituição
permite que a extração determinística rode "como capacidade da Toolbox ou
algoritmo do docstruct". A ADR-0017 acrescenta que o SDK oferece operações
reutilizáveis e workflows determinísticos, executados no processo do chamador.
Por isso, hoje, computação pura sobre documentos roda dentro do core. Medido
em `develop` (`46f2fe7e`):

- **46 arquivos** do core e de `backend/` importam o docstruct diretamente.
  **43** deles importam computação; os outros 3 importam só contratos ou
  validação (`manifest/models.py`, `manifest/document_adapter.py`,
  `pipeline/validators.py`). A computação inclui `fusion.xycut`,
  `fusion.tailjoin`, `fusion.verse`, `fusion.similarity`, `geometry`,
  `tables.ast`, `text.latex`, `text.norm_fix`, `text.unicode_repair` e também
  os renderizadores de exportação `docstruct.export.*` (txt, html, markdown,
  texto de página, formatos, filtros, AST do Pandoc: 7 arquivos, incluindo os
  filtros de acessibilidade), `docstruct.sections`, `docstruct.blocks.lists` e
  `docstruct.data_uri`.
- Dos **25** métodos de plano em `METHOD_HANDLERS`, **14** computam
  localmente, ou seja, seu handler não executa nenhuma capacidade nem chamada
  a modelo: `latex-normalizer`, `norm-fix`, `unicode-repair`, `rep-guard`,
  `line-number-extractor`, `verse-chunker`, `tailjoin`, `tailjoin-positioned`,
  `xycut-order`, `skeleton-order`, `rescue-omitted`, `table-smart-fusion`,
  `agreement-rule`, `deterministic-heading-repair`. Os demais chamam a Toolbox
  (`dual-provider-fusion`, `single-provider`, `vision-page-inspection`,
  `pymupdf-region`, `vlm-pairwise-judge`, `mathml`, `latex-verbalizer`),
  verificam trabalho que o enriquecimento já fez remotamente
  (`vision-description`, `pandoc-table`, `pandoc-code`) ou são simbólicos
  (`human-review`). Só os 5 primeiros declaram requisitos ao gate de
  disponibilidade (`METHOD_TOOLBOX_REQUIREMENTS`).
- **3** operações do SDK rodam no processo do core:
  `acessilia_sdk.operations.formula`, `fusion` e `page_judge`. Seus únicos
  consumidores são o core, os benchmarks (`scripts/bench`) e testes.
- O próprio SDK importa computação do docstruct (`fusion.payload`,
  `geometry.boxes`, `imaging`, `policy`, `text.latex`), além do contrato
  `manifest`.
- Os imports não computacionais do core no docstruct são contratos
  (`docstruct.canonical`, `docstruct.manifest`, `docstruct.types`), validação
  (`docstruct.validation`), vocabulários compartilhados
  (`docstruct.placeholders`, `docstruct.profiles`) e política
  (`docstruct.policy`, por exemplo `verbosity_for_mode` em
  `backend/service.py`).

A [#735](https://github.com/A11yDevs/acessilia/issues/735) pede um core que só
planeja e coordena (ADR-0029). Todo efeito sobre um documento deve ser uma
invocação de capacidade que o planejador escolheu e que pode observar, repetir,
guardar em cache e atribuir. Computação local é invisível para o plano: não
pode ter disponibilidade verificada, ser guardada no cache da Toolbox, ser
cancelada pela ADR-0019 nem ser registrada com proveniência de provider.

Opções consideradas:

1. **Manter os algoritmos puros do docstruct no core.** Barato e
   determinístico; satisfaz a ADR-0003 hoje. Mas deixa dois tipos de passo,
   capacidades planejadas e código local oculto, e mantém a dependência do core
   em computação.
2. **Mover o docstruct para o repositório da Toolbox.** Rejeitada pela #632
   (§3.4): o docstruct é uma biblioteca compartilhada e independente.
3. **O docstruct continua biblioteca independente; a Toolbox o executa.** O
   core mantém só os tipos de contrato do docstruct. Escolhida.

## Decisão

Quatro coisas são decididas separadamente: onde a computação documental
**roda**, quem é **dono** do runtime operacional, onde fica a **biblioteca** e
onde ficam os **contratos**.

### Execução: a Toolbox roda toda a computação documental

- O core não pode executar computação documental no próprio processo.
  Algoritmos estruturais (fusão, ordenação, geometria, normalização, tabelas,
  reparo de texto e de Unicode, normalização matemática) e composições de
  capacidades rodam como capacidades da Toolbox, atômicas ou compostas.
- A migração começa por um inventário de todos os imports `docstruct.*` do
  core e de `backend/`, classificados como contrato, algoritmo, validação,
  política ou operação. Política (regras de decisão como `verbosity_for_mode`)
  pertence ao core (ADR-0029): vai para o core ou entra explicitamente na
  allowlist. A renderização de exportação (`docstruct.export.*`) é
  computação: a exportação acessível é uma ação planejada (ADR-0029) apoiada
  em capacidades da Toolbox. Cada algoritmo ou operação ganha uma capacidade equivalente; o
  ponto de chamada passa ao cliente genérico (ADR-0027); o import é removido.
- A migração é feita por método de plano (P8), com um teste diferencial que
  compara o manifesto produzido antes e depois.

### Ownership: o runtime operacional pertence à Toolbox

- O SDK é separado fisicamente (#639):
  - **`acessilia-core-sdk`**: o cliente genérico de capacidades, os contratos
    como consumidos, transporte, autenticação, erros tipados e referências de
    artefato. Não pode executar operações documentais, depender de algoritmos
    do docstruct, importar internos da Toolbox, carregar dependências de
    providers (OCR, VLM, renderizadores) nem planejar.
  - **Runtime operacional da Toolbox**: operações reutilizáveis, composições
    de capacidades, adaptação de entradas e saídas, a integração com os
    algoritmos do docstruct e as funções usadas pelos workers. Não pode
    planejar, depender do core ou do core SDK, nem coordenar workflows.
- O runtime pertence à Toolbox. Por padrão, é um pacote dentro da Toolbox
  (`acessilia_toolbox.operations`), publicado junto com ela, porque nenhum
  consumidor precisa **importá-lo**: o core, os benchmarks e os testes o
  alcançam por invocação de capacidade. Um benchmark ou script deste
  repositório não pode importar um pacote distribuído dentro da Toolbox (P3,
  P4). O runtime passa a ser um `acessilia-toolbox-sdk` distribuído
  separadamente só quando um consumidor concreto precisar importá-lo.
- O `acessilia-sdk` mantém uma camada temporária de compatibilidade sobre o
  core SDK, com política de depreciação publicada.

### Biblioteca: o docstruct continua independente

- O docstruct continua uma biblioteca pura, determinística e independente,
  sem dependência operacional pesada e sem dependência do core ou da Toolbox.
  A Toolbox o instala em versão fixada (P3). Ele não é movido para dentro do
  código da Toolbox. Um repositório próprio pode ser considerado depois; não é
  requisito da 0.3.0.

### Contratos: o core não deveria precisar do docstruct para eles

- Até que se decida sobre os contratos, o core pode importar só os módulos de
  contrato do docstruct, mantidos como allowlist em
  `tests/test_architecture_layers.py`. A allowlist dos módulos computacionais
  ainda importados durante a migração só pode diminuir.
- Meta: o core não instalar uma biblioteca de algoritmos documentais só para
  ler contratos de interoperabilidade. Extrair os modelos e schemas
  compartilhados (documento canônico, manifesto, envelopes) para um pacote de
  contratos, por exemplo `acessilia-contracts`, será avaliado em uma ADR
  posterior. Essa ADR emenda a ADR-0004 e o P7 (hoje o docstruct é dono dos
  modelos canônicos), mantém uma única fonte de verdade e deixa no docstruct
  as estruturas internas dos algoritmos.

### Constituição

- Se aceita, a constituição é emendada em um pull request seguinte:
  - P2: o SDK deixa de oferecer "acesso a bibliotecas reutilizáveis" para
    computação, e a Toolbox passa a ser dona do runtime operacional;
  - P3: core → docstruct passa a ser "core → módulos de contrato do
    docstruct", e SDK → docstruct passa a ser "runtime da Toolbox →
    docstruct" (os dois apontam para o pacote de contratos, se ele for
    extraído);
  - princípio 5: a extração determinística roda como capacidade da Toolbox.

## Decisões em aberto

Esta ADR continua `Proposto` até que estes pontos sejam fechados na revisão:

- **Pacote de contratos.** Se os contratos de interoperabilidade
  compartilhados serão extraídos (e de quais módulos) é decidido pela ADR
  posterior. Até lá vale a allowlist de contratos.
- **Classificação.** O pull request do inventário classifica todos os imports
  listados acima, incluindo os módulos de política e de vocabulário. Sua
  revisão fecha quais módulos ficam na allowlist. O inventário é
  [docstruct-import-inventory.pt-br.md](../architecture/docstruct-import-inventory.pt-br.md)
  (#758).
- **Revisão entre componentes.** Os donos da Toolbox e do docstruct revisam o
  ownership do runtime e as mudanças de dependência (processo de ADR, passo
  5). Depois disso, um pull request seguinte define `Aceito`.

## Consequências

- Todo efeito sobre um documento é uma chamada de capacidade: disponível para
  o planejador, guardada em cache e atribuída pela Toolbox, e cancelável.
- Mais chamadas remotas e payloads maiores. Mitigações: referências de
  artefato (ADR-0015), capacidades compostas dimensionadas para evitar
  sequências de muitas chamadas pequenas, e o cache de resultados da Toolbox.
- Benchmarks, a CLI e o desenvolvimento local precisam de uma Toolbox no ar
  para todo passo, não só para os pesados. O Compose local da Toolbox passa a
  ser pré-requisito dos testes ponta a ponta do core.
- A Toolbox também roda algoritmos puros. Seu modelo sem estado não muda (filas
  duráveis são uma decisão separada, #639).
- Os indicadores de progresso, com a baseline acima, são acompanhados na #735:
  arquivos do core que importam módulos computacionais do docstruct (43),
  métodos de plano que computam localmente (14 de 25), operações do SDK
  executadas no core (3). Todos devem chegar a zero.
- Quando esta ADR for aceita, a referência de volta na ADR-0002 passa a ser
  "Emendada pelas ADRs 0017 e 0028".
- Conformidade: `tests/test_architecture_layers.py` (allowlist de contrato do
  docstruct, allowlist computacional que só diminui, nenhuma dependência do
  core no runtime da Toolbox), os jobs de instalação isolada do core SDK e do
  runtime da Toolbox, e os testes diferenciais de cada método migrado.
