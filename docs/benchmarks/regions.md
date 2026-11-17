# Benchmark measurement regions

> PT-BR version: [measurement regions](regions.pt-br.md)

This map describes what the Core can measure today and the contracts needed
before adding stage-level capture. It does not introduce a second public
benchmark runner.

## Current regions

| Region | Current owner | Observed work | Boundary |
|---|---|---|---|
| Dataset input | `scripts/bench/datasets/` | Materialize and identify selected page images and available Markdown references | Dataset download time is outside the structure run |
| Structure harness | `scripts/bench/` and the Toolbox SDK | `document.structure.extract`, response-to-canonical conversion, and Markdown export per page | Does not run the Core planner/executor, visual enrichment, remote formula conversion/verbalization, or final product exports |
| Local page scoring | `docstruct.evaluation` | Local text, reading-order, TEDS and CDM approximations | Not an official benchmark result; CDM is diagnostic for the current improvement gate |
| Product scorecards | Core cases 036 and 006 | Product-level checks for their documented inputs and outputs | Separate from the Dr.DocBench structure harness |
| Public campaigns | `acessilia-benchmark` | Public datasets, official evaluators, campaign comparisons and Slurm orchestration | Campaign results and official protocols stay in that repository; Core `compare` is a local improvement gate only |

The current `run-manifest.json` identifies a page selection with SHA-256 hashes
of images and available references. It records the Core revision and dirty
source digest, SDK/docstruct package versions, sanitized endpoint origins and path hashes,
effective provider/timeouts/retries, output hashes, and page status. The API
key and document contents are not copied into this manifest. A requested raw
provider payload is stored as a run artifact under `BENCH_VAR`. Predictions and
raw payloads can contain document content; restrict access to that directory and
apply the dataset's retention policy. The harness does not expire artifacts.

For each page, the selection also records the input media type, byte size and
hash. The Core passes the original page image to the Toolbox without cropping or
transforming it; any transformation inside the Toolbox is not observable here.
If the local data tree has no Git revision, pass its pinned full commit SHA with
`run --dataset-revision`; mutable labels such as `main` are rejected. Without
one, comparison can report diagnostics but cannot return an accepted verdict.

The reported durations are caller-observed Toolbox-call time, post-call input
integrity-check time, and page wall time including conversion and artifact
writes. Toolbox-call time includes transport and waits. The current response
can include provider and model versions, duration and cache hit in its
provenance. Each call records those fields separately. On a hit, the reported
duration comes from the cached result. Queue wait, cache lookup duration,
effective cache policy and actual provider attempts/retries remain unobserved.

## Stage checkpoint contract

Future stage snapshots should use an explicit contract before capture is added:

- **Identity:** run id, dataset and revision, split, item/document/page id,
  input hash, and, for crops, coordinates and coordinate origin, original and
  crop dimensions/DPI, and the applied transform.
- **Representation:** stage id and version, media type, schema/version, and a
  content hash. The current structure protocol is `toolbox-structure@2` over a
  `document-page` unit.
- **Producer:** Core revision, Toolbox/SDK and stage implementation versions,
  effective non-secret configuration, and observed hardware/concurrency.
- **Lineage:** parent checkpoint ids and hashes, so a replay can prove which
  inputs produced each later representation.
- **Status:** `not_executed`, `running`, `completed`, `failed`, `cancelled`,
  `not_applicable`, or `absent` with a reason. Absence is legitimate only when
  the stage contract says the input does not call for that output.
- **Integrity:** write artifacts atomically, verify hashes on resume, and mark a
  run complete only after every selected item has valid required outputs.

| Stage | Input and unit | Output to freeze |
|---|---|---|
| Extraction | Source document or page window and selected provider | Provider response and normalized structured document with source page mapping |
| Fusion | Extraction snapshots for the same document window | Fused elements, primary/secondary lineage and merge decisions |
| OCR | Page or region image with its transform and language | Transcription and source coordinates when available |
| Visual description | Figure region, caption/context and prompt/model configuration | Description with the figure identity and enrichment status |
| Tables | Table region or normalized element | Table structure with cells, headers and spans |
| Mathematics | Formula region for recognition, then LaTeX for conversion and verbalization | Separate recognition, MathML and verbalization outputs linked to their inputs |
| Reading order | Stable element identities for the page or window | Ordered element identities with their original page mapping |
| Planner | Document observations and obligations with the planning strategy | Plan, obligation coverage and reported cost |
| Executor | Plan and input snapshots for its actions | Action results, attempts, failures and recovery outcomes |
| Export | Canonical document and selected format/options | Exported artifact and format/accessibility validation results |

Each future stage contract must assign a schema version to every captured
representation. Capture is opt-in and freezes independent snapshots before
downstream mutation. Test equivalence of the pipeline outputs with capture
enabled and disabled.

Checkpoint payloads can contain document text, images, or provider responses.
Keep those snapshots in the benchmark artifact store with an explicit
retention/access policy; observability events should contain identifiers,
status and timing, not document content.

Replay should consume recorded inputs and parent snapshots without calling a
provider. A replay report must identify its source run and report component
coverage and failures. It must not claim equivalence when a required snapshot
is absent or its hash/schema does not match.

## Dependencies and follow-up

Stage capture should wait for the Core Orchestrator modularization in #381, so
the capture boundary follows stable stage interfaces. The SDK boundary in #402
should provide public contracts to the external benchmark; external code
should not grow new imports of private Core modules. Runtime timing and cache
instrumentation from #370 should distinguish caller-observed duration, provider
duration, cache events and retries instead of inferring one from another.
This protocol records only its effective Toolbox configuration because it does
not run the Core processing pipeline. A future full-pipeline protocol should
reuse `processing_cache_configuration()` for Core processing settings.
Prefer offline replay or isolated runs over a shared production gateway. The
serial worker count is not an admission or user-capacity reservation; gateway
use needs an execution window and stop condition.

For the current implementation details, see the [coverage map](coverage-map.md)
and the [harness guide](../bench.md).
