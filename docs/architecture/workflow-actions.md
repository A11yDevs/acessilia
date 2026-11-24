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
| Enrichment | Four steps before planning, in a fixed order (below); since 0.3.12, steps 5 and 6 run inside the plan (M2) | | Toolbox and the core's model agents | `enriched`, per object, for steps 1–4; the execution checkpoint, per plan step, for 5–6 |
| Planning | | Compiles the problem from the enriched manifest and plans | — | `plan` |

The enrichment steps (`_enrich_before_planning` until core 0.3.11; since
0.3.12, steps 5 and 6 run inside the plan, as the `table-enrichment` method,
M2):

| Step | Function | Calls | Effect on the manifest |
|---|---|---|---|
| 1. Formula regions | `_classify_formula_regions` | Toolbox `pdf.render` (the formula crop); `VisionAgent` | checks the extractor's formula labels. A drawing is described once and becomes a picture, which reconciles its obligations (`reconcile_reclassified_element`); an uncertain candidate goes to human review |
| 2. Picture descriptions | `_enrich_picture_descriptions` | `VisionAgent` | first injects a full-page picture for a standalone raster image and annotates the visual-text ownership, both from the media inspection; then a description per picture |
| 3. Inline math | `_mark_inline_math` | Toolbox `document.text.spans` | marks math in prose |
| 4. Formula LaTeX | `_enrich_formula_latex` | Toolbox `math.recognize`, `pdf.render` | separates equation numbers, then LaTeX per formula |
| 5. Table structures | `_enrich_table_structures` | `DataAgent` | a structured AST per table |
| 6. Table inline math | `_mark_table_inline_math` | Toolbox `document.text.spans` | marks math in cells (after step 5, which can replace cells) |

What the steps share is not uniform:

| Resource | Steps | Where it lives (core 0.3.12) |
|---|---|---|
| Provider breaker | 1, 2, 4, 5 | the run's, `RunPorts.services` (`run_breaker`), shared with the `table-enrichment` method |
| Per-object progress (`on_progress`) | 1, 2, 4 | a local, from `checkpoints.enrichment_progress`; step 5, inside the plan, has the execution checkpoint of its plan step |
| Region cache | 1, 2, 4 | from `RunPorts` (`region_cache_for`) |
| Text-span reader (`_TextSpanReader`) | 3, 6 | the run's, `RunPorts.services` (`run_text_spans`); it keeps no manifest |
| Progress messages | 1, 2, 4, 5 | the status callback before planning; `RunServices.progress` inside the plan |
| Media inspection | 2 | a bootstrap output |
| Source file | all | the run context; the manifest records its digest |

Until M4, steps 3 and 6 also run once after execution, before the canonical
build, over the executed manifest: `rescue-omitted` adds blocks while the plan
runs, and the canonical build only converts the spans the manifest carries
(#599). The pass reuses the run's text-span reader, so no page already fetched
in that run is requested again, and it is a transient exception to ADR-0029:
M4's `mark-inline-math` obligation (after M0's executor preparation, #832)
replaces it. It also drops a stale
`inline_math_detection` from a table adopted from the secondary provider and
invalidates the planned formula conversions when a block added during the plan
carries inline math.

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
     replan that would leave the same open obligations does not run (3).
   - Removed, replaced and rewired obligations are covered (4). A step
     whose obligation now depends on an open obligation this plan does not
     run before it (found during the execution, or planned and not run yet)
     waits for the replan. A removal must rewire the removed obligation's
     dependents (`_rewire_removed_dependencies`); the manifest refuses a
     dangling dependency, and the executor reports one as the handler's bug.
   - `PDDL_MAX_DISCOVERY_REPLANS` (default 3) sets the separate bound; a
     value other than the default enters the checkpoint and cache
     identities.
   - The steps they make obsolete are skipped, not run (5).
   - The discovery count is in the plan checkpoint, and the skips derive from
     the plan's and the checkpoint's manifests, so a resume needs nothing
     else (6).
   - `tests/test_changed_obligations.py` has the scenarios (7), including a
     reclassification inside a real handler, a failure with an alternative
     and the resume of the discovery count.

   Steps whose obligation is still there but whose element changed type are
   not detected yet; M1 meets that case first.
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

   No data dependency was found between prose inline math and the formula
   steps (they read different elements), between pictures and tables, or
   between formula LaTeX and tables. Each migration confirms this for its own
   step.
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
   bootstrap**. The migrated picture method then needs no inspection input.
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
   `METHOD_TOOLBOX_REQUIREMENTS`.
7. **Resume stays idempotent.** A step today skips the objects it already
   finished. As a method, the same record makes a re-executed plan step cheap,
   and the execution checkpoint records which steps ran.
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

**What its result means.** The method succeeds when the collective attempt
ran: the step completed for every target. That is not a claim that every
element is now enriched. Each element keeps its own outcome (for a table,
`table_read_failure` with its reason, including the `admission_rejected` of a
full model-call runner, #590), and the per-element obligations that depend on
it validate their element. Failing the whole obligation for one element would
block the elements that are usable. So the method's message reports what
happened to each element, and it fails only when the step raises.

**Reconciled before each plan (M0, #832).** `add_table_enrichment_obligation`
runs when the manifest is enriched and again before each replan:
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
  table's open enrichment. This is a rule on targets, not a list of kinds:
  besides `linearize-table` and `select-table-source`, it orders the page
  obligations (`refine-reading-order`, `fuse-providers`, `adjudicate-page`)
  of a page with a table, whose targets are the page's elements. That is the
  order of 0.3.11, where the tables were read before planning, at the cost
  of serializing those page obligations behind the reading.

## Migration order

Each step is one pull request. Method and kind names for M3 and M4 are
proposals, settled in their pull requests.

| PR | Step | Obligation and method | Role | Toolbox requirements | Changes obligations while the plan runs |
|---|---|---|---|---|---|
| M2 (done, core 0.3.12) | Table structures and table inline math | `enrich-tables`, one per document with tables, method `table-enrichment`; `linearize-table` and `select-table-source` depend on it. After #170 the method calls `table.recognize`, whose providers compete (`docling-table`, `mineru-table`, the VLM) | `transitional` (`DataAgent`) | none declared: its Toolbox calls (`pdf.render` for a table read again, `document.text.spans` for the marks) are conditional and degrade per table, so they must not rule it out | no |
| M0 (done, core 0.3.13) | Executor preparation | The executor skips, and records as `skipped` with the reason, the step of an obligation this execution removed or replaced, and of one that now waits for an open obligation the plan does not run before it. `complete-job` is skipped while every open obligation was found or deferred; one the plan ran and left open is a failure. The orchestrator replans after such a run with its own bound (`max_discovery_replans`), apart from `max_replans`, and stops when a replan leaves the same open obligations. Document-level obligations are reconciled before each replan | — | — | — |
| M1 | Picture descriptions | `describe-images`, one per document with pictures (or with the placeholder visuals of a mostly visual document), method `picture-description`, running the step with its concurrency and retry pass; `describe-image` keeps `vision-description`, which checks the result, and depends on it | `transitional` (`VisionAgent`) | those `VisionAgent` makes, if any | yes: a description can retype a picture as a formula, which removes its `describe-image` and adds `verbalize-formula` |
| M3 | Formula LaTeX | new kind `recognize-formula`, method `formula-recognizer`, a dependency of `verbalize-formula` and `normalize-formula` | new, declared | `math.recognize`, `pdf.render` | yes: the new kind, per formula |
| M4 | Formula regions and prose inline math | new kinds `classify-formula-region` (method `formula-region-classifier`) and `mark-inline-math` (method `inline-math-marker`), replacing the post-execution pass of #599 | new: `transitional` (`VisionAgent`) and declared | `pdf.render`; `document.text.spans` | yes: reclassification reconciles obligations |
| — | Bootstrap | Kept and documented as the 0.3.0 baseline | — | — | — |

M2 came first because it changes no obligation while the plan runs. M1 was
planned first, but its step retypes elements: a picture the model reads as a
formula becomes a formula, and the reconciliation removes the picture's
`describe-image` and adds `verbalize-formula`. The executor only handles
added obligations today (`_select_discovered`), so M1 waits for M0. M3 and M4
change obligations too, and build on M0.

Each PR:
- removes its step from `_enrich_before_planning`;
- updates `LOCAL_METHODS` and `METHOD_TOOLBOX_REQUIREMENTS`;
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
- Removing the gate's `observe` mode (#809).
- Turning the model agents into capabilities (#804, #640 PR 4).
