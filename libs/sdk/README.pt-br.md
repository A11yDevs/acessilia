# acessilia-sdk

Acesso uniforme às capacidades do Acessilia.

> Também disponível em **inglês (EUA)**: [English version](README.md) — versão autoritativa.

## Camadas

```
core (backend)  →  acessilia-sdk  →  contrato HTTP da Toolbox
                         │
                         └──────→  acessilia-docstruct (algoritmos puros, no próprio processo)
```

- **O core decide o que fazer e quando; o SDK define como acessar uma
  operação; a Toolbox fornece onde e com quais recursos ela roda.**
- O SDK depende da Toolbox apenas pelo **contrato publicado** (IDs de
  capacidade, versões de manifesto, schemas de saída). Ele nunca importa
  `acessilia_toolbox`, e a Toolbox não depende do SDK.
- O SDK nunca importa o core (`backend`) e não lê settings nem variáveis de
  ambiente: a configuração é passada por quem o usa.
- O SDK não tem executores locais: capacidades operacionais rodam só na
  Toolbox ([ADR-0003](../../docs/adr/0003-remote-only-operational-capabilities.pt-br.md)).
  Ele pode chamar os algoritmos puros da docstruct no próprio processo.

## API pública

| Módulo | Símbolos |
|---|---|
| `acessilia_sdk.toolbox.capabilities` | `TOOLBOX_CAPABILITIES`, `ToolboxCapability`, `PROVIDER_DEFAULTS`, `provider_default` — allowlist dos contratos da Toolbox (só dados) |
| `acessilia_sdk.toolbox.transport` | `execute_capability` — único caminho para `POST /v1/capabilities/{id}:execute`; `require_capability`, `raise_for_error`, `auth_headers`, `media_type_for` |
| `acessilia_sdk.toolbox.client` | `ToolboxCapabilityClient` — base dos clientes por capacidade (conexões, header Bearer, provider, failover, `health`, `close`); `FailoverHook` |
| `acessilia_sdk.toolbox.clients` | `ToolboxAdjudicateClient`, `ToolboxArtifactClient`, `ToolboxDatasetClient`, `ToolboxDocxClient`, `ToolboxLayoutClient`, `ToolboxMathClient`, `ToolboxMediaInspectClient`, `ToolboxOcrClient`, `ToolboxOrientationClient`, `ToolboxPageOcrClient`, `ToolboxPdfClient`, `ToolboxPdfUaClient`, `ToolboxStructureClient`, `ToolboxTableClient` — um cliente por família de capacidades; sem settings e sem logs |
| `acessilia_sdk.toolbox.endpoints` | `ToolboxEndpoint`, `parse_endpoints`, `FAILOVER_ERRORS` — as instâncias da Toolbox que um cliente tenta, em ordem |
| `acessilia_sdk.toolbox.clients.pdf` | `RenderedPage` (o PNG de `ToolboxPdfClient.render`, o recorte aplicado e o resultado `image@2`), `ClipOrigin` |
| `acessilia_sdk.toolbox.artifacts` | `ArtifactRef`, `download_artifact`, `read_artifact` — artefatos endereçados por conteúdo, seu download verificado e atômico para um arquivo e sua leitura verificada, com tamanho limitado, para a memória |
| `acessilia_sdk.toolbox.catalog` | `fetch_catalog`, `CatalogSnapshot`, `Requirement`, `missing_requirements`, `CatalogCache` — o catálogo publicado, as verificações contra ele (que só restringem) e o cache do último snapshot válido |
| `acessilia_sdk.toolbox.errors` | `ToolboxError` e subclasses, incluindo `ToolboxUnavailable` (todos os endpoints falharam; `causes` lista cada falha) |
| `acessilia_sdk.runtime` | `run_sync` — executa uma coroutine a partir de código síncrono, dentro ou fora de um event loop |

## Disponibilidade e failover

A forma principal de manter a disponibilidade é **um** `base_url` apontando
para um balanceador na frente de réplicas stateless da Toolbox que compartilham
o armazenamento de artefatos (MinIO) e o cache (Valkey): os ids de artefato
continuam válidos qualquer que seja a réplica que responda. As operações nunca
caem para execução local. Um `base_url` precisa ser uma URL `http(s)`
absoluta; qualquer outra coisa levanta `ValueError` na criação do cliente, em
vez de parecer uma indisponibilidade depois.

Além disso, o cliente oferece:

- **`retries`**: reenvia a requisição ao mesmo endpoint após `ToolboxTimeout`
  ou `ToolboxProviderUnavailable` (erro de rede, 503, 504), esperando
  `retry_backoff_seconds * 2**attempt` com jitter. Desligado por padrão; ligar
  só para capacidades idempotentes.
- **`endpoints=`** (mecanismo secundário): para deploys *independentes* da
  Toolbox, tentados em ordem. Aceita objetos `ToolboxEndpoint`, URLs ou uma
  string separada por vírgulas. Um endpoint secundário só é usado se o
  catálogo dele publicar a capacidade na versão de contrato esperada, para o
  provider do cliente; `catalog_refresh_seconds` e `catalog_stale_seconds`
  ajustam esses catálogos e não têm efeito com um único endpoint. Outros erros
  (4xx, violação de contrato) são iguais em todas as instâncias e são
  levantados na hora.
- **Erros**: quando só um endpoint foi tentado, o erro dele é levantado. A
  partir de dois com falha, `ToolboxUnavailable` traz todas as causas (um
  secundário pulado aparece como `ToolboxIncompatibleEndpoint`).
- **`resend_file_on_missing_artifact`**: desligado por padrão, para que um
  `artifact_id` desconhecido por uma instância seja reportado, e não
  reenviado silenciosamente. Só vale para chamadas que passam **ao mesmo
  tempo** o `artifact_id` e o arquivo (`file_path` ou `upload`).
- **`health()`** também faz failover e chama o hook, mas nunca repete.

`on_failover(endpoint, error)` permite que quem chama registre cada failover;
não é chamado quando há um único endpoint. `self._client` e `self.base_url`
apontam só para o endpoint primário: capacidades que retornam um artefato
devem usar `_execute_on`, que também devolve o cliente HTTP do endpoint que
atendeu a chamada, e obter o artefato por ele: `download_artifact` grava em
um arquivo, `read_artifact` lê um artefato pequeno para a memória (como faz
`ToolboxPdfClient.render` com o PNG da página). Os dois leem o corpo em
streaming e o conferem contra o SHA-256 (e um prefixo mágico opcional). O
download é sincronizado em disco e renomeado de forma atômica, e erros do
sistema de arquivos local se propagam como `OSError`; a leitura recusa um corpo
acima de `max_bytes` (por padrão `READ_ARTIFACT_MAX_BYTES`, 64 MiB). `ArtifactRef` é
provisório até a Toolbox publicar `artifact-ref@1`.

## Adicionar uma capacidade

1. Declarar em `TOOLBOX_CAPABILITIES` (id, versão do manifesto, rótulo de erro,
   chave de provider, schema de saída). Uma chave de provider nova também
   precisa de uma entrada em `PROVIDER_DEFAULTS`.
2. Acrescentar um cliente em `acessilia_sdk/toolbox/clients/`: subclasse de
   `ToolboxCapabilityClient`, com `provider_key` definido, chamando
   `self._execute(capability_id, ...)` (ou `_execute_on` quando o resultado é um
   artefato). Uma capacidade alcançada por uma rota REST dedicada
   (`transport="rest"`) usa `self._request_on(method, path, capability_id=...)`
   e deixa `provider_key` sem valor. Os dois caminhos seguem as mesmas regras de
   failover e retry. Exportar o cliente em `acessilia_sdk.toolbox.clients` e
   testá-lo em `tests/clients/` com um `base_url` explícito.
3. No core, criá-lo com `backend.tools.toolbox_client.make_toolbox_client`, que
   repassa a configuração do `settings`.

## Testes

```bash
cd libs/sdk && python -m pytest
```

Downloads por identificador também procuram no próximo endpoint compatível após
um 404. Essa exceção vale somente para `ToolboxArtifactClient.download`: outros
erros 4xx e chamadas de capacidade mantêm seu comportamento. Se todos retornarem
404, o SDK lança `ToolboxArtifactNotFound`; falhas de integridade não são repetidas.
