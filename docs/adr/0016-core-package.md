# 0016. The core as a package of its own, `acessilia_core`

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](0016-core-package.pt-br.md)

- **Status:** Proposed
- **Date:** 2026-11-11
- **Components:** core
- **Issues:** [#402](https://github.com/A11yDevs/acessilia/issues/402), [#365](https://github.com/A11yDevs/acessilia/issues/365)

## Context

[ADR-0002](0002-component-responsibilities.md) names four components: the
core, the SDK, docstruct and the Toolbox. The core is the one that decides:
policy, flow, plans and what a job delivers. In the code, though, the core is
not a component of its own. It is spread through `backend/`, next to the
service that runs it. `backend/` mixes two things that change for different
reasons:

- **The core**:
  - manifest, planning and execution (`backend/core`);
  - the PDDL orchestrator, with its handlers and enrichment stages
    (`backend/agents/pddl_orchestrator.py`);
  - the agents (`backend/agents`, `backend/ai`, `backend/core/agents`);
  - the dual fusion (`backend/pipeline`) and the exporters (`backend/export`,
    `backend/adapters`);
  - the Toolbox adapters (`backend/tools`);
  - the messages (`backend/i18n`, `log_messages`, `stage_messages`).
- **The service around it**: the API and the worker (`backend/api`, FastAPI),
  jobs, history, e-mail, download tokens and caches (`backend/services`), the
  job state (`backend/agents/state_manager.py`) and the environment
  configuration (`backend/config`).

The only way to run the core is through `backend`, so a benchmark, a script or
another front end carries the whole service. The SDK already lets a script
reach the Toolbox without the core (#402, phase 1). Nothing lets it run the
core without the service.

Measured on develop at fd7f7152, over the modules listed as core above (about
18,000 lines):

- **The framework dependencies are already on the right side.**
  - FastAPI is imported only in `backend/api`.
  - Agno is imported only in three files of `backend/agents`
    (`vision_agent.py`, `data_agent.py`, `output_schemas.py`).
  - `backend/core` imports neither.
- **The core reaches the service in two places.**
  - `backend.config`: 34 imports, and 59 distinct `settings` keys read at
    107 points. The orchestrator alone reads 12 keys, and the exporters 3.
  - `backend.services`, in four imports, from three places:
    - `run_blocking` (`blocking.py`);
    - the vision region cache (`get_cached_bytes`, `set_cache_bytes`,
      `options_cache_key`);
    - `processing_cache_configuration` and `_file_hash`, read by the payload
      and the Toolbox extractor.
- **The service reaches the core** from `backend/service.py`
  (`PddlAccessibilityOrchestrator`), from `backend/api/worker.py` (the
  exporters), and from the API and services (the messages and tools).
- **Size.** `pddl_orchestrator.py` has 5,770 lines (5,823 with #466), and
  `backend/core/manifest/builder.py` has 1,205. Phase 3, step 6 of #402
  reorganizes the orchestrator into modules, which is the moment to choose
  where they go.

Options considered:

1. **Reorganize in place**, inside `backend/`. The code gets organized, but its
   coupling to the environment stays implicit, and every user of the core
   keeps carrying the service.
2. **The core as a package of its own** (`libs/core`, `acessilia_core`), which
   the service depends on. Its configuration is passed explicitly, as the SDK
   takes `ToolboxClientConfig`.
3. **Put the core in the SDK.** Rejected. The SDK is transport, with
   `httpx` as its only dependency and no decisions (ADR-0002; enforced by
   `libs/sdk/tests/test_purity.py` and the isolated SDK job). The core decides,
   and it depends on Agno.
4. **Split the repository** into a service repository and a core repository.
   This goes further than the problem needs; option 2 can lead to it later.

## Decision

Proposed: option 2.

- **The core is a package, `acessilia_core`, in `libs/core`.** Its layout:

  ```text
  libs/core/src/acessilia_core/
    config.py      # CoreConfig: the core's configuration, explicit
    ports.py       # protocols the service implements: caches, blocking calls
    manifest/      # models, schema, builder, Toolbox extractor, slides
    planning/      # domain, planner, PDDL processor, Toolbox gate, comparison
    execution/     # executor, models, messages
    pipeline/      # orchestrator, preflight, payload, enrichment/, handlers/,
                   #   fusion, canonical builder
    agents/        # vision, data and the core's other agents, their schemas,
                   #   the provider breaker and the model factory
    toolbox/       # adapters over the SDK: client from CoreConfig, math,
                   #   media inspection, text spans, render, judge
    export/        # exporters and renderers
    i18n/          # t(), the catalogs, log and stage messages
  ```

  | Today | Moves to |
  |---|---|
  | `backend/core/{manifest,planning,execution}` | `acessilia_core.{manifest,planning,execution}` |
  | `backend/agents/pddl_orchestrator.py`, `backend/pipeline` | `acessilia_core.pipeline` |
  | `backend/agents/{vision_agent,data_agent,output_schemas,provider_breaker,run_helpers}.py`, `backend/ai`, `backend/core/agents` | `acessilia_core.agents` |
  | `backend/tools` (the Toolbox adapters, formula and code tools, prompts, logger) | `acessilia_core.toolbox` and helpers |
  | `backend/export`, `backend/adapters` | `acessilia_core.export` |
  | `backend/i18n.py`, `log_messages.py`, `stage_messages.py`, `locales/` | `acessilia_core.i18n` |

- **What stays in `backend/`, the service:**
  - the API and the worker;
  - jobs, the queue, history, e-mail, download tokens and cleanup;
  - the caches, which implement the core's `ports`;
  - the job state (`state_manager`);
  - the access log filter and upload validation;
  - `config/settings.py`, which reads the environment and builds `CoreConfig`.
- **Dependency direction:**

  ```text
  backend (service) ──▶ acessilia_core ──▶ SDK ──▶ docstruct
                              └────────────────▶ docstruct
  ```

  - `acessilia_core` may import the SDK, docstruct, Agno, pydantic and loguru.
  - It must not import `backend` or FastAPI, and it must not read the
    environment.
  - The SDK and docstruct must not import it.
- **Configuration is explicit.** The core receives a `CoreConfig` built by its
  caller. The service builds it from its environment, as it builds the SDK's
  `ToolboxClientConfig` today.
- **The service's state is injected.** The region and processing caches, and
  the way blocking calls are run, reach the core as arguments that follow the
  protocols in `acessilia_core.ports`. The core does not own the service's
  storage.
- **Agno is a required dependency** for now. Only `acessilia_core.agents`
  imports it, but the orchestrator imports the agents when it loads. Making
  Agno an optional extra is left for later.
- **The move is gradual and neutral**, one responsibility per pull request, as
  in phase 3 of #402:
  1. **Step 6 of phase 3** reorganizes the orchestrator under
     `backend/core/pipeline/`, with the layout `acessilia_core.pipeline` will
     have (see [the inventory](../architecture/pddl-orchestrator-inventory.md)).
  2. The `settings` reads are replaced by `CoreConfig`, one stage at a time.
  3. The caches and `run_blocking` are injected through `ports`.
  4. The modules move to `libs/core`, with an install-and-import check in CI
     like the SDK's isolated job. The folder `backend/core` disappears with
     this step; until then, it is where the core's modules gather.
- **Acceptance evidence** for this ADR: a proof of concept in which one
  enrichment stage (for example, the table structures) runs from a script with
  an explicit `CoreConfig`, with neither FastAPI nor `backend.config` imported,
  and returns the same manifest as the service on the same input.

## Consequences

- **Easier:**
  - benchmarks and scripts run the whole core without the service;
  - the service is left with delivery: the API, jobs and caches;
  - the core's boundary becomes a package dependency, which a test checks, as
    `libs/sdk/tests/test_purity.py` checks the SDK's;
  - the ADRs' word "core" names one package. "The core depends only on the
    SDK's public API" (ADR B of #402) becomes checkable at the package
    boundary.
- **Harder:**
  - every stage that reads `settings` changes its signature (107 reads);
  - tests that set `settings` attributes will build a `CoreConfig` instead;
  - the service depends on the core's message catalogs, since the API uses
    them too;
  - until step 4, "the core" in the documentation means both the future
    package and the folder `backend/core`.
- **Deviations that remain** until the steps above are done:
  - the core keeps reading `settings`;
  - the caches stay in `backend/services`;
  - the core's modules stay under `backend/`.
- **Compliance:**
  - a test that `acessilia_core` imports nothing from `backend` and reads no
    environment variable;
  - an isolated install job in CI.

  Until then, step 6 is checked by the module size limit (decision D4 of the
  inventory).
