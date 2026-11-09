# Changelog

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](CHANGELOG.pt-br.md)

The SDK is a public API for scripts and benchmarks (#402). Changes that a caller
can see are recorded here, newest first.

## Unreleased

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
