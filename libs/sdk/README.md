# acessilia-sdk

Uniform access to Acessilia capabilities.

> Also available in **Brazilian Portuguese**: [Portuguese version](README.pt-br.md)

## Layers

```
core (backend)  →  acessilia-sdk  →  Toolbox HTTP contract
                         │
                         └──────→  acessilia-docstruct (local executors, planned)
```

- **The core decides what to do and when; the SDK defines how to reach an
  operation; the Toolbox provides where and with which resources it runs.**
- The SDK depends on the Toolbox only through its **published contract**
  (capability ids, manifest versions, output schemas). It never imports
  `acessilia_toolbox`, and the Toolbox does not depend on the SDK.
- The SDK never imports the core (`backend`) and reads no settings or
  environment: configuration is passed in by the caller.

## Public API

| Module | Symbols |
|---|---|
| `acessilia_sdk.toolbox.capabilities` | `TOOLBOX_CAPABILITIES`, `ToolboxCapability`, `PROVIDER_DEFAULTS`, `provider_default` — the allowlist of Toolbox contracts (pure data) |
| `acessilia_sdk.toolbox.transport` | `execute_capability` — the only path to `POST /v1/capabilities/{id}:execute`; `require_capability`, `raise_for_error`, `auth_headers`, `media_type_for` |
| `acessilia_sdk.toolbox.client` | `ToolboxCapabilityClient` — base for per-capability clients (connection, Bearer header, provider, `health`, `close`) |
| `acessilia_sdk.toolbox.errors` | `ToolboxError` and its subclasses |
| `acessilia_sdk.runtime` | `run_sync` — run a coroutine from sync code, inside or outside an event loop |

## Adding a capability

1. Declare it in `TOOLBOX_CAPABILITIES` (id, manifest version, error label,
   provider key, output schema). A new provider key also needs an entry in
   `PROVIDER_DEFAULTS`.
2. Subclass `ToolboxCapabilityClient`, set `provider_key` and call
   `self._execute(capability_id, ...)`.

## Tests

```bash
cd libs/sdk && python -m pytest
```
