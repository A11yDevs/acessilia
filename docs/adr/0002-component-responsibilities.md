# 0002. Component responsibilities and dependency direction

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](0002-component-responsibilities.pt-br.md)

- **Status:** Accepted
- **Date:** 2026-10-18
- **Components:** core, SDK, docstruct, Toolbox
- **Issues:** [#150](https://github.com/A11yDevs/acessilia/issues/150), [#152](https://github.com/A11yDevs/acessilia/issues/152)

## Context

The ecosystem has four components. Their boundaries were mostly implicit, and
code drifted across them. For example, `media.inspect` was copied from the
Toolbox into the core and then diverged. The local PDF/UA path in the core
re-implemented, with less hardening, what the Toolbox sidecar already does.
`libs/README.md` justified keeping docstruct out of the SDK by "the Toolbox
depends on docstruct, not on the SDK", while an early draft of #152 allowed the
Toolbox to install the SDK.

## Decision

**One sentence:** the core decides and orchestrates; the SDK provides
interfaces and access; docstruct implements reusable structural algorithms; the
Toolbox executes operational capabilities.

| Component | Owns | Must not |
|---|---|---|
| **Core** (`backend/`) | Agents, PDDL planning, strategies, policies, workflows; when to call a capability, which profile, whether to degrade | Implement generic document algorithms or operational executors; import the Toolbox package; redefine contracts |
| **SDK** (`libs/sdk`) | Contracts as consumed by clients, Toolbox clients and transport, artifact references, availability and failover rules, in-process access to docstruct's pure algorithms | Hold planning policy or agent logic; require heavy operational dependencies; read settings or environment; import the core or the Toolbox package |
| **docstruct** (`libs/docstruct`) | Canonical document models and schemas, normalization, comparison, matching, fusion, structural validation: deterministic and infrastructure-free | Depend on the core, the SDK, the Toolbox, Docker, REST, MCP, the network, files, subprocesses or remote storage |
| **Toolbox** (separate repository) | Providers, conversion, rendering, OCR, validation, specialized processing; artifacts, jobs, sidecars; REST and MCP interfaces; the published operational contracts | Re-implement docstruct algorithms; depend on the SDK or on the core's agent logic; make semantic choices that belong to the core |

**Allowed dependencies** (arrows point to what is depended on):

```
core ──→ SDK ──(published HTTP contract)──→ Toolbox
  │        │                                   │
  └────────┴──────────→ docstruct ←────────────┘
```

- The core depends on the SDK and docstruct.
- The SDK depends on docstruct and on the Toolbox's **published contract**
  only (capability ids, versions, schemas), never on its package.
- The Toolbox depends on docstruct and nothing else from this ecosystem.
- docstruct depends on nothing in the ecosystem.
- Circular dependencies are forbidden.

**Interfaces.** One implementation may be exposed through several interfaces.
The core reaches Toolbox capabilities through the SDK, which speaks the
Toolbox's REST contract. MCP and REST bindings are generated from the same
capability metadata in the Toolbox (Toolbox constitution, principle 7).
docstruct is called as a Python library.

**Where does new code go?** Ask in order:

1. Does it decide *what* to do or *when*: planning, policy, strategy, user
   flow? Then it goes in the **core**.
2. Is it a deterministic algorithm on document structure, with no I/O and no
   heavy dependency? Then it goes in **docstruct**.
3. Does it need an external tool, a model, a sidecar, storage or other
   infrastructure? Then it is a **Toolbox** capability or provider.
4. Is it about *how* to reach a capability: a client, a contract binding,
   error mapping, retries, artifact references? Then it goes in the **SDK**.

If two answers seem to apply, split the code along those lines (for example,
a pure classifier in docstruct and its Pillow/PyMuPDF adapter in a Toolbox
provider).

## Consequences

- **Enforced today:**
  - `tests/test_architecture_layers.py` (the core does not import the Toolbox).
  - `libs/docstruct/tests/test_purity.py` (docstruct does not import the core,
    the SDK or the Toolbox, declares no runtime dependency, and imports
    nothing outside the standard library except guarded optional
    accelerators such as `rapidfuzz`).
  - `libs/sdk/tests/test_purity.py` (the SDK does not import the core or the
    Toolbox, and its dependencies stay within `httpx` and docstruct).
- **Planned in #152:**
  - a Toolbox test forbidding `acessilia_sdk` and `backend` imports.
- **Known deviations, tracked in [#203](https://github.com/A11yDevs/acessilia/issues/203):**
  - The core still runs two operational executors, the `reportlab` PDF
    renderer and the `edge-tts` audio exporter (see
    [ADR-0003](0003-remote-only-operational-capabilities.md)).
  - The manifest's semantic models exist both in the core and in the Toolbox.
  - Callout clustering is implemented both in the Toolbox's normalization
    builder and in `docstruct.regions.grouping`.
  - Some pure algorithms still have a copy in the core next to docstruct:
    the export profiles, the conservative LaTeX normalization and the
    reading order of the manifest builder.
  - Media classification is no longer duplicated: `media.inspect` runs only
    on the Toolbox since #160. It inspects media and artifacts, which is a
    different job from `docstruct.regions.classify`, which classifies
    structural regions.
