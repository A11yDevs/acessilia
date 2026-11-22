# 0027. MCP é o contrato entre o core e a Toolbox

Também disponível em **inglês (EUA)**: [English version](0027-mcp-core-toolbox-contract.md)

- **Status:** Proposto
- **Data:** 2026-11-22
- **Componentes:** core, SDK, Toolbox
- **Issues:** [#735](https://github.com/A11yDevs/acessilia/issues/735), [#639](https://github.com/A11yDevs/acessilia/issues/639), [#632](https://github.com/A11yDevs/acessilia/issues/632)
- **Baseia-se em:** [ADR-0004](0004-single-source-of-truth-for-contracts.pt-br.md), [ADR-0006](0006-availability-and-failover.pt-br.md), [ADR-0015](0015-artifact-reference-v1.pt-br.md), [ADR-0019](0019-operation-identifiers-and-cancellation.pt-br.md)

## Contexto

A [#735](https://github.com/A11yDevs/acessilia/issues/735) define a direção das
etapas de refatoração #632, #639 e #640: o core planeja simbolicamente, a
Toolbox executa todas as capacidades, e os dois se comunicam por MCP,
endereçado por capacidade. Medido em `develop` (`46f2fe7e`) e
`acessilia-toolbox@main`:

- O core alcança a Toolbox só por REST, com um cliente tipado do SDK por
  capacidade (`acessilia_sdk.toolbox.clients.*`). Nada em `libs/` ou
  `backend/` fala MCP.
- A Toolbox tem uma fachada MCP (`acessilia_toolbox.api.mcp.ToolboxMCPServer`),
  mas ela só é servida por stdio (`scripts/mcp_server.py`, JSON-RPC escrito à
  mão) e não está montada na API HTTP; um core remoto não consegue usá-la.
- Suas tools recebem um objeto `parameters` livre e um `file` que é um caminho
  local ou um `artifact_id`. O schema de parâmetros publicado pela capacidade
  não é o schema de entrada da tool.
- Os identificadores de operação da ADR-0019 trafegam só como headers HTTP
  (`X-Acessilia-*`); ainda não há equivalente em MCP.

A #639 deixou "substituir REST por MCP" fora do escopo, e a #632 desenhou
"REST / MCP" como intercambiáveis. Manter os dois como caminhos de cliente de
primeira classe significaria dois contratos a manter iguais (ADR-0004), e
deixaria sem transporte o acesso genérico, endereçado por capacidade, de que o
planejamento precisa (#640, ADR-0029).

Opções consideradas:

1. **Manter REST, com clientes tipados por capacidade.** Nenhum transporte
   novo, mas toda capacidade nova exige código no SDK, e o planejador não
   consegue invocar uma capacidade que conhece só pelo id.
2. **Um cliente REST genérico por id de capacidade.** Resolve o
   endereçamento, mas cria um segundo contrato de descoberta e invocação ao lado
   do MCP que a Toolbox já publica para agentes.
3. **MCP sobre HTTP como caminho primário, REST mantido para compatibilidade e
   operação.** Um único contrato de invocação para o core, scripts e agentes
   externos. Escolhida.

## Decisão

### Transporte

- A Toolbox deve servir MCP pelo transporte Streamable HTTP na sua API HTTP,
  com a mesma autenticação de REST (a chave de API da Toolbox).
- A Toolbox deve declarar no seu contrato publicado a revisão do protocolo MCP
  que implementa. O SDK deve recusar negociar uma revisão que não suporta.
- stdio continua disponível para agentes locais; não é um caminho para o core.

### Tools são capacidades

- Toda capacidade do catálogo deve ser exposta como uma tool MCP, e só
  capacidades catalogadas podem ser expostas. A tool leva o id da capacidade e
  sua versão exata.
- O schema de entrada da tool deve ser o schema de parâmetros publicado da
  capacidade (ADR-0004). Sem objeto `parameters` livre.
- Entradas que são artefatos devem ser valores `artifact/reference@1`
  (ADR-0015). Por HTTP, uma tool não pode aceitar caminho de arquivo local.
- O resultado de uma tool deve trazer, como conteúdo estruturado, o mesmo
  envelope e a mesma proveniência da resposta REST para a mesma chamada.
- Um teste de paridade na Toolbox deve verificar que a lista de tools MCP e o
  catálogo REST nomeiam as mesmas capacidades, versões e schemas.

### Identificadores, progresso, cancelamento e erros

- Os identificadores da ADR-0019 devem trafegar no `_meta` da requisição, nas
  chaves `acessilia/task_id`, `acessilia/operation_id` e
  `acessilia/attempt_id`, com o mesmo significado e a mesma validação dos
  headers.
- Um cliente pode pedir notificações de progresso; a Toolbox informa o
  progresso quando o provider consegue medi-lo.
- A notificação de cancelamento MCP de uma requisição deve cancelar a operação
  da mesma forma que o endpoint de cancelamento da ADR-0019.
- Erros da Toolbox devem chegar ao cliente como erros de tool cujo conteúdo
  estruturado traz o código de erro da Toolbox (`invalid_input`,
  `provider_unavailable`, ...), para que o SDK levante os mesmos erros tipados
  que levanta para REST.

### Clientes

- O SDK deve oferecer um cliente genérico de capacidades: descobrir o
  catálogo, invocar uma capacidade por id e versão com suas entradas e
  identificadores, acompanhar o progresso e cancelar. As regras de failover e
  retry da ADR-0006 se aplicam sem mudança.
- O SDK não pode tornar obrigatória uma dependência pesada para isso
  (constituição, P2). Usar o pacote MCP oficial como extra opcional ou um
  cliente mínimo próprio fica a cargo do pull request que implementar.
- O core deve invocar capacidades da Toolbox só por esse cliente genérico. Os
  clientes tipados existentes viram wrappers finos sobre ele e, depois, são
  depreciados. Nenhum cliente tipado novo por capacidade é adicionado.

### REST

- REST continua para compatibilidade, health e readiness, upload e download de
  artefatos e operação. Nenhuma capacidade pode estar disponível em só um dos
  dois transportes.

## Consequências

- Um único caminho de invocação para o core, benchmarks, scripts e agentes
  externos. O planejador pode chamar uma capacidade que conhece só pelo id
  (ADR-0029).
- A Toolbox mantém duas fachadas sobre um executor; o teste de paridade as
  mantém iguais.
- A execução assíncrona e durável (#639: filas e workers) não é decidida aqui.
  A chamada síncrona com progresso definida acima é a base que ela vai
  estender, em uma ADR posterior.
- Trabalho decorrente, acompanhado na #735:
  - Toolbox: servir MCP por HTTP, derivar os schemas das tools dos schemas das
    capacidades, aceitar referências de artefato, mapear identificadores de
    `_meta` e o cancelamento, adicionar o teste de paridade.
  - SDK: o cliente MCP genérico, com testes de contrato contra uma fixture da
    Toolbox.
  - core: mover os pontos de chamada para o cliente genérico; um teste de
    arquitetura proíbe novos imports de clientes tipados.
- Conformidade: o teste de paridade da Toolbox;
  `scripts/check_capability_contract.py` estendido à lista de tools MCP;
  `tests/test_architecture_layers.py` para os imports de clientes do core.
