# Benchmark ownership and coverage map

> Brazilian Portuguese version: [mapa de responsabilidades e cobertura](coverage-map.pt-br.md)

## Ownership

| Concern | Owner | Core contract |
|---|---|---|
| Core product behavior and product scorecards 036/006 | Acessilia Core | Keep product checks with the product pipeline they exercise |
| Structure-only page run | `scripts/bench` in Core | Measure Toolbox structure extraction, canonical conversion and Markdown export only |
| Reusable local page metrics | `libs/docstruct/src/docstruct/evaluation` | Label them as local approximations and version their scoring protocol |
| SDK access to Toolbox | `acessilia-sdk` public interfaces | Keep benchmark clients on public SDK contracts as #402 progresses |
| Public benchmark datasets and campaign orchestration | `acessilia-benchmark` | Own public dataset definitions, official evaluators, campaign comparisons and Slurm workflows |
| Stage capture and replay | Follow-up after Core #381 and runtime instrumentation #370 | Capture stable stage inputs/outputs without importing `scripts/bench` into runtime code |

Core's structure harness does not implement a parallel campaign system. Public
benchmark code should use the Core/SDK public interfaces; until #402 completes,
the remaining private-module imports are a cross-repository follow-up. Core now
smoke-tests the pinned external adapter revision `810c748` against the current
checkout with local Toolbox and pipeline-service stubs. Temporary Core
compatibility shims preserve the removed `backend.tools.toolbox_client` import
and snapshot `CoreConfig` from settings when the legacy adapter omits it; calls
inside Core must still pass their job config explicitly. The adapter should
migrate to stable Core/SDK APIs and supply that per-job config before these
shims can be removed. The external README records these responsibilities.

Core's `scripts.bench compare` remains a local improvement gate for the
structure harness. It does not own public campaign comparisons or replace the
external benchmark's comparison and official-evaluation workflow.

## Run and comparison coverage

Every run should identify the expected page selection and record, per item,
input/reference hashes, status, observed call and page durations, and hashes of
required outputs. A run is complete only if all selected pages completed and
their required output artifacts still match their recorded hashes.

The score report counts expected and executed pages, failures, reference pages
that can be scored, and scorable item ids per local metric. Comparison requires
matching dataset/revision, selection, references, unit, evaluator protocol and
metric coverage. Duplicate item ids or document/page windows invalidate the
comparison rather than silently replacing a row. A partial or legacy run can
still provide diagnostic scores, but it cannot receive an accepted verdict.

The current `scripts.bench compare` gate is an **improvement** gate: tune must
gain, holdout must not regress, and no gated metric may exceed the configured
loss tolerance. It is not a parity gate. The gate includes text, reading order
and TEDS; CDM is reported for diagnosis and excluded from this gate. Product
parity checks such as the math case remain separate: `math_case compare` names
its parity gate, while the slide-case comparison for 006 is diagnostic only. A
local gate never substitutes for an official evaluator or campaign result.

The run manifest records only the configuration that applies to the selected
measurement protocol. This structure-only run does not call the Core processing
pipeline, so it does not use `processing_cache_configuration()`; a future
full-pipeline protocol must reuse that helper. If a materialized input tree has
no Git revision, provide its pinned full commit SHA to `run --dataset-revision`.
Mutable labels such as `main` are rejected. Without a recorded revision,
comparisons remain diagnostic and cannot receive an accepted verdict.

## Limits of current coverage

- The current harness measures `document.structure.extract`, canonical
  conversion and Markdown writing for one page at a time.
- It does not measure the planner, executor, visual enrichment, final product
  exports, or provider-only latency.
- The manifest keeps the Toolbox-reported provider and model versions, call
  provenance duration and cache hit when present. The Toolbox deployment
  revision, queue wait, cache lookup time and actual attempt counts remain
  unobserved.
- Stage-level checkpoints, offline replay and distributed campaign admission
  remain follow-up work; capture points depend on #381 and shared runtime
  telemetry on #370.
- The structure runner is serial, but this does not reserve capacity on a shared
  gateway. Prefer offline replay or isolated execution; a shared gateway needs
  an admission policy, execution window and stop condition.

See [measurement regions](regions.md) for the proposed checkpoint contract.
