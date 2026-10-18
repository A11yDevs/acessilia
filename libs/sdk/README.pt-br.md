# acessilia-sdk

Acesso uniforme às capacidades do Acessilia.

> Também disponível em **inglês (EUA)**: [English version](README.md) — versão autoritativa.

## Camadas

```
core (backend)  →  acessilia-sdk  →  contrato HTTP da Toolbox
                         │
                         └──────→  acessilia-docstruct (executores locais, previsto)
```

- **O core decide o que fazer e quando; o SDK define como acessar uma
  operação; a Toolbox fornece onde e com quais recursos ela roda.**
- O SDK depende da Toolbox apenas pelo **contrato publicado** (IDs de
  capacidade, versões de manifesto, schemas de saída). Ele nunca importa
  `acessilia_toolbox`, e a Toolbox não depende do SDK.
- O SDK nunca importa o core (`backend`) e não lê settings nem variáveis de
  ambiente: a configuração é passada por quem o usa.

## API pública

| Módulo | Símbolos |
|---|---|
| `acessilia_sdk.toolbox.capabilities` | `TOOLBOX_CAPABILITIES`, `ToolboxCapability`, `PROVIDER_DEFAULTS`, `provider_default` — allowlist dos contratos da Toolbox (só dados) |
| `acessilia_sdk.toolbox.transport` | `execute_capability` — único caminho para `POST /v1/capabilities/{id}:execute`; `require_capability`, `raise_for_error`, `auth_headers`, `media_type_for` |
| `acessilia_sdk.toolbox.client` | `ToolboxCapabilityClient` — base dos clientes por capacidade (conexões, header Bearer, provider, failover, `health`, `close`); `FailoverHook` |
| `acessilia_sdk.toolbox.endpoints` | `ToolboxEndpoint`, `parse_endpoints`, `FAILOVER_ERRORS` — as instâncias da Toolbox que um cliente tenta, em ordem |
| `acessilia_sdk.toolbox.artifacts` | `ArtifactRef`, `download_artifact` — artefatos endereçados por conteúdo e seu download verificado e atômico |
| `acessilia_sdk.toolbox.catalog` | `fetch_catalog`, `CatalogSnapshot`, `Requirement`, `missing_requirements`, `CatalogCache` — o catálogo publicado, as verificações contra ele (que só restringem) e o cache do último snapshot válido |
| `acessilia_sdk.toolbox.errors` | `ToolboxError` e subclasses, incluindo `ToolboxUnavailable` (todos os endpoints falharam; `causes` lista cada falha) |
| `acessilia_sdk.runtime` | `run_sync` — executa uma coroutine a partir de código síncrono, dentro ou fora de um event loop |

## Disponibilidade e failover

A forma principal de manter a disponibilidade é **um** `base_url` apontando
para um balanceador na frente de réplicas stateless da Toolbox que compartilham
o armazenamento de artefatos (MinIO) e o cache (Valkey): os ids de artefato
continuam válidos qualquer que seja a réplica que responda. As operações nunca
caem para execução local.

Além disso, o cliente oferece:

- **`retries`**: reenvia a requisição ao mesmo endpoint após `ToolboxTimeout`
  ou `ToolboxProviderUnavailable` (erro de rede, 503, 504). Desligado por
  padrão; ligar só para capacidades idempotentes.
- **`endpoints=`** (mecanismo secundário): para deploys *independentes* da
  Toolbox, tentados em ordem. Um endpoint secundário só é usado se o catálogo
  dele publicar a capacidade na versão de contrato esperada, para o provider do
  cliente. Outros erros (4xx, violação de contrato) são iguais em todas as
  instâncias e são levantados na hora. Quando todos os endpoints falham,
  `ToolboxUnavailable` traz todas as causas.
- **`resend_file_on_missing_artifact`**: desligado por padrão, para que um
  `artifact_id` desconhecido por uma instância seja reportado, e não
  reenviado silenciosamente.

`on_failover(endpoint, error)` permite que quem chama registre cada failover.
Capacidades que retornam um artefato usam `_execute_on`, que também devolve o
cliente HTTP do endpoint que atendeu a chamada, e baixam o artefato dali.
`ArtifactRef` é provisório até a Toolbox publicar `artifact-ref@1`.

## Adicionar uma capacidade

1. Declarar em `TOOLBOX_CAPABILITIES` (id, versão do manifesto, rótulo de erro,
   chave de provider, schema de saída). Uma chave de provider nova também
   precisa de uma entrada em `PROVIDER_DEFAULTS`.
2. Criar uma subclasse de `ToolboxCapabilityClient`, definir `provider_key` e
   chamar `self._execute(capability_id, ...)`.

## Testes

```bash
cd libs/sdk && python -m pytest
```
