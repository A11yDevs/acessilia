# Enrichment as planned actions, after the bootstrap (#640, PR 2)

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](workflow-actions.pt-br.md)

[ADR-0029](../adr/0029-symbolic-core-every-step-planned.md) makes the
semantic steps of a job actions of the planning domain. For the 0.3.0
baseline it distinguishes two phases:

1. **Bootstrap**, which acquires the initial state: media inspection, the page
   limit and the initial structural extraction. Together they produce the
   manifest from which the core formulates the obligations and objects of the
   first problem. The core keeps the admission policy and coordinates the
   phase; the Toolbox runs the operations and returns observations. A fixed
   initial extraction is a deliberate limitation of the baseline: for
   example, the plan does not yet choose the extraction providers.
2. **Closed-loop planning**, from the manifest on. The core plans, observes
   and replans. The enrichment steps, which run before planning today,
   migrate to planned actions.

This page designs the second phase's migration: what runs today, the
constraints a migration must respect, and the order of the pull requests. It
changes no code. Whether the bootstrap itself should be planned is an
investigation for 0.4.0
([#816](https://github.com/A11yDevs/acessilia/issues/816)).

## Today

`PddlAccessibilityOrchestrator._execute` (`pipeline/orchestrator.py`) runs, in
order:

| Phase | Stage | What it does | Calls | Checkpoint |
|---|---|---|---|---|
| Bootstrap | Media inspection | Reads the file's media facts; a slide deck is structured differently | Toolbox `media.inspect` | `media` |
| Bootstrap | Page limit, before extraction | Rejects a document over `DocumentConfig.max_pages` from the inspection's page count (`DocumentTooLargeError`) | — | — |
| Bootstrap | Extraction | Builds the manifest: elements, then the obligations derived from their types | Toolbox `document.structure.extract` (one or two providers) | `manifest` |
| Bootstrap | Page limit, after extraction | Checks the limit again against the extracted structure | — | — |
| Enrichment | Steps before planning, in a fixed order (below); since 0.3.12, steps 5 and 6 run inside the plan (M2), since 0.3.14 the descriptions of step 2 (M1), since 0.3.15 step 4 (M3), since 0.3.19 step 1 (M4a), and since 0.3.20 step 3 (M4b): only the preparation of step 2 is left before planning | | Toolbox and the core's model agents | `enriched` for the preparation of step 2; the execution checkpoint, per plan step, for the rest |
| Planning | | Compiles the problem from the enriched manifest and plans | — | `plan` |

The enrichment steps (`_enrich_before_planning` until core 0.3.11; since
0.3.12, steps 5 and 6 run inside the plan, as the `table-enrichment` method,
M2; since 0.3.14, the descriptions of step 2, as the `picture-description`
method, M1; since 0.3.15, step 4, as the `formula-recognizer` method, M3;
since 0.3.19, step 1, as the `formula-region-classifier` method, M4a; since
0.3.20, step 3, as the `inline-math-marker` method, M4b):

| Step | Function | Calls | Effect on the manifest |
|---|---|---|---|
| 1. Formula regions | `_classify_formula_regions`, inside the plan since 0.3.19 | Toolbox `pdf.render` (the formula crop); `VisionAgent` | checks the extractor's formula labels. A drawing is described once and becomes a picture, which reconciles its obligations (`reconcile_reclassified_element`); an uncertain candidate goes to human review |
| 2. Picture descriptions | `_prepare_pictures` before planning; `_enrich_picture_descriptions` inside the plan since 0.3.14 | `VisionAgent` | first injects a full-page picture for a standalone raster image and annotates the visual-text ownership, both from the media inspection (these stay before planning); then a description per picture, and the ownership annotated again |
| 3. Inline math | `_mark_inline_math` (inside the plan since 0.3.20, `_enrich_inline_math`) | Toolbox `document.text.spans` | marks math in prose |
| 4. Formula LaTeX | `_enrich_formula_latex`, inside the plan since 0.3.15 | Toolbox `math.recognize`, `pdf.render`; `VisionAgent` as the fallback | separates equation numbers, then LaTeX per formula |
| 5. Table structures | `_enrich_table_structures` | `DataAgent` | a structured AST per table |
| 6. Table inline math | `_mark_table_inline_math` | Toolbox `document.text.spans` | marks math in cells (after step 5, which can replace cells) |

What the steps share is not uniform:

| Resource | Steps | Where it lives (core 0.3.12) |
|---|---|---|
| Provider breaker | 1, 2, 4, 5 | the run's, `RunPorts.services` (`run_breaker`), shared with the `formula-region-classifier`, `picture-description`, `formula-recognizer` and `table-enrichment` methods. Their order is the planner's tie-break, so under a partial outage the step the plan runs first spends the breaker's budget first (#853) |
| Per-object progress (`on_progress`) | 1, 2, 4 | a local, from `checkpoints.enrichment_progress`; steps 1, 2, 4 and 5, inside the plan, save the manifest they are enriching after each object into the execution checkpoint (`step_progress`, #836), and a crash mid-step resumes from it |
| Region cache | 1, 2, 4 | from `RunPorts` (`region_cache_for`) |
| Text-span reader (`_TextSpanReader`) | 3, 6 | the run's, `RunPorts.services` (`run_text_spans`), shared by the `inline-math-marker` and `table-enrichment` methods; it keeps no manifest |
| Progress messages | 1–6 | `RunServices.progress`, inside the plan: each method announces its step |
| Media inspection | 2 | a bootstrap output; inside the plan, `RunServices.media_inspection`, set by the orchestrator when it loads or makes the inspection |
| Source file | all | the run context; the manifest records its digest |

Until core 0.3.19, steps 3 and 6 also ran once after execution, before the
canonical build, over the executed manifest (#599): `rescue-omitted` adds
blocks while the plan runs, and the canonical build only converts the spans
the manifest carries. Since 0.3.20 (M4b) that pass is gone. A block the plan
adds gets the `mark-inline-math` obligation through the reconciliation, and a
run that completed with such work replans for it, as a discovery, its job
reopened for that replan. A table adopted from the secondary provider is
flagged `inline_math_stale`, and the same step marks it again. When the step
marks a block after a formula conversion already ran, it drops that
conversion, so the canonical build redoes it with the final variables.

The plan then works on what enrichment produced. Some methods only check that
work: `vision-description` checks the descriptions and `pandoc-table` checks
the table AST. Both are `validation` in `toolbox_gate.LOCAL_METHODS` (#804).

## What the bootstrap extracts

The bootstrap's extraction is rich. The structure providers detect and label
the page's objects, and the enrichment steps complement and check that output;
they do not redo it.

- **Docling**, the primary provider (`TOOLBOX_PROVIDER=docling`, with
  `FUSION_MODE=single` by default) runs:
  - layout detection, with a label and a box per object: text, titles, lists,
    tables, pictures, formulas, code, captions, footnotes, page headers and
    footers;
  - the reading order;
  - OCR;
  - the table structure, with TableFormer `accurate` (the one pipeline option
    the Toolbox configures, `table_mode`). ADR-0030 moves table recognition to
    the specialized capability, `table.recognize`, once Docling and MinerU
    are its providers
    ([acessilia-toolbox#170](https://github.com/A11yDevs/acessilia-toolbox/issues/170)).
- **Docling's optional enrichments stay off by design**: formula enrichment
  (`do_formula_enrichment`), picture description and classification, and code
  enrichment. More specialized providers do that work, and they give better
  results:
  - formula LaTeX: `math.recognize` (PP-FormulaNet), with the vision model as
    fallback;
  - picture descriptions: the vision model;
  - MathML and spoken math: `math.convert` and `math.verbalize`
    (`math-speech`).
- **MinerU**, the secondary provider in `FUSION_MODE=dual`, detects formulas
  (display and inline), tables (as HTML), charts, captions, code and
  footnotes.

So each enrichment step is **gated on what the bootstrap left missing or
doubtful**:

| Step | Runs on | Because |
|---|---|---|
| 1. Formula regions | the extractor's formula labels | a detection can label a drawing as a formula: the label is an observation to check |
| 2. Picture descriptions | pictures without a description | the extractor does not describe pictures |
| 3. Inline math | prose from the text layer | Docling reports no inline formula region for a typeset PDF |
| 4. Formula LaTeX | formulas without LaTeX markup (`has_latex_markup`) | Docling's formula enrichment is off; a recognition must agree with the text layer when there is one |
| 5. Table structures | tables without a usable structure, or garbled ones (`TABLE_VISUAL_REVIEW`) | TableFormer's structure is kept when it is usable. After #170 the extraction delivers tables as regions, and the gate becomes "every table without a valid recognized structure": a region, a suspect structure or a failed read. A valid structure is reused, on resume too (ADR-0030) |

The migration must keep these gates: **an obligation exists only where its
gate holds**. Otherwise the plan would send to a specialized provider an
object the bootstrap already handled well. The gates are also where the
bootstrap's detections are checked. Checking a label, a table's shape or a
recognition against the text layer decides the workflow, so it belongs in the
plan.

The policy is ADR-0030 (proposed in #819): the structure suites stay
structural, and whatever else they offer is used per capability, as a provider
competing with the others. Two points of today's configuration do not match it
yet:
- **The design intent is enforced only by the Toolbox's defaults.** The core
  sends `document.structure.extract` only the language and the cache flag,
  and no pipeline option. The plugins that are off are off because of the
  Toolbox's provider registry and the providers' defaults, which neither the
  core nor the manifest sees. The Docling adapter records only the request's
  parameters in `extractor.configuration`, not the registry's (`table_mode`).
- **MinerU's formula and table recognition are on by default.** The
  Toolbox's MinerU 2.1 adapter (`main`, release 0.2.0) sends
  `formula_enable=true` and `table_enable=true` unless told otherwise;
  `develop` moves to MinerU 4.0.12 with `--tier basic`. In dual mode, a fused
  formula that comes from MinerU with LaTeX, or a table that comes with HTML,
  passes the gate, and so skips PP-FormulaNet or the table reader. Under
  ADR-0030, formula recognition goes off in the structure capability
  ([acessilia-toolbox#169](https://github.com/A11yDevs/acessilia-toolbox/issues/169)),
  and so does table recognition, once `table.recognize` has Docling's and
  MinerU's recognizers as providers (#170).

## The key observation

The domain already has one generic operational action,
`execute-obligation(o, m)`. A method is a way to satisfy an obligation, and
the executor runs the method's handler. So **a step becomes an action by
becoming a method of an obligation**: the planner then chooses it, orders it
through `depends-on`, accounts its cost, rules it out through the catalogue
facts (domain 2.4) and replans after it fails. None of that needs a new
action schema, and new obligation kinds are objects the compiler emits from
the manifest. **The enrichment migration needs no domain change.**

## Constraints

1. **A plan cannot create objects; obligations change during the plan.**
   Formula classification can reclassify an element and reconcile its
   obligations, so after it the next actions depend on obligations the
   problem did not have: added ones, and also removed, replaced or rewired
   ones.

   Before M0 the executor handled only additions. After a successful, validated
   handler, `_run_obligation_handler` calls `_select_discovered` (#594), which
   selects the obligations the handler added. When one is still unsatisfied,
   it sets `replan_required`. The rest of the plan still runs, and the report
   carries the flag to `_replan_until_done`, which replans with those
   obligations as roots.

   What was missing (met by M0, below):
   - the discovery signal shares the `max_replans` budget with failure
     recovery, and the report does not say why it asks for a replan;
   - it sees only **added** obligations, not the other semantic changes: an
     obligation made inapplicable, removed or replaced by a reclassification,
     or a changed dependency;
   - the rest of the plan runs even if a change invalidated some of its
     steps.

   M3 and M4 evolve this mechanism; they do not add a second one. Their
   criteria:
   1. **Reuse the trigger:** start from `_select_discovered` and the
      `replan_required` flow.
   2. **Tell the reasons apart:** a discovery or state change versus an
      operational failure, both in the report (for observability) and in the
      budget.
   3. **Separate the bounds:** `max_replans` keeps counting failure recovery;
      a separate guard stops expansion or reclassification that makes no
      progress, so it cannot cycle.
   4. **Cover more than additions:** detect when a reclassification makes
      existing obligations inapplicable, changes dependencies or needs new
      obligations.
   5. **Revalidate the remaining plan:** do not run steps based on types or
      obligations made obsolete by a relevant change of the manifest.
   6. **Keep persistence and resume:** `save_plan`, the replacement of the
      execution checkpoint as today, and idempotence tests.
   7. **Test the scenarios:** a success that creates an obligation, a success
      that reclassifies an element, a failure with an alternative, a resume
      from a checkpoint, and the guard against cyclic replans.

   A `MethodResult` flag ("state changed, replan") stays open for discussion,
   as an evolution of the existing contract.

   **Met in core 0.3.13 (M0, #832).**
   - The trigger is the existing one, `_select_discovered` and
     `replan_required` (1).
   - The report tells the reasons apart without a schema change. A step the
     change made obsolete is `skipped` with its reason (`skipped` was already
     a step status), so a run where nothing failed has no `failed` step. The
     orchestrator counts that replan apart and logs its reason (2).
   - `max_replans` counts failures and `max_discovery_replans` the rest. A
     discovery replan whose planning state is the one the previous one
     started from does not run (3). The state is `planning_signature`,
     taken after the reconciliation: each replannable obligation's kind,
     targets, dependencies, status and tried methods, so the same ids with
     other targets or dependencies are progress. It is saved with the plan
     checkpoint (`previous_signature`), so a resume keeps the guard; a
     checkpoint without it resumes as before.
   - A run with a failure and a discovery is a failure replan while
     `max_replans` lasts: the discovery budget never bypasses the failure
     one. Since core 0.3.22 (#842), with `max_replans` spent, the run can
     still be a discovery replan, within `max_discovery_replans` and the
     signature guard, but only for the work no failure touches
     (`_discovered_roots`): never tried, with no open, tried obligation
     among its dependencies. The failed obligations and what waits for them
     are left out of that round and of every later one, so their
     alternatives never run. Left out of a plan is not cancelled: the
     executor preserves `selected` as a job goal. The plan's scope is
     `NominalPlan.selected_obligations`; `complete-job` checks that scope
     plus newly discovered goals. Delivery judges every open goal. Excluded
     work carries `deferred_reason` when known (ADR-0031). A
     critical obligation left open, found, failed or waiting for failed
     work, still fails the job instead of being delivered silently, and a
     refinement is delivered with a warning and no cache.
   - Removed, replaced and rewired obligations are covered (4). A step
     whose obligation now depends on an open obligation this plan does not
     run before it (found during the execution, or planned and not run yet)
     waits for the replan. A removal must rewire the removed obligation's
     dependents (`_rewire_removed_dependencies`); the manifest refuses a
     dangling dependency, and the executor reports one as the handler's bug.
     Before the guard reads the state, the obligation references and the DAG
     of the manifest the run changed are rechecked, so a dangling reference a
     handler left fails the job with the manifest's message, naming the
     obligation and the missing dependency, instead of a `KeyError`. Since
     core 0.3.21 (#844) the manifest a run delivers gets every check a
     resume makes, whatever the run's status, dry runs included
     (`validate_delivered_manifest` in `_check_unsatisfied`): a run that
     completed, or ended without a replan, can no longer deliver a dangling
     reference, a cycle, a satisfied obligation waiting for an open one, or
     stale counts.
   - `PDDL_MAX_DISCOVERY_REPLANS` (default 3) sets the separate bound; a
     value other than the default enters the checkpoint and cache
     identities.
   - The steps they make obsolete are skipped, not run (5). That includes an
     obligation changed under its id: another kind, targets of other types,
     another target set, or the step's method no longer admissible. The
     executor compares each step with what made its method applicable in the
     plan's manifest. Since core 0.3.23 (#843) that includes the target ids.
     `remap_references` (`handlers/structure.py`) records each split's and
     join's mapping on the working manifest, in order; the executor composes
     them over the planned targets and compares the result with the current
     ones (`_retargeted`). A split or a join alone is not a change and spends
     no discovery replan; anything else is, whatever it looks like: an
     element swapped in or added, new or pre-existing, or one dropped
     without a join. The execution checkpoint saves the record for a resume
     (one from before 0.3.23 has none, and a split before it costs one
     replan). A split or a join can still make the step stale for another
     reason (types, method, dependencies). Ids are unique in a manifest; one
     freed by a removal may come back in a later plan.
     Changes of the elements' content under the same type are not compared
     (element revisions are #840).
   - The discovery count is in the plan checkpoint, and the skips derive from
     the plan's and the checkpoint's manifests, so a resume needs nothing
     else (6).
   - `tests/test_changed_obligations.py` and
     `tests/test_changed_obligations_semantics.py` have the scenarios (7),
     including a reclassification inside a real handler, a failure with an
     alternative, a failure next to a discovery, and the resume of the
     discovery count and the guard.
2. **Causal order becomes dependencies, never costs.** Costs choose between
   alternatives; they must not force a technically required order. The
   fixed order turns into `depends-on` between obligations of the same
   element:
   - formula classification comes before the picture description of a
     candidate it reclassifies, and before the formula LaTeX of a candidate it
     keeps or leaves unclassified. Any obligation its reconciliation creates
     comes after it too;
   - formula LaTeX comes before `verbalize-formula` and `normalize-formula`;
   - the table structure comes before the table's inline math.

   No element-level data dependency was found between prose inline math and
   the formula steps (they read different elements), between pictures and
   tables, or between formula LaTeX and tables. Each migration confirms this
   for its own step. M4b revises it for the formula conversions: they read
   the variables the prose's marks give, a dependency across the document
   rather than on a shared element (below).

   **M1 (core 0.3.14).** The descriptions now run after steps 3 and 4.
   Prose inline math reads paragraphs, list items, captions and footnotes,
   and its overlay test matches only text made of negation slashes, not a
   picture's. Formula LaTeX reads formulas, so it no longer sees a picture
   the model reads as a formula: that formula keeps the model's LaTeX,
   without the recognizer's second reading or the separation of its
   equation number. That gap lasted one release: M3 (core 0.3.15, #846)
   makes the formula LaTeX the document's obligation, which the
   reconciliation gives to a formula found during the plan, so its
   `verbalize-formula` waits for it
   (`test_a_picture_read_as_a_formula_gets_the_formula_steps`).

   **M3 (core 0.3.15).** The formula LaTeX now runs inside the plan, after
   prose inline math, which reads other elements, and in no order with the
   pictures and the tables, which take other elements (formulas are never
   described, and never tables). `verbalize-formula` and
   `normalize-formula` depend on it, as do the page obligations of a page
   with a formula: the order before planning.

   What M3 restores for a formula found during the plan (#846) is what the
   step did: its equation label separated and, when the model's text has no
   LaTeX markup, a reading. LaTeX the model already gave is not read again,
   as before; an independent second reading is research (#852). The step's
   selection and its execution share one policy
   (`formulas_needing_number_separation`, `formulas_needing_recognition`),
   so a formula selected only for its label is not read again. Inside the
   step the strategy stays fixed (`math.recognize`, then the vision
   fallback); the plan chooses, orders and accounts the step, not that
   strategy. `math.recognize`'s outage is paid once per obligation: a
   second one, for formulas found during the plan, probes again. A formula
   whose crop could not be made records why (`crop_unavailable`,
   `no_page`), as a picture does.

   Between document steps that take other elements there is no dependency,
   and their costs are equal, so the planner breaks the tie
   (`DOCUMENT_STEPS` is the reconciliation's order, not the plan's).

   **M4a (core 0.3.19).** The formula region classification runs inside the
   plan. It shares the formulas with the formula LaTeX, which must come
   after it (the classification decides whether a region is mathematics), so
   `recognize-formulas` depends on `classify-formula-regions` for the
   formulas they share: recognition declares classification as a predecessor;
   registration order validates that declaration. An element the descriptions
   turned into a formula (a picture or a placeholder visual) is not classified: the
   descriptions ran after the classification before planning, so it never
   was, and a second answer could drop the formula they gave. A
   classification that got no answer (`unclassified`) is tried again when
   the step runs again, like the other composite steps; `math` and
   `unresolved` are decisions. A shared formula makes the whole recognition
   batch wait for the classification batch: the cost of document-level
   granularity, accepted for 0.3.0 (sub-batches are #619 research).

   **M4b (core 0.3.20).** The prose's inline math runs inside the plan, as
   the document's `mark-inline-math` obligation. The formula conversions
   (`verbalize-formula`, `normalize-formula`) read the variables its marks
   give, so they wait for it although they share no element: the step
   declares them as `waiting_kinds`, an explicit document-scope information
   dependency alongside its shared-target `predecessors` (#865). It shares a paragraph with the
   descriptions (a mostly visual document) and a stale table with the table
   enrichment, and comes after both. It calls no model, so the vision
   breaker does not order it; the steps that share that breaker
   (descriptions, formula classification and LaTeX, tables) are ordered by
   it only operationally, under a partial provider outage; that is
   documented, not forced (#853).

   The #867 review fixed four points of that design:
   - *A stale table marked again.* A satisfied obligation does not cover an
     element whose result the run invalidated since (`DocumentStep.renewed`):
     a table flagged `inline_math_stale` after the step marked it joins a new
     obligation. An exhausted obligation still covers it, so a degraded
     attempt is not reopened forever.
   - *Evidence the detection cannot read.* A prose block without boxes that
     already carries `$…$` (a rescued paragraph) joins the step too: the
     step marks nothing in it, but weighs it to drop the conversions made
     before it, as the pass after execution of #599 did. With
     `INLINE_MATH_DETECTION=off` the step is still planned for the same
     reason, marks nothing and reports `detection: off`.
   - *A non-critical step.* `mark-inline-math` is non-critical
     (`DocumentStep.critical=False`): when it is exhausted, the conversions
     that waited for it lose that edge and run without its variables,
     instead of being left out of the replan and failing the job.
   - *The work a completed run leaves.* Finding it does not reopen the job:
     the replan loop does, only once the replan is allowed. With the
     discovery budget spent, the job keeps its status, and
     `_check_unsatisfied` judges what was found as for any run: a critical
     obligation fails the job, a refinement leaves a warning.

   When the step drops a conversion, the `verbalize-formula` or
   `normalize-formula` obligation stays `satisfied`: the step's method ran
   and its evidence holds. The canonical build regenerates `mathml` and
   `verbalization` from the final manifest (`_enrich_math_blocks`, with the
   run's math enricher: the same Toolbox conversions, and the variables of
   every formula and inline span); without them the formula keeps its
   LaTeX, as when the planned methods degrade. The
   regeneration is a projection of the final manifest, not a new semantic
   decision, so it stays outside the plan. Reopening the obligations
   instead, with selective invalidation and provenance, is #871.
3. **Infrastructure stays out of the domain** (ADR-0029). The region cache is
   already in `RunPorts`. The breaker, the progress hook and the text-span
   reader are locals today. The proposal is to make them a per-run
   **enrichment service** in the run context, built by the orchestrator, so
   that the breaker keeps its document-wide scope. Otherwise one provider
   outage would become one failure per obligation.
4. **Stage inputs come from the manifest, not from new ports.** Handlers reach
   the source file through the manifest (`_verify_source_digest`), as
   `pymupdf-region` does. The two parts of step 2 that read the media
   inspection, the full-page picture injection and the ownership annotation,
   derive from bootstrap facts and create objects, so they **stay in the
   bootstrap**. The picture method (M1) annotates the ownership again after
   it retypes elements, as the step did, so it reads the inspection the
   orchestrator gives the run's services (`RunServices.media_inspection`);
   the planner never reads it. Recording the two facts it needs in the
   manifest instead, typed, is #847. Inside the plan the method does not
   inject the full-page picture again: that structural part stays the
   bootstrap's.
5. **Handlers are synchronous.** `MethodHandler` is
   `(manifest, obligation_id) -> MethodResult`; the steps are asynchronous. A
   migrated handler calls them through `acessilia_sdk.runtime.run_sync`, as
   `dual-provider-fusion` does. The executor runs on a worker thread
   (`run_blocking`), where `run_sync` starts its own loop.
6. **Model calls are not capabilities yet.** `VisionAgent` and `DataAgent` are
   the core's model agents ([classification](core-agent-classification.md)).
   Moving a step into a method makes it planned, but its model call stays in
   the core. Such a method is `transitional` in `LOCAL_METHODS` until the call
   becomes a capability (#804, #640 PR 4). Until then the gate cannot check
   the model call; the Toolbox calls the step makes are declared in
   `METHOD_TOOLBOX_REQUIREMENTS` when missing one rules the method out, or
   in `METHOD_OPTIONAL_CAPABILITIES` when missing one only degrades it per
   element (#848). The gate reports a missing optional call as
   `degraded_methods` in the availability metadata and in the log, and
   never rules the method out; its role in `LOCAL_METHODS` (where the
   implementation lives) is a separate dimension.
7. **Resume stays idempotent.** A step today skips the objects it already
   finished. As a method, the same record makes a re-executed plan step cheap,
   and the execution checkpoint records which steps ran.

   **Inside a composite action (#836).** The planner's atomicity is not the
   granularity of persistence. A composite method (`picture-description`,
   `formula-recognizer`, `table-enrichment`) saves the manifest it is
   enriching after each finished object, coalesced as before planning, into
   the execution checkpoint, as `step_progress` next to the last finished
   step (through `RunServices.step_checkpoint`; no new phase). A resumed
   execution of the same plan starts that step again from it, and the step's
   per-object gates (`vision_description_complete`, a table's structure, a
   formula's recognition record) skip the objects already done, so the model
   calls they cost are not paid again. The obligations the interrupted
   step's finished objects added (a picture read as a formula gets
   `verbalize-formula`) are selected on the restore, as the executor would
   have done once the handler returned, so the replan plans them. A resumed
   run's checkpoint starts from the snapshot it resumed, so a second crash in
   the same step keeps the resumed run's progress too. The progress of a
   step the plan does not run next is never used, and the next finished
   step drops it. The
   collective recovery stays the step's: one breaker, one retry pass. The
   progress messages go through `RunServices.progress`, tied to the job.
8. **Equivalence first.** Each migration keeps a differential test of the final
   manifest on fixture documents, before and after (ADR-0028).

## Document-level obligations

The first migration showed that a step cannot always become a per-element
method without losing behaviour. The table step reads the tables with one
provider breaker, makes one retry pass for the whole document (it waits
`VISION_RETRY_PASS_DELAY_SECONDS` once, and with an open breaker lets one
probe call through, which recovers every table if the provider came back) and
reports its progress. Per table, each failing table would wait on its own,
and the tables after the breaker opened would lose the recovery. The
description of pictures, in addition, runs concurrently (`vision.concurrency`),
while the executor runs one step at a time.

So a step that works on the whole document becomes **one obligation of the
document**:
- it targets every element the step works on;
- its method runs the step as before, with the run's breaker and text-span
  reader (`RunPorts.services`);
- the per-element obligations that need its result depend on it.

The planner still chooses, orders and accounts it, rules it out through the
catalogue facts and replans after it fails. ADR-0029 allows a composite action
like this: its internal steps are not PDDL actions. The obligation is created
when the manifest is enriched, before the first plan, and only when the
document has the elements its step works on. That is its gate; the method
keeps the step's per-element gates.

Five steps are planned this way, each a `DocumentStep` of
`pipeline/document_obligations.py`, which holds the rules below once for
all of them:

| Step | Kind and method | Targets | Dropped from its targets | Depends on it |
|---|---|---|---|---|
| Table enrichment (M2, 0.3.12) | `enrich-tables`, `table-enrichment` | every table | an element no longer a table | `linearize-table`, `select-table-source`, and the page obligations of a page with a table |
| Prose inline math (M4b, 0.3.20) | `mark-inline-math`, `inline-math-marker` | in a PDF, the prose (paragraphs, list items, captions, footnotes) with boxes and text that no detection has marked, and the tables whose marks went stale (`inline_math_stale`) | an element no longer prose or a table | the page obligations of a page with such an element, and, whatever their targets, `verbalize-formula` and `normalize-formula` (`waiting_kinds`) |
| Formula region classification (M4a, 0.3.19) | `classify-formula-regions`, `formula-region-classifier` | in a source that can be rendered, the formulas without LaTeX markup that no classification has decided, except one the descriptions turned into a formula | an element no longer a formula (a drawing it described is a picture) | `recognize-formulas` (they share the formula), `verbalize-formula`, `normalize-formula`, and the page obligations of a page with a formula |
| Formula LaTeX (M3, 0.3.15) | `recognize-formulas`, `formula-recognizer` | the formulas with an equation label to separate and, in a source that can be rendered, the ones without LaTeX that no recognition has recorded | an element no longer a formula (the recognition read it as a picture) | `verbalize-formula`, `normalize-formula`, and the page obligations of a page with a formula |
| Picture descriptions (M1, 0.3.14) | `describe-images`, `picture-description` | the pictures not described yet; without pictures, in a mostly visual document, its placeholder visuals, or the first element of a one-page one; never a formula or a table | an element that became a formula or a table | `describe-image`, and the page obligations of a page with a picture |

A manifest whose pictures are all described (an enrichment checkpoint from
0.3.13) gets no `describe-images`. The candidates are chosen before the
described ones are left out, so a document whose pictures are all described
no longer moves on to its placeholder visuals, as the step before planning
did on a resume. The candidates and the elements the step keeps share one
test (`is_describable`), so the step never takes an element it would then
drop. A formula or a table, which the one-page fallback used to take, is
left to its own steps and never retyped as a picture.

**Between document steps**, `DocumentStep.predecessors` declares causal
relationships (#865). An edge requires both a declaration on the dependent and
shared targets. `DOCUMENT_STEPS` is the reconciliation order and checks that a
declared predecessor appears earlier; registration order alone and a shared
vision breaker never create edges. Duplicate kinds/predecessors and unknown,
forward, self or cyclic declarations fail before any manifest mutation. The
second edge pass remains necessary so the first plan sees all declared pairs.

| Consumer | Predecessor / information source | Scope | Exhaustion policy |
|---|---|---|---|
| `recognize-formulas` | `classify-formula-regions` | shared targets | dependency remains mandatory |
| `mark-inline-math` | `describe-images` | shared targets | dependency remains mandatory under the existing step policy |
| `mark-inline-math` | `enrich-tables` | shared targets | dependency remains mandatory |
| `verbalize-formula`, `normalize-formula` | `mark-inline-math` | document (`waiting_kinds`) | may degrade: `critical=False` releases exhausted edges |

These declarations preserve the current real workflows. Independent document
steps can overlap targets without acquiring a dependency; the historical
synthetic description/table overlap now stays unordered in both directions.
Ordinary element/page obligations retain the target-based rule and explicit
`waiting_kinds` information dependencies. Those cross-target waits do not
implicitly declare document-step predecessors. Open edges to a producer that
no longer shares a target are removed; closed dependent obligations retain
their historical graph. `critical` still controls exhaustion for the producer's
managed outgoing edges in both scopes, rather than adding a new per-edge or
manifest-dependent policy. In particular, the descriptions' delivery-dependent
criticality is not redesigned here.

This is a declaration of the existing Python coordination contract, preparing
safe batching (#948) and causal-domain work (#934); it does not yet move these
relations into PDDL. The shipped domain bundle/hashes and accepted plan
checkpoints remain unchanged. No harness/reference regeneration is needed when
only this rule changes and the historical canonical output remains equal.

**The plan decides the targets.** The method describes its obligation's
targets that are still describable and not described, whatever the
candidates are when it runs (a placeholder visual stays a target after a
picture appears), so it never succeeds without trying the work it was
planned for. A target another step now reads is reported as
`not_describable`.

**Resuming an older checkpoint.** An enrichment checkpoint from 0.3.13 is
resumed as it is: its pictures were described, or left with a failure
reason, before planning, so it gets no `describe-images`. A replan's
reconciliation gives the ones left undescribed one obligation, so the
replan the run makes anyway tries them once more.

**What its result means.** The method succeeds when the collective attempt
ran: the step completed for every target. That is not a claim that every
element is now enriched. Each element keeps its own outcome (for a table,
`table_read_failure` with its reason, including the `admission_rejected` of a
full model-call runner, #590), and the per-element obligations that depend on
it validate their element. Failing the whole obligation for one element would
block the elements that are usable. So the method's message reports what
happened to each element, and it fails when the step raises or when local
admission pressure kept the model from being asked (below).

**A local admission rejection is a deferral (#828).** A full model-call
runner is not an element outcome: the provider was never asked. When a
document step leaves any target `admission_rejected`, its `MethodResult` is
`success=False` with `failure_kind="admission_rejected"`. The executor records
the step as `failed` with the same typed kind, leaves the obligation pending
and records no method attempt, so the replan keeps the method available and
runs the step again for the objects still pending, within `max_replans`.
A deferred action spends the failure recovery budget, not the discovery one;
when that budget is spent the open obligation follows the delivery policy (a
critical one fails the job), and a rerun can retry it. The plan checkpoint
records the deferred ids (`admission_deferred_ids`), so a plan replacement or
resume keeps the same budget; a checkpoint before the field restores none, and
the current execution report contributes its deferrals. The rejection keeps
the method eligible; it does not force the planner to choose it again, since
changed availability, costs or goals can legitimately select another admissible
method. Provider unavailability, a timeout and an insufficient answer stay
ordinary method failures: they are recorded as tried and the replan may use
another method.
`ExecutionStepResult.failure_kind` exposes the distinction in the
execution report; the PDDL domain and the Core–Toolbox contracts do not
change. A closed runner is lifecycle, not capacity pressure, and stays an
execution failure.

**Reconciled before each plan (M0, #832).** `reconcile_document_steps`
runs when the manifest is enriched and again before each replan, for each
step. The rules are written here for the tables; they are the same for the
pictures:
- a table that no enrichment covers joins the open one; when the existing
  ones are closed, the new tables get a new one
  (`obligation-enrich-tables-2`, …). Reopening a satisfied one would leave
  satisfied obligations waiting for an open one, and an exhausted (`failed`)
  one is not planned again, so a table joining it would never be read;
- an enrichment drops the tables the document lost, and one left without
  tables is removed with the dependencies on it (an empty `target_ids` is
  invalid). The step that removed an element removes or retargets that
  element's own obligations and the page's `element_ids`;
- every open obligation whose targets include a table depends on that
  table's open enrichment, and only on those: an edge to an enrichment,
  open or closed, that no longer shares a table with it (the enrichment
  lost the table, or the obligation was retargeted) is dropped. Only this
  rule makes edges to an `enrich-tables` obligation, so the edges it drops
  are its own; an edge to a closed one stays while the target that
  justified it does. Otherwise an edge to an exhausted enrichment would
  block its dependents from being replanned at all;
- the rule is on targets, not a list of kinds: besides `linearize-table`
  and `select-table-source`, it orders the page obligations
  (`refine-reading-order`, `fuse-providers`, `adjudicate-page`) of a page
  with a table, whose targets are the page's elements. That is the order of
  0.3.11, where the tables were read before planning, at the cost of
  serializing those page obligations behind the reading. A future step that
  must run before the reading is not one this rule should order; it needs an
  exclusion in the rule.

**Scoped to its targets.** The method reads and marks only its obligation's
tables (`targets` in `_tables_to_read`, `_enrich_table_structures` and
`_mark_table_inline_math`), so a second enrichment never reads again or
changes a table an earlier one owns, even one still eligible for a reading,
and its message counts only its own tables. The breaker, the span reader and
the progress stay the run's. The picture method keeps to its pictures the
same way (`targets` in `_enrich_picture_descriptions`).

**The picture descriptions change obligations (M1).** A picture the model
reads as a formula becomes a formula: the reconciliation of the element
replaces its `describe-image` with `verbalize-formula`, and the placeholder
visual the model describes becomes a picture with a `describe-image`. The
executor skips the step of the replaced obligation and replans for the new
ones (M0). The method's message counts the pictures described, the ones read
as formulas, the ones already described, and the reason each one left
undescribed has.

## Migration order

Each step is one pull request; M4 is two (M4a, M4b), since its two steps
are independent.

| PR | Step | Obligation and method | Role | Toolbox requirements | Changes obligations while the plan runs |
|---|---|---|---|---|---|
| M2 (done, core 0.3.12) | Table structures and table inline math | `enrich-tables`, one per document with tables, method `table-enrichment`; `linearize-table` and `select-table-source` depend on it. After #170 the method calls `table.recognize`, whose providers compete (`docling-table`, `mineru-table`, the VLM) | `transitional` (`DataAgent`) | optional (#848): `pdf.render` for a table read again and `document.text.spans` for the marks degrade per table, so they never rule it out | no |
| M0 (done, core 0.3.13) | Executor preparation | The executor skips, and records as `skipped` with the reason, the step of an obligation this execution removed or replaced, and of one that now waits for an open obligation the plan does not run before it. `complete-job` is skipped while every open obligation was found or deferred; one the plan ran and left open is a failure. A step whose obligation changed under its id is skipped too. The orchestrator replans after such a run with its own bound (`max_discovery_replans`), apart from `max_replans`, and stops when a replan would start from the same planning state. Document-level obligations are reconciled before each replan, and the table enrichment keeps to its targets | — | — | — |
| M1 (done, core 0.3.14) | Picture descriptions | `describe-images`, one per document with pictures to describe (or with the placeholder visuals of a mostly visual document), method `picture-description`, running the step with its concurrency and retry pass; `describe-image` keeps `vision-description`, which checks the result, and depends on it. The injected picture and the first ownership annotation stay before planning | `transitional` (`VisionAgent`) | optional (#848): `pdf.render` for a picture's crop degrades to `crop_unavailable` | yes: a description can retype a picture as a formula, which removes its `describe-image` and adds `verbalize-formula` |
| M3 (done, core 0.3.15) | Formula LaTeX | `recognize-formulas`, one per document with formulas to recognize or equation labels to separate, method `formula-recognizer`, running the step with its concurrency; `verbalize-formula` and `normalize-formula` depend on it. A document-level obligation, like M1 and M2, not one per formula as first proposed: the step shares one breaker, one `math.recognize` probe per obligation and its concurrency across the document | `transitional` (`VisionAgent`, the fallback) | optional (#848): `math.recognize` degrades to the vision fallback and `pdf.render` per formula, so they never rule it out | yes: the fallback can read a formula as a picture, which replaces its formula obligations with `describe-image`; and a formula the descriptions find gets the step on the replan |
| M4a (done, core 0.3.19) | Formula regions | `classify-formula-regions`, one per document with formula regions to check, method `formula-region-classifier`, running the step with its concurrency; `recognize-formulas` depends on it for the formulas they share. Document-level, like M1–M3, not one per region as first proposed (`classify-formula-region`) | `transitional` (`VisionAgent`) | optional (#848): `pdf.render` for a region's crop | yes: a drawing becomes a described picture (its formula obligations replaced by `describe-image`), and an uncertain region goes to human review (`verbalize-formula` keeps only `human-review`, `normalize-formula` is dropped) |
| M4b (done, core 0.3.20) | Prose inline math | `mark-inline-math`, one per PDF with prose to mark, method `inline-math-marker`; `verbalize-formula` and `normalize-formula` wait for it (`waiting_kinds`). Replaces the pass after execution of #599: a block the plan adds gets it on a replan, which a completed run now makes for such work | `transitional` (the detection runs in the core, `docstruct`) | optional (#848): `document.text.spans` | yes: a block the plan adds, and a table adopted from the secondary provider, get the step on the replan |
| — | Bootstrap | Kept and documented as the 0.3.0 baseline | — | — | — |

M2 came first because it changes no obligation while the plan runs. M1 was
planned first, but its step retypes elements: a picture the model reads as a
formula becomes a formula, and the reconciliation removes the picture's
`describe-image` and adds `verbalize-formula`. The executor only handles
added obligations then (`_select_discovered`), so M1 waited for M0 and
followed it in core 0.3.14. M3 followed in 0.3.15 and closed the gap M1
left for a formula found during the plan (#846). M4a followed in 0.3.19 and
M4b in 0.3.20: every enrichment step but the pictures' preparation now runs
inside the plan.

Each PR:
- removes its step from `_enrich_before_planning`;
- updates `LOCAL_METHODS`, `METHOD_TOOLBOX_REQUIREMENTS` and
  `METHOD_OPTIONAL_CAPABILITIES`;
- adds the differential test and a Fast Downward fixture case (the CI job
  from #790);
- updates this page.

## The bootstrap

The bootstrap stays a fixed, auditable phase in 0.3.0:
- media inspection;
- the page limit before and after extraction;
- the initial extraction;
- the picture injection and ownership annotation that derive from the
  inspection.

Encapsulating it in one composite Toolbox capability (for example
`document.bootstrap@1`, returning the media facts, the page count and a
versioned reference to the initial structure) is an option, not a
requirement. It is worth it only if composing `media.inspect` and
`document.structure.extract` actually simplifies the flow, and the Toolbox
would still not formulate obligations or the problem. Planning the bootstrap
itself is #816 (0.4.0).

## Open questions

- **The bootstrap's configuration:** ADR-0030 makes the options the core
  relies on explicit and recorded. Once the Toolbox reports them (#169), the
  manifest keeps them as provenance.

- **The discovery replan:** how the existing `_select_discovered` signal
  reports its reason and gets its own bound, and whether a `MethodResult`
  flag is worth the contract change.
- **Costs** of the new methods, so that, when nothing fails, the planner
  picks the same methods enrichment runs today. The order itself comes from
  `depends-on`.
- **The enrichment service:** its shape in the run context, and confirming
  that the breaker's document-wide scope is kept.
- **M1 and M4 overlap:** formula classification already describes a drawing
  it reclassifies. Once both are methods, the description should be made
  once, by `vision-description`.

## Out of scope

- Planning the bootstrap: #816 (0.4.0).
- Composing the domain from Toolbox fragments. That waits on ADR-0029's open
  decision, "Fragments per version", which the Toolbox's owners must accept.
- Turning the model agents into capabilities (#804, #640 PR 4).
