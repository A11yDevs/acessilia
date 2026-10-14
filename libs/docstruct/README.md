# acessilia-docstruct

Pure document-structure processing core for Acessilia.

> Also available in **Brazilian Portuguese**: [Portuguese version](README.pt-br.md)

## Principles

- **Pure**: no function touches network, files, subprocess, settings, logger, or dynamic i18n. Zero heavy ML dependencies (`dependencies = []`).
- **Single dependency direction**: `backend → docstruct` or `acessilia-toolbox → docstruct`. The library never imports from `backend/` or `acessilia_toolbox/`.
- **i18n = msgids**: functions that produce messages return `(msgid, args)`; the consumer translates.
- **Deterministic or injected IDs**: no `uuid4` inside the lib.

## Public API

| Module | Symbols |
|---|---|
| `docstruct.types` | `BBox`, `CanonicalBlock`, `CanonicalDocument`, `Region`, `BlockPairing`, `OrientationResult` |
| `docstruct.geometry` | `content_fingerprint`, `overlaps_clean`, `merge_bboxes`, `union`, `intersection_area` |
| `docstruct.geometry.reading_order` | `refine_reading_order` — column-aware reading order refinement with marginal isolation and 2-/3-column gutter partitioning |
| `docstruct.policy` | `FusionPolicy` (+ presets: `drbench_v12`, `drbench_v13`) |
| `docstruct.fusion` | `merge_blocks`, `block_to_diff`, `DiffBlock`, `ProviderBlocks`, `quality`, `is_junk` |
| `docstruct.fusion.xycut` | `xycut_order`, `count_columns`, `column_balance`, `reorder` — optional XY-cut reading order (`FusionPolicy.order_xycut`) |
| `docstruct.fusion.verse` | `record_like`, `verse_lines`, `chunk_verse`, `split_box_rows`, `verse_blocks` |
| `docstruct.fusion.line_numbers` | `line_number_chain`, `extract_line_numbers` |
| `docstruct.fusion.flood` | `flood_guard` |
| `docstruct.fusion.tailjoin` | `is_page_number`, `join_tail`, `page_number_position`, `tailjoin3` |
| `docstruct.fusion.repetition` | `collapse`, `guard_page`, `is_blank_page`, `strip_comment` |
| `docstruct.fusion.page_select` | `fuse`, `select_by_agreement`, `swap_low_agreement_pages`, `ratio` |
| `docstruct.fusion.judge` | `debias`, `decide_pair`, `p2_from_logprobs`, `should_judge` |
| `docstruct.fusion.adjudication` | `decide_v0`, `decide_v1`, `decide`, `filter_decision` |
| `docstruct.fusion.oracle` | `oracle_page`, `best_score`, `summarize` |
| `docstruct.fusion.hf_end` | `move_hf_to_end`, `move_body_hf_to_tail` |
| `docstruct.fusion.table_specialist` | `extract_table`, `norm_table`, `select_table`, `select_greedy` |
| `docstruct.text.latex` | `strip_latex_delimiters`, `normalize_latex`, `wrap_latex` — canonical LaTeX formula normalization and standardization |
| `docstruct.text.normalize` | `norm` — deterministic text cleanups |
| `docstruct.text.norm_fix` | `norm_fix` — post-normalization repairs |
| `docstruct.adapters.mineru` | `clean_mineru_text`, `format_mineru_block_text`, `extract_mineru_blocks` — MinerU `middle_json` parsing, spacing, de-hyphenation, and formula/table formatting |
| `docstruct.tables.ast` | `table_ast_from_docling_grid`, `analyze_table_complexity`, `TableAST`, `TableComplexityMetrics`, `TableASTError` |
| `docstruct.text` | `sanitize_text`, `merge_broken_paragraphs`, `normalize_code_text`, `classify_text_block` |
| `docstruct.imaging.policy` | `upscale_factor`, `decide_orientation` (no PIL/cv2) |
| `docstruct.evaluation.holdout` | `partition`, `score`, `evaluate_candidate` |
| `docstruct.profiles` | `OUTPUT_PROFILES`, `filter_blocks_for_profile`, `normalize_profile` |
| `docstruct.validation` | `validate_canonical_document`, `validate_output_text`, `Finding` |

Planned modules (phases 2–3): `blocks/`, `regions/`, `tables/`, `math/`, `render/`, `validation.py`.

## Modules

### LaTeX Normalization (`docstruct.text.latex`)

Canonical routines for standardizing and cleaning mathematical formulas:
- `strip_latex_delimiters(text)`: Removes enclosing inline (`$...$`, `\(...\)`) and display (`$$...$$`, `\[...\]`) delimiters.
- `normalize_latex(text)`: Standardizes Unicode symbols to ASCII equivalents (e.g., Greek characters, exponents, operators), canonicalizes common macros (such as `\bm` to `\mathbf`, `\bold` to `\mathbf`), and collapses redundant whitespace.
- `wrap_latex(text, display=False)`: Wraps raw LaTeX expressions in standard delimiters (`$...$` or `$$...$$`).

### MinerU Adapter (`docstruct.adapters.mineru`)

Lightweight parser for MinerU `middle_json` output:
- `clean_mineru_text(lines_or_pieces)`: Preserves line spacing and automatically re-assembles words broken at end of line (e.g., `["impor-", "tant"]` -> `"important"`).
- `format_mineru_block_text(block)`: Formats formulas and tables into canonical text representations (display math wrapped with `$$...$$`, inline math with `$...$`, tables with markdown/HTML).
- `extract_mineru_blocks(middle_json)`: Extracts flattened lists of layout blocks with normalized geometry and content.

### Table AST & Complexity (`docstruct.tables.ast`)

Pure grid analysis and AST conversion:
- `table_ast_from_docling_grid(grid_or_cells, caption=None)`: Builds a canonical `TableAST` from Docling grid cells (`start_row_offset_idx`, `start_col_offset_idx`, row and column spans).
- `analyze_table_complexity(table_ast_or_cells)`: Evaluates table complexity returning `TableComplexityMetrics` (`has_spans`, `max_rowspan`, `max_colspan`, `spanned_cell_count`, `is_complex`).

### Reading Order Refinement (`docstruct.geometry.reading_order`)

Topological page reading order optimization:
- `refine_reading_order(blocks)`: Partitions blocks per page, isolates running headers and footers to top and bottom margins, and reconstructs reading flow for multi-column pages (2-column and 3-column gutters separated by full-width banners).

### Fusion (`docstruct.fusion`)

Port of the Tree Differ v2 from PR #98 (Dr.DocBench) as a pure library:

- `merge_blocks(D, M, policy)` — block-level merge of two providers with
  Hungarian text+bbox alignment; provider B (MinerU) provides the reading
  order skeleton; unmatched A blocks are inserted next to their geometric
  nearest neighbor.
- `_hungarian.py` — pure Kuhn-Munkres O(n³) implementation (replaces scipy;
  zero dependencies).
- `noise.py` — decor-tail, running heads, junk filter, region suppression,
  paragraph re-fusion, line-run fusing.
- `FusionPolicy` — frozen dataclass. The defaults are the **production**
  policy: the deterministic capabilities with evidence of gain (or that fix a
  defect) are on, and anything that consumes a model is off. Benchmark presets
  (`drbench_v12`, `drbench_v13`, `drbench_v14`, `drbench_v15`,
  `drbench_best_method`) are named classmethods, never defaults (they were
  overfitted to the dev split).
- `fusion/verse.py`, `fusion/line_numbers.py`, `fusion/flood.py`,
  `fusion/tailjoin.py`, `fusion/repetition.py`, `fusion/page_select.py`,
  `fusion/judge.py`, `fusion/adjudication.py`, `fusion/oracle.py`,
  `fusion/hf_end.py`, `fusion/table_specialist.py` — the deterministic
  Dr.DocBench PR #125 policies, ported as pure functions.
- `text/normalize.py`, `text/norm_fix.py` — text normalization primitives.
- `imaging/policy.py` — pure upscale/orientation decisions (no PIL/cv2).

### Production defaults

| Capability | Default | Why |
|---|---|---|
| `verse_chunk` 300, `verse_kind` records | on | deterministic; keeps real verse whole |
| `line_numbers`, `table_eq`, `norm_text`, `hf_end` | on | deterministic, low risk |
| `tailjoin` end / 50 / 3 / `hdr` | on | the `tj3` rule: Δtune +1.47, Δhold +0.79 |
| `rep_guard`, `blank_pages` | on | fixes degenerate generation loops |
| `upscale`, `orientation` | on | largest isolated gain of the Tele line (Δtune +1.59, Δhold +2.91) |
| `page_judge` | **off** | consumes a model; enable when the Toolbox exposes `document.adjudicate.page` |

Rejected experiments (word_vote, dedup_blocks, medoid, block judge, header
move, dots tables, DeepSeek arbiter, logistic selector, prompt ensemble,
threshold retuning) are **not** in the defaults: they showed Δtune ≤ 0 and
Δhold ≤ 0.

### Dr.DocBench presets

| Preset | Composition | Status |
|---|---|---|
| `drbench_v12` | differ-v12 (calibrated on dev) | named, never default |
| `drbench_v13` | v12 + pic-need-text + formula-text | named, never default |
| `drbench_v14` | v13 + line-numbers + table-eq + verse-chunk 300 | named, never default |
| `drbench_v15` | v14 + page judge + tailjoin `end/50/3/hdr` + rep-guard + hf-end + upscale + orientation | **confirmed leaderboard best** (EvalAI 70.37) |
| `drbench_best_method` | v15 + judge2 thresholds + page swap + blank pages + norm-text | dev best (87.33), **never confirmed** — dev→test gap ≈ 8 pts |

`drbench_best_method` exists to make the loop's best method reproducible for
future performance work. It must never become a default: the TEDS gain did not
transfer (dev +5.9 → test +0.2), and the real test gain came from reading order
with the MinerU hybrid-VLM source.

## Development

```bash
pip install -e "libs/docstruct[dev]"
pytest libs/docstruct/tests
```

CI runs `pytest libs/docstruct/tests` without the backend installed — if a change needs to import `backend/`, it is violating the decoupling.
