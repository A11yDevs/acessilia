# 0027. Contratos versionados de capacidades, invocados por MCP, entre o core e a Toolbox

Também disponível em **inglês (EUA)**: [English version](0027-mcp-core-toolbox-contract.md)

- **Status:** Proposto
- **Data:** 2026-11-22
- **Componentes:** core, SDK, Toolbox
- **Issues:** [#735](https://github.com/A11yDevs/acessilia/issues/735), [#639](https://github.com/A11yDevs/acessilia/issues/639), [#632](https://github.com/A11yDevs/acessilia/issues/632)
- **Baseia-se em:** [ADR-0004](0004-single-source-of-truth-for-contracts.pt-br.md), [ADR-0006](0006-availability-and-failover.pt-br.md), [ADR-0015](0015-artifact-reference-v1.pt-br.md), [ADR-0019](0019-operation-identifiers-and-cancellation.pt-br.md)

## Contexto

A [#735](https://github.com/A11yDevs/acessilia/issues/735) define a direção das
etapas de refatoração #632, #639 e #640: o core planeja e coordena, a
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
  local ou um `artifact_id`. Nenhuma capacidade publica schema de parâmetros:
  `capabilities/*.yaml` declaram `input.schema` e `output.schema` como schemas
  de artefato (por exemplo `artifact/document@1`), além de `execution`,
  `semantics` e `providers`, e o `:execute` do REST recebe `parameters` como
  string JSON.
- A fachada MCP cria uma tool por manifesto *mais recente*, com nome
  `id.replace(".", "_")`, sem a versão no nome nem no schema. O REST lista
  todas as versões, e o `:execute` aceita `version`.
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

### Fonte de verdade

- Os contratos versionados de capacidades publicados pela Toolbox são a fonte
  de verdade semântica (ADR-0004), independente do transporte: identidade e
  versão, entradas e saídas, erros, idempotência, referências de artefato,
  estados operacionais e semântica de cancelamento.
- MCP é o protocolo primário de descoberta e invocação de capacidades entre o
  core e a Toolbox. REST é uma interface compatível, derivada dos mesmos
  contratos. Os fragmentos PDDL acrescentam a semântica de que o planejamento
  precisa (pré-condições, efeitos) sem redefinir o contrato operacional
  (ADR-0029).

### Transporte

- A Toolbox deve servir MCP pelo transporte Streamable HTTP na sua API HTTP,
  com a mesma autenticação de REST (a chave de API da Toolbox).
- A Toolbox deve declarar no seu contrato publicado a revisão do protocolo MCP
  que implementa. O SDK deve recusar negociar uma revisão que não suporta.
- stdio continua disponível para agentes locais; não é um caminho para o core.

### Tools são capacidades

- Toda **versão** de capacidade catalogada deve ser exposta como uma tool MCP,
  e só capacidades catalogadas podem ser expostas. O nome da tool é
  `{id}__v{versão}` (por exemplo `document.ocr__v1`): o id é mantido como está,
  sem trocar os pontos, e o sublinhado duplo não ocorre em ids de capacidade,
  então os nomes não colidem. A tool também traz o id e a versão nos seus
  metadados. Uma ação ligada a uma versão anterior continua invocável.
- O schema de entrada da tool tem duas partes:
  - os **controles de invocação** que o REST já expõe: `provider` (opcional; a
    ADR-0029 planeja com a disponibilidade de providers), `language`,
    `no_cache` e o artefato de entrada como valor `artifact/reference@1`
    (ADR-0015). Por HTTP, uma tool não pode aceitar caminho de arquivo local.
  - os **parâmetros** da capacidade, descritos por um JSON Schema publicado no
    contrato da capacidade. Hoje nenhuma capacidade publica um, então isso é
    uma mudança de contrato na Toolbox (ADR-0004, P7): cada manifesto ganha um
    schema de parâmetros, com uma regra para parâmetros específicos de
    provider (por exemplo, um schema por provider, indexado pelo id do
    provider). Até a capacidade publicar seu schema, a tool mantém um objeto
    `parameters` livre, e o teste de paridade o aponta.
- Um resultado de sucesso traz, como `structuredContent`, o mesmo envelope e a
  mesma proveniência da resposta REST para a mesma chamada. O `outputSchema`
  da tool, quando declarado, é esse envelope de sucesso.
- Um teste de paridade na Toolbox deve verificar que a lista de tools MCP e o
  catálogo REST nomeiam as mesmas capacidades, versões e schemas.

### Identificadores, progresso, cancelamento e erros

- Os identificadores da ADR-0019 devem trafegar no `_meta` da requisição, nas
  chaves em DNS reverso `io.github.a11ydevs/task-id`,
  `io.github.a11ydevs/operation-id` e `io.github.a11ydevs/attempt-id`, com o
  mesmo significado e a mesma validação dos headers. O prefixo é o domínio do
  GitHub Pages da organização invertido, então não colide com outros
  fornecedores, e não contém rótulo reservado pelo MCP (`mcp`,
  `modelcontextprotocol`).
- Um cliente pode pedir notificações de progresso; a Toolbox informa o
  progresso quando o provider consegue medi-lo.
- O cancelamento tem dois caminhos, porque a notificação MCP é "dispare e
  esqueça" (o receptor pode ignorá-la, ela nomeia um id de requisição em uma
  conexão, e pode chegar depois da resposta):
  - **caminho rápido:** `notifications/cancelled` para uma requisição em
    andamento. O servidor associa o id da requisição ao `operation_id` que
    recebeu no `_meta` dessa requisição, enquanto a sessão durar;
  - **caminho durável:** o endpoint de cancelamento da ADR-0019, por
    `operation_id`. O cliente deve usá-lo sempre que a sessão que levou a
    requisição não existir mais (reconexão, failover) ou a notificação não
    tiver efeito, e para cancelar um job.
- Erros da Toolbox são resultados de tool com `isError: true`. Eles levam o
  envelope de erro (código como `invalid_input` ou `provider_unavailable`,
  mensagem, se é repetível) como JSON em `content` e em
  `_meta["io.github.a11ydevs/error"]`, nunca em `structuredContent`, que fica
  reservado ao envelope de sucesso. O SDK lê o código em `_meta` e levanta os
  mesmos erros tipados que levanta para REST.

### Clientes e sessões

- O SDK deve oferecer um cliente genérico de capacidades: descobrir o
  catálogo, invocar uma capacidade por id e versão com suas entradas e
  identificadores, acompanhar o progresso e cancelar.
- As regras de failover e retry da ADR-0006 se aplicam, com as regras que uma
  sessão Streamable HTTP acrescenta:
  - uma sessão (`Mcp-Session-Id`) pertence a um endpoint e não é portável. O
    failover para outra réplica abre uma sessão nova com `initialize`, e um
    `404` para uma sessão significa reinicializar;
  - uma requisição repetida após um stream interrompido ou em outra réplica
    mantém seu `operation_id`, para que a Toolbox junte a operação conhecida
    em vez de executá-la duas vezes (ADR-0019, `execution.idempotent`);
  - antes de repetir num secundário, o cliente verifica que o `tools/list` do
    secundário contém a `capability@version` vinculada, como os clientes
    tipados verificam hoje o catálogo do secundário (#429);
  - o snapshot do catálogo usado no planejamento vem do primário e não faz
    failover silencioso, como o `toolbox_gate` já faz.
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

## Decisões em aberto

Esta ADR continua `Proposto` até que estes pontos sejam fechados na revisão:

- **Schemas de parâmetros.** A forma do schema de parâmetros por capacidade e
  a regra para parâmetros específicos de provider são uma mudança de contrato
  da Toolbox. Fecha quando os donos da Toolbox a aceitarem no
  `acessilia-toolbox`.
- **Revisão entre componentes.** Os donos da Toolbox revisam as regras da
  fachada MCP acima (processo de ADR, passo 5). Depois disso, um pull request
  seguinte define `Aceito`.

## Consequências

- Um único caminho de invocação para o core, benchmarks, scripts e agentes
  externos. O planejador pode chamar uma capacidade que conhece só pelo id e
  pela versão (ADR-0029).
- A Toolbox mantém duas fachadas sobre um executor; o teste de paridade as
  mantém iguais.
- A execução assíncrona e durável (#639: filas e workers) não é decidida aqui.
  A chamada síncrona com progresso definida acima é a base que ela vai
  estender, em uma ADR posterior.
- Trabalho decorrente, acompanhado na #735:
  - Toolbox: publicar schemas de parâmetros nos contratos das capacidades;
    servir MCP por HTTP com uma tool por `(id, versão)`; aceitar referências
    de artefato; mapear os identificadores de `_meta`, o cancelamento e o
    envelope de erro; adicionar o teste de paridade.
  - SDK: o cliente MCP genérico com as regras de sessão e failover acima, com
    testes de contrato contra uma fixture da Toolbox.
  - core: mover os pontos de chamada para o cliente genérico; um teste de
    arquitetura proíbe novos imports de clientes tipados.
- Conformidade: o teste de paridade da Toolbox;
  `scripts/check_capability_contract.py` estendido à lista de tools MCP;
  `tests/test_architecture_layers.py` para os imports de clientes do core.
