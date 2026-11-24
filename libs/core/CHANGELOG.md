# Core changelog

Brazilian Portuguese: [português brasileiro](CHANGELOG.pt-br.md).

## 0.3.17 — checkpoints inside a composite action (#836)

The picture descriptions (M1), the formula LaTeX (M3) and the table
enrichment (M2) are each one planned action over many elements. To the
planner each is atomic; its persistence no longer is. Until now a crash in
the middle of one resumed the whole step, paying again the model calls of
the objects it had finished. Now:
- **After each finished object** the method saves the manifest it is
  enriching into the run's execution checkpoint, as `step_progress` next to
  the last finished step: the stage's `on_progress`, coalesced as before
  planning (one write at a time, the latest manifest), serialized on the
  stage's event loop. It goes through `RunServices.step_checkpoint`, which
  the orchestrator sets to its execution checkpoint; no new checkpoint phase.
- **A resumed execution of the same plan** starts that step again from it
  (`resumed_manifest`), and the step's per-object gates skip what was done:
  a described picture, a read table, a recognized formula. The progress of a
  step the plan does not run next is never used, and the next finished step
  drops it.
- The collective recovery (one breaker, one retry pass) and the progress
  messages (`RunServices.progress`) are unchanged.
- Tests: a crash on the fourth of five pictures resumes with the fourth and
  fifth only; on the sixth of eight tables, with the last three; on the
  third of four formulas, with the last two.

## 0.3.16 — optional Toolbox capabilities (#848)

A method's Toolbox calls are now of three kinds:
- **required** (`METHOD_TOOLBOX_REQUIREMENTS`): missing one rules the method
  out, as before;
- **optional** (`METHOD_OPTIONAL_CAPABILITIES`, new): missing one degrades
  the method per element, so it never rules the method out;
- none: the method runs in the core alone.

`picture-description` (`pdf.render`), `formula-recognizer`
(`math.recognize`, `pdf.render`) and `table-enrichment` (`pdf.render`,
`document.text.spans`) declare their optional calls; until now the gate did
not record them at all. A snapshot that lacks one reports the method under
`degraded_methods`, next to `optional`, in the availability metadata the
output carries and in a log warning, in `observe` and in `enforce` alike. The
catalogue facts and the plan do not change, and the methods degrade as
before. Without a snapshot nothing is reported degraded (`catalog_error`
says why). A document whose only Toolbox calls are optional now has its
catalogue read. A plan checkpoint from before restores no optional calls.
Where a method lives (`LOCAL_METHODS`' role) stays a separate dimension.

## 0.3.15 — the formula LaTeX is a planned action (#640, M3, #846)

Until 0.3.14 the orchestrator read the formulas' LaTeX before planning. Now a
document with formulas to recognize, or equation labels to separate, gets
one `recognize-formulas` obligation, satisfied by the `formula-recognizer`
method, which runs the same step inside the plan: it separates the equation
labels, then reads the LaTeX of the formulas without it, `math.recognize`
first and the vision model as the fallback, with its concurrency, the run's
breaker and region cache.
- **One obligation for the document,** like the pictures (M1) and the
  tables (M2), and not one per formula as first proposed: the step shares
  one breaker, one `math.recognize` probe per obligation (a second one,
  for formulas found during the plan, probes again) and its concurrency
  across the document. It targets the formulas with a label to separate and, in a
  source that can be rendered, the ones without LaTeX that no recognition
  has recorded. `verbalize-formula` and `normalize-formula` depend on it, as
  do the page obligations of a page with a formula. It is the third
  `DocumentStep`, and shares no element with the other two.
- **The gap of M1 is closed (#846).** A picture the descriptions read as a
  formula gets the step on the replan, through the reconciliation, so its
  `verbalize-formula` sees the equation label separated, as before planning
  until 0.3.13. The test that pinned the gap is inverted:
  `test_a_picture_read_as_a_formula_gets_the_formula_steps`. The scope is
  what the step did: a formula whose model text has no LaTeX markup is read
  by `math.recognize` before its verbalization; LaTeX the model already
  gave is not read again (an independent second reading is #852).
- **One policy for selection and execution.** The obligation's targets and
  the step's work share `formulas_needing_number_separation` and
  `formulas_needing_recognition`, so a formula selected only to separate
  its label is not read again, nor its recognition record overwritten.
- **It can change obligations.** A formula the vision fallback reads as a
  picture becomes one, so its formula obligations are replaced by a
  `describe-image`; the executor skips them and replans (M0).
- The method succeeds when the step ran for every formula of the
  obligation; one left without LaTeX keeps its text and its reason
  (`formula_recognition_failure`). Its message counts the formulas
  recognized per method, the labels separated, the ones read as pictures,
  and the reason of each one left. The step announces itself once (the
  method; the stage no longer repeats `STAGE_ENRICHING_FORMULAS`). A formula
  whose crop could not be made now records why (`crop_unavailable`, which
  the delivered warnings count like a picture's and keeps the run out of
  the cache, or `no_page`), instead of being left unchanged in silence.
- The three document steps share no element, so their order is the
  planner's tie-break; under a partial provider outage, the one that runs
  first spends the shared breaker's budget first (#853).
- `formula-recognizer` is `transitional` in `LOCAL_METHODS` (its fallback is
  the core's `VisionAgent`) and declares no Toolbox requirement:
  `math.recognize` degrades to the fallback and `pdf.render` per formula
  (#848).
- Before planning the run now classifies formula regions, prepares the
  pictures and marks prose inline math. An enrichment checkpoint from 0.3.14
  read its formulas already and gets no obligation.
- Tests: the obligation and its targets, the plan order (also under Fast
  Downward), the method's message and scope, a formula read as a picture,
  the end-to-end picture → formula → label → verbalization, and a
  differential test of the elements before and after the migration.

## 0.3.14 — the picture descriptions are a planned action (#640, M1)

Until 0.3.13 the orchestrator described the pictures before planning. Now a
document with pictures to describe gets one `describe-images` obligation,
satisfied by the `picture-description` method, which runs the same step
inside the plan: the vision model, with its concurrency, the run's breaker
and region cache, one retry pass, and the ownership annotation again after
the descriptions.
- **One obligation for the document.** It targets the pictures not described
  yet; without pictures, in a mostly visual document, its placeholder
  visuals, or the first element of a one-page one, as the step chose them,
  but never a formula or a table: the candidates and the elements the step
  keeps share one test (`is_describable`), so it never takes one it would
  then drop, and never retypes a formula or a table as a picture. The two
  document steps share no element, so neither depends on the other; as a
  guard, the edges between them follow `DOCUMENT_STEPS` (a step's may depend
  on an earlier step's, never on a later one's), so they make no cycle.
  The method describes its obligation's targets still describable and not
  described, whatever the candidates are when it runs, so it never succeeds
  without trying them; a target another step now reads is reported as
  `not_describable`.
  Each picture's `describe-image` keeps `vision-description`, which checks
  the result, and depends on it, as do the page obligations of a page with a
  picture. The only alternative is `human-review`. The method succeeds when
  the step ran for every picture; a picture left undescribed keeps its
  reason (`vision_failure_reason`), and its `describe-image` validates it.
  Its message counts the pictures described, read as formulas, already
  described, and the reason of each one left.
- **It changes obligations while the plan runs.** A picture the model reads
  as a formula becomes a formula, so its `describe-image` is replaced by
  `verbalize-formula`; a placeholder visual it describes becomes a picture
  with a `describe-image`. The executor skips the replaced step and replans
  for the new ones, within `max_discovery_replans` (M0).
- **What stays before planning.** What derives from the media inspection: the
  injected full-page picture and the first ownership annotation
  (`_prepare_pictures`), so the plan's obligations include the injected
  picture's. The method annotates again with the inspection the orchestrator
  gives the run's services (`RunServices.media_inspection`; recording the
  facts it needs in the manifest is #847), and does not inject the
  full-page picture again. The progress
  message before planning is now the formulas' (`STAGE_ENRICHING_FORMULAS`);
  the method announces the descriptions inside the plan.
- **One rule for both document steps.** The rules of 0.3.13 for the table
  enrichment (cover, drop the lost targets, reconcile the edges, select a new
  obligation before a replan) move to `pipeline/document_obligations.py` and
  hold for both steps (`DocumentStep`, `reconcile_document_steps`).
  `add_table_enrichment_obligation` and the table constants keep their names.
- **Known gap until M3.** The formula LaTeX step runs before planning, so it
  no longer sees a picture the model reads as a formula: that formula keeps
  the model's LaTeX, without the recognizer's second reading or the
  separation of its equation number. M3 (#846) makes the recognition the
  formula's own obligation; closing the gap is a condition of the 0.3.0
  release, and a test pins it, failing once M3 closes it.
- A manifest whose pictures are all described, such as an enrichment
  checkpoint from 0.3.13, gets no `describe-images`, so a resume describes
  nothing again before the first plan; a replan's reconciliation gives its
  pictures left undescribed one obligation, tried in the replan the run
  makes anyway. The candidates are chosen before the described ones are
  left out, so a document whose pictures are all described no longer moves
  on to its placeholder visuals, as the step did on a resume.
- `picture-description` is `transitional` in `LOCAL_METHODS` (its model call
  is the core's `VisionAgent`) and declares no Toolbox requirement: its
  `pdf.render` crop is per picture and degrades to `crop_unavailable`.
- Tests: the obligation, the plan order (also under Fast Downward), the
  method's scope and message, a picture read as a formula replanned end to
  end, the resume of a 0.3.13 checkpoint, and a differential test of the
  elements before and after the migration.

## 0.3.13 — the executor handles obligations an execution changes (#832, M0 of #640)

A reclassification during the plan, such as a picture the vision model reads
as a formula, removes the element's old obligations and adds new ones. The
executor already selected the added ones (#594). Now it also handles the
rest, so M1 (the picture descriptions as a planned action) can follow:
- **Skipped, not failed.** The step of an obligation this execution removed
  or replaced is `skipped`, with the reason (`EXE_OBLIGATION_REMOVED`). So is
  the step of an obligation that now depends on an open obligation this plan
  does not run before it: one found during the execution, or one planned and
  not run yet (`EXE_OBLIGATION_WAITS_FOR_OPEN`). The replan orders the two.
  `complete-job` is `skipped`, no longer `failed`, while every open
  obligation was found or deferred by this execution
  (`EXE_DISCOVERED_OBLIGATIONS_OPEN`, which names them by kind). One the plan
  ran and left open is still a failure.
- **Stale under the same id.** A step whose obligation changed under its id
  (another kind, targets of other types, or the step's method no longer
  admissible) is `skipped` too (`EXE_OBLIGATION_CHANGED`), and the replan
  decides again. A retarget that keeps the types (a split or a join) is not
  a change.
- **A removal rewires.** A handler that removes an obligation must rewire
  its dependents to the replacement, as the reconciliation does; the
  manifest refuses a dangling dependency. The executor reports one left
  dangling by name (`EXE_DEPENDENCY_REMOVED`) instead of a `KeyError`. Before
  the discovery guard reads the state, the orchestrator rechecks the
  obligation references and the DAG of the manifest the run changed, so a
  dangling reference a handler left anywhere in the graph fails the job with
  the manifest's message instead of a `KeyError` from the guard. The
  messages of the graph checks (unknown targets, dependencies and artifacts,
  a self-dependency, a cycle) follow the locale, like the executor's.
- `skipped` was already a step status of the execution report, so the
  contract does not change. A run where only obligations changed has no
  `failed` step.
- **Its own bound.** After a run without a failed step, the orchestrator
  replans with its own bound, `max_discovery_replans`, apart from
  `max_replans`, which keeps counting failures. It is a constructor option
  (negative values count as 0), set by the service from
  `PDDL_MAX_DISCOVERY_REPLANS` (default 3). A value other than the default
  enters the checkpoint and cache identities, so the default keeps those of
  0.3.12. It stops when a replan would start from the planning state the
  previous one started from (`planning_signature`, taken after the
  reconciliation: targets, dependencies, statuses and tried methods, not
  only ids). The count and the signature are saved with the plan checkpoint
  (`discoveries`, `previous_signature`) and restored on resume; a
  checkpoint without them resumes as before.
- **A failure takes precedence.** A run with a failed step and a discovery
  is a failure replan, so the discovery budget never bypasses
  `max_replans`. With it spent, a critical obligation left open fails the
  job. Serving the discovery without retrying the failed work is #842.
- **Document-level obligations reconciled.** `add_table_enrichment_obligation`
  also runs before each replan:
  - a new table joins the open enrichment, or gets a new one
    (`obligation-enrich-tables-2`) when the existing ones are closed:
    satisfied, or exhausted (`failed`), which is not planned again. Before a
    replan the new one is selected, so the replan schedules it;
  - an enrichment drops the tables the document lost, and one left without
    tables is removed with the dependencies on it (`target_ids` cannot be
    empty);
  - every open obligation whose targets include a table depends on that
    table's open enrichment, and an edge to an enrichment, open or closed,
    that no longer shares a table with it is dropped. That is a rule on
    targets instead of the list of 0.3.12: besides `linearize-table` and
    `select-table-source`, it orders the page obligations of a page with a
    table after the reading, as in 0.3.11, at the cost of serializing them
    behind it. An edge to a closed one stays while the target that justified
    it does, so an exhausted enrichment does not block a dependency that was
    retargeted to another table.
- **The table enrichment keeps to its targets.** `_tables_to_read`,
  `_enrich_table_structures` and `_mark_table_inline_math` take `targets`,
  so a second enrichment reads and marks only its own tables, and its
  message counts only them.
- `_plan_progress` and `_thread_status` move to `pipeline/progress.py`.

## 0.3.12 — the table enrichment is a planned action (#640, M2)

The two table steps that ran before planning move into the plan
(`docs/architecture/workflow-actions.md`):
- reading the tables without a usable structure, or garbled ones, with the
  `DataAgent`;
- marking their cells' inline math from the text layer.

A document with tables gets one `enrich-tables` obligation, which targets all
its tables, satisfied by the `table-enrichment` method. That method runs both
steps as before: one breaker, one retry pass and one text-span reader for the
whole document. The tables' `linearize-table` and, in dual mode,
`select-table-source` obligations depend on it, so the plan reads before it
linearizes or chooses a source, as before. A per-table method was ruled out:
it would wait the retry pass once per failing table and lose the recovery of
the tables read after the breaker opened.

- `RunPorts.services` (`RunServices`) holds the infrastructure a run's stages
  and methods share, one run of one document: `run_breaker`, `run_text_spans`
  and `progress`. The text-span reader keeps no manifest; a step that cannot
  read the text layer records `inline_math_detection = unavailable` on the
  manifest it enriches, the executor's copy included.
- **What the method's result means:** the collective attempt ran. Each table
  keeps its own outcome (`table_read_failure`: `model_failed`,
  `admission_rejected`, `crop_unavailable`), and its `linearize-table`
  validates it. The message reports how many tables needed a reading, how
  many got a structure, what was left and why, and the inline math status
  (`fonts`, `unavailable` or `off`). An admission rejection (#590) is kept and
  still spares the breaker inside the plan.
- `table-enrichment` is `transitional` in `LOCAL_METHODS`: the same
  computation, moved. Its Toolbox calls are conditional, so they are not
  requirements.
- A location label over more than five pages gives the count and the span
  ("12 pages, from 1 to 12"), so the step over every table does not list
  them all.
- A Fast Downward fixture case checks the new order under both planners.

What changes, observably:
- The progress stays: inside the plan the method reports "Enriching the
  tables with OCR" and "Recognizing table N of M" through the run's
  `RunServices.progress`, after the executor's own step message.
- For a document with tables, the plan has one more step, and its
  `problem_sha256` and `plan_id` change.
- The manifest checkpoint is saved after the four enrichment steps before
  planning, not six. Inside the plan the execution checkpoint covers the step
  as a whole, so a crash in the middle of it reads again the tables it had
  already read in that attempt (follow-up: #836).
- A step that raises no longer fails the job at once. Like any method, it
  records a failed attempt, the planner replans with `human-review`, and the
  job then fails on that critical obligation (with `PDDL_MAX_REPLANS`, one
  more execution).
- A job resumed from a 0.3.11 enrichment checkpoint already has its tables
  enriched and gets no obligation; one resumed from an earlier phase gets it.

The picture descriptions (M1) wait for an executor preparation (M0): a
description can retype a picture as a formula, which removes an obligation
while the plan runs.

## 0.3.11 — catalogue facts bound to the exact capability version

The requirement facts name each capability at the exact contract version the
SDK client calls, `capability_id@version` (for example `math.convert@1`, PDDL
symbol `math-convert-1`). That is also the version the catalogue check requires
(#640, PR 2). `toolbox_gate.capability_ref` builds the reference from the SDK
registry; a capability outside the allowlist keeps its bare id.

The plan steps do not change, in `observe` or `enforce`. The problem of a
document with Toolbox methods names the versions, so its `problem_sha256` and
`plan_id` change. A resumed job keeps the plan checkpoint it has, and that
checkpoint's unversioned requirements stay as they are for its replans.

`observe` stays the default; removing it is a later step, once production logs
show no false "would remove" (#809).

## 0.3.10 — the formula methods declare their Toolbox requirements

`mathml` and `latex-verbalizer` call the Toolbox (`math.convert` and
`math.verbalize`, through the math transform provider), but they were missing
from `METHOD_TOOLBOX_REQUIREMENTS`, so the availability gate never checked them
(#789). They are declared now:
- in `observe` the plan steps do not change. The problem of a document with
  formula obligations gains their `requires` facts, so its `problem_sha256` and
  `plan_id` change; a resumed job keeps the plan checkpoint it has;
- in `enforce`, a catalogue without them rules both methods out: a
  `verbalize-formula` obligation falls back to `human-review`, and a
  `normalize-formula` one to `latex-normalizer`.

Every other method without Toolbox requirements is classified in
`planning/toolbox_gate.py`:
- `LOCAL_METHODS` maps each one to a role and a reason. The roles are
  `transitional` (document computation still in the core, which ADR-0028 moves
  to the Toolbox, #804), `validation` (checks work done before planning) and
  `symbolic` (`human-review`);
- `NEVER_AVAILABLE_METHODS` holds `table-specialist`, which has a cost but no
  handler.

Tests fail for a method, with a cost or a handler, that is neither declared nor
classified, and the transitional set only shrinks.

## 0.3.9 — the Toolbox catalogue as planning facts (domain 2.4)

ADR-0029 makes capability and provider availability predicates of the
planning problem (#640, PR 1). The PDDL domain goes to **2.4**:
- `capability` and `provider` types;
- `(requires m c p)` and `(offered c p)` facts;
- a derived `(runnable m)`: the method is `available` (the core has a
  handler) and the catalogue offers every requirement.

`execute-obligation` now needs `runnable` instead of `available`. Domain 2.3
stays shipped.

`PddlProblemCompiler.compile`, `PlannerAgent` and `PlanningProblem` take a
`catalogue` (`CatalogueFacts`). The availability gate builds it from the
catalogue snapshot (`AvailabilityDecision.catalogue_facts()`):
- in `observe`, every requirement is offered, so the catalogue is visible in
  the problem and the plans do not change. These facts are assumed, not
  observed: the gate metadata says `offered_source: assumed` and lists the
  methods the snapshot rules out (`assumed_runnable_methods`); `off` adds no
  catalogue facts;
- in `enforce`, the snapshot decides what is offered, and without a snapshot
  nothing is (fail closed). The gate no longer excludes methods by name
  (`unavailable_methods` is empty), and the same methods are excluded through
  the facts.

The decision's requirements and offered pairs are saved with the plan
checkpoint (`AvailabilityDecision.from_metadata`, which replaces the
orchestrator's `_availability_from`), so a replan after a restart sees the
same catalogue. A checkpoint from before 2.4 keeps its own list of excluded
methods.

The planning checkpoint's identity now includes the domain's hashes. The
executor refuses a plan built under another domain, so after this deploy a
resumed job plans again instead of failing. A resumed job reuses the plan
checkpoint's catalogue decision and does not read the catalogue again
(revalidation on resume: #640, PR 3).

PDDL symbols are unique across the whole problem: values of different types
that normalize alike (a method and a provider both called `docling`) get
distinct symbols, and the validator refuses an object declared twice.

The internal planner is tested with domain 2.4. Fast Downward 26.6 was checked
locally and agrees with it; CI does not run it yet (#790).
`tests/test_fast_downward_domain.py` compares both backends. It carries the
`fast_downward` marker, deselected by default because CI rejects skipped tests:
run it with `-m fast_downward` and `ACESSILIA_FAST_DOWNWARD` set.

## 0.3.8 — the PDDL compiler refuses cyclic and unknown dependencies

The manifest model refuses cyclic and unknown obligation dependencies, but a
replan changes the manifest in place. Before, the compiler let both through:
- a cycle compiled, and only the internal planner refused it, when ordering;
  Fast Downward just found no plan;
- an unknown dependency raised a bare `KeyError`.

`PddlProblemCompiler` now refuses both before any planner runs, with a
`ValueError` that names the cycle or the missing obligation (#783).
The check covers the selected closure: a cycle reached below a root names only
the cycle, and an unknown dependency names the obligation that has it. The
model and the compiler share one walk (`acessilia_core.manifest.dependencies`),
so they report the same cycle; the model's message now names it too.

## 0.3.7 — a planning engine seam

The default plans are unchanged. `acessilia_core.planning.engine` adds the seam between
planning and workflow coordination (#632, PR 3; ADR-0029):
- `PlanningProblem` (manifest, selected roots, unavailable methods);
- `PlanningResult` (plan, compiled problem, optional comparison);
- the `PlanningEngine` protocol;
- `PddlPlanningEngine`, the adapter over `PlannerAgent`.

The adapter now owns the choice of backend (`internal`, `fast-downward`,
`both`) that used to live in the orchestrator. `PddlAccessibilityOrchestrator`
plans through `planning_engine`: an engine passed to its constructor, or by
default a `PddlPlanningEngine` built from its backend options at each planning
call. A test can therefore replace the planner with a fake.

The engine contract:
- `plan` is synchronous and the engine is stateless between calls; the
  property is settable and rejects an object without the protocol.
- An engine has an `identity`. The report's `mode` is `pddl-<identity>`, which
  is `pddl-<backend>` for the default engine, as before. An injected engine's
  identity also enters the planning checkpoint identity, so a job resumed with
  another engine plans again. The default engine's checkpoints keep their
  identity.
- The coordinator rejects a result whose plan does not match its compiled
  problem's hash.
- `PlanningProblem` and `PlanningResult` are only shallowly immutable: they
  share the manifest and the plan (#751).

Two smaller changes:
- `PlannerAgent` is built on first use, so an orchestrator with an injected
  engine does not load the PDDL domain for it.
- The both-mode preferred-plan rule is now `PlannerAgent.preferred`, shared
  with the CLI path; the CLI error message is now the catalogued one.

The defaults `DEFAULT_PLANNER_BACKEND` and `DEFAULT_FAST_DOWNWARD_SEARCH` live
in `planning.models`.

## 0.3.6 — canonical descriptions for the PDDL schemas

The PDDL schema descriptions now use the canonical English message constants
instead of the active-locale lookup, so generating the schemas is deterministic
regardless of the server locale. The execution-report, nominal-plan and
planning-comparison schemas were regenerated with those descriptions; their
versions and structure are unchanged. The three schema-description msgids were
removed from the translation catalogs because they are canonical schema text,
not localized strings. A root test now checks the four committed schemas against
their generators, under both supported locales (#737).

## 0.3.5 — one writer for the JSON Schema files

No behaviour change. The four `write_*_schema` functions now delegate to
`acessilia_core.schema_files.write_schema`, which owns the parent creation and
the UTF-8 JSON formatting (#656).

## 0.3.4 — structured findings rendered through the SDK

No behaviour change. `acessilia_core.pipeline.validators` renders its
`(msgid, kwargs)` findings through
`acessilia_sdk.i18n.translation.resolve_findings` instead of keeping the
formatting loop in the Core. The core now requires `acessilia-sdk>=0.6,<0.7`
(#656).

## 0.3.3 — Toolbox timeout metadata through the SDK

No behaviour change. The Core reads the clients' own timeout keys through
`acessilia_sdk.toolbox.clients.client_timeout_keys()` instead of introspecting
the SDK clients module's internals; `TIMEOUT_KEYS` remains the public Core name
used by the service configuration. The core now requires
`acessilia-sdk>=0.5,<0.6` (#656).

## 0.3.2 — formula_tools docstruct re-exports deprecated

No behaviour change for migrated callers; the old names now emit a
`DeprecationWarning`. `acessilia_core.formula_tools` keeps `wrap_latex` and
`label_spoken_formula`. Import the replacements directly from
`docstruct.text.latex`: `bare_latex` for `normalize_latex` and
`ensure_math_delimiters` for the name of the same name. In-repository consumers
were migrated, and the compatibility names stay until a later breaking version
removes them (#656).

## 0.3.1 — docstruct re-exports deprecated in the pipeline bridges

No behaviour change. `acessilia_core.pipeline.table_ast` and
`acessilia_core.pipeline.validators` keep their localized functions, but the
pure docstruct functions and msgids they used to re-export now emit a
`DeprecationWarning`; import them from `docstruct.tables.ast` and
`docstruct.validation` instead. In-repository consumers were migrated, and the
compatibility names stay until a later breaking version removes them (#656).

## 0.3.0 — the Toolbox adapter no longer re-exports the SDK

**Breaking change** for callers that imported SDK names from
`acessilia_core.toolbox.toolbox_client`. Import `PROVIDER_DEFAULTS`, the
`Toolbox*` errors, `ToolboxCapabilityClient`, `auth_headers`,
`execute_capability` and `require_capability` from `acessilia_sdk.toolbox`
instead.

Runtime behaviour is unchanged. The Core adapter now only maps the run's
`ToolboxConfig` to the SDK client configuration and builds clients, so the
Core no longer acts as an SDK facade (#656).

## 0.2.6 — i18n infrastructure through the SDK

No behaviour change. The generic i18n infrastructure now lives in
`acessilia_sdk.i18n` (#712): locale parsing and normalization, negotiation,
per-task request context, catalog compilation and gettext/plural lookup. The
core keeps its catalogs, message ids, locale policies and the public `t()`/`n()`
translation API. The temporary `acessilia_core.i18n.parse_locales` facade is
removed; the existing `set_request_locale`/`reset_request_locale` names remain
as compatibility re-exports, and new code should import them from the SDK. The
core now requires `acessilia-sdk>=0.4,<0.5`. The new floor also covers the SDK
APIs Core 0.2.5 already consumed -- dual-provider fusion, downscale/renderable
check and `run_sync` -- which the SDK publishes in 0.4.0; the 0.2.5 metadata
still pointed at 0.3.x.

## 0.2.5 — dual-provider fusion, downscale, render check and sync bridge via SDK and docstruct

No behaviour change, except two minor edge cases noted below. The core now
delegates its dual-provider extraction, pure payload fusion/page routing, image
downscaling, renderable-media pre-check, and sync/async bridges to
`acessilia-sdk` and `acessilia-docstruct` (#612):

- `pipeline/fusion.py`: `extract_fused` delegates to
  `acessilia_sdk.operations.fusion.extract_dual_fused` (preserving per-provider
  failure and artifact-fallback logging via `DualFusionUnavailable`), while
  `fuse_extraction_payloads` and `apply_page_routes` delegate to
  `docstruct.fusion.payload.fuse_extraction_payloads` and `route_pages`
  (preserving routed and missing-page logs).
- `toolbox/vision_payload.py`: `downscale_image` delegates rendering to
  `acessilia_sdk.toolbox.clients.pdf.downscale_image`, keeping `ToolboxConfig`
  client lifecycle, localized warning log, and `None` recovery in the core.
- `pipeline/toolbox.py` and `pipeline/judge.py`: replace `_check_renderable`
  with `acessilia_sdk.toolbox.clients.pdf.check_renderable`.
- `pipeline/handlers/inspection.py` and `pipeline/handlers/fusion.py`: replace
  duplicated thread-pool sync/async bridges with `acessilia_sdk.runtime.run_sync`.

Minor edge-case changes:

- The media-type mismatch `ValueError` raised by `check_renderable` now says
  `Source is <declared> but would be sent as <extension>` (dropping
  `"in the manifest"`).
- `vision_payload.downscale_image` with a non-positive or non-finite `scale`
  now returns `None` without constructing a Toolbox client instead of rendering
  a 1 px image.

The core now requires `acessilia-docstruct>=0.5.8,<0.6` (#612).

## 0.2.4 — structural primitives from docstruct 0.5.7

No behaviour change, except one stricter edge case. The core's duplicated
implementations now call `acessilia-docstruct` directly (#612): the table
checks and `DataOutput.table_ast` (`docstruct.tables.structured`), the
heading-hierarchy gap detection and repair (`docstruct.sections`), the
skeleton-order ranking (`docstruct.fusion.skeleton`, same 0.5 threshold), the
slide box helpers (`docstruct.geometry.boxes`), the PNG/JPEG header inspection
(`docstruct.imaging`) and `is_legitimate_text` (`docstruct.fusion.noise`).

The stricter edge case: a `table_ast` whose `rowspan`/`colspan` carries a JSON
boolean used to survive `isinstance(span, int)`; the strict normalizer drops
it. Characterized in `libs/core/tests/test_docstruct_057_adoption.py`.

The core now requires docstruct 0.5.7 or later (#612).

## 0.2.3 — the page judge through the SDK's operation

The `vlm-pairwise-judge` method renders the page and asks the judge through
the SDK's page judge operation (`acessilia_sdk.operations.page_judge`, #470).
The core keeps its decisions: the source check, which pages, the truncation
warning, the threshold and what each failure means. Requests, choices and
failure messages are unchanged, except for one case. An answer whose document
is not an object (null, a list, a string, a number, a boolean) used to raise
`AttributeError` out of the method; it now fails the method as an answer
without a valid `pB`.

## 0.2.2 — table AST from rows by docstruct

The payload builder and the table backfill build a table AST from rows with
`docstruct.tables.ast.table_ast_from_rows` instead of the core's copy (#470).
On the core's inputs, lists of cells, the two differ only on rows whose cells
are all blank, which docstruct leaves out, returning `None` when none is left. The one input that reaches it is a
table whose text is all whitespace and that has no usable table AST: its
payload block now has `table_ast: None` instead of an AST of one empty cell.
The canonical document's table and the exports are unchanged.

## 0.2.1 — slide box geometry from docstruct

No behaviour change. The slide layout (`manifest/slides.py`) uses docstruct's
box geometry instead of its own copies: `boxes_overlap` and `union_area`, new
in `docstruct.geometry.boxes`, and `docstruct.fusion.similarity.area`. The
core now requires docstruct 0.5.6 or later (#470).

## 0.2.0 — strict canonical export validation

**Breaking validation change:** TXT, HTML, DOCX and PDF/UA now require the full
normalized canonical document to match docstruct's packaged schema after the
existing audit and before profile selection. Previously accepted custom block
types, missing block/section IDs and invalid field values now raise localized
`ValueError` before rendering. Existing audit failures retain precedence.

Before adopting 0.2.0, build document trees with `docstruct.canonical` or supply
all required IDs/fields. Repair invalid values; represent custom semantics with
one of the eleven supported block types and metadata. Passing a custom block
in a level filtered by TXT does not bypass the gate. Numeric table cells still
receive the existing sanitizer's text conversion; metadata extensions remain
valid. Raw text/Markdown still goes through the builder.

Persisted/cached canonical mappings, including resumed jobs, are checked again
when exported. Existing artifacts and download tokens are not revalidated.

Pure docstruct serializers and their fallback behavior, the schema, SDK
contracts, profiles, filenames and legacy downloads remain unchanged. No
strictness flag or fallback is added. See [ADR 0026](../../docs/adr/0026-strict-canonical-export-gate.md)
and the [compatibility corpus](../../tests/fixtures/export_schema_gate/README.md).
