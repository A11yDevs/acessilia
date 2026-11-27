# Toolbox runtime placement and first migration slices

Brazilian Portuguese: [português brasileiro](toolbox-runtime-placement.pt-br.md).

This is the evidence and implementation map for [ADR-0032](../adr/0032-toolbox-runtime-library-placement.md)
and [#913](https://github.com/A11yDevs/acessilia/issues/913). Source snapshots
on 2026-11-27: Acessilia `02678e5e` and
[Toolbox develop at `dac17c24`](https://github.com/A11yDevs/acessilia-toolbox/commit/dac17c24ad709398a49418f1eb71493b22816660).
This inventory describes source/configuration, not the health or image digests
of a running deployment. No benchmark or topology change is claimed.

The Core audit began at `02678e5e`. This documentation branch was rebased onto
`689e555b` (including #922/#923); the intervening changes cover duplication
documentation and formula deprecation shims/tests. The method classifications,
three SDK compositions and Docstruct pin were rechecked at that base. The
earlier hash records the audit baseline, not a claim that the branch predates
the rebase; Toolbox evidence remains pinned to `dac17c24`.

## Existing execution path

The Toolbox's [application factory](https://github.com/A11yDevs/acessilia-toolbox/blob/dac17c24ad709398a49418f1eb71493b22816660/src/acessilia_toolbox/api/app.py)
loads capability manifests and provider descriptors and injects an adapter
factory, artifact store and cache into `CapabilityExecutor`.

```text
Core chooses a semantic operation and its targets
  -> public SDK -> capability id/version and explicit provider, when needed
  -> CapabilityRegistry.get -> ProviderRegistry.resolve
  -> CapabilityExecutor -> create_adapter -> ProviderAdapter.execute
       -> local function / Docstruct algorithm
       -> or existing external provider contract
  -> result, observations, artifacts and provenance -> Core updates its state
```

The [executor](https://github.com/A11yDevs/acessilia-toolbox/blob/dac17c24ad709398a49418f1eb71493b22816660/src/acessilia_toolbox/core/executor.py)
binds the requested capability version, checks input, resolves a provider,
accounts for provider/component versions in its cache key, executes the
adapter, normalizes/publishes results and records provenance. Provider
resolution refuses an ambiguous choice instead of silently choosing a semantic
alternative. New runtime functions reuse this path and its manifest source;
there is no new routing catalogue.

REST uses bounded execution slots and a threadpool. The
[MCP facade](https://github.com/A11yDevs/acessilia-toolbox/blob/dac17c24ad709398a49418f1eb71493b22816660/src/acessilia_toolbox/api/mcp.py)
uses the same registries/executor; its tools currently select the latest
version. The HTTP app does not mount that facade as a Streamable HTTP endpoint.
Authenticated MCP and version binding remain [#632](https://github.com/A11yDevs/acessilia/issues/632),
[#639](https://github.com/A11yDevs/acessilia/issues/639) and
[ADR-0027](../adr/0027-mcp-core-toolbox-contract.md), not completed work here.

## Deployment and package inventory

| Existing unit | Execution and dependencies | Placement consequence |
|---|---|---|
| Toolbox API/executor process | Lightweight Python adapters, normalization and local algorithms. The default image installs the Toolbox wheel and Docstruct; optional extras select native/client dependencies. | Initial host for compatible bounded CPU operations; no extra server hop to call a local library. |
| Docling, MinerU and OCR/model sidecars | Separate images, endpoints and model volumes in Compose. | Keep their ML/GPU runtimes isolated; migrating a pure helper does not justify installing those runtimes in the API image. |
| Math, rendering and validation sidecars | `math-speech`, `pdf-ua-render`, `verapdf-validate`; gateway/upstream VLM configuration is separate. | Reuse specialized services through their current adapters; operational compositions need not add another sidecar. |
| Audio and music providers | `piper-tts` with its model volume; `audiveris-serve` under the optional `music` Compose profile. Package extras `audio` (`edge-tts`) and `music` (`homr`) are separate from those sidecars. | Reuse the existing providers. None of the initial migration targets requires these extras; the local Compose API build does not enable them. |
| MinIO and Valkey | Artifact storage and execution cache in Compose; filesystem fallback has an explicit mode. | These services do not establish durable task queues or authoritative workflow state. |

Sources: [Dockerfile](https://github.com/A11yDevs/acessilia-toolbox/blob/dac17c24ad709398a49418f1eb71493b22816660/Dockerfile),
[local Compose](https://github.com/A11yDevs/acessilia-toolbox/blob/dac17c24ad709398a49418f1eb71493b22816660/docker-compose.yml),
[production Compose](https://github.com/A11yDevs/acessilia-toolbox/blob/dac17c24ad709398a49418f1eb71493b22816660/docker-compose.production.yml),
[VLM deployment definition](https://github.com/A11yDevs/acessilia-toolbox/blob/dac17c24ad709398a49418f1eb71493b22816660/deploy/vlm-gateway/docker-compose.yml).
The local Compose build enables `api,storage,cache,pdf,media`; the production
file selects an approved image by digest, not a fresh dependency resolution.
Its actual installed extras must be established from that image's build.

| Package or namespace | Current state | Decision / migration obligation |
|---|---|---|
| `acessilia-docstruct` | Independent library; both snapshots use 0.5.8. Toolbox pins the release wheel by SHA-256 in [pyproject.toml](https://github.com/A11yDevs/acessilia-toolbox/blob/dac17c24ad709398a49418f1eb71493b22816660/pyproject.toml). | Keep it independent and install it in images that execute its algorithms; never copy its source into adapters. |
| `acessilia_toolbox.operations` | Not present in the inspected tree. | Create the internal package when the first migrated composition needs it; release/version it with the Toolbox. |
| `acessilia_toolbox.core.operations` | Existing operation-id joining and cooperative cancellation; process-local state. | Keep that distinct responsibility; it is not the document-operation runtime or a durable queue. |
| `acessilia_sdk.operations` | Three local compositions: formula, fusion and page judge. | Decompose and migrate through reviewed contracts. Keep compatibility until consumers move; do not make the server import its client package. |
| Core SDK and shared contracts | Core SDK split/MCP and the shared-contract ownership decision are pending. | Use the SDK's public `execute_capability` transport during transition; keep existing schema owners until an explicit contract decision. No new contracts package is imposed. |

The new runtime uses functions with explicit arguments/results and injected
I/O services. Validate public DTOs at the boundary using the existing models
and contracts; keep pure transforms independent of storage, settings and
workflow models. A request must identify its bounded targets and options;
result validation must reject missing/duplicate/unrequested ids before the
Core applies observations. Generic provider-output schema enforcement remains
[Toolbox #117](https://github.com/A11yDevs/acessilia-toolbox/issues/117).

## Boundaries for migrated compositions

These are requirements for new slices, not claims that the current runtime
already enforces every guarantee.

| Boundary | Rule and example |
|---|---|
| Internal function | Call a pure function directly, for example Unicode substitution or grayscale conversion. It needs neither a public capability nor a PDDL action of its own. |
| Bounded capability | A versioned batch normalization contract may compose private functions with explicit context/I/O. Reusing another public capability must preserve the validation, authorization, error, cancellation, provenance and cache guarantees its contract requires. Local reuse need not re-enter the executor or use loopback HTTP. |
| Core action/decision | Independently relevant preconditions/effects, obligation outcomes, strategy alternatives or acceptance/replanning needs make an operation a candidate planned action. Formula recognition and a separately needed MathML conversion can be distinct actions; technical preprocessing can stay inside recognition. Do not hide workflow choices inside a Python composition. |

Coordinate action granularity with #640 and proposed ADR-0029. A deployment
family does not determine the planning domain. Migrating `norm-fix` does not
require rewriting the entire planner first.

Provider/strategy choice belongs to the Core (including its explicit
configuration). Resolving a compatible implementation, selecting its available
instance or failing over infrastructure is allowed only under the authorized
operational policy, preserving semantic/provider/version constraints and
recording the implementation used. Availability cannot silently replace
Docling with MinerU or OCR with VLM. This does not accept the remaining scope
of [proposed ADR-0030](../adr/0030-providers-compete-per-capability.md).

A composition must not hold an admission slot while waiting for dependent work
in the same saturated pool. Define bounded admission and propagation of
timeouts/cancellation; a threadpool alone does not isolate CPU/GIL or memory.
Try bounded pools or processes before requiring a separate image/service,
using measured resource or security/isolation needs to justify the split.
This is preventive guidance, not a reproduced deadlock.

During 0.3.0, the Core may retain contract/data representations for coordination
under the [current import classification and allowlist](docstruct-import-inventory.md).
Existing non-contract imports stay pinned transitional debt; remove the
computational call and its allowance together when the capability replaces it.
Do not widen those exceptions or treat data access as permission for new local
algorithms. Full reference-only separation remains the #914 proposal.

## Initial migration map

These are logical execution families, not new service names. Entries below
are **migration candidates**, not newly registered capabilities. The current
Core still has 20 transitional and two validation methods in
[`LOCAL_METHODS`](../../libs/core/src/acessilia_core/planning/toolbox_gate.py).

| Core/SDK work | Suitable execution family and library | Contract status and Core responsibility |
|---|---|---|
| `norm-fix` | Existing lightweight process → new runtime function → `docstruct.text.norm_fix`. | First slice [#929](https://github.com/A11yDevs/acessilia/issues/929). New versioned normalization contract; Core selects targets and applies validated observations. |
| `unicode-repair`, `latex-normalizer`, `rep-guard`, `line-number-extractor`, `verse-chunker`, `pandoc-code`, `tailjoin`, `tailjoin-positioned`, `deterministic-heading-repair` | CPU text/structure functions from Docstruct, grouped only where contracts permit. | Audit existing `code.normalize@1`/`text.postprocess@1` for reusable primitives; no equivalent batch contract is demonstrated. Preserve context/evidence and keep eligibility/acceptance decisions in the Core. |
| `xycut-order`, `skeleton-order` | CPU layout functions (`docstruct.fusion.xycut`, `skeleton`). | Stable ids, boxes, source order and resulting order need an explicit contract. Core chooses which evidence/obligation to serve. |
| `agreement-rule`, `rescue-omitted`, `table-smart-fusion`; SDK fusion composition | CPU fusion/runtime plus existing extraction providers. | Reuse structural primitives; define fusion/route/provenance results and partial-failure semantics. Core owns quality policy and alternative selection. |
| `table-enrichment`, `pandoc-table` validation | Existing recognizers/VLM plus CPU AST normalization. | Reuse table capability work, including [Toolbox #170](https://github.com/A11yDevs/acessilia-toolbox/issues/170). An extracted table and a valid recognized table are not interchangeable without contract checks. |
| `picture-description`, `formula-recognizer`, `formula-region-classifier`, `vision-description` validation; SDK formula/page-judge compositions | Existing render/math/VLM providers plus bounded runtime composition. | Reuse `pdf.render`, `math.*` and `document.adjudicate.page` where their contracts fit. Core keeps candidate selection, thresholds, fallback and reclassification decisions; agents do not move to the Toolbox. |
| `inline-math-marker` | CPU font/span algorithms with the existing `document.text.spans` provider. | Preserve evidence, effective policy, invalidation and progress; Core owns target discovery and obligation transitions. |

`human-review` remains symbolic in the Core. `table-specialist` has no handler
and is not an available implementation. This decision does not change those
classifications or remove a transitional allowance before a migration works.

## First slice and acceptance gates

The existing [text provider](https://github.com/A11yDevs/acessilia-toolbox/blob/dac17c24ad709398a49418f1eb71493b22816660/src/acessilia_toolbox/providers/pure_text.py)
behind `text.postprocess@1` adds markers, deduplicates and emits processed text.
The original Core `norm-fix` handler preserves targets/ids and applies
ligature, soft-hyphen, NBSP and spacing repair, with protected table/formula
prefixes. That contract is not equivalent to `text.postprocess@1`.
[#929](https://github.com/A11yDevs/acessilia/issues/929) now uses the published
`document.text.normalize@1` / `docstruct-text@1.0.0` contract after Toolbox
#174/#177. The [consumer report](norm-fix-consumer.md) records atomic acceptance,
recovery, differential evidence and measured limits. Existing obligation
granularity is preserved; cross-obligation batching is tracked in #948.

Each slice must:

1. Publish compatible input/output/error contracts and a provider first;
   include runtime/provider/Docstruct versions in cache identity and provenance.
   Preserve old consumers and define new-consumer/old-Toolbox failure or
   explicitly authorized degradation and rollback, using existing capability
   requirements ([#848](https://github.com/A11yDevs/acessilia/issues/848)).
2. Prove algorithm, metadata, target/order and checkpoint equivalence. Keep
   source evidence separate from Core planning envelopes ([#908](https://github.com/A11yDevs/acessilia/issues/908)).
   A new capability takes bounded DTOs/references/options, never the complete
   `ProcessingManifest` with goals, obligations or attempts. It need not wait
   for all of #908; keep validators strict and schema identities unambiguous.
3. Specify repeat/recovery, side effects, timeouts, artifact retention/cleanup
   and publication rules, including response loss after execution. Distinguish
   job id, operation id, processed-input identity, cache key and any idempotency
   key; process-local joining/cache is not durable distributed idempotency.
   State batch item/byte, time and concurrency limits and cancellation boundaries.
4. Correlate observations with operation, target, processed content/context,
   capability version and provenance. Core must verify applicability before
   updating state, rejecting stale input/context even if ids still match;
   use relevant revisions/digests where needed, not an imposed global protocol.
   Reuse target checks from [#843](https://github.com/A11yDevs/acessilia/issues/843)
   and coordinate content invalidation with [#840](https://github.com/A11yDevs/acessilia/issues/840).
   Version effective internal algorithms/options that affect results and cache;
   an event for every private helper is not required.
5. Switch the public SDK call only when the capability exists; propagate
   typed failures without a local computational fallback. Preserve existing
   bounded admission and cancellation-before-publication semantics; do not
   claim hard preemption from a cancellation acknowledgment.
6. Close the missing Core-import guard in Toolbox #172 before publishing
   migrated runtime code. Shrink method/import allowances and verify isolated
   installs, contracts and differential outputs. Changes to `HARNESS_FILES` require the existing
   [reference-recording workflow](../../tests/differential/README.md).
7. Measure batch request count, serialized bytes, latency, CPU and memory before choosing
   a new deployment split or asserting a speedup. A placement decision alone
   is not evidence of output equivalence or better performance.

## Guard coverage and remaining owners

| Boundary / remaining work | Current coverage / owner |
|---|---|
| Core/backend → Toolbox internals | Existing `tests/test_architecture_layers.py` rejects these imports. |
| SDK → Core/Toolbox | Existing SDK purity/isolated-install checks. Keep them when client/runtime responsibilities separate. |
| Docstruct → infrastructure or upper layers | Existing Docstruct purity/infrastructure checks and isolated installation. |
| Toolbox → Core/SDK | [Existing guard](https://github.com/A11yDevs/acessilia-toolbox/blob/dac17c24ad709398a49418f1eb71493b22816660/tests/unit/test_architecture.py) forbids legacy SDK/backend/frontend roots but omits `acessilia_core`. Close that real gap in [Toolbox #172](https://github.com/A11yDevs/acessilia-toolbox/issues/172); do not report it as already enforced. |
| First operational migration | [#929](https://github.com/A11yDevs/acessilia/issues/929); the remaining methods stay in umbrella [#804](https://github.com/A11yDevs/acessilia/issues/804). |
| SDK split, shared contracts and MCP | Existing [#639](https://github.com/A11yDevs/acessilia/issues/639), [#632](https://github.com/A11yDevs/acessilia/issues/632) and proposed ADRs 0027–0029; keep their ownership and review requirements. |
| Durable queues/workers and observation recovery | Existing #639/#640 work. `OperationRegistry`, MinIO and Valkey cache alone do not implement it. |

The bootstrap decision for 0.3.0 remains in force. Planning that bootstrap and
making the Core fully reference-only remain [#816](https://github.com/A11yDevs/acessilia/issues/816)
and [#914](https://github.com/A11yDevs/acessilia/issues/914), respectively.
