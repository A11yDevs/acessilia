# Core changelog

Brazilian Portuguese: [português brasileiro](CHANGELOG.pt-br.md).

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
