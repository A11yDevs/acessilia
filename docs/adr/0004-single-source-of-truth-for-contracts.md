# 0004. One source of truth per contract

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](0004-single-source-of-truth-for-contracts.pt-br.md)

- **Status:** Accepted
- **Date:** 2026-10-18
- **Components:** core, SDK, docstruct, Toolbox
- **Issues:** [#152](https://github.com/A11yDevs/acessilia/issues/152) (P7)

## Context

The same models exist in several places. Examples:

- The Processing Manifest 1.1 models and schema exist in both the core
  (`backend/core/manifest/models.py`, `schema.py`) and the Toolbox
  (`core/normalization/`).
- The layout vocabulary is defined by the Toolbox's docling layout provider
  and mapped back by hand in the core (`toolbox_layout_structurer.py`).
- The SDK keeps a hand-written allowlist of capability ids and versions.
  `scripts/check_capability_contract.py` compares it with the Toolbox
  catalogue.

Making the Toolbox depend on the SDK to share these types was considered and
rejected: the server would depend on its own client package and the two would
have to be released together.

## Decision

Each contract has exactly one owner. The others consume it and do not
redefine it:

| Contract | Source of truth | Consumers |
|---|---|---|
| Canonical document models and schemas (canonical document, manifest structure, tables, geometry) | **docstruct** | core, SDK, Toolbox |
| Operational API contracts: capability manifests, input and output schemas, `ArtifactRef`, jobs, errors | **Toolbox**, published as OpenAPI and JSON Schema | SDK (and, through it, the core) |
| Client-side contract bindings (allowlist, typed results) | **SDK**, derived from the Toolbox's published contracts, preferably generated, never edited by hand once generation exists | core |

- The Toolbox keeps depending on docstruct and does not depend on the SDK.
- The core uses the SDK's public interfaces and does not redefine contracts.
- `scripts/check_capability_contract.py` verifies that the contracts the SDK
  consumes match the ones the Toolbox publishes (ids, exact versions,
  providers). Compatibility is exact: a new major version is a new contract.
- A separate `acessilia-contracts` package is considered only if a concrete
  need appears that this split cannot meet.

## Consequences

- Duplicated models move to their owner. The manifest builder is first split
  into models, pure algorithms and integrations, and only then migrated; it is
  not moved wholesale. This is tracked in the #152 audit.
- The SDK's hand-written allowlist stays until generation from the Toolbox
  schemas exists; the contract script keeps it honest meanwhile.
- docstruct releases are coordinated: the Toolbox pins a docstruct wheel by
  version and hash. Today the core (editable, from `libs/docstruct`) and the
  Toolbox (wheel and SHA-256 in `pyproject.toml` and `uv.lock`) both use
  0.4.0. That release carries the manifest's document model
  (`docstruct.manifest`). The core's and the Toolbox's wire models are
  checked against it in each repository's contract test, and the two publish
  the same 1.1.0 schema
  ([#203](https://github.com/A11yDevs/acessilia/issues/203)).
