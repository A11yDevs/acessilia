# Pre-planning stages as planned actions (#640, PR 2)

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](workflow-actions.pt-br.md)

[ADR-0029](../adr/0029-symbolic-core-every-step-planned.md) makes every
semantically relevant step of a job an action of the planning domain. Today
the orchestrator runs four stages before it plans. Of these, inspection,
extraction and enrichment must become actions; the page limit stays an
admission policy. This page is the design of that migration: what each stage
does today, the constraints a migration must respect, and the order of the
pull requests. It changes no code. The proposals below are open to review
(see [Open questions](#open-questions)).

## Today

`PddlAccessibilityOrchestrator._execute` (`pipeline/orchestrator.py`) runs, in
order:

| Stage | What it does | Calls | Writes | Checkpoint |
|---|---|---|---|---|
| Media inspection | Reads the file's media facts; a slide deck is structured differently | Toolbox `media.inspect` | the inspection and the media configuration | `media` |
| Page limit | Rejects a document over `DocumentConfig.max_pages` (`DocumentTooLargeError`) | — | — | — |
| Extraction | Builds the manifest: elements, then the obligations derived from their types | Toolbox `document.structure.extract` (one or two providers) | the manifest | `manifest` |
| Enrichment | Six steps, in a fixed order (below) | Toolbox and the core's model agents | the manifest, step by step | `enriched`, per object |
| Planning | Compiles the problem from the enriched manifest and plans | — | the plan | `plan` |

The six enrichment steps (`_enrich_before_planning`) share one provider
breaker, one region cache and one per-object progress record:

| Step | Function | Calls | Effect on the manifest |
|---|---|---|---|
| 1. Formula regions | `_classify_formula_regions` | Toolbox `pdf.render` (the formula crop); `VisionAgent` | may change an element's type, then reconciles its obligations (`reconcile_reclassified_element`) |
| 2. Picture descriptions | `_enrich_picture_descriptions` | `VisionAgent` | a description per picture |
| 3. Inline math | `_mark_inline_math` | Toolbox `document.text.spans` | marks math in prose |
| 4. Formula LaTeX | `_enrich_formula_latex` | Toolbox `math.recognize`, `pdf.render` | LaTeX per formula |
| 5. Table structures | `_enrich_table_structures` | `DataAgent` | a structured AST per table |
| 6. Table inline math | `_mark_table_inline_math` | Toolbox `document.text.spans` | marks math in cells (after step 5, which can replace cells) |

The plan then works on what enrichment produced. Some methods only check
that work: `vision-description` checks the descriptions and `pandoc-table`
checks the table AST. Both are classified `validation` in
`toolbox_gate.LOCAL_METHODS` (#801).

## The key observation

The domain already has one generic operational action,
`execute-obligation(o, m)`. A method is a way to satisfy an obligation, and
the executor runs the method's handler. So **a step becomes an action by
becoming a method of an obligation**: the planner then chooses it, orders it
through `depends-on`, accounts its cost, rules it out through the catalogue
facts (domain 2.4) and replans after it fails. None of that needs a new
action schema. The enrichment migration needs **no domain change**. Inspection
and extraction need one manifest change (below), and possibly none in the
domain.

## Constraints

1. **A plan cannot create objects.** Extraction creates the elements and their
   obligations, and formula classification can change an element's type and
   so its obligations. After such an action the next actions depend on objects
   the problem did not have. The closed loop handles this: run the action,
   observe the new state, replan. Replanning is bounded (`max_replans`), so an
   action that creates objects must not count as a failure toward that bound.
2. **Order becomes dependencies.** Enrichment's fixed order turns into
   `depends-on` between obligations of the same element:
   - formula classification comes before the description of a picture it may
     reclassify;
   - LaTeX recognition comes before `verbalize-formula` and
     `normalize-formula`;
   - the table structure comes before table inline math.
3. **Infrastructure stays out of the domain.** The provider breaker, the region
   cache, the per-object progress and the checkpoints are runtime concerns
   (ADR-0029). Handlers reach them through the run context (`RunPorts`), not
   through facts.
4. **Handlers are synchronous.** `MethodHandler` is
   `(manifest, obligation_id) -> MethodResult`; the enrichment steps are
   asynchronous. A migrated handler calls them through
   `acessilia_sdk.runtime.run_sync`, as `dual-provider-fusion` already does.
5. **Model calls are not capabilities yet.** `VisionAgent` and `DataAgent` are
   the core's model agents ([classification](core-agent-classification.md)).
   Moving a step into a method makes it planned, but its model call stays in
   the core. Such a method is `transitional` in `LOCAL_METHODS` until the call
   becomes a capability (#804, #640 PR 4), and the gate cannot check it until
   then. The Toolbox calls a step makes (`math.recognize`, `pdf.render`,
   `document.text.spans`) are declared in `METHOD_TOOLBOX_REQUIREMENTS` when the step
   becomes a method.
6. **Resume stays idempotent.** A step today skips the objects it already
   finished. As a method, the same record makes a re-executed plan step cheap,
   and the execution checkpoint records which steps ran.
7. **Equivalence first.** Each migration keeps a differential test of the final
   manifest on fixture documents, before and after (ADR-0028).

## Migration order

Each step is one pull request, from the least to the most structural:

| PR | Step | Obligation and method | Domain | Manifest |
|---|---|---|---|---|
| M1 | Picture descriptions | `describe-image`: `vision-description` produces the description instead of checking it | — | — |
| M2 | Table structures and table inline math | `linearize-table`: `pandoc-table` reads the structure and marks the math | — | — |
| M3 | Formula LaTeX | A new kind, `recognize-formula`, before `verbalize-formula` and `normalize-formula` | — | new kind |
| M4 | Formula regions and inline math | New kinds per candidate region and per prose block. A reclassification creates obligations, so the loop replans | — | new kinds |
| M5 | Inspection and extraction | Job-level obligations, `inspect-media` and `extract-structure`, on a seed manifest that exists before extraction | possibly none | a seed state (schema version) |

M1 is the smallest. The obligation and its method exist, the method's role
moves from `validation` to `transitional`, and only the pre-planning call
moves. M5 is the largest. It needs a manifest that exists before its elements
do, and it is the step where hierarchical planning (#774) is the alternative.

Each PR:
- removes its step from `_enrich_before_planning` (or from `_execute` for M5);
- updates `LOCAL_METHODS` and `METHOD_TOOLBOX_REQUIREMENTS`;
- adds the differential test and the Fast Downward fixture case (the CI job
  from #790);
- updates this page.

## Open questions

- **M5: seed manifest or a separate job-level problem.** A seed manifest keeps
  one problem and one loop, but it changes the manifest schema. A job-level
  problem that plans inspection and extraction, and then hands over to the
  document problem, is hierarchical planning (#774).
- **Replans that create objects.** Should they count toward `max_replans`?
  The proposal is no: count only the replans that follow a failure, and give
  the creating replans their own bound.
- **Costs** of the new methods and kinds, so that the planner orders them as
  enrichment does today when nothing fails.
- **The shared breaker** spans every step of a document today. As a run
  service it keeps that scope; confirming this keeps one provider outage from
  becoming one failure per obligation.

## Out of scope

- Composing the domain from Toolbox fragments. That waits on ADR-0029's open
  decision, "Fragments per version", which the Toolbox's owners must accept.
- Removing the gate's `observe` mode (#809).
- Turning the model agents into capabilities (#804, #640 PR 4).
