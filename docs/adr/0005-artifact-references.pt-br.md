# 0005. Processamento orientado a referências com `ArtifactRef`

Também disponível em **inglês (EUA)**: [English version](0005-artifact-references.md)

- **Status:** Aceito
- **Data:** 2026-10-18
- **Componentes:** core, SDK, Toolbox
- **Issues:** [#152](https://github.com/A11yDevs/acessilia/issues/152) (P5)

## Contexto

A Toolbox guarda artefatos em armazenamento de objetos (MinIO) e os
identifica pelo SHA-256 do conteúdo. Várias capacidades já retornam um
`artifact_id` em vez dos bytes; `document.export.pdf_ua` é uma delas. Outros
fluxos ainda enviam documentos inteiros ou árvores canônicas entre serviços,
ou reenviam o mesmo arquivo a cada chamada de capacidade. O SDK acrescentou
`ArtifactRef` e `download_artifact` no
[#153](https://github.com/A11yDevs/acessilia/pull/153), como modelo
provisório.

## Decisão

- **Processar onde está guardado.** Artefatos persistidos são processados onde
  estão armazenados. Os serviços trocam referências tipadas e opacas
  (`ArtifactRef`) em vez de documentos ou árvores canônicas.
- **A Toolbox é dona do modelo de referência.** Ela o publica como schema
  versionado, `artifact-ref@1`, conforme o
  [ADR-0004](0004-single-source-of-truth-for-contracts.pt-br.md). O SDK
  consome esse schema.
- **Conteúdo mínimo de uma referência:**
  - `id`: opaco para os clientes, estável e imutável;
  - `digest`: algoritmo e valor, para que os clientes verifiquem os downloads;
  - `media_type` e `size`;
  - o `store` lógico que o guarda;
  - o `scope`, que diz quem pode lê-lo;
  - proveniência: a capacidade, o provider e as versões que o produziram, e
    as referências de entrada.
- **Artefatos são imutáveis.** Um artefato alterado é um novo artefato, com
  uma nova referência.
- **A materialização é explícita.** Um cliente baixa os bytes só quando
  precisa deles e os verifica contra o digest. O `download_artifact` do SDK
  faz o download em streaming, verifica e grava de forma atômica.
- **O escopo é conferido antes do uso.** A Toolbox valida o escopo e as
  permissões de uma referência antes de lê-la ou processá-la. Uma referência,
  sozinha, não é um token de acesso.
- **As referências continuam válidas entre réplicas.** As réplicas de um mesmo
  deploy da Toolbox compartilham o armazenamento, então uma referência vale em
  todas elas (veja o [ADR-0006](0006-availability-and-failover.pt-br.md)).
  Entre deploys independentes, uma referência só vale onde o armazenamento
  dela for alcançável.
- **Objetos pequenos dispensam referências.** Entradas e saídas que cabem com
  folga numa requisição ou resposta, como uma fórmula LaTeX, um texto curto ou
  um julgamento de página, trafegam inline.

## Consequências

- **SDK:** o `ArtifactRef` em `acessilia_sdk.toolbox.artifacts` está marcado
  como provisório. Ele é substituído pelo modelo gerado a partir de
  `artifact-ref@1` quando a Toolbox publicar esse schema; isso exige uma issue
  na Toolbox. O upload (`upload_artifact`, hoje no `ToolboxClient` legado do
  core) vai para o SDK, ao lado do download, na F1 da #150.
- **Verificado hoje:** `libs/sdk/tests/test_failover.py` cobre a verificação
  do digest, a gravação atômica e o download pelo endpoint que atendeu a
  chamada.
- **Verificação prevista:** testes de contrato contra `artifact-ref@1` quando
  ele for publicado.
