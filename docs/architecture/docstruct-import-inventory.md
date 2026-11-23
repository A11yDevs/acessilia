# Inventory: the core's docstruct imports (#735 phase 4, ADR-0028)

You can also read this documentation in **Brazilian Portuguese**: [português brasileiro](docstruct-import-inventory.pt-br.md)

[ADR-0028](../adr/0028-operational-execution-in-the-toolbox.md) moves all
document computation out of the core's process. Its migration starts with
this inventory: every `docstruct.*` module the core
(`libs/core/src/acessilia_core`) and `backend/` import, classified as
contract, algorithm, validation, policy or operation. The review of the
classification closes which modules stay allowlisted, which is one of the
ADR's open decisions ([#758](https://github.com/A11yDevs/acessilia/issues/758)).

The classification is kept as data in
[`tests/fixtures/docstruct_import_allowlist.json`](../../tests/fixtures/docstruct_import_allowlist.json),
and `tests/test_architecture_layers.py` keeps the code, the data and this page
in step (see [The guard](#the-guard)).

## Summary

Measured on `develop` at `82424b34` with an AST scan that includes imports
inside functions and `import docstruct.x` statements (the guard's scan).

- **50 files** import **57 docstruct modules**.
- **45 files** import computation (algorithm or operation). ADR-0028 gives
  43; the difference is `pipeline/judge` and `pipeline/handlers/judge`, which
  import `docstruct.fusion.judge`, classified here as an algorithm (see
  [The classification rule](#the-classification-rule)).
- **5 files** import only contracts, validation or policy:
  - contract only: `export/catalog`, `manifest/document_adapter`,
    `manifest/models`;
  - validation only: `pipeline/validators`;
  - policy only: `manifest/toolbox_extractor`.
- ADR-0028 counts 46 files at `46f2fe7e`. The same scan finds 50 there, with
  the same files as today: the difference is the counting, and no file has
  started importing docstruct since.

| Class | Modules | What it is | Target |
|---|---|---|---|
| contract | 2 | Interoperability models, messages and schemas | Importable anywhere, until the contracts ADR decides where they live |
| validation | 1 | Checks of a document against a schema or rules | Transitional, pinned: schema validation stays near the interoperability layer; the document audit becomes a capability |
| policy | 2 | Decision rules the core uses to coordinate | Transitional, pinned: the strategic part moves into the core (ADR-0029); the algorithms' parameters stay with the Toolbox |
| operation | 10 | Compositions: canonical assembly, export rendering, payload fusion, the table specialist | A composite Toolbox capability, backing a planned action |
| algorithm | 42 | Structural algorithms over document content, and the types internal to them | An atomic Toolbox capability, migrated with the plan method or agent that uses it |

Every class but contract is pinned: each importer and each name it imports
is listed, and the list only shrinks.

## The classification rule

> Mixed modules are classified by their most operational responsibility. A
> module is not classified as contract or policy only because it holds some
> contract or policy symbols: while it also holds document algorithms, it
> stays pinned until the parts are physically separated.

Contract is the only unpinned class, so it is kept narrow: a module is a
contract when two components exchange it, not because it is a pure dataclass
or has no external dependency. The guard fixes the set of contract modules in
the test itself, so widening it is a reviewed change to the test.

## The classes

- **Contract.** Models, constants and messages two components exchange:
  - `docstruct.export.formats.FormatSpec`, the format identity records;
  - `docstruct.manifest`, the normative manifest model (ADR-0007). It is a
    **transitional** contract: it also checks invariants and adapts payloads,
    and it depends on `docstruct.geometry.boxes` (`OrientedBox`) and
    `docstruct.validation` (`Finding`). The contracts ADR separates the
    models and schemas from those algorithms and keeps one source of truth.
- **Validation.** `docstruct.validation`, **transitional** and pinned. It
  holds two different things:
  - `validate_against_schema` checks a document against an interoperability
    schema; it stays near the interoperability layer;
  - `audit_canonical_document` inspects the processed document's structure,
    semantics and accessibility; it becomes a Toolbox capability (for
    example `document.audit.*`).

  The whole module does not get a permanent allowlist.
- **Policy.** Decision rules, **transitional** and pinned:
  - `profiles.verbosity_for_mode`, the example ADR-0028 gives;
  - `policy.FusionPolicy`, which mixes workflow policy with the algorithms'
    parameters (see [Strategic policy and operational configuration](#strategic-policy-and-operational-configuration)).
- **Operation.** A composition of algorithms with one document-level result:
  - `canonical`, the canonical builder;
  - the eight `export.*` modules except `formats`. ADR-0028 classifies
    export rendering as computation behind a planned action;
  - `fusion.payload`, multi-provider fusion and page routing;
  - `fusion.table_specialist`, generation, comparison and adjudication.
- **Algorithm.** Everything else: fusion, reading order, geometry, tables,
  text, math, Unicode repair, images and visual text, and the types internal
  to them. This includes three modules that hold some policy or types, by
  the rule above:
  - `docstruct.types`: `Region` carries processing data (`image_bytes`),
    next to `CanonicalBlock`, `BlockPairing`, `OrientationResult` and legacy
    document types. Only the genuinely shared types move to the contracts
    package later;
  - `docstruct.regions.classify`: `region_needs_vision` and
    `region_prompt_key` route a region, but `classify_region` computes over
    geometry, text density and confidence;
  - `docstruct.fusion.judge`: `should_judge` decides whether to ask the VLM
    judge, but `debias`, `p2_from_logprobs` and `decide_pair` normalize
    probabilities, correct bias and compare candidates.

  In each case the computation moves to the Toolbox. The core keeps the
  decision of when to ask for a capability, from the evidence the Toolbox
  returns.

## Strategic policy and operational configuration

`FusionPolicy` holds both kinds of setting:

| Kind | What it decides | Fields, for example |
|---|---|---|
| Workflow policy (core) | Which steps run and which evidence to ask for | `page_judge` (ask the VLM judge), `text_pick` (whose text to prefer), `upscale`, `orientation_reinfer` |
| Operational configuration (Toolbox) | How an algorithm runs | `align_tau`, `align_lambda`, `xycut_min_balance`, `tailjoin_k`, `rep_max_n`, the `pic_*` and `merge_*` calibration |

Moving the whole class into the core would make the core depend on the
Toolbox's internal parameters. The strategic policy belongs to the core
(ADR-0029); the algorithms' parameters stay with the Toolbox, behind the
capabilities. Until the class is split physically, with compatibility kept
during the migration, it stays pinned to its current importers.

## Mixed modules

By the classification rule, a module has one class: the most operational of
its parts. Some modules also carry vocabulary or types that are contracts in
nature; the contracts ADR decides whether those move to a contracts package:

- `docstruct.placeholders`: `UNSTRUCTURED_PAGE_FLAG` and
  `UNSTRUCTURED_PAGE_LABEL` are vocabulary; `has_meaningful_text`,
  `is_mostly_visual` and `is_placeholder_visual` are algorithms.
- `docstruct.geometry`: `OrientedBox` and `ReadingItem` are types;
  `order_reading_items`, `reading_role`, `union` and `is_bottom_left` are
  algorithms.
- `docstruct.geometry.boxes`: `PageBox` is a type; the rest are algorithms.
- `docstruct.tables.ast`: `TABLE_SECTIONS` and the `MSG_TABLE_TEXT_*` messages
  are vocabulary; the AST builders and the linearization are algorithms.
- `docstruct.fusion.judge` and `docstruct.regions.classify`: see the
  algorithm class above.
- `docstruct.imaging.policy` is classified as **algorithm** despite its name:
  `upscale_factor` and `decide_orientation` set the parameters of the
  page-level agent's image processing and move with it.
- `docstruct.fusion.types` is **not** a contract: its docstring says it is
  internal to the fuser and not a stable public API.

## Where the computation is

The importers group by the part of the core that runs the computation. This
is the order the migration can follow, per plan method or agent (ADR-0028):

| Part of the core | Files | What moves |
|---|---|---|
| Operational agents (`agents/*`) | fusion, page-level, adjudication, order adjudication, table specialist, vision, prompt tools, output schemas | Fusion, reading order, adjudication protocol, repetition guard, table specialist. They move with the agents classified as operational (#735, the agents row) |
| Plan-method handlers (`pipeline/handlers/*`) | text, content, formula, structure, order, rescue, unicode repair, inspection, fusion, judge | One capability per method, the per-method migration of ADR-0028 |
| Enrichment (`pipeline/enrichment/*`) | common, formulas, inline math, pictures, tables | Image clipping, formula and inline math, picture context, table recovery. These are also the semantic stages ADR-0029 plans |
| Payload and canonical assembly | `pipeline/payload`, `pipeline/canonical_builder`, `pipeline/elements`, `pipeline/obligations` | Canonical assembly and page text: the composite behind accessible export |
| Accessible export (`export/*`) | renderers, exporters, Pandoc exporter, markers, catalog | Rendering, behind the export capability (`document.export.*`) |
| Manifest construction (`manifest/*`) | builder, layout and text detectors, slides | Reading order, tail join, verse, normalization while building the manifest |
| Coordination and boundary | `pipeline/fusion`, `pipeline/secondary`, `pipeline/toolbox`, `pipeline/judge`, `toolbox/vision_payload`, `manifest/toolbox_extractor` | Payload fusion, region clipping and the judge's threshold; the fusion policy is policy |
| Compatibility shims | `pipeline/table_ast`, `formula_tools`, `pipeline/validators` | Re-exports kept for old imports (`import docstruct.x`); removed when their callers move |
| Service (`backend/service.py`) | `backend/service` | `merge_broken_paragraphs` (algorithm) and `verbosity_for_mode` (policy) |

## Modules
| Module | Class | Names the core imports | Importers |
|---|---|---|---|
| `docstruct.export.formats` | contract | `FormatSpec` | `export/catalog` |
| `docstruct.manifest` | contract | `MSG_CHAR_RANGE_REVERSED`, `MSG_DUPLICATE_ELEMENT_IDS`, `MSG_DUPLICATE_PAGE_NUMBERS`, `MSG_ELEMENT_UNKNOWN_PAGE`, `MSG_PAGE_DUPLICATE_ELEMENT_IDS`, `MSG_PAGE_UNKNOWN_ELEMENTS`, `MSG_PARENT_CYCLE`, `MSG_PARENT_REF_MISMATCH`, `MSG_PROVENANCE_UNKNOWN_PAGE`, `MSG_SELF_PARENT`, `MSG_UNKNOWN_PARENT`, `StructuredDocument`, `document_invariant_findings`, `structured_document_from_payload`, `structured_document_to_payload` | `manifest/document_adapter`, `manifest/models` |
| `docstruct.validation` | validation | module, `FindingTuple`, `audit_canonical_document`, `validate_against_schema` | `agents/fusion_agent`, `export/pandoc_exporter`, `pipeline/validators` |
| `docstruct.policy` | policy | `FusionPolicy` | `manifest/toolbox_extractor`, `pipeline/fusion`, `pipeline/handlers/fusion` |
| `docstruct.profiles` | policy | `verbosity_for_mode` | `backend/service` |
| `docstruct.canonical` | operation | `MathEnricher`, `_enrich_math_blocks`, `build_canonical_document`, `sanitize_canonical_document` | `pipeline/canonical_builder` |
| `docstruct.export.filters` | operation | `strip_internal_audit_blocks` | `export/pandoc_exporter` |
| `docstruct.export.html` | operation | `HtmlLabels`, `_all_blocks`, `_collect_section`, `_render_block`, `_render_html_table_row`, `document_to_html` | `export/renderers/html_renderer` |
| `docstruct.export.markdown` | operation | `document_to_markdown` | `export/exporters/drbench_md_exporter` |
| `docstruct.export.markers` | operation | `wrap_object_markers` | `export/markers` |
| `docstruct.export.page_text` | operation | `blocks_text`, `pages_text` | `pipeline/payload` |
| `docstruct.export.pandoc_ast` | operation | `build_pandoc_ast`, `count_math_nodes`, `degrade_math_to_text`, `unconverted_math_indices` | `export/pandoc_exporter` |
| `docstruct.export.txt` | operation | `_render_block`, `_render_section`, `document_to_txt_lines` | `export/renderers/txt_renderer` |
| `docstruct.fusion.payload` | operation | `fuse_extraction_payloads`, `normalize_element_ids`, `route_pages` | `manifest/builder`, `pipeline/fusion` |
| `docstruct.fusion.table_specialist` | operation | `build_candidates`, `extract_table`, `is_valid_table`, `medoid_index`, `norm_table`, `select_greedy`, `select_table` | `agents/table_specialist_agent` |
| `docstruct.blocks.callouts` | algorithm | `callout_titles`, `dedupe_callout_titles` | `pipeline/payload` |
| `docstruct.blocks.lists` | algorithm | `marker_numbering`, `merge_list_blocks`, `recover_empty_lettered_list_items` | `pipeline/elements`, `pipeline/payload` |
| `docstruct.data_uri` | algorithm | `decode_data_uri` | `pipeline/enrichment/common` |
| `docstruct.fusion.adjudication` | algorithm | `clean_transcription`, `decide`, `decide_v0`, `decide_v1`, `filter_decision` | `agents/adjudication_agent`, `pipeline/handlers/fusion` |
| `docstruct.fusion.hf_end` | algorithm | `move_hf_to_end` | `agents/fusion_agent`, `agents/page_level_agent` |
| `docstruct.fusion.judge` | algorithm | `DEFAULT_NEW_THR`, `decide_pair`, `should_judge` | `agents/adjudication_agent`, `pipeline/handlers/judge`, `pipeline/judge` |
| `docstruct.fusion.line_numbers` | algorithm | `extract_line_numbers` | `agents/fusion_agent`, `manifest/detectors/layout` |
| `docstruct.fusion.noise` | algorithm | `PAGE_NUMBER_MARGIN`, `element_role`, `is_bare_page_number`, `is_decorated_page_number`, `is_legitimate_text`, `is_page_number_in_margin`, `select_page_numbers` | `pipeline/handlers/rescue`, `pipeline/handlers/text`, `pipeline/payload` |
| `docstruct.fusion.oracle` | algorithm | `oracle_page` | `agents/adjudication_agent` |
| `docstruct.fusion.page_select` | algorithm | `fuse`, `page_agreement`, `page_norm`, `select_by_agreement`, `swap_low_agreement_pages` | `agents/adjudication_agent`, `agents/page_level_agent` |
| `docstruct.fusion.repetition` | algorithm | `collapse`, `guard_page` | `agents/fusion_agent`, `agents/vision_agent` |
| `docstruct.fusion.similarity` | algorithm | `area`, `is_duplicate`, `ordered_box`, `pair_block` | `manifest/slides`, `pipeline/handlers/rescue`, `pipeline/secondary` |
| `docstruct.fusion.skeleton` | algorithm | `DEFAULT_MIN_SKELETON_MATCH`, `skeleton_reading_order` | `pipeline/handlers/order` |
| `docstruct.fusion.tailjoin` | algorithm | `join_tail`, `page_number_position`, `tailjoin3` | `agents/fusion_agent`, `agents/page_level_agent`, `manifest/detectors/layout`, `pipeline/handlers/text` |
| `docstruct.fusion.types` | algorithm | `DiffBlock` | `agents/fusion_agent`, `manifest/detectors/layout` |
| `docstruct.fusion.verse` | algorithm | `split_box_rows`, `verse_blocks` | `agents/fusion_agent`, `manifest/detectors/layout`, `pipeline/handlers/structure` |
| `docstruct.fusion.xycut` | algorithm | `xycut_order` | `agents/fusion_agent`, `agents/order_adjudication_agent`, `manifest/detectors/layout` |
| `docstruct.geometry` | algorithm | `OrientedBox`, `ReadingItem`, `is_bottom_left`, `order_reading_items`, `reading_role`, `union` | `manifest/builder`, `manifest/detectors/types`, `manifest/slides`, `pipeline/elements`, `pipeline/payload`, `pipeline/secondary` |
| `docstruct.geometry.boxes` | algorithm | `PageBox`, `best_effort_clip`, `box_contains_center`, `box_distance`, `boxes_overlap`, `boxes_side_by_side`, `downward_edges`, `expand_box`, `holds_point`, `spans_horizontally`, `union_area` | `manifest/slides`, `pipeline/enrichment/common`, `pipeline/enrichment/inline_math`, `pipeline/handlers/unicode_repair`, `pipeline/toolbox` |
| `docstruct.imaging` | algorithm | `image_dimensions` | `toolbox/vision_payload` |
| `docstruct.imaging.policy` | algorithm | `decide_orientation`, `upscale_factor` | `agents/page_level_agent` |
| `docstruct.placeholders` | algorithm | `UNSTRUCTURED_PAGE_FLAG`, `UNSTRUCTURED_PAGE_LABEL`, `has_meaningful_text`, `is_mostly_visual`, `is_placeholder_visual`, `is_unstructured_page_placeholder` | `manifest/builder`, `pipeline/enrichment/pictures`, `pipeline/handlers/content`, `pipeline/payload` |
| `docstruct.regions.classify` | algorithm | `classify_region`, `region_needs_vision`, `region_prompt_key` | `agents/fusion_agent`, `agents/vision_agent` |
| `docstruct.regions.letterhead` | algorithm | `PlacedItem`, `letterhead_groups` | `pipeline/payload` |
| `docstruct.sections` | algorithm | `find_heading_gaps`, `repair_heading_levels` | `manifest/builder`, `pipeline/handlers/text` |
| `docstruct.tables.ast` | algorithm | module, `TABLE_SECTIONS`, `analyze_table_complexity`, `linearize_table_for_text`, `raw_rows_from_table_ast`, `table_ast_column_count`, `table_ast_from_rows` | `manifest/detectors/text`, `pipeline/elements`, `pipeline/enrichment/inline_math`, `pipeline/enrichment/tables`, `pipeline/handlers/content`, `pipeline/handlers/fusion`, `pipeline/handlers/unicode_repair`, `pipeline/table_ast` |
| `docstruct.tables.garble` | algorithm | `table_garble_reason` | `pipeline/enrichment/tables` |
| `docstruct.tables.structured` | algorithm | `normalize_strict_table_ast`, `table_ast_from_structured_rows`, `table_ast_has_structured_content` | `agents/output_schemas`, `pipeline/elements` |
| `docstruct.tables.text_rows` | algorithm | `rows_from_visual_table_text` | `pipeline/enrichment/tables` |
| `docstruct.text.code_reflow` | algorithm | `normalize_code_text` | `pipeline/elements`, `pipeline/handlers/content` |
| `docstruct.text.equations` | algorithm | `preserve_equation_number`, `split_equation_number` | `manifest/builder`, `pipeline/enrichment/formulas` |
| `docstruct.text.implicit_products` | algorithm | `implicit_product_variables`, `mark_implicit_products` | `pipeline/handlers/formula` |
| `docstruct.text.inline_math` | algorithm | `Placement`, `assign_runs_to_cells`, `detect_inline_math_by_page`, `splice_inline_math`, `top_left_box` | `pipeline/enrichment/inline_math` |
| `docstruct.text.latex` | algorithm | module, `bare_latex`, `has_latex_markup`, `latex_text_agreement`, `normalize_latex` | `agents/fusion_agent`, `formula_tools`, `manifest/builder`, `manifest/detectors/text`, `pipeline/canonical_builder`, `pipeline/enrichment/formulas`, `pipeline/handlers/formula`, `pipeline/handlers/inspection`, `pipeline/handlers/unicode_repair`, `pipeline/obligations` |
| `docstruct.text.math_spans` | algorithm | `block_prose`, `inline_math_sources` | `pipeline/handlers/formula` |
| `docstruct.text.named_operators` | algorithm | `normalize_named_operators`, `speak_named_operators` | `pipeline/handlers/formula` |
| `docstruct.text.negation_overlay` | algorithm | `compose_in_grid`, `compose_in_text`, `is_detached_overlay` | `pipeline/enrichment/inline_math`, `pipeline/handlers/unicode_repair` |
| `docstruct.text.norm_fix` | algorithm | `norm_fix` | `agents/fusion_agent`, `manifest/detectors/text`, `pipeline/handlers/text` |
| `docstruct.text.paragraphs` | algorithm | `merge_broken_paragraphs` | `backend/service` |
| `docstruct.text.unicode_repair` | algorithm | `Detection`, `UnicodeRepairContext`, `detect_legacy_unicode`, `repair_legacy_unicode` | `manifest/detectors/text`, `pipeline/handlers/unicode_repair` |
| `docstruct.types` | algorithm | `Region` | `agents/fusion_agent` |
| `docstruct.visual_text` | algorithm | `TextOwnership`, `analyze_visual_text_ownership`, `bound_surrounding_items`, `collect_picture_context`, `deduplicate_picture_description`, `is_confirmed_logo_description`, `is_document_artifact`, `is_scene_artifact`, `scene_text_residue` | `agents/prompt_tools`, `pipeline/enrichment/pictures`, `pipeline/payload` |

## The SDK, for information

The SDK imports six docstruct modules. The five computational ones are the
"5" in #735's indicators:

- `docstruct.manifest` (contract), in `toolbox/results/layout`;
- `docstruct.geometry.boxes` and `docstruct.text.latex`, in
  `operations/formula`;
- `docstruct.fusion.payload` and `docstruct.policy`, in `operations/fusion`;
- `docstruct.imaging`, in `toolbox/clients/pdf`.

Its operations move with the operational runtime to the Toolbox (#735
phase 1, ADR-0028). The SDK's own `tests/test_purity.py` guards its
dependencies, so this page does not pin them.

## The guard

The tests in `tests/test_architecture_layers.py` read the fixture:

- **Classified and pinned.** Every docstruct module the core or `backend/`
  imports must be in the fixture. A contract module may be imported by any
  file. Every other module lists the files that import it and the names each
  file imports. For `import docstruct.x as m`, the names are the `m.attr` the
  file reads, and `*` marks any other use of `m`. A new file, or a new name in
  an existing import, fails: it calls a Toolbox capability instead.
- **Only shrinks.** A module, file or name no longer imported fails until it
  is removed, so each migration removes its lines from the fixture, and a
  module's last importer removes its row from this page.
- **Closed classes.** The classes are the five above, and the set of
  contract modules is fixed in the test: reclassifying a computational module
  as contract changes the test, not only the fixture.
- **The guard's own cases.** Synthetic tests check a new name in an existing
  import, a new importer, an unclassified module, obsolete pins and the
  resolution of module aliases.
- **In step with this page.** The module rows in the table above, in both
  languages, must be the fixture's modules.

### Transitional exceptions: `*`

Two compatibility shims read their docstruct module dynamically, with
`getattr(module, name)` over a tuple of deprecated names, so their pins carry
`*` and do not restrict which attributes they read:

- `pipeline/table_ast` (`docstruct.tables.ast`, `_DEPRECATED_NAMES`);
- `pipeline/validators` (`docstruct.validation`).

They are transitional: each goes when its deprecated names have no caller
left, or when the calls behind it become Toolbox capabilities. A new `*` is a
new pin, so the guard refuses it like any other.

### What the guard does not do yet

The guard compares the code with the fixture. A pull request that changes
both together still passes, so between commits the allowlist only shrinks
through review. [#764](https://github.com/A11yDevs/acessilia/issues/764)
compares the fixture with the base branch's in CI, and makes a new exception
an explicit architectural decision.

## Indicators

The baseline of this inventory, for #735 to follow as the migration
progresses:

| Indicator | Baseline (`82424b34`) | Target |
|---|---|---|
| docstruct modules imported directly | 57 | only the contract modules |
| Files importing computation (algorithm or operation) | 45 | 0 |
| Pinned `*` exceptions | 2 | 0 |
| Imports outside the allowlist | 0 | 0 |
| New exceptions without an architectural decision | 0 | 0 |

## How a migration shrinks the allowlist

Each migration, per plan method or agent (ADR-0028):

1. provides an equivalent Toolbox capability;
2. replaces the local computation with a call through the core SDK;
3. keeps the contracts and the functional equivalence;
4. adds a differential regression test;
5. removes the obsolete files and names from the fixture, and a module's row
   from this page when its last importer goes;
6. updates the indicators above.

A capability follows the semantics of the plan methods and agents. Not every
utility function becomes a remote call: low-level algorithms are composed
inside the Toolbox runtime, which keeps latency down and the PDDL planning
simple.

## Still open

The classification itself was settled in the review of #760. These remain:

- **Physical splits.** When `docstruct.validation` (schema validation and
  document audit), `FusionPolicy` (workflow policy and operational
  configuration), `docstruct.fusion.judge` and `docstruct.regions.classify`
  are split, and in which pull requests.
- **Vocabulary and the manifest.** Which types and vocabulary of the mixed
  modules and of `docstruct.manifest` go to the contracts package that the
  contracts ADR evaluates.
- **Shims.** Are the three compatibility shims removed with their last
  caller, or earlier?
