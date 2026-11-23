# Classification: the core's agents (#735 phase 4, ADR-0029)

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](core-agent-classification.pt-br.md)

[ADR-0029](../adr/0029-symbolic-core-every-step-planned.md) classifies the
agents in `acessilia_core.agents` as strategic or operational:

- **Strategic agents stay in the core.** They interpret goals, decompose
  tasks, choose strategies, coordinate subplans, evaluate state and goals,
  decide to replan, and host the future LLM + planning integration (#619).
- **Operational agents become Toolbox capabilities.** They do OCR and
  semantic extraction, document classification, image description, visual
  adjudication, table and formula extraction, and multimodal processing.

This page classifies every module in `libs/core/src/acessilia_core/agents/`
([#768](https://github.com/A11yDevs/acessilia/issues/768)). The classification
is kept as data in
[`tests/fixtures/core_agent_classification.json`](../../tests/fixtures/core_agent_classification.json),
and `tests/test_architecture_layers.py` keeps the directory, the data and this
page in step.

## Summary

Measured on `develop` at `a1a68a7b`.

- **8 agents: 0 strategic, 8 operational.** This closes #735's indicator
  "Agentes do Core classificados" (8/8).
- **The strategic functions are not in `agents/`.** Planning, coordination,
  state evaluation and replanning live in `planning/`, `execution/` and
  `pipeline/` (see [Where the strategic functions are](#where-the-strategic-functions-are)).
  They stay in the core, and none of them is an agent of this directory.
- **Only two agents call a model:** `VisionAgent` and `DataAgent`. With
  `AI_CLIENT=toolbox` (ADR-0012) the call itself already goes through the
  Toolbox; the prompts, the validation of the answer, the retries and the
  region cache still run in the core.
- **The Agno envelopes do not run in production.** Six agents wrap
  deterministic methods (`process`, `process_*`) in an Agno agent
  (`build_agent`). No production code runs that agent (`.agent.run`); the
  pipeline calls the methods directly.
- **Four agents have no caller in the pipeline.** `AdjudicationAgent`,
  `OrderAdjudicationAgent`, `PageLevelAgent` and `TableSpecialistAgent` came
  with the Dr.DocBench work (#125). Only their unit tests and
  `tests/test_docs_pr125.py` use them.

## Agents

| Module | Class | What it does | Called by (pipeline) | Calls a model | Route |
|---|---|---|---|---|---|
| `agents/vision_agent` | operational | Image and region description, page and region inspection, formula reading | `pipeline/enrichment/pictures`, `pipeline/enrichment/formulas`, `pipeline/handlers/inspection` | yes | A model-backed Toolbox capability per use (image description, region inspection, formula reading), with its prompts, validation, retries and cache |
| `agents/data_agent` | operational | Validated extraction of tables and formulas from a region | `pipeline/enrichment/tables` | yes | A model-backed Toolbox capability for table and formula extraction |
| `agents/informational_structural` | operational | Extracts the document through the Toolbox, fuses the providers and builds the processing manifest | `pipeline/orchestrator` | no (Agno envelope only) | Extraction is already a Toolbox call. The local fusion and manifest assembly become a composite extraction capability. Deriving the obligations stays in the core (see below) |
| `agents/fusion_agent` | operational | Deterministic fusion, audit, classification, verse, tail join, repetition guard, normalization and reading order (`process_*`) | `pipeline/handlers/common`, for the plan-method handlers | no (Agno envelope only) | Each `process_*` leaves with the plan method that uses it, as part of the [docstruct inventory](docstruct-import-inventory.md)'s migration |
| `agents/adjudication_agent` | operational | Page routing between providers, VLM transcription decisions, the pairwise judge, the oracle | none | no (Agno envelope only) | Not migrated until a plan method needs it (see [Still open](#still-open)) |
| `agents/order_adjudication_agent` | operational | Parses and completes a VLM reading order; Kendall tau | none | no (Agno envelope only) | As above |
| `agents/page_level_agent` | operational | Whole-page fusion and selection, page agreement, upscale and orientation | none | no (Agno envelope only) | As above |
| `agents/table_specialist_agent` | operational | Generate, compare and adjudicate table candidates | none | no (Agno envelope only) | As above |

## Support modules

| Module | Class | What it is | Used by | Route |
|---|---|---|---|---|
| `agents/model_call_policy` | operational | The deadline margin of the vision and data model calls | `vision_agent`, `data_agent` | Moves with those agents |
| `agents/prompt_tools` | operational | Loads and assembles the vision and region prompts (`agents/prompts/`) | `vision_agent`, `data_agent` | Moves with those agents, with the prompts |
| `agents/output_schemas` | operational | Validated output contracts of the vision and data agents | the two agents, enrichment and the inspection handler | Moves with those agents; the result contract the core reads stays as a capability contract |
| `agents/run_helpers` | operational | Reads the result of an Agno run | `output_schemas` | Moves with `output_schemas` |
| `agents/agno_support` | infrastructure | Builds Agno agents when the optional stack is installed | the agents above, `planning/planner_agent`, `execution/executor` | Stays: the planner and the executor use it |
| `agents/ai_client` | infrastructure | The model client for each `AI_CLIENT` (Ollama, OpenRouter, the Toolbox gateway) | `vision_agent`, `data_agent`, `backend/api/routes/health` | Stays while the core makes model calls (ADR-0012); a strategic LLM (#619) needs it |
| `agents/model_calls` | infrastructure | The application's execution port for synchronous model calls | `pipeline/orchestrator`, the two agents, `backend/services/model_calls` | Stays while the core makes model calls |
| `agents/provider_breaker` | infrastructure | Stops calling a failing provider for the rest of a job | `pipeline/orchestrator`, enrichment | Stays: a job-level coordination concern; once the calls are capabilities it guards those |

## Where the strategic functions are

These are the strategic functions ADR-0029 keeps in the core. None of them is
in `agents/`:

| Function | Where |
|---|---|
| Building the planning problem: the obligations a document needs | `manifest/builder` (`_derive_processing_needs`, `inspect_document_needs`) |
| Planning | `planning/planner_agent`, behind `planning/engine` (`PlanningEngine`, #744) |
| Capability availability as a planning restriction | `planning/toolbox_gate` |
| Executing and observing the plan | `execution/executor` (`ExecutorAgent`) |
| Coordination and bounded replanning | `pipeline/orchestrator` (`_replan_until_done`) |
| Evaluating the result: open obligations, critical ones block delivery | `pipeline/obligations` |

Building the manifest mixes both sides: extraction and fusion are
operational, while deriving the obligations defines the planning problem and
stays in the core. Migrating `InformationalStructuralAgent` keeps that line.

## The migration, in order

1. **`VisionAgent` and `DataAgent`.** They are the only model-backed agents,
   and they are where ADR-0029's "image description" and "table and formula
   extraction" run. Each use becomes a capability. The core keeps the
   decision of when to ask for one and interprets the result in the plan's
   context.
2. **`FusionAgent`'s `process_*` methods**, per plan method, with the
   docstruct inventory's migration.
3. **`InformationalStructuralAgent`.** A composite extraction capability
   returns the fused document; the core derives the obligations from it.
4. **The Agno envelopes.** They go with their agents; none runs in
   production.

Each step follows the [docstruct inventory](docstruct-import-inventory.md#how-a-migration-shrinks-the-allowlist)'s
steps: an equivalent capability, the call through the core SDK, a
differential test, and the obsolete pins removed.

## The guard

`tests/test_architecture_layers.py` checks that:

- every module in `acessilia_core/agents/` is in the fixture, and no entry is
  stale. A new agent lands classified;
- an agent is strategic or operational, and a support module is operational
  or infrastructure;
- both pages list the fixture's modules.

## Still open

- **The four agents without a pipeline caller.** Should they move to the
  benchmark tooling (Dr.DocBench, #125) outside the core, be retired, or
  become capabilities when a plan method needs them?
- **Infrastructure after the migration.** Do `ai_client` and `model_calls`
  stay only for a strategic LLM (#619), or go once the core makes no model
  call of its own?
- **Result and decision contracts.** ADR-0029 asks the contracts to
  distinguish an operational result from a strategic decision. The
  capability contracts (ADR-0027) define that for each migrated agent.
