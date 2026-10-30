# acessilia-sdk

Uniform access to Acessilia capabilities.

> Also available in **Brazilian Portuguese**: [Portuguese version](README.pt-br.md)

## Layers

```
core (backend)  →  acessilia-sdk  →  Toolbox HTTP contract
                         │
                         └──────→  acessilia-docstruct (pure algorithms, in-process)
```

- **The core decides what to do and when; the SDK defines how to reach an
  operation; the Toolbox provides where and with which resources it runs.**
- The SDK depends on the Toolbox only through its **published contract**
  (capability ids, manifest versions, output schemas). It never imports
  `acessilia_toolbox`, and the Toolbox does not depend on the SDK.
- The SDK never imports the core (`backend`) and reads no settings or
  environment: configuration is passed in by the caller.
- The SDK has no local executors: operational capabilities run only in the
  Toolbox ([ADR-0003](../../docs/adr/0003-remote-only-operational-capabilities.md)).
  It may call docstruct's pure algorithms in-process.

## Public API

| Module | Symbols |
|---|---|
| `acessilia_sdk.toolbox.capabilities` | `TOOLBOX_CAPABILITIES`, `ToolboxCapability`, `PROVIDER_DEFAULTS`, `ROUTE_PROVIDER_DEFAULTS`, `provider_default` — the allowlist of Toolbox contracts and the default providers (pure data) |
| `acessilia_sdk.toolbox.transport` | `execute_capability` — the only path to `POST /v1/capabilities/{id}:execute`; `require_capability`, `raise_for_error`, `auth_headers`, `media_type_for` |
| `acessilia_sdk.toolbox.client` | `ToolboxCapabilityClient` — base for per-capability clients (connections, Bearer header, provider, failover, `health`, `close`); `FailoverHook` |
| `acessilia_sdk.toolbox.clients` | `ToolboxAdjudicateClient`, `ToolboxArtifactClient`, `ToolboxDatasetClient`, `ToolboxDocxClient`, `ToolboxLayoutClient`, `ToolboxMathClient`, `ToolboxMediaInspectClient`, `ToolboxOcrClient`, `ToolboxOrientationClient`, `ToolboxPageOcrClient`, `ToolboxPdfClient`, `ToolboxPdfUaClient`, `ToolboxStructureClient`, `ToolboxTableClient` — one client per capability family; no settings, no logging |
| `acessilia_sdk.toolbox.endpoints` | `ToolboxEndpoint`, `parse_endpoints`, `FAILOVER_ERRORS` — the Toolbox instances a client tries, in order |
| `acessilia_sdk.toolbox.clients.pdf` | `RenderedPage` (the PNG of `ToolboxPdfClient.render`, the clip applied and the `image@2` result), `ClipOrigin` |
| `acessilia_sdk.toolbox.artifacts` | `ArtifactRef`, `download_artifact`, `read_artifact` — content-addressed artifacts, their verified, atomic download to a file, and their verified, size-bounded read into memory |
| `acessilia_sdk.toolbox.catalog` | `fetch_catalog`, `CatalogSnapshot`, `Requirement`, `missing_requirements`, `CatalogCache` — the published catalogue, checks against it (it only restricts) and the last-good cache |
| `acessilia_sdk.toolbox.vlm` | `vlm_gateway_base_url`, `vlm_provider_healthy`, `VLM_GATEWAY_PATH` — the Toolbox VLM gateway, an OpenAI-compatible chat route that is not a capability, and its provider health ([ADR-0012](../../docs/adr/0012-agents-reach-the-vlm-through-the-toolbox.md)) |
| `acessilia_sdk.toolbox.errors` | `ToolboxError` and its subclasses, including `ToolboxUnavailable` (every endpoint failed; `causes` lists each one) |
| `acessilia_sdk.runtime` | `run_sync` — run a coroutine from sync code, inside or outside an event loop |

## Availability and failover

The primary way to stay available is **one** `base_url` pointing at a load
balancer in front of stateless Toolbox replicas that share the artifact store
(MinIO) and cache (Valkey): artifact ids stay valid whichever replica answers.
Operations never fall back to running locally. A `base_url` must be an absolute
`http(s)` URL; anything else raises `ValueError` when the client is built,
instead of looking like an outage later.

On top of that, the client offers:

- **`retries`**: re-sends a request to the same endpoint after
  `ToolboxTimeout` or `ToolboxProviderUnavailable` (network error, 502, 503, 504),
  waiting `retry_backoff_seconds * 2**attempt` with jitter. Off by default;
  enable it only for idempotent capabilities.
- **`endpoints=`** (secondary mechanism): for *independent* Toolbox
  deployments, tried in order. It takes `ToolboxEndpoint` objects, URLs or a
  comma-separated string. A secondary endpoint is used only when its catalogue
  publishes the capability at the expected contract version for the client's
  provider; `catalog_refresh_seconds` and `catalog_stale_seconds` tune those
  catalogues and do nothing with a single endpoint. Other errors (4xx,
  contract violation) are the same on every instance and are raised at once.
- **Errors**: when only one endpoint was tried, its own error is raised. Once
  two or more failed, `ToolboxUnavailable` carries every cause (a skipped
  secondary appears as `ToolboxIncompatibleEndpoint`).
- **`resend_file_on_missing_artifact`**: off by default, so an `artifact_id`
  an instance does not know is reported, not silently re-uploaded. It only
  applies to calls that pass **both** the `artifact_id` and the file
  (`file_path` or `upload`).
- **`health()`** fails over and calls the hook too, but never retries.

`on_failover(endpoint, error)` lets the caller log each failover; it is not
called when there is a single endpoint. `self._client` and `self.base_url`
address the primary endpoint only: capabilities that return an artifact must
use `_execute_on`, which also returns the HTTP client of the endpoint that
served the call, and fetch the artifact through it: `download_artifact`
writes it to a file, `read_artifact` reads a small one into memory (as
`ToolboxPdfClient.render` does with the page PNG). Both stream the body and
check it against the SHA-256 (and an optional magic prefix). The download is
synced to disk and renamed atomically, and local file system errors propagate
as `OSError`; the read refuses a body above `max_bytes`
(`READ_ARTIFACT_MAX_BYTES`, 64 MiB, by default). `ArtifactRef` is provisional
until the Toolbox publishes `artifact-ref@1`.

## Adding a capability

1. Declare it in `TOOLBOX_CAPABILITIES` (id, manifest version, error label,
   provider key, output schema). A new provider key also needs an entry in
   `PROVIDER_DEFAULTS`.
2. Add a client in `acessilia_sdk/toolbox/clients/`: subclass
   `ToolboxCapabilityClient`, set `provider_key` and call
   `self._execute(capability_id, ...)` (or `_execute_on` when the result is an
   artifact). A capability reached through a dedicated REST route
   (`transport="rest"`) uses `self._request_on(method, path, capability_id=...)`
   instead and leaves `provider_key` unset. Both paths share the failover and
   retry rules. Export the client from `acessilia_sdk.toolbox.clients` and test
   it in `tests/clients/` with an explicit `base_url`.
3. In the core, build it with `backend.tools.toolbox_client.make_toolbox_client`,
   which passes the configuration from `settings`.

## Tests

```bash
cd libs/sdk && python -m pytest
```

Artifact downloads by ID also try the next compatible endpoint after a 404.
This exception is limited to `ToolboxArtifactClient.download`: other 4xx errors
and capability calls keep their existing behavior. When every endpoint returns
404, the SDK raises `ToolboxArtifactNotFound`; integrity failures are not retried.
