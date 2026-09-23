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

**Key point:** the core **has no provider registry**. The `provider` is just a string
sent in the form; the actual routing happens in the Toolbox `providers-config.yaml`.
Validation that a provider exists happens on the Toolbox side — when it fails, the core
receives `ToolboxCapabilityError` or `ToolboxContractViolation`.

### Exception hierarchy

All exceptions inherit from `ToolboxError` (defined in `backend/tools/toolbox_client.py`):

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

| Aspect | Local tool (`libs/`) | Toolbox tool |
|---|---|---|
| **Where it runs** | In the core process (same machine/container) | Remote HTTP service (`TOOLBOX_BASE_URL`, port 8002) |
| **Examples** | `libs/docstruct/` — `docstruct.fusion`, `docstruct.policy.FusionPolicy`, `docstruct.types.CanonicalBlock`; PyMuPDF fallback in `backend/tools/structurer.py` | `document.structure.extract`, `document.layout.analyze`, `document.ocr`, `math.*`, `pdf.split` |
| **Interface** | Direct Python import (pure function/class) | `ToolboxClient` / specialized clients → `POST /v1/capabilities/{capability}:execute` |
| **Failure** | Local Python exception | `ToolboxError` → typed subclasses |
| **State/cache** | In memory / local disk | Artifact store (`/v1/artifacts`) + remote cache (`cache_key` in provenance) |
| **Versioning** | Coupled to the core repo (same commit) | Independent (`provider_version` in provenance) |

### 2.2 Decision policy

**Implement locally (`libs/`) when:**

- It is a pure transformation over already-canonical data (block fusion, grouping,
  decision policies) — no network I/O needed.
- It must run offline / without a network dependency.
- It needs a deterministic guarantee and atomic versioning with the core.

**Expose via the Toolbox when:**

- It requires heavy model/infra (GPU, OCR engines, docling-serve, mineru-serve).
- It makes sense to share among multiple consumers (core, drbench, future clients).
- It evolves on its own cadence (e.g. swapping the MinerU version without touching the core).

### 2.3 The bridge: wrapper with local fallback

When a Toolbox capability has a local equivalent, the core uses an **Agno tool wrapper
with local fallback**: it tries the Toolbox first and, if it is unavailable, degrades to
the local implementation. This is exactly the pattern of `toolbox_ocr_tools.py`,
`toolbox_math_tools.py`, and `toolbox_pdf_tools.py`.

```
                    ┌─────────────────────────────┐
                    │  Agno tool (wrapper)        │
                    │  backend/tools/toolbox_*_tools.py │
                    └──────────────┬──────────────┘
                       tries        │
                       Toolbox      ▼
                    ┌──────────────┐   failure → ┌──────────────────┐
                    │ ToolboxClient │──────────▶│ Local impl        │
                    │ (remote)      │            │ (libs/)           │
                    └──────────────┘            └──────────────────┘
```

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

- Unit: `tests/test_toolbox_client.py` (respx mock) — verifies the provider is sent in
  the form and that HTTP errors map to typed exceptions.
- E2E: `tests/test_toolbox_e2e.py` (`e2e` marker) — against a real `TOOLBOX_BASE_URL`.

---

## 4. Scenario B — New capability (new endpoint)

When the Toolbox exposes a **new capability** (e.g. `document.layout.analyze`), the core
needs a specialized client. Follow the `toolbox_layout_client.py` pattern:

### 4.1 Specialized client

Create `backend/tools/toolbox_<x>_client.py`:

```python
"""Specialized client for the <capability> Toolbox capability."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from backend.config.settings import settings
from backend.tools.toolbox_client import (
    ToolboxContractViolation,
    ToolboxProviderUnavailable,
    ToolboxTimeout,
    _media_type,
    _raise_for_error,
)

CAPABILITY = "<capability>"
EXECUTE_PATH = f"/v1/capabilities/{CAPABILITY}:execute"


class Toolbox<X>Client:
    """Client for <capability> via the Acessilia Toolbox."""

    def __init__(
        self,
        base_url: str | None = None,
        provider: str | None = None,
        timeout_seconds: int | None = None,
        api_key: str | None = None,
    ) -> None:
        self.base_url = (base_url or settings.toolbox_base_url).rstrip("/")
        self.provider = provider or settings.toolbox_provider
        self.timeout_seconds = timeout_seconds or settings.toolbox_timeout_seconds
        self.api_key = api_key if api_key is not None else settings.toolbox_api_key
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(self.timeout_seconds),
            headers=headers,
        )

    async def execute(
        self,
        file_path: Path | None = None,
        artifact_id: str | None = None,
        *,
        language: str = "pt-BR",
        use_remote_cache: bool | None = None,
    ) -> dict[str, Any]:
        if file_path is None and artifact_id is None:
            raise ValueError("Provide file_path or artifact_id")

        url = f"{self.base_url}{EXECUTE_PATH}"
        try:
            if artifact_id:
                data: dict[str, Any] = {
                    "artifact_id": artifact_id,
                    "language": language,
                    "provider": self.provider,
                }
                if use_remote_cache is False:
                    data["no_cache"] = True
                response = await self._client.post(url, data=data)
            else:
                with open(file_path, "rb") as f:
                    files = {"file": (file_path.name, f, _media_type(file_path))}
                    params: dict[str, Any] = {
                        "language": language,
                        "provider": self.provider,
                    }
                    if use_remote_cache is False:
                        params["no_cache"] = True
                    response = await self._client.post(url, files=files, data=params)

            _raise_for_error(response, CAPABILITY)
            result = response.json()
            if result.get("status") != "succeeded":
                raise ToolboxContractViolation(
                    f"{CAPABILITY}: unexpected status {result.get('status')!r}"
                )
            return result
        except httpx.TimeoutException as exc:
            raise ToolboxTimeout(f"{CAPABILITY}: timeout") from exc
        except httpx.HTTPStatusError as exc:
            raise ToolboxProviderUnavailable(
                f"{CAPABILITY}: HTTP {exc.response.status_code}"
            ) from exc
```

### 4.2 Agno tool wrapper (optional, with local fallback)

If a local equivalent exists, create `backend/tools/toolbox_<x>_tools.py` following the
`toolbox_ocr_tools.py` pattern: expose the capability as an Agno tool, try the Toolbox
first, and degrade to the local implementation on failure.

### 4.3 Pipeline integration (if applicable)

- **Structurer** (`backend/tools/structurer.py`): if the capability produces per-page
  regions, add a new structurer in `get_structurer()` (e.g. `toolbox-layout` →
  `ToolboxLayoutStructurer`).
- **Dual fusion** (`backend/pipeline/fusion.py`): if the capability produces canonical
  blocks, it can participate as a provider in `extract_fused()`.

### 4.4 Tests

- **Unit** (respx mock): `tests/test_toolbox_client.py`-style — verifies the mapping of
  HTTP errors to typed exceptions and the provider being sent.
- **E2E** (`e2e` marker): `tests/test_toolbox_e2e.py`-style — against a real
  `TOOLBOX_BASE_URL`; skipped if the variable is not set.

---

## 5. Configuration (environment variables)

Defined in `backend/config/settings.py` and documented in `.env.example`:

| Variable | Default | Description |
|---|---|---|
| `TOOLBOX_BASE_URL` | `http://localhost:8002` | Service base URL |
| `TOOLBOX_PROVIDER` | `docling` | Primary extraction provider |
| `TOOLBOX_API_KEY` | *(empty)* | Key for `Authorization: Bearer` |
| `TOOLBOX_TIMEOUT_SECONDS` | `3600` | Request timeout |
| `TOOLBOX_USE_ARTIFACT_STORE` | `true` | Upload the file to `/v1/artifacts` before extracting |
| `TOOLBOX_USE_REMOTE_CACHE` | `true` | Use the remote cache (`no_cache=false`) |
| `FUSION_MODE` | `single` | `single` (one provider) or `dual` (two providers + fusion) |
| `FUSION_SECONDARY_PROVIDER` | `mineru` | Secondary provider for `FUSION_MODE=dual` |
| `STRUCTURER` | `toolbox` | Per-page region engine (`toolbox`, `toolbox-layout`, `pymupdf`) |

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

- `backend/tools/toolbox_client.py` — base client and exception hierarchy
- `backend/tools/toolbox_layout_client.py` — Scenario B template
- `backend/tools/toolbox_ocr_tools.py`, `toolbox_math_tools.py`, `toolbox_pdf_tools.py` — wrappers with local fallback
- `backend/tools/structurer.py` — `get_structurer()` and structurer selection
- `backend/core/manifest/toolbox_extractor.py` — `ToolboxManifestExtractor`
- `backend/pipeline/fusion.py` — `extract_fused()` (dual fusion)
- `backend/config/settings.py` — Toolbox configuration
- `docs/drbench.md` — provider benchmark (Docling vs MinerU)