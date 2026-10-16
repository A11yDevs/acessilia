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
| `acessilia_sdk.toolbox.client` | `ToolboxCapabilityClient` — base dos clientes por capacidade (conexão, header Bearer, provider, `health`, `close`) |
| `acessilia_sdk.toolbox.errors` | `ToolboxError` e subclasses |
| `acessilia_sdk.runtime` | `run_sync` — executa uma coroutine a partir de código síncrono, dentro ou fora de um event loop |

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
