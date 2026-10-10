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
| `docstruct.text.latex` | `strip_latex_delimiters`, `normalize_latex`, `wrap_latex` — canonical LaTeX formula normalization and standardization |
| `docstruct.adapters.mineru` | `clean_mineru_text`, `format_mineru_block_text`, `extract_mineru_blocks` — MinerU `middle_json` parsing, spacing, de-hyphenation, and formula/table formatting |
| `docstruct.tables.ast` | `table_ast_from_docling_grid`, `analyze_table_complexity`, `TableAST`, `TableComplexityMetrics`, `TableASTError` |
| `docstruct.text` | `sanitize_text`, `merge_broken_paragraphs`, `normalize_code_text`, `classify_text_block` |
| `docstruct.profiles` | `OUTPUT_PROFILES`, `filter_blocks_for_profile`, `normalize_profile` |
| `docstruct.validation` | `validate_canonical_document`, `validate_output_text`, `Finding` |

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

- `merge_blocks(D, M, policy)` — block-level merge of two providers with Hungarian text+bbox alignment; provider B (MinerU) provides the reading order skeleton; unmatched A blocks are inserted next to their geometric nearest neighbor.
- `_hungarian.py` — pure Kuhn-Munkres O(n³) implementation (replaces scipy; zero dependencies).
- `noise.py` — decor-tail, running heads, junk filter, region suppression, paragraph re-fusion, line-run fusing.
- `FusionPolicy` — frozen dataclass with conservative defaults; benchmark presets (`drbench_v12`, `drbench_v13`) are named classmethods, never defaults.

## Development

```bash
pip install -e "libs/docstruct[dev]"
pytest libs/docstruct/tests
```

CI runs `pytest libs/docstruct/tests` without the backend installed — if a change needs to import `backend/`, it is violating the decoupling.
