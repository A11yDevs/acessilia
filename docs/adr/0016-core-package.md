# 0016. The core as a package of its own, `acessilia_core`

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](0016-core-package.pt-br.md)

- **Status:** Accepted (2026-11-18, evidence below)
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
    (`backend/core/pipeline/`, where step 6 of #402 moved them from
    `backend/agents/pddl_orchestrator.py`);
  - the agents (`backend/agents`, `backend/ai`, `backend/core/agents`);
  - the dual fusion (`backend/core/pipeline/fusion.py`, which step 2 gathered from
    `backend/pipeline`) and the exporters (`backend/core/export`, which step 2 gathered from
    `backend/export`; the unused
    `backend/adapters` wrappers were removed in step 2);
  - the Toolbox adapters (`backend/core/toolbox`, with the helpers `backend/core/logger.py`
    and `backend/core/formula_tools.py`; step 2 gathered them from `backend/tools`);
  - the messages (`backend/core/i18n`, with `log_messages`, `stage_messages` and the
    catalogs, which step 2 gathered from `backend/i18n.py`, `backend/log_messages.py`,
    `backend/stage_messages.py` and `backend/locales`).
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

- **FastAPI is already on the service's side.** It is imported only in
  `backend/api`, at module level or inside a function.
- **Agno is in the core, not only in its agents.**
  - At module level: three files of `backend/agents` (`vision_agent.py`,
    `data_agent.py`, `output_schemas.py`).
  - Inside functions:
    - `backend/core/agno_support.py` imports `agno.agent`, `agno.tools` and
      `agno.workflow`; the executor, the planner and the six agents of
      `backend/core/agents` use it;
    - `backend/ai/models/ai_client.py` imports the three Agno model classes.
  - **Planning and execution need Agno at run time.** `ExecutorAgent.execute`
    always builds an Agno workflow (`build_workflow`), and
    `require_workflow_classes` raises `RuntimeError` when Agno is missing,
    even for a plan with no steps.
- **The other libraries the core imports**, counted with an AST scan that
  includes imports inside functions:
  - pydantic and loguru;
  - Babel (`backend/core/i18n/__init__.py`);
  - jsonschema (`backend/core/manifest/schema.py`);
  - rapidfuzz (`backend/core/pipeline/fusion.py`);
  - edge-tts (`backend/core/export/exporters/audio_exporter.py`). This is the
    local executor that [ADR-0003](0003-remote-only-operational-capabilities.md)
    records as a known deviation
    ([acessilia-toolbox#73](https://github.com/A11yDevs/acessilia-toolbox/issues/73)).
- **The core imports the frontend.** `backend/core/planning/models.py` and
  `backend/core/execution/models.py` take schema descriptions and validation
  messages from `frontend.telegram.messages`. Without `frontend` installed,
  both raise `ImportError`. (Fixed in step 2: those messages now live in
  `backend/core/planning/messages.py` and `backend/core/execution/messages.py`.)
- **The core reaches the service in two places.**
  - `backend.config`: 34 imports, and 59 distinct `settings` keys read at
    107 points. The orchestrator alone reads 12 keys, and the exporters 3.
  - `backend.services`, in four imports, from three places:
    - `run_blocking` (`blocking.py`; moved into the core in step 4);
    - the vision region cache (`get_cached_bytes`, `set_cache_bytes`,
      `options_cache_key`; in step 4 the core takes it as a port, and
      `options_cache_key` moved into the core);
    - `processing_cache_configuration` and `_file_hash`, read by the payload
      and the Toolbox extractor (in step 3 the core stopped importing these
      two, which stay in the service: it builds its identities in
      `backend/core/run_identity.py`, #544).

    Imports added after this inventory: the job checkpoints
    (`job_checkpoint`) and the job id (`operation_context`) in the
    orchestrator, which take the `JobCheckpoints` port in step 4, and the
    registry of remote operations (`operation_registry`,
    `operation_context`) in the Toolbox extractor, which takes the
    `RemoteOperations` port in step 4. Since then the core imports nothing
    from `backend.services`, which `tests/test_run_ports.py` checks.
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
3. **Put the core in the SDK.** Rejected. The SDK takes no decisions
   (ADR-0002). [ADR-0017](0017-operational-sdk-and-agentic-core.md) widens
   it from transport to deterministic operations, but not to decisions. Its
   base installation stays light: `httpx`, and docstruct once it composes
   docstruct algorithms (enforced by `libs/sdk/tests/test_purity.py` and the
   isolated SDK job). The core decides, and it depends on Agno.
4. **Split the repository** into a service repository and a core repository.
   This goes further than the problem needs; option 2 can lead to it later.

## Decision

Option 2.

- **The core is a package, `acessilia_core`, in `libs/core`.** Its layout:

  ```text
  libs/core/src/acessilia_core/
    config.py      # CoreConfig: the core's configuration, explicit
    ports.py       # protocols the service implements: caches, checkpoints, operations
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
  | `backend/core/pipeline` (the orchestrator was `backend/agents/pddl_orchestrator.py` until #402's step 6 moved it; `backend/pipeline` gathered there in step 2) | `acessilia_core.pipeline` |
  | `backend/core/agents` (gathered in step 2 from `backend/agents/{vision_agent,data_agent,output_schemas,provider_breaker,run_helpers}.py`, `backend/ai` and `backend/core/agno_support.py`, with the prompt loading of `backend/tools`) | `acessilia_core.agents` |
  | `backend/core/toolbox`, `backend/core/logger.py`, `backend/core/formula_tools.py` (gathered from `backend/tools` in step 2; its prompt loading went with the agents) | `acessilia_core.toolbox` and helpers |
  | `backend/core/export` (gathered from `backend/export` in step 2; `backend/adapters`, unused, was removed) | `acessilia_core.export` |
  | `backend/core/i18n` (gathered in step 2 from `backend/i18n.py`, `log_messages.py`, `stage_messages.py` and `locales/`) | `acessilia_core.i18n` |

- **What stays in `backend/`, the service:**
  - the API and the worker;
  - jobs, the queue, history, e-mail, download tokens and cleanup;
  - the caches, which implement the core's `ports`;
  - the job state (`state_manager`);
  - the access log filter and upload validation (`backend/services`, from
    `backend/tools` in step 2, with the output file names);
  - `config/settings.py`, which reads the environment and builds `CoreConfig`.
- **Dependency direction:**

  ```text
  backend (service) ──▶ acessilia_core ──▶ SDK ──▶ docstruct
                              └────────────────▶ docstruct
  ```

  - `acessilia_core` may import the standard library, the SDK, docstruct,
    Agno, pydantic, loguru, Babel, jsonschema and rapidfuzz. These are the
    libraries it imports today.
  - edge-tts is allowed only as the deviation ADR-0003 records. It leaves when
    the audio export becomes a Toolbox capability. The neutral move does not
    replace it, or any other implementation.
  - It must not import `backend`, `frontend` or FastAPI, and it must not read
    the environment.
  - The SDK and docstruct must not import it.
- **Configuration is explicit.** The core receives a `CoreConfig` built by its
  caller. The service builds it from its environment, as it builds the SDK's
  `ToolboxClientConfig` today.
- **The service's state is injected.** The region cache, the job
  checkpoints and the registry of remote operations reach each run as one
  `RunPorts` object, whose members follow the protocols in
  `acessilia_core.ports`; the service builds it for the job. The core does
  not own the service's storage. The processing cache is the service's alone:
  it wraps the run, and the core only gives it the run's identity
  (`run_identity`). `run_blocking`, a stateless helper on the standard
  library, belongs to the core, and the service imports it from there
  (amended in step 4).
- **Agno is a required dependency** for now. The agents need it, and so do
  planning and execution: the executor runs every plan as an Agno workflow.
  Making Agno optional would take more than moving the agents into a package
  of their own: execution would need a path that does not build the workflow.
  That is left for later.
- **The move is gradual and neutral**, one responsibility per pull request, as
  in phase 3 of #402. Every module of the core first gathers under
  `backend/core/`, with the package's layout, so that the extraction is a
  change of path only. Extraction comes last:
  1. **Step 6 of phase 3** reorganizes the orchestrator under
     `backend/core/pipeline/`, with the layout `acessilia_core.pipeline` will
     have (see [the inventory](../architecture/pddl-orchestrator-inventory.md)).
  2. **The rest of the core gathers under `backend/core/`**, one group per
     pull request. Each resource moves with the code that loads it.

     | Today | Gathers in | Resources that move with it |
     |---|---|---|
     | `backend/core/{manifest,planning,execution}` | already in place | `planning/domains/`: the PDDL domains and their descriptions |
     | `backend/pipeline` | `backend/core/pipeline/` (done) | |
     | `backend/agents/{vision_agent,data_agent,output_schemas,provider_breaker,run_helpers}.py`, `backend/ai`, `backend/core/agents`, `backend/core/agno_support.py` | `backend/core/agents/` (done: `ai_client`, `agno_support` and `prompt_tools` with them) | `backend/ai/prompts/` (10 prompts) → `backend/core/agents/prompts/` (done) |
     | `backend/tools` (Toolbox adapters, formula and code tools, prompt loading, logger) | `backend/core/toolbox/` and helpers (done: the adapters to `backend/core/toolbox/`, `logger` and `formula_tools` to `backend/core/`, the service's `validators`, `access_log_filter` and `filenames` to `backend/services/`; `code_tools`, dead, removed; `prompt_tools` went with the agents) | |
     | `backend/export` (`backend/adapters`: removed, nothing imported it) | `backend/core/export/` (done) | |
     | `backend/i18n.py`, `log_messages.py`, `stage_messages.py` | `backend/core/i18n/` (done) | `backend/locales/` (the `.po` catalogs) → `backend/core/i18n/locales/` |

     The job state (`backend/agents/state_manager.py`) stays in the service.

     The messages the core takes from `frontend.telegram.messages` (the schema
     descriptions and validation messages of `planning/models.py` and
     `execution/models.py`) move to the core's messages in the same step. If
     the frontend still uses them, it imports them from the core. Done: the 18
     msgids moved to `planning/messages.py` and `execution/messages.py`, and
     the frontend did not use them.

     **Operations that may go to the SDK stay where they are** until
     [ADR-0017](0017-operational-sdk-and-agentic-core.md) decides their
     split into mechanism (SDK) and policy (core), so they do not move twice.
     These are the page judge, the core's Toolbox adapters (then in
     `backend/tools`, now in `backend/core/toolbox`), and the formula chain (the core's binding to the render stays in the core and is
     not part of that hold; see ADR-0017); the
     [inventory of #470](../architecture/operational-boundaries-inventory.md)
     lists them. What stays in the core after the split (the policy, and the
     binding of `CoreConfig` to each operation's parameters) then gathers
     here. ADR-0017 was accepted on 2026-11-13: the formula chain's policy
     moved into `backend/core/pipeline/` (#513, #515), and the page judge
     moved there whole, its SDK split left for later. The Toolbox adapters
     moved whole to `backend/core/toolbox/` in step 2, their SDK split left for
     later as well.
  3. The `settings` reads are replaced by `CoreConfig`, one stage at a time.
     Done: `backend/core/config.py` defines `CoreConfig` as frozen
     groups (Toolbox, models, vision, fusion, document, export, paths), the
     service builds it in `backend/config/core_config.py`, and the
     orchestrator builds one per run until every stage takes its group. Moved
     so far: the `document` group (the page limit first, then inline math,
     the legacy Unicode repair, the slide options and the formula agreement
     threshold), the `export` group, which the worker snapshots once per
     job and passes to the exporters, the `fusion` group, and the `vision`
     group (the stages' concurrency, breaker threshold, retry delay, table
     review and region cache, and the page inspection's DPI). The `toolbox`
     group moves in three pull requests: the planning gate and its
     catalogue (done; the catalogue cache is shared by runs with the same
     endpoint, key and timings), then the switches and the extractor's
     options (done: media inspection, PDF validation, remote cache, artifact
     store, extraction timeout, and the primary and math providers; each
     helper that calls the client factory takes the run's `ToolboxConfig`),
     then the client factory and its callers (done:
     `make_toolbox_client(cls, toolbox)`). The `models` group is done too:
     `get_agno_model(models, toolbox)` and `active_model_name(models)`, and
     `VisionAgent` and `DataAgent` take the run's `ModelConfig`, given by
     the stages and the inspection handlers. The `paths` group closes the
     groups: the extractor's fusion evidence and the fusion and inspection
     handlers' artifacts are written under the run's `PathsConfig.data_dir`, so
     the core reads no setting of a run; and the configuration groups are done.
     A run then requires its config and its model-call runner (`execute(...,
     config=, model_calls=)`, and `ports=` since step 4), the service builds one config per job and the
     worker's exports and audit reuse it, and the Agno tools without a run take
     the config their agent was built with: the bridges are gone. The
     processing cache key and the fusion reuse are then built from the run's
     config (#544): `backend/core/run_identity.py` classifies every
     `CoreConfig` field as part of the processed document's identity or not,
     and the service adds its own options. Last, the process setup is passed at
     process start: `backend/config/process_setup.py::setup_process` gives
     the logger `LOG_LEVEL` and `LOGS_DIR` and the catalogs
     `I18N_LOCALES_ACTIVE` (`i18n.configure_locales`), so `backend/core`
     reads no settings and imports nothing from `backend.config`, which
     `tests/test_core_config.py` checks. The method handlers
     that read the config declare a `config` parameter (the dual-provider and
     single-provider fusion handlers, the region and page inspection handlers,
     the `mathml` and `latex-verbalizer` formula handlers, and the VLM
     judge's), and each run binds its config to them (`bind_run`) on a copy
     of the registry.
  4. The caches and `run_blocking` are injected through `ports`. Done, in
     three pull requests:
     - **The region cache and `run_blocking` (done).** `backend/core/ports.py`
       defines `RegionCache` and `RunPorts`, with a no-op for runs outside the
       service (`RunPorts.none()`). `execute(..., ports=)` is required, like
       `config` and `model_calls`. The stages take the run's region cache, or
       `None` when its config turns it off, and the handlers that declare
       `ports` get them (`bind_run`, which replaces `bind_config`). The
       service implements the port on its file cache (`ContentCache`).
       `run_blocking` and `options_cache_key` moved into the core.
     - **The job checkpoints and the job id (done).** `RunPorts.checkpoints`
       is the job's `JobCheckpoints` (`load`, `save`, `remove` by phase, and
       the `job_id` for the log), or `None` outside a job, which writes and
       resumes nothing. The phase names are the core's (`CHECKPOINT_PHASES`).
       The service binds `FileJobCheckpoints` to the job's task id, and the
       orchestrator no longer reads the job id.
     - **The registry of remote operations (done).** `RunPorts.operations`
       is the job's `RemoteOperations` (`begin` a call of an
       `OperationKind`, `finish` it, and the `job_id` that labels it), or
       `None` outside a job, whose calls are neither registered nor
       labelled. The run passes it to the extractor; the service binds
       `JobOperations` to the task id. The core and the service no longer
       read the job id from the service's context variable, so
       `backend/services/operation_context.py` (`task_context`,
       `current_task_id`) is gone. The SDK keeps its own: the extractor
       opens `operation_context(job_id, operation_id)` around each call, and
       the clients read it through `current_operation()` to send the
       ADR-0019 headers.

     The core imports nothing from `backend.services`, inside functions
     included, which `tests/test_run_ports.py` checks.
  5. **A boundary test** checks `backend/core/`, imports inside functions
     included:
     - it imports nothing from `backend` outside `backend/core`, and nothing
       from `frontend`;
     - its other imports are only the allowed libraries above, with edge-tts
       on the test's allowlist and a reference to acessilia-toolbox#73;
     - it reads no environment variable.

     It must pass before the extraction. Done: `tests/test_core_boundary.py`
     checks the three rules, keeps the library allowlist from growing
     (a library the core stops importing leaves it), confines edge-tts to
     the audio exporter, and checks that the SDK and docstruct do not import
     the core. The scan follows aliases (`import os as o`) and catches
     `expanduser`/`expandvars` on any receiver. Two environment reads were
     left, both moved out:
     - the server-side locale, which `t()` negotiated from `LOCALE`,
       `LANGUAGE`, `LC_ALL` and `LANG` at every call. The service now
       negotiates it once at startup (`setup_process`, with
       `negotiate_server_locale`) and passes it to the catalogs
       (`configure_server_locale`). A process that skips the setup uses
       `en_US`;
     - `expanduser` (`HOME`) in the planner's sandbox paths, which a home
       path could not pass anyway.

     `tempfile` honours `TMPDIR` inside the standard library; that is not
     the core reading its environment, so the test allows it.
  6. **The extraction**, in three pull requests:
     - **Resources prepared in place (done).** Two resources were located
       through the module's own path, which an installed package breaks.
       The translation catalogs compiled `messages.mo` next to their `.po`
       sources at import, and a read-only package left every message in
       English: they now compile in memory, on first use. The planner's
       sandbox was `<repo>/temp/pddl-sandbox`, four folders up from the
       module: `PlannerAgent(sandbox_dir=)` now takes it from its caller
       (`PathsConfig.data_dir / "pddl-sandbox"`), and its file tools refuse
       to run without it. `plan` and `compare`, which the pipeline calls,
       work in memory and need none.
     - **The move and the import rename (done).** `backend/core` is now
       the package `acessilia_core` in `libs/core/src/acessilia_core`
       (`libs/core/pyproject.toml`, version 0.1.0), installed editable like
       the SDK and docstruct, and every `backend.core` import is
       `acessilia_core`, with no bridge left. The steps above name
       `backend/core` as it was when they were done. The boundary test now
       scans the package, which may import itself but nothing from
       `backend`; the guards that scanned `backend/` scan the package too,
       and the SDK's purity test and both libraries' CI isolation jobs also
       refuse `acessilia_core`.
     - **The clean installation, its smoke test, and the proof of concept
       (done).** The CI job `core-isolated` installs `libs/core` from its
       own lock as a wheel, checks that neither the service, the front ends
       nor FastAPI is importable, runs the boundary test on the source, and
       runs `libs/core/tests/test_smoke.py` from a folder outside the
       checkout: it loads the PDDL domain, every prompt file the loaders
       name and both catalogs, and plans and executes a fixture manifest
       (dry run). Each kind of package data left out of the wheel fails it.
       The proof of concept is `libs/core/examples/table_stage.py`: the
       table-structure stage runs with an explicit `CoreConfig` and a
       model-call runner of the script's own, in that job too, where the
       service is not installed; `tests/test_core_standalone_table_stage.py`
       checks that it returns the same manifest as the service on the same
       input and loads neither `backend` nor FastAPI.

     The tests stay in `tests/`; only the boundary test and the smoke test
     go to `libs/core/tests`. When the three are done:

     - the modules move to `libs/core`, and `backend/core` disappears;
     - the PDDL domains, the prompts and the catalogs are declared as package
       data;
     - a CI job installs the package in a clean environment, outside the
       checkout, and runs a smoke test from there: it plans and executes a
       fixture manifest (dry run), loads the PDDL domain, a prompt and both
       catalogs. Importing the modules alone would not load these resources.
- **Acceptance evidence** for this ADR: a proof of concept in which one
  enrichment stage (for example, the table structures) runs from a script with
  an explicit `CoreConfig`, with neither FastAPI nor `backend.config` imported,
  and returns the same manifest as the service on the same input.

## Acceptance evidence

The six steps were done by 2026-11-18, and the conditions above held:

- **The core is a package of its own.** `acessilia_core` lives in
  `libs/core` (`acessilia-core` 0.1.0, #572); `backend/core` is gone, with no
  bridge left. Its wheel carries the PDDL domains and their descriptions, the
  prompts and the `.po` catalogs, which it locates from its own package and
  compiles in memory (#569).
- **Its boundary is checked.** `libs/core/tests/test_boundary.py` (#568, moved
  in #575) checks, imports inside functions included, that it imports nothing
  from `backend` or `frontend`, only the allowed libraries with edge-tts as the
  recorded deviation, and reads no environment variable; and that the SDK and
  docstruct do not import it. Its caller passes everything it needs: a
  `CoreConfig` per run (step 3, #537 to #562), the run's `RunPorts` (step 4,
  #563, #565, #566), the model-call runner, and the process setup once
  (#562, #568).
- **It works alone.** The `core alone` CI job (#575) installs the core from
  its own lock as a wheel, where neither the service, the front ends, FastAPI
  nor the Toolbox package is importable, and runs the smoke test from outside
  the checkout: the PDDL domain, every prompt file and both catalogs load, and
  a fixture manifest is planned and executed (dry run). Leaving the prompts,
  the catalogs or the domains out of the wheel fails it.
- **The proof of concept.** `libs/core/examples/table_stage.py` runs the
  table-structure stage with a `CoreConfig` built field by field and a
  model-call runner of its own, in that job too.
  `tests/test_core_standalone_table_stage.py` checks that it returns the same
  manifest as the service on the same input, imports neither `backend` nor
  FastAPI, and that a table the model reads goes through the script's runner
  with the model its config names.

## Consequences

- **Easier:**
  - benchmarks and scripts run the whole core without the service;
  - the service is left with delivery: the API, jobs and caches;
  - the core's boundary becomes a package dependency, which a test checks, as
    `libs/sdk/tests/test_purity.py` checks the SDK's;
  - the resources the core loads (PDDL domains, prompts, catalogs) live with
    the code that loads them;
  - the ADRs' word "core" names one package. "The core depends only on the
    SDK's public API" (ADR B of #402, now
    [ADR-0018](0018-core-uses-sdk-public-api.md)) is checked over `backend/`,
    `scripts/` and `tests/` today, and holds at the package boundary after the
    extraction.
- **Harder:**
  - every stage that reads `settings` changes its signature (107 reads);
  - the paths of the modules the service and the tests import change twice:
    once when they gather under `backend/core/`, once at the extraction;
  - tests that set `settings` attributes will build a `CoreConfig` instead;
  - the service depends on the core's message catalogs, since the API uses
    them too;
  - until step 4, "the core" in the documentation means both the future
    package and the folder `backend/core`.
- **Deviations that remain** until the steps above are done:
  - the core keeps reading `settings`;
  - the caches stay in `backend/services`;
  - the core's modules stay under `backend/`;
  - the audio export keeps synthesizing locally with edge-tts until
    acessilia-toolbox#73 (ADR-0003).
- **Compliance:**
  - before the extraction, the boundary test of step 5;
  - after it, a test that `acessilia_core` imports nothing from `backend` or
    `frontend`, imports only the allowed libraries, and reads no environment
    variable;
  - the isolated install job with its planning and execution smoke test
    (step 6).

  Until then, step 6 is checked by the module size limit (decision D4 of the
  inventory).
