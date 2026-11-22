# 0028. Toda computação documental roda na Toolbox

Também disponível em **inglês (EUA)**: [English version](0028-operational-execution-in-the-toolbox.md)

- **Status:** Proposto
- **Data:** 2026-11-22
- **Componentes:** core, SDK, docstruct, Toolbox
- **Issues:** [#735](https://github.com/A11yDevs/acessilia/issues/735), [#639](https://github.com/A11yDevs/acessilia/issues/639), [#656](https://github.com/A11yDevs/acessilia/issues/656)
- **Emenda, se aceita:** [ADR-0017](0017-operational-sdk-and-agentic-core.pt-br.md) (operações executadas pelo chamador), [ADR-0003](0003-remote-only-operational-capabilities.pt-br.md) (o que "operacional" abrange) e os princípios P2, P3 e 5 da [constituição](../constitution.pt-br.md)

## Contexto

A ADR-0003 envia para a Toolbox o que precisa de "uma ferramenta externa, um
modelo ou infraestrutura especializada", e o princípio 5 da constituição
permite que a extração determinística rode "como capacidade da Toolbox ou
algoritmo do docstruct". A ADR-0017 acrescenta que o SDK oferece operações
reutilizáveis e workflows determinísticos, executados no processo do chamador.
Por isso, hoje, computação pura sobre documentos roda dentro do core. Medido
em `develop` (`46f2fe7e`):

- **46 arquivos** do core e de `backend/` importam o docstruct diretamente,
  quase tudo computação: `fusion.xycut`, `fusion.tailjoin`, `fusion.verse`,
  `fusion.similarity`, `geometry`, `tables.ast`, `text.latex`,
  `text.norm_fix`, `text.unicode_repair`.
- Dos **25** métodos de plano em `METHOD_HANDLERS`, **5** declaram requisitos
  de Toolbox; cerca de **20** computam localmente sobre o docstruct
  (`xycut-order`, `tailjoin`, `norm-fix`, `unicode-repair`, `verse-chunker`,
  `latex-normalizer`, `agreement-rule`, `table-smart-fusion`, ...).
- **3** operações do SDK rodam no processo do core:
  `acessilia_sdk.operations.formula`, `fusion` e `page_judge`.

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

- O core não pode executar computação documental no próprio processo.
  Algoritmos estruturais (fusão, ordenação, geometria, normalização, tabelas,
  reparo de texto e de Unicode, normalização matemática) e composições de
  capacidades rodam como capacidades da Toolbox, atômicas ou compostas.
- O core pode importar do docstruct só os módulos de contrato: os modelos e
  schemas do documento canônico que ele lê e escreve (por exemplo
  `docstruct.manifest`). A lista fica em `tests/test_architecture_layers.py`. A
  allowlist dos módulos computacionais ainda importados durante a migração só
  pode diminuir.
- As operações de `acessilia_sdk.operations` viram capacidades compostas da
  Toolbox. O SDK mantém contratos, clientes, referências de artefato e helpers
  que não computam sobre documentos (por exemplo, a localização de findings
  estruturados).
- O docstruct continua um pacote independente, sem mudança de repositório. A
  Toolbox depende dele em versão fixada (P3, sem mudança).
- A migração é feita por método de plano (P8). Cada passo publica a capacidade,
  troca o handler para invocá-la e passa num teste diferencial que compara o
  manifesto produzido antes e depois.
- Se aceita, a constituição é emendada em um pull request seguinte:
  - P2: o SDK deixa de oferecer "acesso a bibliotecas reutilizáveis" para
    computação;
  - P3: core → docstruct passa a ser "core → módulos de contrato do docstruct";
  - princípio 5: a extração determinística roda como capacidade da Toolbox.

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
  arquivos do core que importam módulos computacionais do docstruct (46),
  métodos de plano locais (cerca de 20 de 25), operações do SDK executadas no
  core (3). Todos devem chegar a zero.
- Conformidade: `tests/test_architecture_layers.py` (allowlist de contrato do
  docstruct e allowlist computacional que só diminui) e os testes diferenciais
  de cada método migrado.
