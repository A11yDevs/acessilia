# Changelog

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](CHANGELOG.pt-br.md)

The SDK is a public API for scripts and benchmarks (#402). Changes that a caller
can see are recorded here, newest first.

## Unreleased

- **Added** `artifact_endpoint_urls(*clients)` and `one_artifact_endpoint(*clients)`
  (`acessilia_sdk.toolbox.artifacts`): the URLs a set of clients may address,
  and whether an artifact id can be shared among them (at most one URL;
  ADR-0006, ADR-0013). They were private helpers of the core's extractor,
  which keeps the decision to upload or send the file (#402).
- **Added** `ToolboxDatasetClient.list_all_items(dataset_id, split, *,
  revision, limit, page_size)`: every item of a split, or the first `limit`,
  read page by page on one client (`MAX_PAGE_SIZE = 1000`, the Toolbox's cap);
  a failed page raises its typed error rather than returning a partial list.
  The benchmark harness pages with it (#402).
- **Added** `read_catalog` takes an optional `api_key`, used when the endpoint
  has no key of its own, as the capability clients do. The core's
  availability gate passes its clients' key with their primary endpoint
  (#402).
- **Added** `read_catalog(endpoint, *, timeout_seconds)`
  (`acessilia_sdk.toolbox.catalog`): reads one endpoint's catalogue on a
  short-lived HTTP client, with the caller's per-request timeout and no
  retries. The core's availability gate uses it instead of building its own
  client (#402).
- **Added** `ArtifactReference` (`acessilia_sdk.toolbox.reference`), the
  published `artifact/reference@1`, generated from the Toolbox's schema;
  `parse_reference`, which also checks `digest == artifact_id`; and
  `ToolboxArtifactClient.upload_reference`. `upload()` and `ArtifactRef.parse`
  are unchanged (#185).
- **Changed** The registry's `output_schema` and `idempotent` are generated
  from the Toolbox's published contract by the core's
  `scripts/generate_sdk_bindings.py` (#213); the allowed ids, versions,
  transports, provider keys and labels stay hand-written in `_selected(...)`.
  `TOOLBOX_CAPABILITIES` is unchanged, field by field.
- **Changed** Retries and failover apply only to capabilities the registry
  marks `idempotent` (ADR-0006, #406). After a timeout or an unavailable
  instance, a call to `dataset.sample` gets one attempt on the first endpoint
  and raises that attempt's error; it was re-sent before, to the same and to
  another endpoint. Idempotent capabilities keep their retries, backoff and
  failover.
- **Changed** `ToolboxCapability` has a required keyword field `idempotent`,
  the manifest's `execution.idempotent` at `contract_version`. Every registry
  entry sets it; only `dataset.sample` is `False` (#406). A caller that builds
  its own `ToolboxCapability` must pass it.

## 0.2.0 (2026-11-09)

- **Added** `ToolboxClientConfig` and `make_client` (`acessilia_sdk.toolbox.config`,
  also exported from `acessilia_sdk.toolbox`). A caller builds every client
  setting as an explicit value and gets a configured client, with no core
  install. The core's `make_toolbox_client` now delegates to it; the clients it
  builds are unchanged (#402, step 1).
- **Added** a test that fails if any SDK module reads the process environment
  (`os.environ`, `os.getenv`, through any name `os` is imported as), as
  ADR-0002 requires.
- `acessilia_sdk.__version__` reports 0.2.0, and a test keeps it equal to the
  version in `pyproject.toml`.

## 0.1.0

The first version, before this changelog: the capability registry, the
transport, the per-capability clients, endpoints and failover, artifacts, the
catalogue, the VLM gateway helpers and `run_sync`.
