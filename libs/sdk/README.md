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

Each module's `__all__` is the SDK's public API ([ADR-0018](../../docs/adr/0018-core-uses-sdk-public-api.md)); a name outside it is internal and may change in any release. This table summarizes it, and `tests/test_public_api.py` checks it against `__all__` and checks that the English and Portuguese tables match.

| Module | Symbols |
|---|---|
| `acessilia_sdk.toolbox.capabilities` | `TOOLBOX_CAPABILITIES`, `ToolboxCapability`, `PROVIDER_DEFAULTS`, `ROUTE_PROVIDER_DEFAULTS`, `provider_default` — the allowlist of Toolbox contracts and the default providers (pure data) |
| `acessilia_sdk.toolbox.transport` | `execute_capability` — the only path to `POST /v1/capabilities/{id}:execute`; `require_capability`, `raise_for_error`, `auth_headers`, `media_type_for` |
| `acessilia_sdk.toolbox.client` | `ToolboxCapabilityClient` — base for per-capability clients (connections, Bearer header, provider, failover, `health`, `close`); `FailoverHook` |
| `acessilia_sdk.toolbox.config` | `ToolboxClientConfig`, `make_client` — every client setting as an explicit value (endpoints, API key, timeouts, retries, providers by `provider_key`, export timeouts by `timeout_key`, failover hook), and the factory that builds a client from it |
| `acessilia_sdk.toolbox.clients` | `ToolboxAdjudicateClient`, `ToolboxArtifactClient`, `ToolboxDatasetClient`, `ToolboxDocxClient`, `ToolboxLayoutClient`, `ToolboxMathClient`, `ToolboxMediaInspectClient`, `ToolboxOcrClient`, `ToolboxOrientationClient`, `ToolboxPageOcrClient`, `ToolboxPdfClient`, `ToolboxPdfUaClient`, `ToolboxPdfValidateClient`, `ToolboxStructureClient`, `ToolboxTableClient` — one client per capability family; no settings, no logging |
| `acessilia_sdk.toolbox.clients.adjudicate` | `page_judgement_probability` — the `pB` of a `document.adjudicate.page` answer, or `None` when it is missing or outside [0, 1] |
| `acessilia_sdk.toolbox.endpoints` | `ToolboxEndpoint`, `parse_endpoints`, `FAILOVER_ERRORS` — the Toolbox instances a client tries, in order |
| `acessilia_sdk.toolbox.clients.pdf` | `RenderedPage` (the PNG of `ToolboxPdfClient.render`, the clip applied and the `image@2` result), `ClipOrigin`, `RENDER_MEDIA_TYPES` (the inputs `pdf.render@2` opens: PDF, PNG, JPEG); `ToolboxPdfClient.text_spans_by_page` reads the `text-spans@1` pages of any number of pages, in calls of at most `TEXT_SPANS_MAX_PAGES` |
| `acessilia_sdk.toolbox.artifacts` | `ArtifactRef`, `download_artifact`, `read_artifact` — content-addressed artifacts, their verified, atomic download to a file, and their verified, size-bounded read into memory; `parse_reference` reads an `artifact/reference@1` document; `artifact_endpoint_urls` and `one_artifact_endpoint` tell whether an artifact id can be shared among clients (one deployment only, ADR-0013) |
| `acessilia_sdk.toolbox.reference` | `ArtifactReference`, `SCHEMA_ID`, `REQUIRED` — the published `artifact/reference@1` (ADR-0015), **generated** from the Toolbox's schema by the core's `scripts/generate_sdk_bindings.py`; never edited by hand |
| `acessilia_sdk.toolbox.catalog` | `fetch_catalog`, `read_catalog`, `CatalogSnapshot`, `Requirement`, `missing_requirements`, `CatalogCache` — the published catalogue, checks against it (it only restricts) and the last-good cache |
| `acessilia_sdk.toolbox.vlm` | `vlm_gateway_base_url`, `vlm_provider_healthy`, `VLM_GATEWAY_PATH` — the Toolbox VLM gateway, an OpenAI-compatible chat route that is not a capability, and its provider health ([ADR-0012](../../docs/adr/0012-agents-reach-the-vlm-through-the-toolbox.md)) |
| `acessilia_sdk.toolbox.errors` | `ToolboxError` and its subclasses, including `ToolboxUnavailable` (every endpoint failed; `causes` lists each one) |
| `acessilia_sdk.runtime` | `run_sync` — run a coroutine from sync code, inside or outside an event loop |
| `acessilia_sdk.cli` | `main` — the command line, `python -m acessilia_sdk` (see [Command line](#command-line)) |

## Configuring a client

A caller builds a `ToolboxClientConfig` from its own configuration source and
passes it to `make_client`. The SDK reads no settings or environment, so a
script needs nothing from the core:

```python
from pathlib import Path

from acessilia_sdk.runtime import run_sync
from acessilia_sdk.toolbox import ToolboxClientConfig, make_client
from acessilia_sdk.toolbox.clients import ToolboxMediaInspectClient

config = ToolboxClientConfig(
    endpoints="https://toolbox.example.org",   # or a list of independent deployments
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

`providers` maps a client's `provider_key` to a provider id, and a missing key
keeps the default in `PROVIDER_DEFAULTS`. `timeouts` maps an export client's
`timeout_key` to its own timeout; without one, the shared `timeout_seconds`
applies. Keyword arguments to `make_client` override the configuration;
`None` is ignored, and `base_url` replaces the configured endpoints. The core
builds the same object from its `settings` (`backend/tools/toolbox_client.py`).

## Availability and failover

The primary way to stay available is **one** `base_url` pointing at a load
balancer in front of stateless Toolbox replicas that share the artifact store
(MinIO) and cache (Valkey): artifact ids stay valid whichever replica answers.
Operations never fall back to running locally. A `base_url` must be an absolute
`http(s)` URL that `httpx` can parse, with a port between 0 and 65535 when one
is given; anything else raises `ValueError` when the endpoint or the client is
built, instead of looking like an outage later.

On top of that, the client offers:

- **`retries`**: re-sends a request to the same endpoint after
  `ToolboxTimeout` or `ToolboxProviderUnavailable` (network error, 502, 503, 504),
  waiting `retry_backoff_seconds * 2**attempt` with jitter. Off by default.
- **Idempotent capabilities only** (ADR-0006, #406): retries and failover to
  another endpoint apply only to capabilities the registry marks
  `idempotent`. After `ToolboxTimeout` or `ToolboxProviderUnavailable`, a call
  to any other capability (`dataset.sample`) is not re-sent, here or
  elsewhere, and that attempt's error is raised as it is: the client cannot
  tell whether the operation already ran. The policy is decided per call, so
  one client instance serves both kinds.
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
(`READ_ARTIFACT_MAX_BYTES`, 64 MiB, by default).

### Artifact references

`ArtifactReference` is the published `artifact/reference@1` (ADR-0015): the
canonical `artifact_id`, its `digest`, `media_type`, `size` and `store`.
`parse_reference` reads one: the generated model checks the schema, ignoring
unknown fields so a later version that only adds fields is still read, and
`parse_reference` adds the rule the schema cannot state, `digest ==
artifact_id`. A document that is not a `reference@1` raises
`ToolboxContractViolation`; missing fields are never invented.
`ArtifactRef.parse` stays the helper for callers that only hold an id, with or
without the `sha256:` prefix.

| SDK | Toolbox | Behaviour |
|---|---|---|
| this version | answers `POST /v1/artifacts` with `reference@1` (acessilia-toolbox#151) | `upload()` returns the id; `upload_reference()` returns the `ArtifactReference` |
| this version | earlier, answers with its stored record | `upload()` returns the id; `upload_reference()` raises `ToolboxContractViolation` saying the Toolbox predates `reference@1` |
| earlier | either | `upload()` reads the id only, so it keeps working |

Ids already stored, by the core or in documents, are plain ids: they keep
going through `ArtifactRef.parse` and the verified download.

## Command line

`python -m acessilia_sdk` reaches the Toolbox with the SDK alone: no core, no
settings, no environment. Every value is an argument (ADR-0002); the API key
is read from a file, or from standard input with `-`, so it never shows in the
process list.

```bash
TB="--endpoint https://toolbox.example --api-key-file key.txt"

# The catalogue of the first endpoint, as JSON (revision, capabilities, providers)
python -m acessilia_sdk $TB catalog

# Call a capability of the registry; prints the response envelope
python -m acessilia_sdk $TB run media.inspect --file doc.pdf
python -m acessilia_sdk $TB run pdf.render --file doc.pdf --parameters '{"page_number": 2, "max_side": 1024}'
python -m acessilia_sdk $TB run math.verbalize --file formula.txt --language pt-BR

# Store a file once, then call capabilities on it by id
ID=$(python -m acessilia_sdk $TB upload doc.pdf)
python -m acessilia_sdk $TB run document.structure.extract --artifact "$ID" --provider mineru

# A stored artifact (an export's, for example), checked against its digest
python -m acessilia_sdk $TB download sha256:<64 hex> out.pdf

# The dataset routes
python -m acessilia_sdk $TB dataset list
python -m acessilia_sdk $TB dataset items dr-docbench dev --all --limit 50
python -m acessilia_sdk $TB dataset artifact dr-docbench dev <item> images/page_1.jpg page_1.jpg
```

**`run` dispatches by transport.** It calls the registry's `execute`
capabilities through `POST /v1/capabilities/{id}:execute`, with the
registry's provider and contract version unless `--provider` says otherwise.
`rest` capabilities have routes and arguments of their own, so each has a
command, and `run` points to it: `artifact.store` and `artifact.retrieve` are
`upload` and `download`; `dataset.list`, `.describe`, `.list_splits`,
`.list_items`, `.get_item`, `.get_artifact`, `.sample` and `.sync` are
`dataset list`, `describe`, `splits`, `items` (`--limit`, `--offset`, or
`--all` to page through the split), `item`, `artifact` (written atomically to a
file), `sample` (`--n`; one attempt, since it is not idempotent) and `sync`
(`--split`). A capability outside the registry is refused: the SDK calls only
the contracts it was written against. `--file` sends the file with
the media type of its extension; `--artifact` sends an id the Toolbox already
stores.

**Endpoints and timeouts.** Repeat `--endpoint` for independent deployments:
`catalog` reads the first; the other commands try them in order, like the
clients, and report each endpoint they leave on standard error as a
`warning:` line, even when a later one succeeds (ADR-0006). `--timeout` sets
the per-request timeout; without it, `catalog` uses 10 s and the other
commands the clients' default, since a capability can run for minutes.

**Exit status:** 0 on success; 1 when the Toolbox or the file system fails,
with the typed error (such as `ToolboxTimeout`) on standard error; 2 for
invalid arguments, checked before any request (an endpoint URL the HTTP client
cannot use, an unknown or `rest` capability for `run`, a malformed id, a
missing input file, `--parameters` that is not a JSON object).

## Adding a capability

1. Select it in `_CAPABILITIES` with `_selected(id, version, label,
   transport=..., provider_key=...)`: these are the SDK's own choices. Then run
   `python scripts/generate_sdk_bindings.py` in the core, which writes the
   capability's output schema and `idempotent` from the Toolbox's published
   contract (`tests/fixtures/toolbox-contract.json`, refreshed with
   `scripts/capture_toolbox_contract.py --ref <ref>`) into the generated block
   of `capabilities.py`. That block is never edited by hand (ADR-0004, #213);
   a test fails while it is stale or when the contract does not publish the
   selected version. A new provider key also needs an entry in
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
