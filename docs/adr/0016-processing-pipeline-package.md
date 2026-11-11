# 0016. The processing pipeline as a package of its own

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](0016-processing-pipeline-package.pt-br.md)

- **Status:** Proposed
- **Date:** 2026-11-11
- **Components:** core
- **Issues:** [#402](https://github.com/A11yDevs/acessilia/issues/402), [#365](https://github.com/A11yDevs/acessilia/issues/365)

## Context

The core (`backend/`) holds two things that change for different reasons:

- **The processing pipeline**: the manifest, planning and execution
  (`backend/core`), the PDDL orchestrator with its handlers and enrichment
  stages (`backend/agents/pddl_orchestrator.py`), the vision and data agents
  (`backend/agents`, `backend/ai`), the dual fusion (`backend/pipeline`), the
  Toolbox adapters (`backend/tools`) and the messages
  (`backend/i18n`, `log_messages`, `stage_messages`).
- **The service around it**: the API (`backend/api`, FastAPI), jobs, state and
  caches (`backend/services`), the exporters (`backend/export`) and the
  environment configuration (`backend/config`).

The only way to run the pipeline is through `backend`, so a benchmark, a script
or another front end carries the whole service. The SDK already lets a script
reach the Toolbox without the core (#402, phase 1); nothing lets it run the
pipeline without the service.

Measured on develop at fd7f7152:

- **Framework dependencies are already on the right side.** FastAPI is
  imported only in `backend/api`; Agno only in three files of `backend/agents`
  (`vision_agent.py`, `data_agent.py`, `output_schemas.py`); `backend/core`
  imports neither.
- **The pipeline reaches the service in two places.**
  - `backend.config`: 31 imports, and 55 distinct `settings` keys read at
    101 points. The orchestrator alone reads 12 keys.
  - `backend.services`, in three places:
    - `run_blocking` (`blocking.py`);
    - the vision region cache (`get_cached_bytes`, `set_cache_bytes`,
      `options_cache_key`);
    - `processing_cache_configuration` and `_file_hash`, read by the payload
      and the Toolbox extractor.
- **The service reaches the pipeline** through `backend/service.py`
  (`PddlAccessibilityOrchestrator`), and through the messages and tools from
  the API, services and exporters.
- **Size.** `pddl_orchestrator.py` has 5,770 lines (5,823 with #466) and
  `backend/core/manifest/builder.py` 1,205. Phase 3, step 6 of #402 reorganizes
  the orchestrator into modules, which is the moment to choose where they go.

Options considered:

1. **Reorganize in place** under `backend/core`, and keep the pipeline inside
   the service. The code is organized, but the coupling to the environment
   configuration stays implicit and every user of the pipeline keeps carrying
   the service.
2. **A pipeline package** (`libs/pipeline`), which the service depends on,
   with its configuration passed explicitly, as the SDK takes
   `ToolboxClientConfig`.
3. **Split the whole repository** into a service repository and a pipeline
   repository. This goes further than the problem needs; option 2 can lead to
   it later if a second service appears.

## Decision

Proposed: option 2. The rules below are what the ADR would make binding; the
open questions at the end must be answered before it is accepted.

- **The pipeline is a package**, `libs/pipeline`, with the modules that turn a
  source file into a canonical document: manifest, planning, execution,
  orchestrator, handlers, enrichment, agents, fusion, Toolbox adapters and
  messages.
- **Dependency direction:**

  ```text
  backend (service) ──▶ pipeline ──▶ SDK ──▶ docstruct
                           └──────────────▶ docstruct
  ```

  The pipeline must not import the service (`backend`). The SDK and docstruct
  must not import the pipeline.
- **Configuration is explicit.** The pipeline must not read the environment
  or a global `settings`. It receives a configuration object built by its
  caller; the service builds it from its environment, as it builds the SDK's
  `ToolboxClientConfig` today.
- **The service's state is injected.** The region and processing caches, and
  the way blocking calls are run, reach the pipeline as arguments that follow
  a protocol the pipeline declares. The pipeline does not own the service's
  storage.
- **The move is gradual and neutral**, one responsibility per pull request,
  as in phase 3 of #402:
  1. **Step 6 of phase 3** reorganizes the orchestrator under
     `backend/core/pipeline/`, with the module layout the package will have
     (see [the inventory](../architecture/pddl-orchestrator-inventory.md)).
     Extracting the package later is then a change of path, not a second
     reorganization.
  2. The `settings` reads are replaced by the configuration object, one
     stage at a time.
  3. The caches and `run_blocking` are injected.
  4. The folder becomes `libs/pipeline`, with an install-and-import check in
     CI, like the SDK's isolated job.
- **Acceptance evidence** for this ADR: a proof of concept in which one
  enrichment stage, for example the table structures, runs from a script with
  an explicit configuration object, with neither FastAPI nor
  `backend.config` imported, and returns the same manifest as the service on
  the same input.

## Consequences

- **Easier:**
  - benchmarks and scripts run the whole pipeline without the service;
  - the service is left with delivery: the API, jobs, caches and exporters;
  - the boundary becomes a package dependency, which a test checks, as
    `libs/sdk/tests/test_purity.py` checks the SDK's.
- **Harder:**
  - every stage that reads `settings` changes its signature (101 reads);
  - tests that set `settings` attributes will build a configuration instead;
  - the package depends on Agno because of the agents.
- **Deviations that remain** until the steps above are done:
  - the pipeline keeps reading `settings`;
  - the caches stay in `backend/services`.
- **Open questions**, to answer before this ADR is accepted:
  - **Do the exporters belong to the pipeline or to the service?** They use
    `backend.pipeline` four times, and produce what the service delivers.
  - **Do the agents stay in the pipeline package or form one of their own?**
    A package of their own would keep Agno out of anyone who only plans or
    executes.
  - **Do the message catalogs move with the pipeline or get injected?** The
    API also uses them, so moving them makes the service depend on the
    pipeline's catalogs.
  - **What is the package called?**
- **Compliance:**
  - a test that the pipeline package imports nothing from `backend`;
  - a test that it does not read the environment;
  - an isolated install job in CI.

  Until then, step 6 is checked by the module size limit (decision D4 of the
  inventory).
