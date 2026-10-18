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
| `acessilia_sdk.toolbox.client` | `ToolboxCapabilityClient` — base for per-capability clients (connections, Bearer header, provider, failover, `health`, `close`); `FailoverHook` |
| `acessilia_sdk.toolbox.endpoints` | `ToolboxEndpoint`, `parse_endpoints`, `FAILOVER_ERRORS` — the Toolbox instances a client tries, in order |
| `acessilia_sdk.toolbox.artifacts` | `ArtifactRef`, `download_artifact` — content-addressed artifacts and their verified, atomic download |
| `acessilia_sdk.toolbox.catalog` | `fetch_catalog`, `CatalogSnapshot`, `Requirement`, `missing_requirements`, `CatalogCache` — the published catalogue, checks against it (it only restricts) and the last-good cache |
| `acessilia_sdk.toolbox.errors` | `ToolboxError` and its subclasses, including `ToolboxUnavailable` (every endpoint failed; `causes` lists each one) |
| `acessilia_sdk.runtime` | `run_sync` — run a coroutine from sync code, inside or outside an event loop |

## Availability and failover

The primary way to stay available is **one** `base_url` pointing at a load
balancer in front of stateless Toolbox replicas that share the artifact store
(MinIO) and cache (Valkey): artifact ids stay valid whichever replica answers.
Operations never fall back to running locally.

On top of that, the client offers:

- **`retries`**: re-sends a request to the same endpoint after
  `ToolboxTimeout` or `ToolboxProviderUnavailable` (network error, 503, 504).
  Off by default; enable it only for idempotent capabilities.
- **`endpoints=`** (secondary mechanism): for *independent* Toolbox
  deployments, tried in order. A secondary endpoint is used only when its
  catalogue publishes the capability at the expected contract version for the
  client's provider. Other errors (4xx, contract violation) are the same on
  every instance and are raised at once. When every endpoint fails,
  `ToolboxUnavailable` carries all the causes.
- **`resend_file_on_missing_artifact`**: off by default, so an `artifact_id`
  an instance does not know is reported, not silently re-uploaded.

`on_failover(endpoint, error)` lets the caller log each failover. Capabilities
that return an artifact use `_execute_on`, which also returns the HTTP client
of the endpoint that served the call, and download it from there.
`ArtifactRef` is provisional until the Toolbox publishes `artifact-ref@1`.

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
