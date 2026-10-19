# Acessilia libraries

Shared Python packages that live in this repository, next to the core (`backend`).

> Also available in **Brazilian Portuguese**: [Portuguese version](README.pt-br.md)

| Package | Directory | In one sentence |
|---|---|---|
| `acessilia-docstruct` | [docstruct/](docstruct/) | **What** is computed on a document: pure structural algorithms. |
| `acessilia-sdk` | [sdk/](sdk/) | **How** the core asks the Toolbox to run an operation: contracts, HTTP transport, clients, artifact references and failover. |

## docstruct vs. SDK

| | **acessilia-docstruct** | **acessilia-sdk** |
|---|---|---|
| **What it is** | Document structure algorithms: canonical types (`CanonicalDocument`, `BBox`…), reading order, multi-provider fusion, text and LaTeX normalization, tables, validation | Uniform access to Toolbox capabilities: contract registry, HTTP transport (`execute_capability`), clients, catalog, errors, artifact references, retries and failover |
| **Nature** | Pure: no network, files, subprocess or settings | Performs I/O: asynchronous HTTP client |
| **Dependencies** | None (`dependencies = []`) | `httpx` |
| **Consumers** | The core (`backend/pipeline`, `tools`, `export`…) **and the Toolbox**, which runs these algorithms on its side | The core only, to talk to the Toolbox |
| **Distribution** | Wheel published on a GitHub Release (`.github/workflows/docstruct-release.yml`, tags `docstruct-v*`); the Toolbox pins it by hash | Installed editable, inside this repository only |
| **Import guard** (`tests/test_purity.py`) | Must not import `backend`, `acessilia_toolbox` or `acessilia_sdk` | Must not import `backend` or `acessilia_toolbox` |

## Dependency direction

```
backend (core) ──→ acessilia-sdk ──HTTP contract──→ Toolbox
      │                  │                             │
      ▼                  ▼                             ▼
            acessilia-docstruct  ←─────────────────────┘
```

Dependencies only point downward: docstruct imports nothing above it, the SDK
never imports the core or the Toolbox package, and the Toolbox never imports
the SDK. The full matrix of responsibilities and allowed dependencies is in
[ADR-0002](../docs/adr/0002-component-responsibilities.md).

## Why docstruct is not part of the SDK

The separation is intentional, and the purity tests enforce it:

1. **The Toolbox depends on docstruct, not on the SDK.** Merging them would make
   the Toolbox install the SDK (and `httpx`, and the client code that calls the
   Toolbox itself) just to get the algorithms. The server would end up depending
   on its own client package.
2. **Purity is a contract.** docstruct has no dependencies and is forbidden from
   importing `acessilia_sdk`. Merging would mix deterministic, pure code with
   asynchronous I/O.
3. **They evolve at different paces.** docstruct has its own version, release
   tags and update procedure in the Toolbox; the SDK follows the Toolbox
   capability contracts. A single package would force a release of one whenever
   the other changes.

The intended relationship is the reverse: **the SDK may use docstruct's pure
algorithms in-process**, for example to build or validate canonical models.
That is not a local executor: operational capabilities (Pandoc, TeX Live,
veraPDF, PyMuPDF rendering, media inspection, OCR, AI models) run only in the
Toolbox, and the SDK has no local executors and no `[local]` extra for them
([ADR-0003](../docs/adr/0003-remote-only-operational-capabilities.md)).

## Tests

```bash
cd libs/docstruct && python -m pytest
cd libs/sdk && python -m pytest
```
