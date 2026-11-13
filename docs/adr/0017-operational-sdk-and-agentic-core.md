# 0017. Operational SDK and agentic core boundaries

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](0017-operational-sdk-and-agentic-core.pt-br.md)

- **Status:** Accepted (2026-11-13, evidence below)
- **Date:** 2026-11-12
- **Components:** core, SDK, docstruct, Toolbox
- **Issues:** [#470](https://github.com/A11yDevs/acessilia/issues/470), [#402](https://github.com/A11yDevs/acessilia/issues/402)
- **Amends:** [ADR-0002](0002-component-responsibilities.md) (the SDK's row and the "where does new code go?" questions); it clarifies [ADR-0003](0003-remote-only-operational-capabilities.md) and complements [ADR-0016](0016-core-package.md)

## Context

ADR-0002 gives the SDK "contracts as consumed by clients, Toolbox clients and
transport, artifact references, availability and failover rules, in-process
access to docstruct's pure algorithms". Its fourth question sends to the SDK
only what is about *how* to reach a capability. So a sequence of capability
calls with explicit parameters has no home but the core. The formula chain is
one example: render a region, then `math.recognize`, `math.convert` and
`math.verbalize`. In the core it is mixed with the policy that decides when to
run it. A script, a benchmark or another front end cannot run that sequence
without the core.

[#470](https://github.com/A11yDevs/acessilia/issues/470) proposes:
- the SDK offers reusable operations and deterministic workflows;
- the core keeps the authority to decide strategies and goals;
- docstruct's portability and its role as the shared structural contract
  become explicit, testable principles.

The [inventory of #470, phase 1](../architecture/operational-boundaries-inventory.md)
measured where things stand:

- **Much of #470 is already decided and enforced.**
  - Docstruct is standard library only, with one guarded optional
    accelerator, `rapidfuzz`; `libs/docstruct/tests/test_purity.py` checks
    this. It does not check that docstruct stays away from the network, the
    environment, files and subprocesses: it allows the whole standard
    library.
  - `docstruct.manifest` is the normative document model (ADR-0007), with the
    Pydantic models kept as checked wire models.
  - ADR-0002 already allows SDK → docstruct.
  - The Toolbox test forbids imports of the SDK and the core.
- **Four gaps remain** (as measured; phases 2 and 3 of #470 have closed all
  four since, marked below):
  - the SDK does not depend on docstruct, and its isolated CI job refuses it
    (**closed in phase 3**: the formula operation composes docstruct, and the
    `SDK alone` job installs it);
  - docstruct has no isolated install job (**closed by #495**, the
    `docstruct alone` job);
  - nothing tests docstruct's independence from infrastructure (**closed by
    #497**, `test_infrastructure.py`);
  - nothing checks that the Toolbox's docstruct pin follows the core's. The
    branches agree today (0.4.0 on both `main`s, 0.5.0 on both `develop`s),
    but only by convention (**closed by #498** for the pin,
    `scripts/check_docstruct_pin.py`).
- **The core holds six deterministic operations next to the policy that runs
  them:**
  - the formula chain;
  - the page judge;
  - media inspection;
  - the PDF/UA audit;
  - text spans (already in the SDK, #455);
  - the exports.

Options considered:

1. **Keep the SDK at transport.** Every composition stays in the core, and
   every user of a composition carries the core.
2. **The SDK offers deterministic operations and workflows; the core keeps
   every decision** (#470).
3. **The SDK executes operational plans** given as data. Rejected for now:
   it is the shortest path to a second orchestrator, the risk #470 lists
   first.

## Decision

Option 2.

- **The criterion is the authority to decide, not the presence of AI or of
  conditionals.**
  - **Mechanism:** a function that runs capabilities and docstruct
    algorithms in a fixed order with explicit parameters, and reports what
    happened. It goes in the SDK.
  - **Policy:** a function that chooses goals, strategies, providers,
    thresholds, retries or what a result is worth. It stays in the core.
  - **Mixed code:** a function that does both is split along that line.
- **What the SDK may offer**, in addition to ADR-0002's list:
  - reusable operations and deterministic workflows composed of Toolbox
    capabilities and docstruct algorithms;
  - validation of their inputs and outputs, typed errors and the provenance
    of each step (P10 of #470): the capability and version, the effective
    parameters, the provider, the input and output references.

  An operation may call a probabilistic capability through the Toolbox (a
  model), provided its steps and parameters are explicit.
- **What the SDK must not do**, in addition to ADR-0002's list:
  - plan, choose goals, replan, or hold a policy;
  - depend on the core;
  - run locally a heavy capability that belongs to the Toolbox
    ([ADR-0003](0003-remote-only-operational-capabilities.md)).

  Composing remote capabilities does not change the `remote_only` policy.
- **docstruct's principles**, as tested rules:
  - **standard library only:** optional accelerators are allowed only when
    guarded by `except ImportError`, listed in the purity test, and backed by
    an equivalent standard library implementation. This is #470's
    alternative A, already in place;
  - **docstruct is the normative source of the structural models and
    invariants** (ADR-0007). Shared Python models do not replace versioned
    wire contracts: REST and MCP schemas keep their own versions and contract
    tests;
  - **no infrastructure:** no network, environment, files, subprocesses or
    imports of the core, the SDK or the Toolbox. `test_purity.py` tests the
    imports, and `test_infrastructure.py` (#470, phase 2) the rest, for the
    modules, built-ins and `sys` attributes it lists.
- **Dependencies:** unchanged from ADR-0002.
  - The SDK may depend on docstruct, and does once its first operation
    composes a docstruct algorithm (#470, phase 3: a required dependency,
    not an optional extra, since the operation cannot run without it).
  - Neither package is on a package index: both install from the repository
    or their release wheels, docstruct first. Publishing the SDK on an index
    requires publishing docstruct there first.
  - The SDK's base installation stays light: no agent framework and no heavy
    operational library.
- **Where new code goes**, replacing ADR-0002's four questions:

  | Question | Component |
  |---|---|
  | A pure structural algorithm, independent of infrastructure? | docstruct |
  | A reusable operation or composition, with explicit parameters? | SDK |
  | Needs a model, a converter, a sidecar or a heavy operational library? | Toolbox |
  | Decides goals, strategies, quality or replanning? | core |
  | Manages the API, jobs, authentication or the service's infrastructure? | the service (`backend/`, ADR-0016) |

  When code answers more than one question, it is split.
- **The first operation is the formula chain**, as the acceptance evidence for
  this ADR:
  - the SDK runs it from a script without the core or the service;
  - the core's formula enrichment reuses it, keeping its decisions;
  - the manifests of case 036 match before and after.

## Acceptance evidence

The three conditions above held on 2026-11-13:

- **The SDK runs the chain without the core.** `acessilia_sdk.operations.formula`
  (#504) has a step per capability. `python -m acessilia_sdk formula` runs it
  from the SDK's own wheel, and the `SDK alone` CI job installs docstruct as
  its only project dependency (with the SDK's test tools).
- **The core reuses it and keeps its decisions.** The core's formula crop and
  recognition (#507) and its MathML and speech (#509) call the operation's
  steps. Differential tests of develop's code against the new code found no
  difference for any answer inside the Toolbox's contract: 2,520 crop cases;
  738 recognition cases, compared at the value the enrichment consumes
  (develop's answer after the ranking its enrichment applied, against the
  SDK step's ranked answer, since the wrapper now returns it ranked); and
  420 conversion and speech cases (14 answer shapes). The one declared change
  concerns answers outside the contract, which now report an unavailable
  capability.
- **Case 036 matches before and after.** develop before the change (731a1bfb)
  and after it (dcc8cbfa) processed case 036 against the same Toolbox and
  vision model, each with a fresh source hash (#511). `math_case compare` found
  **0 differences** in the 16 formulas (LaTeX, MathML, spoken form, method,
  text layer), the text, the tables, the structure and the warnings. That held
  in both before-and-after pairs, and between two runs of the base. Case 006
  (42 slides) also matched outside what the vision model wrote: its 6 formulas
  are identical, and the one slide that differs (slide 5) holds a table that
  the data agent re-read from its image differently in each run.

## Consequences

- **Easier:**
  - scripts, benchmarks and other front ends run the operations without the
    core;
  - the core keeps only decisions;
  - the boundary between mechanism and policy has one written criterion.
- **Harder:**
  - an SDK operation is a public API: it needs versioning, a changelog and
    deprecation;
  - the SDK's isolated CI job changes when the SDK starts depending on
    docstruct.
- **Follow-up work**, in its own pull requests:
  - a CI job that installs docstruct alone in a clean environment (done,
    #495);
  - a test that no docstruct module reads the environment or files, opens a
    socket or starts a subprocess (phase 2 of #470). The isolated install job
    does not check this (done, #497);
  - a check that the Toolbox's docstruct pin follows the core's release, or
    shared fixtures both test against (#470's P8). The pin check is done
    (#498); shared fixtures are still open;
  - the formula chain in the SDK (the acceptance evidence above). The
    operation is `acessilia_sdk.operations.formula` (#504); the core's formula
    crop and recognition call its steps, keeping the saved crop, the source
    check, the failure handling and the outage flag (phase 3 of #470). MathML
    and speech call its `convert_formula` and `verbalize_formula` steps, one
    per capability, so each obligation still fails on its own; an answer
    outside the contract is now an unavailable capability, not a formula
    without that text, so the rest of the document skips that capability,
    as after an outage (a broken answer is taken for a broken provider).
    Case 036's manifests were compared on acceptance (#511, see *Acceptance
    evidence*): done;
  - the other operations of the inventory, one per pull request, each with
    characterization and a comparison of the manifests before and after.
- **Interaction with ADR-0016.** Phase 3, step 6 of #402 does not move into
  `backend/core/` the modules that hold these operations, so they do not move
  twice: the page judge, `backend/tools`' Toolbox adapters, and the formula
  chain. Each moves once its split into mechanism (SDK) and policy (core) is
  decided. The core keeps the binding of its configuration (`CoreConfig`) to
  each operation's explicit parameters. So the core's binding to the render
  (`_source_artifact_id` and `_toolbox_render`, which bind the settings to
  `ToolboxPdfClient.render` and decide whether the stored source can be
  referenced) stays in the core and is not part of that hold: step 6 moves it
  to `backend/core/pipeline/toolbox.py`.
- **Still open:**
  - which operations follow the formula chain, and in which order;
  - what docstruct's stable public API is. The proposal is: what each module
    lists in `__all__` and the README tables;
  - an operational plan contract, deferred;
  - whether docstruct must also be deterministic: no clock, randomness or
    threads. `test_infrastructure.py` leaves them out, since they are not
    infrastructure; docstruct uses none of them today.
- **Compliance:**
  - `libs/docstruct/tests/test_purity.py` and `libs/sdk/tests/test_purity.py`
    (they exist);
  - the Toolbox's architecture test (it exists);
  - the isolated install jobs of docstruct (new) and of the SDK (adjusted);
  - the infrastructure test of docstruct (new);
  - a review item: an SDK operation has no decision it could take differently
    for another caller.
- **On acceptance** (done in #511):
  - ADR-0002 gets an "Amended by ADR-0017" line, and its SDK row and its four
    questions point here;
  - ADR-0003 gets a "Clarified by ADR-0017" line.

  Neither is rewritten (process of the [ADR index](README.md)).
