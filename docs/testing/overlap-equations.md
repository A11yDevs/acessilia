## Coverage overlap (#644)

91 tests, 32 executed lines, 1 pairs at Jaccard >= 0.5 with at least 2 shared lines.
1 parametrized families with identical line coverage; 90 tests without an exclusive production line.

No test is removed by this report: high overlap is a review candidate.

| Test A | Test B | Jaccard | Shared | Only A | Only B | Param. |
|---|---|---:|---:|---:|---:|---|
| `tests/test_equation_numbers.py::test_number_survives_canonical_and_all_export_boundaries` | `tests/test_equation_numbers.py::test_the_pdf_ua_text_fallback_shows_the_label_not_the_tag` | 0.543 | 19 | 8 | 8 |  |

### Parametrized families with identical coverage

| Family | Variants | Lines |
|---|---:|---:|
| `tests/test_equation_numbers.py::test_recognized_label_replaces_missing_or_invalid_metadata` | 3 | 16 |

### Tests with no exclusive line

These tests cover no line that another test in the same report does not also cover. They are the strongest overlap candidates, not a verdict: they can still be the only one checking a contract or an error message.

| Test | Lines |
|---|---:|
| `tests/test_equation_numbers.py::test_number_survives_canonical_and_all_export_boundaries` | 27 |
| `tests/test_equation_numbers.py::test_the_pdf_ua_text_fallback_shows_the_label_not_the_tag` | 27 |
| `tests/test_equation_numbers.py::test_existing_number_and_idempotence` | 23 |
| `tests/test_export_characterization.py::test_export_matches_frozen_baseline[blocks-pandoc-docx.json]` | 20 |
| `tests/test_export_characterization.py::test_export_matches_frozen_baseline[blocks-pandoc-pdf-ua.json]` | 20 |
| `tests/test_export_walk_parity.py::test_characterized_export_uses_shared_traversal_and_typed_dispatch[blocks-pandoc-docx.json]` | 20 |
| `tests/test_export_walk_parity.py::test_characterized_export_uses_shared_traversal_and_typed_dispatch[blocks-pandoc-pdf-ua.json]` | 20 |
| `tests/test_equation_numbers.py::test_a_promoted_numbered_span_is_converted_without_its_label` | 19 |
| `tests/test_equation_numbers.py::test_numbered_formula_without_speech_keeps_expression_in_accessible_label` | 19 |
| `tests/test_equation_numbers.py::test_invalid_metadata_cannot_inject_export_markup` | 18 |
| `tests/test_equation_numbers.py::test_unnumbered_block_is_unchanged_without_an_enricher` | 18 |
| `tests/test_export_characterization.py::test_export_matches_frozen_baseline[sections-pandoc-docx.json]` | 18 |
| `tests/test_export_characterization.py::test_export_matches_frozen_baseline[sections-pandoc-pdf-ua.json]` | 18 |
| `tests/test_export_walk_parity.py::test_characterized_export_uses_shared_traversal_and_typed_dispatch[sections-pandoc-docx.json]` | 18 |
| `tests/test_export_walk_parity.py::test_characterized_export_uses_shared_traversal_and_typed_dispatch[sections-pandoc-pdf-ua.json]` | 18 |
| `tests/test_pandoc_ast_degrade.py::test_count_math_nodes_covers_all_block_types` | 18 |
| `tests/test_pandoc_ast_degrade.py::test_degrade_math_to_text_all_indices_matches_full_degradation` | 18 |
| `tests/test_pandoc_ast_degrade.py::test_degrade_math_to_text_empty_indices_keeps_ast_equal` | 18 |
| `tests/test_pandoc_ast_degrade.py::test_degrade_math_to_text_selective_preserves_other_formulas_and_alt_spans` | 18 |
| `tests/test_pandoc_ast_degrade.py::test_unconverted_math_indices_empty_when_all_formulas_have_mathml` | 18 |
| `tests/test_pandoc_ast_degrade.py::test_unconverted_math_indices_empty_when_ast_drifted_from_source` | 18 |
| `tests/test_pandoc_ast_degrade.py::test_unconverted_math_indices_empty_when_no_formula_has_mathml` | 18 |
| `tests/test_pandoc_ast_degrade.py::test_unconverted_math_indices_requires_target_format` | 18 |
| `tests/test_pandoc_ast_degrade.py::test_unconverted_math_indices_tracks_every_block_visitor` | 18 |
| `tests/test_export_characterization.py::test_export_matches_frozen_baseline[blocks-markdown.md]` | 17 |
| `tests/test_export_walk_parity.py::test_characterized_export_uses_shared_traversal_and_typed_dispatch[blocks-markdown.md]` | 17 |
| `tests/test_equation_numbers.py::test_recognized_label_replaces_missing_or_invalid_metadata[None]` | 16 |
| `tests/test_equation_numbers.py::test_recognized_label_replaces_missing_or_invalid_metadata[\\input{file}]` | 16 |
| `tests/test_equation_numbers.py::test_recognized_label_replaces_missing_or_invalid_metadata[]` | 16 |
| `tests/test_equation_numbers.py::test_existing_delimiters_do_not_nest_in_numbered_output` | 15 |
| `tests/test_equation_numbers.py::test_zero_is_a_valid_equation_number` | 15 |
| `tests/test_export_characterization.py::test_export_matches_frozen_baseline[sections-markdown.md]` | 15 |
| `tests/test_export_walk_parity.py::test_characterized_export_uses_shared_traversal_and_typed_dispatch[sections-markdown.md]` | 15 |
| `tests/test_markdown_export.py::test_blocks_render_in_reading_order` | 15 |
| `tests/test_schema_validation.py::test_pure_builder_output_conforms_without_enabling_runtime_validation[source3]` | 12 |
| `tests/test_equation_numbers.py::test_ambiguous_or_unsafe_input_is_unchanged[\\sinh (1)]` | 10 |
| `tests/test_equation_numbers.py::test_ambiguous_or_unsafe_input_is_unchanged[a \\times b (1)]` | 10 |
| `tests/test_equation_numbers.py::test_split_label[a < b (6)-a < b-6]` | 10 |
| `tests/test_equation_numbers.py::test_split_label[f \\propto g (8)-f \\propto g-8]` | 10 |
| `tests/test_equation_numbers.py::test_split_label[x = 28h.(1)-x = 28h.-1]` | 10 |
| `tests/test_equation_numbers.py::test_split_label[x = y (3)-x = y-3]` | 10 |
| `tests/test_equation_numbers.py::test_split_label[x = y\\quad(2)-x = y-2]` | 10 |
| `tests/test_equation_numbers.py::test_split_label[x \\neq 0 (7)-x \\neq 0-7]` | 10 |
| `tests/test_equation_numbers.py::test_split_label[x \\to \\infty (9)-x \\to \\infty-9]` | 10 |
| `tests/test_equation_numbers.py::test_split_label[x=y\\qquad\\text{(4)}-x=y-4]` | 10 |
| `tests/test_equation_numbers.py::test_split_label[x=y\\quad\\text{ (5) }-x=y-5]` | 10 |
| `tests/test_equation_numbers.py::test_split_label[$$x=y\\tag{01}$$-x=y-01]` | 9 |
| `tests/test_equation_numbers.py::test_split_label[x = y\\tag{1}-x = y-1]` | 9 |
| `tests/test_equation_numbers.py::test_split_label[x=y\\tag{A.1}-x=y-A.1]` | 9 |
| `tests/test_equation_numbers.py::test_ambiguous_or_unsafe_input_is_unchanged[f(x) = (1)]` | 8 |
| `tests/test_equation_numbers.py::test_ambiguous_or_unsafe_input_is_unchanged[x + (1)]` | 8 |
| `tests/test_equation_numbers.py::test_ambiguous_or_unsafe_input_is_unchanged[x < (1)]` | 8 |
| `tests/test_equation_numbers.py::test_ambiguous_or_unsafe_input_is_unchanged[x = y + (1)]` | 8 |
| `tests/test_equation_numbers.py::test_ambiguous_or_unsafe_input_is_unchanged[x = y \\times (1)]` | 8 |
| `tests/test_equation_numbers.py::test_ambiguous_or_unsafe_input_is_unchanged[x \\le (1)]` | 8 |
| `tests/test_equation_numbers.py::test_ambiguous_or_unsafe_input_is_unchanged[x \\neq (1)]` | 8 |
| `tests/test_equation_numbers.py::test_ambiguous_or_unsafe_input_is_unchanged[x=\\sin (1)]` | 8 |
| `tests/test_equation_numbers.py::test_ambiguous_or_unsafe_input_is_unchanged[(1)]` | 6 |
| `tests/test_equation_numbers.py::test_ambiguous_or_unsafe_input_is_unchanged[f(x) = (x + 1)]` | 6 |
| `tests/test_equation_numbers.py::test_ambiguous_or_unsafe_input_is_unchanged[x(1)]` | 6 |
| `tests/test_equation_numbers.py::test_ambiguous_or_unsafe_input_is_unchanged[x=\\frac{1}{(2)}]` | 6 |
| `tests/test_equation_numbers.py::test_ambiguous_or_unsafe_input_is_unchanged[x=y\\tag{\\input{file}}]` | 6 |
| `tests/test_export_characterization.py::test_export_matches_frozen_baseline[blocks-html-docx.html]` | 6 |
| `tests/test_export_characterization.py::test_export_matches_frozen_baseline[blocks-html-pdf.html]` | 6 |
| `tests/test_export_characterization.py::test_export_matches_frozen_baseline[blocks-html-pdf_ua.html]` | 6 |
| `tests/test_export_characterization.py::test_export_matches_frozen_baseline[blocks-html-txt.html]` | 6 |
| `tests/test_export_characterization.py::test_export_matches_frozen_baseline[blocks-html-unrecognized.html]` | 6 |
| `tests/test_export_characterization.py::test_export_matches_frozen_baseline[blocks-html.html]` | 6 |
| `tests/test_export_characterization.py::test_export_matches_frozen_baseline[blocks-txt-docx.txt]` | 6 |
| `tests/test_export_characterization.py::test_export_matches_frozen_baseline[blocks-txt-html.txt]` | 6 |
| `tests/test_export_characterization.py::test_export_matches_frozen_baseline[blocks-txt-pdf.txt]` | 6 |
| `tests/test_export_characterization.py::test_export_matches_frozen_baseline[blocks-txt-pdf_ua.txt]` | 6 |
| `tests/test_export_characterization.py::test_export_matches_frozen_baseline[blocks-txt-unrecognized.txt]` | 6 |
| `tests/test_export_characterization.py::test_export_matches_frozen_baseline[blocks-txt.txt]` | 6 |
| `tests/test_export_characterization.py::test_export_matches_frozen_baseline[sections-html.html]` | 6 |
| `tests/test_export_characterization.py::test_export_matches_frozen_baseline[sections-txt.txt]` | 6 |
| `tests/test_export_walk_parity.py::test_characterized_export_uses_shared_traversal_and_typed_dispatch[blocks-html-docx.html]` | 6 |
| `tests/test_export_walk_parity.py::test_characterized_export_uses_shared_traversal_and_typed_dispatch[blocks-html-pdf.html]` | 6 |
| `tests/test_export_walk_parity.py::test_characterized_export_uses_shared_traversal_and_typed_dispatch[blocks-html-pdf_ua.html]` | 6 |
| `tests/test_export_walk_parity.py::test_characterized_export_uses_shared_traversal_and_typed_dispatch[blocks-html-txt.html]` | 6 |
| `tests/test_export_walk_parity.py::test_characterized_export_uses_shared_traversal_and_typed_dispatch[blocks-html-unrecognized.html]` | 6 |
| `tests/test_export_walk_parity.py::test_characterized_export_uses_shared_traversal_and_typed_dispatch[blocks-html.html]` | 6 |
| `tests/test_export_walk_parity.py::test_characterized_export_uses_shared_traversal_and_typed_dispatch[blocks-txt-docx.txt]` | 6 |
| `tests/test_export_walk_parity.py::test_characterized_export_uses_shared_traversal_and_typed_dispatch[blocks-txt-html.txt]` | 6 |
| `tests/test_export_walk_parity.py::test_characterized_export_uses_shared_traversal_and_typed_dispatch[blocks-txt-pdf.txt]` | 6 |
| `tests/test_export_walk_parity.py::test_characterized_export_uses_shared_traversal_and_typed_dispatch[blocks-txt-pdf_ua.txt]` | 6 |
| `tests/test_export_walk_parity.py::test_characterized_export_uses_shared_traversal_and_typed_dispatch[blocks-txt-unrecognized.txt]` | 6 |
| `tests/test_export_walk_parity.py::test_characterized_export_uses_shared_traversal_and_typed_dispatch[blocks-txt.txt]` | 6 |
| `tests/test_export_walk_parity.py::test_characterized_export_uses_shared_traversal_and_typed_dispatch[sections-html.html]` | 6 |
| `tests/test_export_walk_parity.py::test_characterized_export_uses_shared_traversal_and_typed_dispatch[sections-txt.txt]` | 6 |
