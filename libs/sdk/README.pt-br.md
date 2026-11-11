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
| `acessilia_sdk.toolbox.capabilities` | `TOOLBOX_CAPABILITIES`, `ToolboxCapability`, `PROVIDER_DEFAULTS`, `ROUTE_PROVIDER_DEFAULTS`, `provider_default` — allowlist dos contratos da Toolbox e os providers padrão (só dados) |
| `acessilia_sdk.toolbox.transport` | `execute_capability` — único caminho para `POST /v1/capabilities/{id}:execute`; `require_capability`, `raise_for_error`, `auth_headers`, `media_type_for` |
| `acessilia_sdk.toolbox.client` | `ToolboxCapabilityClient` — base dos clientes por capacidade (conexões, header Bearer, provider, failover, `health`, `close`); `FailoverHook` |
| `acessilia_sdk.toolbox.config` | `ToolboxClientConfig`, `make_client` — toda a configuração de um cliente como valores explícitos (endpoints, chave de API, timeouts, retries, providers por `provider_key`, timeouts de exportação por `timeout_key`, hook de failover) e a factory que monta um cliente a partir dela |
| `acessilia_sdk.toolbox.clients` | `ToolboxAdjudicateClient`, `ToolboxArtifactClient`, `ToolboxDatasetClient`, `ToolboxDocxClient`, `ToolboxLayoutClient`, `ToolboxMathClient`, `ToolboxMediaInspectClient`, `ToolboxOcrClient`, `ToolboxOrientationClient`, `ToolboxPageOcrClient`, `ToolboxPdfClient`, `ToolboxPdfUaClient`, `ToolboxStructureClient`, `ToolboxTableClient` — um cliente por família de capacidades; sem settings e sem logs |
| `acessilia_sdk.toolbox.endpoints` | `ToolboxEndpoint`, `parse_endpoints`, `FAILOVER_ERRORS` — as instâncias da Toolbox que um cliente tenta, em ordem |
| `acessilia_sdk.toolbox.clients.pdf` | `RenderedPage` (o PNG de `ToolboxPdfClient.render`, o recorte aplicado e o resultado `image@2`), `ClipOrigin` |
| `acessilia_sdk.toolbox.artifacts` | `ArtifactRef`, `download_artifact`, `read_artifact` — artefatos endereçados por conteúdo, seu download verificado e atômico para um arquivo e sua leitura verificada, com tamanho limitado, para a memória; `parse_reference` lê um documento `artifact/reference@1` |
| `acessilia_sdk.toolbox.reference` | `ArtifactReference`, `SCHEMA_ID`, `REQUIRED` — o `artifact/reference@1` publicado (ADR-0015), **gerado** a partir do schema da Toolbox pelo `scripts/generate_sdk_bindings.py` do core; nunca editado à mão |
| `acessilia_sdk.toolbox.catalog` | `fetch_catalog`, `read_catalog`, `read_first_catalog`, `CatalogSnapshot`, `Requirement`, `missing_requirements`, `CatalogCache` — o catálogo publicado, as verificações contra ele (que só restringem) e o cache do último snapshot válido |
| `acessilia_sdk.toolbox.vlm` | `vlm_gateway_base_url`, `vlm_provider_healthy`, `VLM_GATEWAY_PATH` — o gateway VLM da Toolbox, uma rota de chat compatível com OpenAI que não é capacidade, e a saúde do seu provider ([ADR-0012](../../docs/adr/0012-agents-reach-the-vlm-through-the-toolbox.pt-br.md)) |
| `acessilia_sdk.toolbox.errors` | `ToolboxError` e subclasses, incluindo `ToolboxUnavailable` (todos os endpoints falharam; `causes` lista cada falha) |
| `acessilia_sdk.runtime` | `run_sync` — executa uma coroutine a partir de código síncrono, dentro ou fora de um event loop |

## Configurar um cliente

Quem chama monta um `ToolboxClientConfig` a partir da própria fonte de
configuração e o passa para `make_client`. O SDK não lê settings nem o
ambiente, então um script não precisa de nada do core:

```python
from pathlib import Path

from acessilia_sdk.runtime import run_sync
from acessilia_sdk.toolbox import ToolboxClientConfig, make_client
from acessilia_sdk.toolbox.clients import ToolboxMediaInspectClient

config = ToolboxClientConfig(
    endpoints="https://toolbox.example.org",   # ou uma lista de deploys independentes
    api_key="...",
    timeout_seconds=600,
    providers={"toolbox_media_inspect_provider": "pure-media-inspect"},
)

async def main():
    client = make_client(ToolboxMediaInspectClient, config)
    try:
        return await client.inspect(Path("input.pdf"))
    finally:
        await client.close()

print(run_sync(main()))
```

`providers` liga a `provider_key` de um cliente a um ID de provider, e uma
chave ausente mantém o padrão de `PROVIDER_DEFAULTS`. `timeouts` liga a
`timeout_key` de um cliente de exportação ao timeout próprio dele; sem ela,
vale o `timeout_seconds` compartilhado. Argumentos nomeados de `make_client`
sobrepõem a configuração; `None` é ignorado, e `base_url` substitui os
endpoints configurados. O core monta o mesmo objeto a partir dos seus
`settings` (`backend/tools/toolbox_client.py`).

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
  ou `ToolboxProviderUnavailable` (erro de rede, 502, 503, 504), esperando
  `retry_backoff_seconds * 2**attempt` com jitter. Desligado por padrão.
- **Só capacidades idempotentes** (ADR-0006, #406): retries e failover para
  outro endpoint valem só para capacidades que o registro marca como
  `idempotent`. Após `ToolboxTimeout` ou `ToolboxProviderUnavailable`, uma
  chamada a qualquer outra capacidade (`dataset.sample`) não é reenviada, nem
  ali nem em outro endpoint, e o erro dessa tentativa sobe como está: o
  cliente não sabe se a operação já rodou. A política é decidida por chamada,
  então uma mesma instância atende os dois tipos.
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
acima de `max_bytes` (por padrão `READ_ARTIFACT_MAX_BYTES`, 64 MiB).

### Referências de artefato

`ArtifactReference` é o `artifact/reference@1` publicado (ADR-0015): o
`artifact_id` canônico, seu `digest`, `media_type`, `size` e `store`.
`parse_reference` lê uma referência: o modelo gerado confere o schema,
ignorando campos desconhecidos para que uma versão posterior que só acrescente
campos continue sendo lida, e o `parse_reference` acrescenta a regra que o
schema não consegue expressar, `digest == artifact_id`. Um documento que não é
um `reference@1` levanta `ToolboxContractViolation`; campos ausentes nunca são
inventados. `ArtifactRef.parse` continua como o helper de quem só tem um id,
com ou sem o prefixo `sha256:`.

| SDK | Toolbox | Comportamento |
|---|---|---|
| esta versão | responde `POST /v1/artifacts` com `reference@1` (acessilia-toolbox#151) | `upload()` devolve o id; `upload_reference()` devolve o `ArtifactReference` |
| esta versão | anterior, responde com o registro guardado | `upload()` devolve o id; `upload_reference()` levanta `ToolboxContractViolation` dizendo que a Toolbox é anterior ao `reference@1` |
| anterior | qualquer uma | `upload()` só lê o id, então continua funcionando |

Ids já guardados, pelo core ou em documentos, são ids simples: continuam
passando pelo `ArtifactRef.parse` e pelo download verificado.

## Adicionar uma capacidade

1. Selecioná-la em `_CAPABILITIES` com `_selected(id, versão, rótulo,
   transport=..., provider_key=...)`: essas são as escolhas próprias do SDK.
   Depois, rodar `python scripts/generate_sdk_bindings.py` no core, que escreve
   o schema de saída e o `idempotent` da capacidade, a partir do contrato
   publicado pela Toolbox (`tests/fixtures/toolbox-contract.json`, atualizado
   com `scripts/capture_toolbox_contract.py --ref <ref>`), no bloco gerado de
   `capabilities.py`. Esse bloco nunca é editado à mão (ADR-0004, #213); um
   teste falha enquanto ele estiver desatualizado ou quando o contrato não
   publicar a versão selecionada. Uma chave de provider nova também precisa de
   uma entrada em `PROVIDER_DEFAULTS`.
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
