# Integrating Toolbox tools into the core

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](toolbox_integration.pt-br.md)

## Purpose

This guide explains how to integrate into the **core** (the Acessilia backend) a tool
that has just been made available in the **Acessilia Toolbox** — the remote service
that exposes capabilities for structure extraction, layout, OCR, math, and PDF. It
distinguishes the two possible scenarios and defines the implementation policy between
**local tools** (`libs/`) and **Toolbox tools**.

> The Toolbox lives in a separate repository (`A11yDevs/acessilia-toolbox`). This
> document covers **only the core side**: how to consume a new capability, not how to
> implement the capability in the Toolbox.

---

## 1. Toolbox contract as seen by the core

The core talks to the Toolbox over HTTP. All clients live in `backend/tools/` and share
the same pattern:

| Endpoint | Method | Use |
|---|---|---|
| `/v1/health` | `GET` | Availability check |
| `/v1/capabilities` | `GET` | Discover available capabilities and providers |
| `/v1/capabilities/{capability}:execute` | `POST` | Execute a capability (form: `file` or `artifact_id`, `language`, `provider`, `no_cache`) |
| `/v1/artifacts` | `POST` / `GET` | Upload / download artifacts (artifact store) |
| `/v1/datasets` | `GET` / `POST` | List and sync datasets |

A successful extraction response has the following shape:

```json
{
  "status": "succeeded",
  "provider": "docling",
  "provenance": {
    "duration_ms": 1234,
    "provider_version": "1.2.3",
    "cache_key": "abc123"
  },
  "document": {
    "elements": [
      {"type": "text", "text": "...", "bbox": [0, 0, 100, 50], "page": 1, "reading_order": 0, "page_size": [595, 842], "coord_origin": "top-left"}
    ]
  }
}
```

**Key point:** the core **does not register which providers exist**. Its only provider
table is `PROVIDER_DEFAULTS` in `libs/sdk/src/acessilia_sdk/toolbox/capabilities.py`, which holds the
default provider per capability. It does not list existing providers or route anything.
The `provider` is just a string sent in the form; the actual routing happens in the
Toolbox `providers-config.yaml`.
Validation that a provider exists happens on the Toolbox side — when it fails, the core
receives `ToolboxCapabilityError` or `ToolboxContractViolation`.

### Exception hierarchy

All exceptions inherit from `ToolboxError` (defined in the SDK, `acessilia_sdk.toolbox.errors`, and re-exported by `backend/tools/toolbox_client.py`):

- `ToolboxProviderUnavailable` — service/provider unavailable (e.g. HTTP 503)
- `ToolboxTimeout` — exceeded `toolbox_timeout_seconds`
- `ToolboxUnsupportedMediaType` — unsupported media type
- `ToolboxArtifactNotFound` — artifact does not exist
- `ToolboxContractViolation` — response does not meet the contract (e.g. `status != "succeeded"`)
- `ToolboxCapabilityError` — unknown capability/provider
- `ToolboxAuthenticationError` — invalid credentials

---

## 2. Local tools vs. Toolbox tools

### 2.1 Architectural difference

| Aspect | Library (`libs/docstruct`) | Toolbox capability |
|---|---|---|
| **Where it runs** | In the core process (same machine/container) | Remote HTTP service (`TOOLBOX_BASE_URL`, port 8002) |
| **Examples** | `libs/docstruct/` — `docstruct.fusion`, `docstruct.policy.FusionPolicy`, `docstruct.types.CanonicalBlock` | `document.structure.extract`, `document.layout.analyze`, `document.ocr`, `math.*`, `pdf.split` |
| **Interface** | Direct Python import (pure function/class) | SDK clients (`acessilia_sdk.toolbox.clients`) built with `make_toolbox_client` → `POST /v1/capabilities/{capability}:execute` or the artifact and dataset routes |
| **Failure** | Local Python exception | `ToolboxError` → typed subclasses |
| **State/cache** | In memory / local disk | Artifact store (`/v1/artifacts`) + remote cache (`cache_key` in provenance) |
| **Versioning** | Coupled to the core repo (same commit) | Independent (`provider_version` in provenance) |

### 2.2 Decision policy

The full guide is in [ADR-0002](adr/0002-component-responsibilities.md#decision).
In short:

**Implement in docstruct (`libs/docstruct`) when:**

- It is a pure, deterministic transformation over document structure (block
  fusion, grouping, reading order, validation), with no I/O and no heavy
  dependency.
- It needs a deterministic guarantee and versioned releases shared by the core
  and the Toolbox.

Running offline is not by itself a reason to execute an operational tool in the
core; that is an exception that needs an ADR.

**Expose via the Toolbox when:**

- It requires heavy model/infra (GPU, OCR engines, docling-serve, mineru-serve).
- It makes sense to share among multiple consumers (core, drbench, future clients).
- It evolves on its own cadence (e.g. swapping the MinerU version without touching the core).

### 2.3 No local fallback

Operational capabilities run only in the Toolbox: the production policy is
`remote_only`, and the core does not degrade to a local implementation when the
Toolbox is unavailable ([ADR-0003](adr/0003-remote-only-operational-capabilities.md)).
Availability comes from Toolbox replicas behind a load balancer and from the
SDK's bounded retries ([ADR-0006](adr/0006-availability-and-failover.md)). When
a capability stays unavailable, the core fails the step or degrades it visibly
as a business decision, and records the cause.

The "Toolbox first, local fallback" wrappers still in the code are **deviations
being removed** in [#150](https://github.com/A11yDevs/acessilia/issues/150):
the two Toolbox structurers. PDF/UA export and `media.inspect` no longer have
one: they run only on the Toolbox, and `toolbox_pdf_tools.py` is gone. Do not
copy that pattern into new code; a local or offline executor needs its own ADR.

---

## 3. Scenario A — New provider for an existing capability

When the Toolbox exposes a **new provider** for a capability the core already consumes
(e.g. a new `document.structure.extract` service), **no core code change is needed**.
Just:

1. **Register the provider in the Toolbox** (external repo): add the service to the
   Toolbox `providers-config.yaml`, mapping the provider name to the service endpoint
   (e.g. `docling-serve`, `mineru-serve`).
2. **Point the core at the new provider** via environment variable:

   ```bash
   # Primary structure-extraction provider
   TOOLBOX_PROVIDER=mineru

   # For dual fusion (FUSION_MODE=dual), secondary provider
   FUSION_SECONDARY_PROVIDER=mineru
   FUSION_MODE=dual
   ```

3. **Validate** that the Toolbox knows the provider:

   ```bash
   curl -s "$TOOLBOX_BASE_URL/v1/capabilities" | jq
   ```

### Verification

- Unit: `libs/sdk/tests/clients/test_structure.py` (respx mock) — verifies the provider is sent in
  the form and that HTTP errors map to typed exceptions.
- E2E: `tests/test_toolbox_e2e.py` (`e2e` marker) — against a real `TOOLBOX_BASE_URL`.

---

## 4. Scenario B — New capability (new endpoint)

When the Toolbox exposes a **new capability** (e.g. `document.layout.analyze`), the core
needs a specialized client in the SDK. Follow the pattern of
`libs/sdk/src/acessilia_sdk/toolbox/clients/layout.py`:

### 4.1 Register the capability and write a thin client

Every Toolbox call goes through `execute_capability`
(SDK, `libs/sdk`: `acessilia_sdk.toolbox.transport`), which refuses any capability that is not in
the registry. Adding a capability takes three steps.

**1. Declare it** in `libs/sdk/src/acessilia_sdk/toolbox/capabilities.py`:

```python
ToolboxCapability(
    "<capability>", 1, "<Label>",                # id, manifest version, error label
    provider_key="toolbox_<x>_provider",     # Settings attribute / TOOLBOX_<X>_PROVIDER
    output_schema="<schema>@1",                  # manifest output.schema
),
```

If the provider setting is new, add its default to `PROVIDER_DEFAULTS` and the
matching attribute to `Settings` (`os.getenv("TOOLBOX_<X>_PROVIDER",
provider_default("toolbox_<x>_provider"))`).

**2. Write the client** in `libs/sdk/src/acessilia_sdk/toolbox/clients/<x>.py`
and export it from `acessilia_sdk.toolbox.clients`. It reads no settings and
logs nothing. It subclasses `ToolboxCapabilityClient`, which
already owns the connections, the Bearer header, `health()`, `close()`, the
timeout/network error mapping, the response envelope check, bounded retries
and failover between independent Toolbox endpoints (see
[the SDK README](../libs/sdk/README.md#availability-and-failover)). A
capability that returns an artifact must call `_execute_on` and download it
with `download_artifact` through the HTTP client it returns, not through
`self._client`:

```python
"""Client for the <capability> Toolbox capability."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from acessilia_sdk.toolbox.client import ToolboxCapabilityClient

CAPABILITY = "<capability>"


class Toolbox<X>Client(ToolboxCapabilityClient):
    provider_key = "toolbox_<x>_provider"

    async def run(
        self,
        file_path: Path | None = None,
        artifact_id: str | None = None,
        *,
        use_remote_cache: bool | None = None,
    ) -> dict[str, Any]:
        return await self._execute(
            CAPABILITY,
            file_path=file_path,
            artifact_id=artifact_id,
            parameters={...},                      # optional, sent as JSON
            no_cache=use_remote_cache is False,
        )
```

**3. Build it in the core** with `make_toolbox_client` (`backend/tools/toolbox_client.py`).
It fills the endpoints, the provider from the `settings` attribute named by
`provider_key`, the timeout, the API key and a failover log hook; keyword
arguments override them:

```python
from acessilia_sdk.toolbox.clients import Toolbox<X>Client
from backend.tools.toolbox_client import make_toolbox_client

client = make_toolbox_client(Toolbox<X>Client)
try:
    result = await client.run(file_path=path)
finally:
    await client.close()
```

Client tests live in `libs/sdk/tests/clients/` and build the client with an
explicit `base_url`; tests of how the core configures it belong in
`tests/test_toolbox_client_factory.py`.

Text inputs use `upload=(filename, content_bytes, media_type)` instead of
`file_path` (see `acessilia_sdk/toolbox/clients/math.py`). `scripts/check_capability_contract.py`
reads the registry, so the new id is checked against the Toolbox catalogue
without further changes; `tests/test_toolbox_capability_registry.py` fails if a
client hard-codes an `:execute` route or uses an unregistered id.

### 4.2 Agno tool wrapper (optional)

To expose the capability to an agent, create `backend/tools/toolbox_<x>_tools.py`
that calls the client from 4.1 and turns `ToolboxError` into the tool's failure
result. Do not add a local implementation behind it (see 2.3).

### 4.3 Pipeline integration (if applicable)

- **Dual fusion** (`backend/pipeline/fusion.py`): if the capability produces canonical
  blocks, it can participate as a provider in `extract_fused()`.
- **PDDL method** (`backend/core/planning/toolbox_gate.py`): if a planning method's
  handler calls the capability, declare it in `METHOD_TOOLBOX_REQUIREMENTS`
  (capability and provider). The availability gate then checks it against the live
  catalogue before each document is planned (see below).

#### Availability gate

Before planning a document the orchestrator takes one catalogue snapshot
(`GET /v1/capabilities` + `/v1/providers`, cached for
`TOOLBOX_CATALOG_REFRESH_SECONDS`) and checks every requested method listed in
`METHOD_TOOLBOX_REQUIREMENTS`: the capability must be in the SDK allowlist, be
published with the exact contract version, and the configured provider must be
registered and implement it. The catalogue only restricts; it never makes a method
available.

| `TOOLBOX_AVAILABILITY_GATE` | Effect |
|---|---|
| `observe` (default) | Logs what would be removed and records it in `canonical_metadata.pddl_toolbox_availability`; the plan is unchanged |
| `enforce` | Removes those methods from the plan and from every replan of the document. When the catalogue cannot be read and the last good snapshot is older than `TOOLBOX_CATALOG_STALE_SECONDS`, every method with Toolbox requirements is removed (fail closed) |
| `off` | No check |

### 4.4 Tests

- **Unit** (respx mock): in `libs/sdk/tests/clients/`, like the existing client tests — verifies the mapping of
  HTTP errors to typed exceptions and the provider being sent.
- **E2E** (`e2e` marker): `tests/test_toolbox_e2e.py`-style — against a real
  `TOOLBOX_BASE_URL`; skipped if the variable is not set.

### 4.5 Concrete example: `media.inspect`

The `media.inspect` capability (provider `pure-media-inspect`, PR
`A11yDevs/acessilia-toolbox#33`) is consumed in the core with the Scenario B pattern:

- **Client:** `acessilia_sdk.toolbox.clients.ToolboxMediaInspectClient`
  (`ToolboxMediaInspectClient` → `POST /v1/capabilities/media.inspect:execute`).
- **Core wrapper:** `backend/tools/media_inspect.py` (`inspect_source_media`) calls
  only the Toolbox; there is no local fallback (ADR-0003, #150 F3). With
  `TOOLBOX_MEDIA_INSPECT_ENABLED=false` it returns `None` without calling the
  Toolbox, and a Toolbox failure raises `ToolboxError`.
- **Integration:** `backend/agents/pddl_orchestrator.py` calls
  `inspect_source_media()` after extraction and uses the `requires_visual_inspection`
  signal to inject a full-page `picture` element when the input is a standalone image
  with no visual blocks — ensuring the VisionAgent audiodescribes it.

  The signal only feeds this heuristic, so a failure of the step (any
  exception, not only `ToolboxError`) does not fail the job: the run continues
  without it, logs a warning and records the outcome in
  `manifest.extractor.configuration` (`media_inspection`: `toolbox`, `disabled`,
  `source_missing` or `failed`, plus `media_inspection_error` with the cause).
  The status and the cause also reach the document as
  `canonical_metadata.pddl_media_inspection` (`{"status": ..., "error": ...}`).

  A run degraded by a failure is **not cached** (the payload carries
  `cacheable: false`): otherwise a transient Toolbox outage would replay a
  standalone image without its audio description after the Toolbox recovers.

The PDDL predicates `media_inspected`/`media_profile_classified` belong to the Toolbox
domain; the core consumes the signal only as an enrichment heuristic and it does not
enter the planning problem.

---

## 5. Configuration (environment variables)

Defined in `backend/config/settings.py` and documented in `.env.example`:

| Variable | Default | Description |
|---|---|---|
| `TOOLBOX_BASE_URL` | `http://localhost:8002` | Service base URL; in production, the load balancer in front of the replicas (ADR-0006) |
| `TOOLBOX_BASE_URLS` | *(empty)* | Comma-separated URLs of independent Toolbox deployments, tried in order by the capability clients; empty means `TOOLBOX_BASE_URL` only |
| `TOOLBOX_PROVIDER` | `docling` | Primary extraction provider |
| `TOOLBOX_API_KEY` | *(empty)* | Key for `Authorization: Bearer` |
| `TOOLBOX_AVAILABILITY_GATE` | `observe` | Availability gate: `observe`, `enforce` or `off` (section 4.3) |
| `TOOLBOX_CATALOG_REFRESH_SECONDS` | `60` | How long a catalogue snapshot is reused |
| `TOOLBOX_CATALOG_STALE_SECONDS` | `900` | How long the last good snapshot is served when the catalogue cannot be read |
| `TOOLBOX_TIMEOUT_SECONDS` | `3600` | Request timeout |
| `TOOLBOX_RETRIES` | `1` | Retries on the same endpoint after a timeout or an unavailable instance (503/504), for every capability client; `0` disables them (ADR-0006). A timeout is retried too, so the worst case for a hung call is `TOOLBOX_TIMEOUT_SECONDS × (TOOLBOX_RETRIES + 1)` per endpoint in `TOOLBOX_BASE_URLS` (2 h per endpoint with the defaults) |
| `TOOLBOX_RETRY_BACKOFF_SECONDS` | `0.5` | Base of the exponential backoff between retries, with jitter |
| `TOOLBOX_USE_ARTIFACT_STORE` | `true` | Upload the file to `/v1/artifacts` before extracting |
| `TOOLBOX_USE_REMOTE_CACHE` | `true` | Use the remote cache (`no_cache=false`) |
| `TOOLBOX_MEDIA_INSPECT_PROVIDER` | `pure-media-inspect` | Provider for the `media.inspect` capability |
| `TOOLBOX_MEDIA_INSPECT_ENABLED` | `true` | Run `media.inspect` on the Toolbox or skip it. There is no local fallback: when `false`, the step is skipped; a Toolbox failure is logged and recorded in the manifest, the run continues without the standalone-image signal, and the degraded result is not cached |
| `TOOLBOX_PDF_UA_PROVIDER` | `pandoc-pdf-ua` | Provider for the `document.export.pdf_ua` capability |
| `TOOLBOX_PDF_UA_ENABLED` | `true` | Render PDF/UA on the Toolbox (pinned Pandoc + TeX Live) or skip it. There is no local fallback: when `false`, the worker skips the format without an error; a Toolbox failure is reported as an optional export error |
| `TOOLBOX_PDF_UA_TIMEOUT_SECONDS` | `300` | How long to wait for the Toolbox render before the export is reported as an optional error |
| `FUSION_MODE` | `single` | `single` (one provider) or `dual` (two providers + fusion) |
| `FUSION_SECONDARY_PROVIDER` | `mineru` | Secondary provider for `FUSION_MODE=dual` |
| `STRUCTURER` | `toolbox` | Unused: it chose the region engine of the legacy pipeline, which has been removed. It is still part of the cache key and is due to be removed |
| `TOOLBOX_PAGE_OCR_PROVIDER` | `qwen3-vl-8b` | Whole-page VLM transcription (`document.ocr.page`) |
| `TOOLBOX_ADJUDICATE_PROVIDER` | `qwen3-vl-8b` | Pairwise judge / region transcription (`document.adjudicate.*`) |
| `TOOLBOX_TABLE_PROVIDER` | `qwen3-vl-8b` | Table re-generation for the table specialist (`table.recognize`) |
| `TOOLBOX_ORIENTATION_PROVIDER` | `rapidocr-orient` | Rotation detection (`image.page.orient`) |
| `FUSION_HYBRID_PROVIDER` | `mineru-hyb` | MinerU hybrid-VLM provider id (the B source of the confirmed leaderboard best) |

> `TOOLBOX_USE_ARTIFACT_STORE` and `TOOLBOX_USE_REMOTE_CACHE` directly affect the
> extraction flow: with the artifact store on, the core uploads the file once and
> reuses the `artifact_id`; with the remote cache on, the Toolbox can answer from
> `cache_key` without reprocessing.

---

## 6. Full flow (core → Toolbox)

```
service.py: _build_orchestrator()
  └─ PddlAccessibilityOrchestrator(extractor_backend="toolbox")
       └─ ToolboxManifestExtractor (backend/core/manifest/toolbox_extractor.py)
            ├─ [artifact store] upload_artifact() → /v1/artifacts
            └─ extract_structure(artifact_id=..., use_remote_cache=...)
                 → POST /v1/capabilities/document.structure.extract:execute
                 → ToolboxExtraction (configuration: toolbox_base_url, provider, artifact_id, cache_key)
       └─ InformationalStructuralAgent.process() → manifest
       └─ PlannerAgent → ExecutorAgent (MethodRegistry)
```

---

## 7. Code references

- `libs/sdk/src/acessilia_sdk/toolbox/` — capability registry, transport, client base class, failover, artifacts and exception hierarchy (SDK)
- `libs/sdk/src/acessilia_sdk/toolbox/clients/` — one client per capability family; `layout.py` is the Scenario B template
- `backend/tools/toolbox_client.py` — `make_toolbox_client` (SDK clients configured from the core settings) and the re-exported error types
- `clients/structure.py`, `clients/artifact.py`, `clients/dataset.py` — structure extraction, the artifact store and the dataset routes
- `backend/tools/toolbox_ocr_tools.py`, `toolbox_math_tools.py` — Agno wrappers over the OCR and math clients
- `clients/page_ocr.py` — `document.ocr.page` (whole-page VLM)
- `clients/adjudicate.py` — `document.adjudicate.page` / `.region`
- `clients/orientation.py` — `image.page.orient`
- `backend/core/manifest/toolbox_extractor.py` — `ToolboxManifestExtractor`
- `backend/pipeline/fusion.py` — `extract_fused()` (dual fusion)
- `backend/config/settings.py` — Toolbox configuration
- `docs/drbench.md` — provider benchmark (Docling vs MinerU)

### 7.1 Capabilities added for Dr.DocBench (PR #125)

| Capability | Client | Providers | Purpose |
|---|---|---|---|
| `document.ocr.page` | `ToolboxPageOcrClient` | `qwen3-vl-8b` | Whole-page VLM transcription — the B source of the page hybrid |
| `document.adjudicate.page` | `ToolboxAdjudicateClient` | `qwen3-vl-8b` | Pairwise judge between two candidate transcriptions (both orders, position debiasing); used by the `vlm-pairwise-judge` method |
| `document.adjudicate.region` | `ToolboxAdjudicateClient` | `qwen3-vl-8b` | Exact transcription of a region crop, turned into a differ decision |
| `table.recognize` | `ToolboxTableClient` | `qwen3-vl-8b` | Greedy plus seeded HTML generations of a table crop, for the table specialist |
| `image.page.orient` | `ToolboxOrientationClient` | `rapidocr-orient` | Rotation 0/90/180/270 detection |

The provider registrations live in the Toolbox repository; the Dr.DocBench job
config that mirrors them is `scripts/drbench/experiments/slurm/providers-config-vlm.yaml`.

`mineru-hyb` (MinerU 3.x, `backend=hybrid-engine`) is registered as a
`document.structure.extract` / `document.layout.analyze` / `document.ocr`
provider. It is the B source of the confirmed leaderboard best
(`differ-v15-hyb`, EvalAI 70.37): the real test gain came from reading order
(+16.4) with this source, not from TEDS. Adopt it explicitly with
`FUSION_SECONDARY_PROVIDER=mineru-hyb`; the dual-fusion default stays `mineru`.