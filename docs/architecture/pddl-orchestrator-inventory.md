# PDDL orchestrator inventory

> A Brazilian Portuguese translation is available in [pddl-orchestrator-inventory.pt-br.md](pddl-orchestrator-inventory.pt-br.md).

This is Phase 2 of the plan in [#402](https://github.com/A11yDevs/acessilia/issues/402) (the "Plano complementar" comment). It sorts every top-level definition of `backend/agents/pddl_orchestrator.py` by responsibility and proposes a destination for each group: the core, docstruct, the SDK or the Toolbox. Code with mixed responsibilities is marked to be decomposed first. Phase 3 migrates the groups one PR at a time, following this table. The orchestrator gets smaller because it loses responsibilities that are not its own, not because it is cut into files. That was the approach of [#381](https://github.com/A11yDevs/acessilia/issues/381), now `status:blocked`.

It also carries out the inventory tasks of [#365](https://github.com/A11yDevs/acessilia/issues/365), which #381 absorbed:
- map the groups and the state they share;
- check, for each group, whether it is a pure structural algorithm, which belongs in docstruct ([ADR-0002](../adr/0002-component-responsibilities.md));
- list the largest functions.

- **Snapshot:** `acessilia` `develop` at `a5ae2a8e`. `backend/agents/pddl_orchestrator.py` has **6,185 lines**, and 192 top-level definitions are assigned to the groups.
- **How it was measured:** the file was parsed with `ast`. Each top-level function, class and constant is assigned to one group, and none is left unassigned. A group's "Depends on" lists the other groups whose names its code refers to; the state groups share through the manifest is mapped separately, in "Shared state". The groups cover 5,599 lines; the rest is imports, the module docstring and blank lines.

## Destination rule

Each definition is classified by what it does, not by the file it is in or by whether it calls an agent ([ADR-0002](../adr/0002-component-responsibilities.md), "Where does new code go?").

| If the code… | Destination | Basis |
|---|---|---|
| decides what to do or when: policy, plan, recovery, degradation, flow, user-facing messages | **core** | ADR-0002; constitution P2, P6 |
| is a deterministic structural algorithm, with no I/O | **docstruct** | ADR-0002, [ADR-0009](../adr/0009-legacy-unicode-repair.md), [ADR-0011](../adr/0011-inline-math-from-font-runs.md) |
| says how to reach a capability or an artifact: client call, render request, artifact id | **SDK** | ADR-0002 (question 4), [ADR-0005](../adr/0005-artifact-references.md), [ADR-0015](../adr/0015-artifact-reference-v1.md) |
| runs a model, OCR, VLM or a renderer | **Toolbox** | [ADR-0003](../adr/0003-remote-only-operational-capabilities.md), [ADR-0012](../adr/0012-agents-reach-the-vlm-through-the-toolbox.md) |
| mixes more than one of these | **decompose first**, then move each part | Plan, principle 1 |

**docstruct works on its own types.** The orchestrator's functions take the core's Pydantic models: `ManifestElement`, `ProcessingManifest`, `Obligation`. docstruct cannot import them. Since [#203](https://github.com/A11yDevs/acessilia/issues/203) the document part has its normative definition in `docstruct.manifest` (`DocumentElement`, `BoundingBox`, `Provenance`), and the core's models are adapters over it (see the [manifest model inventory](manifest-model-inventory.md), decision D1).

So "docstruct" below means the algorithm moves and works on docstruct types or plain values: boxes as tuples, text, rows. A small core adapter keeps the current signature, converts, and calls it. The adapter is what stays patchable for the tests.

No group goes to the Toolbox: the orchestrator already runs no model or renderer locally. #402 Phase 1 and ADR-0003 removed the last ones.

## Inventory

Groups are lettered as in the analysis that produced this table. "Lines" is the span of the group's definitions and "Size" their total length. "PT" counts lines with Portuguese text, which the language guard and [#410](https://github.com/A11yDevs/acessilia/issues/410) track when they move.

| Id | Group | Lines | Size | Depends on | PT | Destination |
|---|---|---|---|---|---|---|
| A | User-facing message ids (`MSG_*`) | 148–163 | 10 | — | 0 | core |
| B | Formula handlers: MathML and speech | 166–286 | 115 | X | 11 | core (execution handler) |
| C | Fusion infrastructure (`_run_extract_fused`, `_fusion_agent`) | 289–334 | 44 | — | 8 | core |
| D | Shared targeting and element geometry | 337–1409 | 93 | — | 1 | **decompose** |
| E | Simple deterministic handlers | 392–594 | 195 | D, O, S | 12 | core (execution handlers) |
| F | Unicode repair and negation overlays | 599–957 | 334 | D | 2 | **decompose**: geometry to docstruct |
| G | Rendering, region and page inspection | 960–1327 | 350 | D | 0 | core, over the existing SDK render; accepted input types to SDK |
| H | FusionAgent-backed text handlers | 1330–1527 | 140 | C, D | 7 | core; `_tailjoin_position` to docstruct |
| I | Calibrated provider choice | 1539–1979 | 410 | D, K | 12 | **decompose**: box geometry to docstruct |
| J | VLM pairwise judge | 1984–2226 | 231 | D, G, I | 10 | **decompose**: `pB` reading to SDK |
| K | Order and review handlers, handler registry | 2229–2396 | 158 | C, D, E, F, G, H, I | 5 | core |
| L | Dual- and single-provider fusion | 2399–2680 | 274 | C, D, G | 16 | core |
| M | Errors and page limits | 2683–2733 | 43 | — | 0 | core |
| N | `PddlAccessibilityOrchestrator` (pipeline, plan, executor) | 2736–3071 | 336 | B, J, K, L, M, O–V | 2 | core (orchestration) |
| O | Picture enrichment | 3079–4961 | 483 | G, U | 15 | **decompose**: heuristics and clip geometry to docstruct |
| P | Formula enrichment | 3339–4160 | 510 | G, O, U | 0 | **decompose**: ranking to docstruct |
| Q | Inline math | 3424–3722 | 280 | F, G | 0 | **decompose**: span geometry to docstruct, span batching to SDK |
| R | Media triage | 4163–4216 | 52 | — | 0 | core |
| S | Table enrichment and table text | 4288–4670 | 343 | G, O, U, X | 0 | **decompose**: row parsing to docstruct |
| T | Obligation status and replanning | 4868–5059 | 144 | B, O, U | 0 | core |
| U | Progress, page labels, availability log | 5031–5136 | 89 | — | 4 | core |
| V | Payload builder | 5139–5358 | 204 | A, T, W, X | 1 | core |
| W | Page payload: page numbers and letterhead | 5361–5666 | 271 | A, D, X | 0 | **decompose**: detection rules to docstruct |
| X | Blocks, lists, text and table AST | 5669–6180 | 488 | A | 0 | **decompose**: list, text and table algorithms to docstruct |
| Z | Legacy aliases (`PmvAccessibilityOrchestrator`, `build_pmv_structured_payload`) | 6184–6185 | 2 | N, V | 0 | remove (no caller) |

Ranges overlap where a group's definitions are spread through the file. For example, D's `_element_role` and `_block_kind` sit near line 1400, and O's pure heuristics sit after S.

### What moves, group by group

Only the groups marked "decompose" or with a docstruct or SDK part are listed. The others stay whole in the core.

- **D: shared targeting and element geometry.**
  - `_element_bbox` turns a manifest element into a box in one coordinate origin, using `docstruct.geometry.is_bottom_left`. It is an adapter and stays in the core.
  - `_element_role` and `_block_kind` are document semantics.
    - `_element_role` maps page-furniture types to fusion roles with the same table as `docstruct.fusion.noise.DECOR_TYPES`, so it goes there as `element_role`.
    - `_block_kind` stays in the core for now: docstruct's `fusion.convert.classify_kind` is a near-duplicate that decides differently. See "Findings".
  - `_target_elements` and `_missing_obligation` read obligations, which is process, so they stay in the core.
- **F: Unicode repair and negation overlays.** ADR-0009 already put detection and repair in docstruct (`docstruct.text.unicode_repair`). The overlay geometry goes to `docstruct.text.negation_overlay`, which already has `compose_negation`, `locate_in_grid` and `locate_in_text`: that is `_vertical`, `_table_grid`, `_compose_in_host` and the box tolerances. `_reattach_negation_overlays` and `_repair_table_cells` walk manifest elements; they become adapters over docstruct functions. The handler stays in the core.
- **G: rendering, region and page inspection.** The render itself is already in the SDK: `ToolboxPdfClient.render` takes a file or an artifact, a page, a clip and its origin, checks the answer and fetches the verified image. No new render binding is needed.
  - `_toolbox_render` stays in the core as the adapter over that method. It builds the client with the core's factory (and so the core's configuration), checks that the manifest's media type agrees with the file's extension, and decides to resend the file when the stored artifact is gone. These are core concerns.
  - The set of inputs `pdf.render@2` accepts (`_RENDERABLE_MEDIA_TYPES`: PDF, PNG, JPEG) is contract knowledge, so it moves to the SDK next to the render method, as a constant the adapter checks against: `acessilia_sdk.toolbox.clients.pdf.RENDER_MEDIA_TYPES`.
  - `_source_artifact_id` stays in the core. It reads the manifest (`extractor.configuration["artifact_id"]`) and decides to ignore an id that does not parse or whose digest is not the source's. The parsing it relies on is already the SDK's `ArtifactRef`.
  - `_save_region_artifact` writes evidence under `settings.data_dir`, so it stays in the core.
  - `_inspect_region` and `_inspect_page` call `VisionAgent`, so they stay in the core.
  - The two handlers stay in the core.
- **H: text handlers.** `_tailjoin_position` repeated `docstruct.fusion.tailjoin.page_number_position`, the rule the builder applies to fusion blocks, over manifest elements. It now calls that function through `_FurnitureView`, a read-only view that reads an element's box only when it is page-number furniture, as before. The handlers use `FusionAgent` and stay in the core.
- **I: calibrated provider choice.**
  - `_ordered_box`, `_iou` and `_pair_block` are box geometry and go to docstruct, as `docstruct.fusion.similarity.ordered_box` and `pair_block`. `_iou` gives the same value as the existing `docstruct.fusion.similarity.iou` for every input, so it is replaced by it; see "Findings". `_pair_block` stays in the core as the adapter that reads the element's and the candidates' boxes; the thresholds are policy and stay with it.
  - `_page_number` and `_page_markdown` are small document helpers.
  - `_load_secondary_extraction` reads a file and checks its digest, so it stays in the core.
  - The calibrated pair, the preferences and the thresholds are policy: core.
- **J: VLM pairwise judge.**
  - `_render_page_png` renders through G's adapter, so it stays in the core.
  - `_judge_probability` reads `pB` from the `document.adjudicate.page` answer, which `ToolboxAdjudicateClient.judge_page` already documents. Reading a capability's answer is SDK work, as `math.recognize`'s shapes were in #434, so it moves next to that client. The move keeps today's behaviour: a missing, non-numeric or out-of-range `pB` gives `None`. What to do with `None` stays the handler's decision, in the core. Raising instead would be a separate behaviour change. It is now `acessilia_sdk.toolbox.clients.adjudicate.page_judgement_probability`.
  - `_judge_page` is the core's synchronous wrapper over `ToolboxAdjudicateClient`.
  - The handler (179 lines, the fourth largest function) stays in the core and is split there. Step 5 did: `_judge_texts` gives a page's two candidates, `_judge_one_page` renders the page and reads the judge's answer, and `_judgement_result` records the judgements and reports the outcome; the handler keeps the loop over pages (50 lines, 22 of them its docstring).
- **O: picture enrichment.**
  - The flow, retries and breaker stay in the core (`_enrich_picture_descriptions`, 197 lines, and `_retry_failed`). Step 5 split it in the core: `_pictures_to_describe` chooses the elements, `_fold_picture_description` folds an answer into one, and `_retype_element` makes it a formula or a picture; the function keeps the flow (109 lines).
  - `_extract_picture_bytes`, `_picture_clip` and `_embedded_picture_bytes` (#386) mix a render through G's adapter, clip geometry (docstruct) and a size limit (core policy). They are split: `_picture_clip` is `docstruct.geometry.boxes.best_effort_clip`, and the `data:` URI decoding of `_embedded_picture_bytes` is `docstruct.data_uri.decode_data_uri`, which takes the accepted types and the size limit from the core. `_extract_picture_bytes` keeps the render calls and their fallbacks (the page for a refused box or a sliver, no image for any other failure).
  - The heuristics `_is_ocr_noise`, `_is_placeholder_text`, `_is_placeholder_visual_element` and `_has_meaningful_text` are pure text and element tests, so they go to `docstruct.placeholders` (`is_ocr_noise`, `is_placeholder_text`, `is_placeholder_visual`, `has_meaningful_text`). `_is_mostly_visual_manifest` reads only the elements, so it moves too, as `is_mostly_visual`. They read an element through a read-only protocol that the core's `ManifestElement` satisfies, so the core needs no adapter.
  - `_inject_full_page_picture` changes the manifest, so it stays in the core.
- **P: formula enrichment.**
  - `_formula_recognition_crop` renders through G's adapter and crops (docstruct for the clip geometry). Its clip is `docstruct.geometry.boxes.best_effort_clip` since #459; what it keeps (the saved crop, the render, no crop for a sliver) is the core's.
  - `_ranked_formula_candidates` normalizes LaTeX and ranks by confidence. It is pure and goes to docstruct, as `docstruct.text.latex.ranked_latex_candidates`. Its normalization is `bare_latex`, the conservative one, which the core imports as `normalize_latex` (`backend/tools/formula_tools.py`), not docstruct's `normalize_latex`.
  - `_reclassify_formula_picture` and `_escalate_unresolved_formula` change the manifest, so they stay in the core.
  - `_enrich_formula_latex`, at 299 lines the largest function in the file, stays in the core and is split there (#365). It now keeps the selection, the setup and the summary logs (131 lines, 61 of them its docstring). `_FormulaEnrichment` holds one document's shared state and `enrich_one`; `_MathRecognizer` the once-per-document outage probe; `_TextLayerGate` the agreement gate and what it refused; `_first_agreeing_candidate`, `_formula_by_vision` and `_record_formula_recognition` the three steps of one formula.
- **Q: inline math.**
  - The span geometry goes to `docstruct.text.inline_math`, which already detects and splices the runs (ADR-0011): `_top_left_box`, `_detect_by_page` and `_element_span_lines`, which read an element's boxes as `(page, box)` placements. The containment test they share with `_claim_negation_overlay` is `docstruct.geometry.boxes.holds_point`. `_claim_negation_overlay` writes the claim and finds the slash's box with F's `_bbox`, and `_boxed_pages` reads the core's elements, so both stay in the core.
  - `ToolboxPdfClient.text_spans` already reads `document.text.spans` and checks the answer. What is left is batching: `backend/tools/text_spans.fetch_text_spans` asks for at most `TEXT_SPANS_MAX_PAGES` pages per call, which is transport and moves to the SDK, as the dataset paging did in #432. It is now `ToolboxPdfClient.text_spans_by_page`; `fetch_text_spans` stays in the core, binding it to the settings (the client, `toolbox_use_remote_cache`). `_TextSpanReader`'s per-document cache, and its record of a failure (`configuration["inline_math_detection"]`), stay in the core.
  - `_mark_inline_math`, `_mark_table_inline_math` and the setting check stay in the core.
- **S: table enrichment.**
  - `_rows_from_visual_table_text`, `_rows_from_pipe_table`, `_rows_from_delimited_lines`, `_looks_like_markdown_separator`, `_score_rows`, `_rows_look_like_placeholder` and `_table_ast_column_count` parse text into rows, so they go to `docstruct.tables`.
  - The re-read rules (`_table_reread_disqualified`, `_keep_misread_table`, attempts and thresholds) and `_enrich_table_structures`, which calls `DataAgent`, stay in the core. Step 5 split it there: `_tables_to_read` chooses the tables and why each misread one is read again, `_read_table` makes the readings, `_record_unread_table` records a table no reading was kept for, and `_fold_table_reading` writes a kept one; the function keeps the flow (91 lines).
- **W: page numbers and letterhead.**
  - The detection rules go to docstruct, next to `docstruct.fusion.tailjoin.is_page_number`: `_is_decorated_page_number`, `_is_page_number_in_margin`, `_page_number_ids`, `_is_page_header_line`, `_is_beside` and `_letterhead_groups`.
  - `_letterhead_block` sets the request locale for its message, so it stays in the core.
  - `_manifest_pages_to_payload` builds the core's payload, so it stays in the core.
- **X: blocks, lists, text and table AST.**
  - These are list and text algorithms and go to docstruct: `_recover_empty_lettered_list_items` (130 lines) and `_merge_list_blocks` join `docstruct.blocks.lists`; `_callout_titles` joins `docstruct.blocks.callouts`; `_render_text_from_blocks`, `_render_text_from_pages` and `_normalize_metadata_links` go to docstruct too.
  - `_table_ast_from_rows` and `_table_ast_from_metadata` overlap with `docstruct.tables.ast`; see "Findings".
  - `_elements_to_blocks`, `_element_to_block` and `_text_kept_by_picture` turn manifest elements into blocks and use the `MSG_*` messages. They are adapters and stay in the core; the pure part of `_element_to_block` (110 lines) is split out first.

### Largest functions

These are the functions #365 asked to split, at their current size. All stay in the core; Phase 3 splits them after their pure parts have moved out.

| Function | Group | Lines |
|---|---|---|
| `PddlAccessibilityOrchestrator` (class) | N | 336; `execute` alone 198 (renamed from `executar`, and split in step 5: 81, with `_extract_structure`, `_enrich_before_planning`, `_replan_until_done` and `_check_unsatisfied`) |
| `_enrich_formula_latex` | P | 299 |
| `_enrich_picture_descriptions` | O | 197 |
| `_handle_vlm_pairwise_judge_method` | J | 179 |
| `_enrich_table_structures` | S | 179 |
| `build_pddl_structured_payload` | V | 134 |
| `_recover_empty_lettered_list_items` | X | 130 (moves to docstruct) |

## Shared state

"Depends on" counts names, so it misses the coupling that travels through the manifest: a group writes a key or a field that another group reads later. Moving either side without the other, or reordering them, changes behaviour while every name reference stays intact. This map was measured with `ast` on the same snapshot. It covers:
- element and obligation `metadata["…"]`, through subscripts, `.get`, `.setdefault`, `.pop` and `in`;
- `extractor.configuration["…"]`;
- assignments to element and obligation fields.

It finds 63 keys, 17 of them written or read by more than one group.

| Key | Written by | Read by | What the current order guarantees |
|---|---|---|---|
| `metadata["negation_overlay"]` | F, Q | F, Q, W | Q, before planning, claims a detached negation bar for inline math only if no one has claimed it. F, during execution, skips claimed bars and marks the ones it composes. W leaves claimed bars out of the payload. Q's claim therefore wins, and F is idempotent. |
| `metadata["vision_description_complete"]` | O, P | E, O, X | O sets it on a description and clears it when it records a failure. P sets it when a formula region turns out to be a described picture. E's vision handler skips complete pictures, and X uses it to decide which picture text the payload keeps. |
| `metadata["vision_failure_reason"]` | O | E, O, V | O records the cause and its retry reads it. E's handler reads it. V reports it as a visible degradation (`records_visual_failures`). |
| `metadata["vision_confidence" / "vision_elements" / "vision_language" / "vision_warnings"]` | O, P | — | Two writers of the same description fields: O for pictures, P for the vision fallback of formulas. They must keep one shape. |
| `metadata["original_type"]` | K, O, P | — | Assigned, not set once. When an element is reclassified twice, the last writer decides which original type survives, so the order is part of the behaviour. |
| `metadata["src"]` | G, P | O | Region and page inspection and the formula crop record the image source; picture enrichment reads it. |
| `metadata["table_ast"]` | S | E, F, I, Q, S | S writes it before planning. Q's table pass runs after S, because S can replace a table's cells. E, F and I read it during execution. |
| `metadata["table_read_failure"]` | S | S, V | S records why a table was not read, and V reports it as a degradation. |
| `metadata["mathml"]`, `metadata["verbalization"]`, `metadata["latex_normalized"]` | B, B, E | T | T counts a formula as readable from these (`_formula_has_readable_content`), so its delivery check depends on the handlers having run first. |
| `metadata["blank_page"]` | G | W | Page inspection marks blank pages, and the page payload uses the mark. |
| `configuration["region_inspection_mode"]` | N | G | The pipeline chooses the inspection mode, and the region and page handlers read it. |
| `configuration["toolbox_provider"]` | (the extractor) | I, L | Written outside the orchestrator; provider choice and fusion read it. |

**Element and obligation fields.** These were measured by attribute name, so a few hits may be other objects with the same attribute; read them as an upper bound.
- `text` is written by E, F, G, H, I, L, O, P, Q and S;
- `type` by G, K, O and P;
- `raw_label` by G, O and P;
- `reading_order` by K and L;
- `page_number` by G, L, O and S;
- the `elements` list by G, L and O;
- the `obligations` list by O and P.

**Order of `execute`.** Before planning it runs:
1. P classifies formula regions;
2. O describes pictures;
3. Q marks inline math in prose;
4. P recognizes formulas;
5. S reads tables;
6. Q marks inline math in tables.

The plan's handlers (B, E–L) run next. T's status checks and the payload (V, W, X) come last.

**Characterization first.** Before a move touches either side of a shared key, a test should pin the pair end to end on one manifest, not each side alone:
- F, Q and W on `negation_overlay`;
- O, P, E and X on `vision_description_complete`;
- S before Q on `table_ast`;
- B and E before T on the readable-formula keys;
- O and S into V on the failure records;
- K, O and P on `original_type`.

## Findings

1. **Near-duplicates of docstruct functions** (constitution P1). Merging them means choosing one behaviour, so each needs its own decision, not a neutral move:
   - `_table_ast_from_rows` versus `docstruct.tables.ast.table_ast_from_rows`. The orchestrator's version returns `{"body": []}` when there are no rows and skips non-list rows. docstruct's returns `None` and normalizes mixed inputs.
   - `_block_kind` versus `docstruct.fusion.convert.classify_kind`. Both give a block's `DiffBlock.kind`. The orchestrator's version reads only the element type. docstruct's also reads the text and the type's synonyms: a `title` is a heading there and text in the core, and a paragraph made of one inline span (`$x + y$`) is a formula there and text in the core. Moving `_block_kind` as it is would put two kind classifiers in docstruct. Choosing one changes the blocks the fusion handlers receive, so it needs its own decision.
   - `_iou` versus `docstruct.geometry.intersection_area`. The intersection is the same; `_iou` adds the union. **Resolved without a behaviour change:** `docstruct.fusion.similarity.iou` already computed the same value for every input (#402, Phase 3), and replaced `_iou`.
2. **Dead aliases.** No module, script or test uses `PmvAccessibilityOrchestrator` or `build_pmv_structured_payload` (group Z). They can be removed in a small PR of their own.
3. **Test patch points.** Tests replace **20 names** on the orchestrator module:

   `VisionAgent` (10 files), `_extract_picture_bytes` (9), `inspect_source_media` (9), `_enrich_picture_descriptions` (5), `_enrich_table_structures` (5), `DataAgent` (4), `_formula_recognition_crop` (3), `_run_extract_fused` (3), `toolbox_recognize_formula` (3), `_toolbox_render` (2), `_EMBEDDED_PICTURE_MAX_BYTES`, `_inspect_page`, `_judge_page`, `_manifest_pages_to_payload`, `_render_source_page`, `_save_region_artifact`, `asyncio`, `t`, `toolbox_convert_latex`, `toolbox_verbalize_latex` (1 each).

   Code that looks these names up must either keep doing so through the module that tests patch, or have its tests changed to patch the module where it now lives. The second option is the one this plan recommends: #381's injected hooks were where its four inconsistencies came from.
4. **Portuguese lines move with their code.** The groups hold 106 lines with Portuguese text, mostly docstrings and log messages in B, C, E, I, J, L and O. Each move must lower the orchestrator's count in `tests/fixtures/portuguese_allowlist.json` by the lines that leave, and a new file cannot get an allowlist entry. So the moved lines are either exempted per path in `tests/test_no_portuguese.py` (user-facing text) or translated in the same PR (docstrings). #410 tracks the translation.
5. **No local operation is left.** The orchestrator imports no operational library (`tests/test_architecture_layers.py`). Rendering, OCR, the VLM and conversion all go through the Toolbox, so nothing here moves to the Toolbox.

## Phase 3 order

Each step is one PR with no behaviour change. Characterization tests come first and run on develop. The core imports the new location directly, with no bridge and no wrapper, and tests patch names where they are looked up. The parity checkpoints on cases 036 and 006 in staging are taken at the end of each destination, with the processing cache off: its key does not include the code revision, so a branch run would read develop's output.

1. **Remove the dead aliases** (Z).
2. **docstruct, leaves first:**
   - X's list and text algorithms;
   - W's detection rules;
   - S's row parsing;
   - F's overlay geometry;
   - Q's span geometry;
   - O's text heuristics, I's box geometry and `_tailjoin_position`;
   - `_element_role` and `_block_kind`.

   Each moves with its tests into `libs/docstruct/tests`, and leaves an adapter in the core where the signature takes core models.
3. **SDK.** Rendering, artifact parsing and the text spans call already exist in the SDK, so this step is small and reuses them:
   - the batched text spans read, from `backend/tools/text_spans.fetch_text_spans`, as a `ToolboxPdfClient` method;
   - the input types `pdf.render@2` accepts, from `_RENDERABLE_MEDIA_TYPES`, as a constant next to `render`;
   - the `pB` reading of `document.adjudicate.page`, from `_judge_probability`, next to `ToolboxAdjudicateClient`.
4. **Decompose the mixed functions in the core:** O's `_extract_picture_bytes`, and P's `_formula_recognition_crop` and `_enrich_formula_latex`. Their render calls keep going through G's adapter.
5. **Split the largest functions** in the table above, one per PR.
6. **Reorganize inside the core** only what is still above the size limit (decision D4), for example the execution handlers into `backend/core/execution/handlers/`.
   - **Revised after step 5:** the modules go under `backend/core/pipeline/`, with the layout `acessilia_core.pipeline` would have under [ADR-0016](../adr/0016-core-package.md). If that ADR is accepted, moving them to `libs/core` is a change of path, and `backend/core` disappears with it. Each module stays under 900 lines:

     ```text
     backend/core/pipeline/
       orchestrator.py   # the class: the sequence of execute
       preflight.py      # media inspection, page limits, presentations (A, M)
       toolbox.py        # adapters: render, source artifact, judge (G, J)
       payload.py        # build_pddl_structured_payload (V)
       enrichment/       # pictures (O), formulas (P), tables (S), inline_math (Q), regions (G)
       handlers/         # registry (K), and one module per handler group
     ```

   - **Order:** the leaves first (payload, adapters), then the handlers group by group, the enrichment stages, and the class last. Each pull request is neutral, with characterization and a differential test. Tests that patch a name on `pddl_orchestrator` (finding 3) move to the module where the name now lives.
   - **The rest of the core** (the agents and their prompts, the fusion, the Toolbox adapters, the exporters, the messages and their catalogs) gathers under `backend/core/` after this step, following step 2 of [ADR-0016](../adr/0016-core-package.md)'s roadmap. A boundary test there must pass before the modules move to `libs/core`.

The near-duplicates in finding 1 are behaviour decisions, each in its own PR (P8).

## Decisions to take

- **D1. Types for docstruct functions.**
  - **The question:** should the moved algorithms take docstruct's `DocumentElement`, or plain values (box tuples, strings, rows)?
  - **Proposal:** plain values for geometry and text, `DocumentElement` only where the algorithm needs the element's structure. That keeps adapters small and does not require the core to build docstruct elements on the hot path.
- **D2. The two near-duplicates.**
  - **The question:** which behaviour wins for the empty case of `table_ast_from_rows` (`None` or an empty body)? And should docstruct gain an `iou`?
  - **Proposal:** decide each with its callers' tests in a behaviour PR, after the neutral moves.
- **D3. What the SDK step adds.**
  - **The question:** does the SDK need a new render or text spans binding?
  - **Proposal:** no. `ToolboxPdfClient.render` and `ToolboxPdfClient.text_spans` already cover the calls, and `ArtifactRef` covers the id parsing. The SDK step adds only the three pieces listed in Phase 3, step 3, as client methods or constants. Composing several calls into one SDK function is what ADR A, in Phase 4, decides.
- **D4. Module size limit.**
  - **The question:** #365 asked for an agreed limit on module size, checked by a test.
  - **Proposal:** 900 lines for any module under `backend/agents/` and `backend/core/`. Two modules exceed it today: `pddl_orchestrator.py` (6,185) and `backend/core/manifest/builder.py` (1,205). Both enter the test's allowlist at their current size, which can only shrink; the next largest is `backend/agents/vision_agent.py` (758).
  - **Adjusted after step 5** (#402):
    - **No test enforced D4 yet**, and step 5 grew the orchestrator from 5,531 to 5,823 lines (#461–#466). Each split shortened its function, but added signatures and docstrings. The allowlist starts at the sizes of the day the test lands.
    - **The test lands with step 6**, before its first move: `tests/test_module_size.py`, with the allowlist in a fixture.
    - **What it checks:**
      - a module of the core above 900 lines fails, unless it is listed. The scan covers the core's modules where they are today (`backend/agents/`, `backend/core/`, `backend/ai/`, `backend/pipeline/`, `backend/tools/`, `backend/export/`, `backend/adapters/` and the message modules), and `acessilia_core` once [ADR-0016](../adr/0016-core-package.md) moves them;
      - a listed module that grows fails;
      - a listed module that shrinks fails until its entry is lowered, as the Portuguese allowlist does (`tests/test_no_portuguese.py`), so a gain is kept;
      - an entry at 900 or below is removed.
    - **Step 6 brings both listed modules under 900.** `builder.py` is split by its own responsibilities (building from the Toolbox document, reading order, processing needs, unstructured pages) in its own pull requests.
