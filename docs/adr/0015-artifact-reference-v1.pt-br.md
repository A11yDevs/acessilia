# 0015. O contrato de referência de artefato, `artifact/reference@1`, em fases

Também disponível em **inglês (EUA)**: [English version](0015-artifact-reference-v1.md)

- **Status:** Aceito
- **Data:** 2026-11-09
- **Componentes:** core, SDK, Toolbox
- **Issues:** [#185](https://github.com/A11yDevs/acessilia/issues/185) (P5), [#152](https://github.com/A11yDevs/acessilia/issues/152)
- **Substitui:** [ADR-0005](0005-artifact-references.pt-br.md)

## Contexto

A [ADR-0005](0005-artifact-references.pt-br.md) decidiu pelo processamento
orientado a referências e pediu que a Toolbox publicasse o modelo de
referência como `artifact-ref@1`, com `id`, `digest`, `media_type`, `size`,
`store`, `scope` e proveniência. A revisão da
[#185](https://github.com/A11yDevs/acessilia/issues/185) constatou que isso
não pode ser publicado como está escrito:

- **Os nomes colidem.** Os manifests de `artifact.store` e `artifact.retrieve`
  da Toolbox já citam `artifact/reference@1`, seguindo a convenção da Toolbox
  (`artifact/<nome>@<major>`, arquivo `schemas/<nome>@<major>.json`, `$id`
  `urn:a11y-devs:schema:<nome>:<semver>`). Não existe arquivo para ele, e a
  ADR-0005 usa outro nome.
- **A Toolbox não consegue informar escopo nem proveniência hoje.** O
  `ArtifactRef` dela (`core/artifact.py`) tem `artifact_id`, `media_type`,
  `size`, `uri`, `storage_backend` e `filename`. Não há `digest` explícito; o
  digest está no id endereçado por conteúdo.
- **O acesso é por deploy, não por referência.** Toda rota de artefato exige a
  chave de API do deploy (`require_api_key`). O id sozinho não dá acesso a
  nada, mas uma chave que lê um artefato lê todos. Conferir o escopo de cada
  referência é comportamento novo, e o ciclo de refatoração separa mudanças de
  comportamento da padronização (P8).
- **A proveniência ainda não tem lugar.** Se ela fica na referência ou nos
  metadados do artefato continua em aberto.

## Decisão

Os princípios da ADR-0005 continuam valendo; o contrato é publicado em duas
versões.

- **Processar onde está guardado.** Artefatos persistidos são processados onde
  estão armazenados. Os serviços trocam referências tipadas e opacas em vez de
  documentos ou árvores canônicas.
- **A Toolbox é dona do contrato de referência,** conforme a
  [ADR-0004](0004-single-source-of-truth-for-contracts.pt-br.md). O nome é
  `artifact/reference@1`, em `schemas/reference@1.json`, com `$id`
  `urn:a11y-devs:schema:reference:1.0.0`. O SDK o consome; não existe um
  segundo nome para a mesma referência.
- **O `artifact/reference@1` contém o que a Toolbox consegue informar hoje:**
  - `artifact_id`: o id endereçado por conteúdo, opaco para os clientes,
    estável e imutável;
  - `digest`: escrito `sha256:<64 hex>` e igual ao digest do `artifact_id`;
  - `media_type` e `size`;
  - `store`: o armazenamento lógico que guarda o artefato. O
    `storage_backend` atual da Toolbox é mapeado para ele por um adapter, e
    não vira um segundo campo.
- **O `@2` só acrescenta campos.** Ele acrescenta o `scope`, que diz quem pode
  ler o artefato, e a proveniência: a capacidade, o provider e as versões que
  o produziram, e as referências de entrada. Nenhum campo do `@1` é renomeado
  ou removido.
- **O escopo é conferido antes do uso, a partir do `@2`.** Até lá, o acesso é
  concedido pela chave de API do deploy, e o id nunca é tratado como
  credencial.
- **Documentos com schema próprio continuam separados.** `pdf-export@1` e
  `image@2` mantêm seus campos; transformá-los em referências completas é uma
  mudança de contrato à parte.
- **Clientes que só têm um id continuam funcionando.** O SDK mantém um helper
  que interpreta um id (com ou sem o prefixo `sha256:`) ao lado do modelo
  gerado a partir do schema. Campos ausentes nunca são inventados.
- **Artefatos são imutáveis.** Um artefato alterado é um novo artefato, com
  uma nova referência.
- **A materialização é explícita.** Um cliente baixa os bytes só quando
  precisa deles e os verifica contra o digest. Um digest divergente é uma
  violação de contrato, nunca um "não encontrado", e por isso não dispara o
  reenvio da [ADR-0014](0014-artifact-download-not-found-failover.pt-br.md).
- **As referências continuam válidas entre réplicas.** As réplicas de um mesmo
  deploy da Toolbox compartilham o armazenamento, então uma referência vale em
  todas elas (veja a [ADR-0006](0006-availability-and-failover.pt-br.md)).
  Entre deploys independentes, uma referência só vale onde o armazenamento
  dela for alcançável.
- **Objetos pequenos dispensam referências.** Entradas e saídas que cabem com
  folga numa requisição ou resposta, como uma fórmula LaTeX, um texto curto ou
  um julgamento de página, trafegam inline.

## Consequências

- **Toolbox:** publica `schemas/reference@1.json` e o adapter
  `storage_backend` → `store` (uma issue na Toolbox), junto com os outros
  schemas que os manifests citam sem arquivo
  ([acessilia-toolbox#142](https://github.com/A11yDevs/acessilia-toolbox/issues/142)).
  A conferência de escopo por referência é uma issue de `security` à parte.
- **SDK:** o `ArtifactRef` em `acessilia_sdk.toolbox.artifacts` continua
  provisório até que um modelo seja gerado a partir de `artifact/reference@1`
  ([#213](https://github.com/A11yDevs/acessilia/issues/213)), só com código da
  biblioteca padrão e com a regeneração conferida na CI. O helper que
  interpreta ids permanece. A
  [#185](https://github.com/A11yDevs/acessilia/issues/185) define a
  compatibilidade entre versões do SDK e da Toolbox e para referências já
  guardadas.
- **Desvio que permanece:** sem escopo por referência até o `@2`; uma chave de
  deploy lê todos os artefatos daquele deploy.
- **Verificado hoje:** `libs/sdk/tests/test_failover.py` cobre a verificação
  do digest, a gravação atômica e o download pelo endpoint que atendeu a
  chamada.
- **Verificação prevista:** testes de contrato contra `artifact/reference@1`,
  incluindo a regra de que o `digest` é igual ao digest do id.
