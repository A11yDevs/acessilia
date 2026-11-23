## Coverage overlap (#644)

1807 tests, 6342 executed lines, 1231 pairs at Jaccard >= 0.8 with at least 5 shared lines.
39 parametrized families with identical line coverage; 1519 tests without an exclusive production line.

No test is removed by this report: high overlap is a review candidate.

| Test A | Test B | Jaccard | Shared | Only A | Only B | Param. |
|---|---|---:|---:|---:|---:|---|
| `tests/test_inline_math_detection.py::test_a_decimal_comma_stays_in_the_run[1.000,50]` | `tests/test_inline_math_detection.py::test_a_decimal_comma_stays_in_the_run[3,5]` | 1.000 | 181 | 0 | 0 | yes |
| `tests/test_fusion_payload.py::TestRoutePagesAndApplyPageRoutes::test_an_id_less_element_with_a_zero_based_page_is_normalized` | `tests/test_fusion_payload.py::TestRoutePagesAndApplyPageRoutes::test_an_unpaged_id_less_element_gets_an_id_outside_page_membership` | 1.000 | 171 | 0 | 0 |  |
| `tests/test_fusion_payload.py::TestRoutePagesAndApplyPageRoutes::test_an_id_less_element_joins_a_page_that_already_lists_ids` | `tests/test_fusion_payload.py::TestRoutePagesAndApplyPageRoutes::test_primary_elements_without_a_usable_id_get_a_deterministic_id[]` | 1.000 | 169 | 0 | 0 |  |
| `tests/test_fusion_payload.py::TestRoutePagesAndApplyPageRoutes::test_an_id_less_element_joins_a_page_that_already_lists_ids` | `tests/test_fusion_payload.py::TestRoutePagesAndApplyPageRoutes::test_primary_elements_without_a_usable_id_get_a_deterministic_id[absent]` | 1.000 | 169 | 0 | 0 |  |
| `tests/test_fusion_payload.py::TestRoutePagesAndApplyPageRoutes::test_an_id_less_element_joins_a_page_that_already_lists_ids` | `tests/test_fusion_payload.py::TestRoutePagesAndApplyPageRoutes::test_primary_elements_without_id_get_a_deterministic_id` | 1.000 | 169 | 0 | 0 |  |
| `tests/test_fusion_payload.py::TestRoutePagesAndApplyPageRoutes::test_primary_elements_without_a_usable_id_get_a_deterministic_id[]` | `tests/test_fusion_payload.py::TestRoutePagesAndApplyPageRoutes::test_primary_elements_without_a_usable_id_get_a_deterministic_id[absent]` | 1.000 | 169 | 0 | 0 | yes |
| `tests/test_fusion_payload.py::TestRoutePagesAndApplyPageRoutes::test_primary_elements_without_a_usable_id_get_a_deterministic_id[]` | `tests/test_fusion_payload.py::TestRoutePagesAndApplyPageRoutes::test_primary_elements_without_id_get_a_deterministic_id` | 1.000 | 169 | 0 | 0 |  |
| `tests/test_fusion_payload.py::TestRoutePagesAndApplyPageRoutes::test_primary_elements_without_a_usable_id_get_a_deterministic_id[absent]` | `tests/test_fusion_payload.py::TestRoutePagesAndApplyPageRoutes::test_primary_elements_without_id_get_a_deterministic_id` | 1.000 | 169 | 0 | 0 |  |
| `tests/test_reading_order.py::TestMultiColumnReadingOrder::test_full_width_banner_splits_sections` | `tests/test_reading_order.py::TestMultiColumnReadingOrder::test_mid_page_banner_splits_column_sections` | 1.000 | 103 | 0 | 0 |  |
| `tests/test_blocks_lists.py::test_a_prefix_after_the_first_item_becomes_its_preamble` | `tests/test_blocks_lists.py::test_the_elements_are_read_and_never_changed` | 1.000 | 89 | 0 | 0 |  |
| `tests/test_blocks_lists.py::test_a_sibling_paragraph_fills_the_empty_items_and_keeps_its_prefix` | `tests/test_blocks_lists.py::test_docstruct_document_elements_are_list_sources` | 1.000 | 87 | 0 | 0 |  |
| `tests/test_blocks_lists.py::test_a_sibling_paragraph_fills_the_empty_items_and_keeps_its_prefix` | `tests/test_blocks_lists.py::test_items_without_markers_and_an_unknown_source_are_recovered` | 1.000 | 87 | 0 | 0 |  |
| `tests/test_blocks_lists.py::test_docstruct_document_elements_are_list_sources` | `tests/test_blocks_lists.py::test_items_without_markers_and_an_unknown_source_are_recovered` | 1.000 | 87 | 0 | 0 |  |
| `tests/test_unicode_repair.py::TestSpacingDiacritics::test_enabled_by_the_caller` | `tests/test_unicode_repair.py::TestSpacingDiacritics::test_explicit_enablement_is_the_evidence` | 1.000 | 79 | 0 | 0 |  |
| `tests/test_unicode_repair.py::TestSpacingDiacritics::test_enabled_by_the_caller` | `tests/test_unicode_repair.py::TestSpacingDiacritics::test_spaced_function_and_negation` | 1.000 | 79 | 0 | 0 |  |
| `tests/test_unicode_repair.py::TestSpacingDiacritics::test_enabled_by_the_caller` | `tests/test_unicode_repair.py::TestSpacingDiacritics::test_standalone_accent_with_document_evidence` | 1.000 | 79 | 0 | 0 |  |
| `tests/test_unicode_repair.py::TestSpacingDiacritics::test_enabled_by_the_caller` | `tests/test_unicode_repair.py::TestSpacingDiacritics::test_word_internal_dotless_base` | 1.000 | 79 | 0 | 0 |  |
| `tests/test_unicode_repair.py::TestSpacingDiacritics::test_explicit_enablement_is_the_evidence` | `tests/test_unicode_repair.py::TestSpacingDiacritics::test_spaced_function_and_negation` | 1.000 | 79 | 0 | 0 |  |
| `tests/test_unicode_repair.py::TestSpacingDiacritics::test_explicit_enablement_is_the_evidence` | `tests/test_unicode_repair.py::TestSpacingDiacritics::test_standalone_accent_with_document_evidence` | 1.000 | 79 | 0 | 0 |  |
| `tests/test_unicode_repair.py::TestSpacingDiacritics::test_explicit_enablement_is_the_evidence` | `tests/test_unicode_repair.py::TestSpacingDiacritics::test_word_internal_dotless_base` | 1.000 | 79 | 0 | 0 |  |
| `tests/test_unicode_repair.py::TestSpacingDiacritics::test_spaced_function_and_negation` | `tests/test_unicode_repair.py::TestSpacingDiacritics::test_standalone_accent_with_document_evidence` | 1.000 | 79 | 0 | 0 |  |
| `tests/test_unicode_repair.py::TestSpacingDiacritics::test_spaced_function_and_negation` | `tests/test_unicode_repair.py::TestSpacingDiacritics::test_word_internal_dotless_base` | 1.000 | 79 | 0 | 0 |  |
| `tests/test_unicode_repair.py::TestSpacingDiacritics::test_standalone_accent_with_document_evidence` | `tests/test_unicode_repair.py::TestSpacingDiacritics::test_word_internal_dotless_base` | 1.000 | 79 | 0 | 0 |  |
| `tests/test_blocks_lists.py::test_nothing_is_recovered_unless_one_source_fits_one_group_exactly[known-mismatch]` | `tests/test_blocks_lists.py::test_nothing_is_recovered_unless_one_source_fits_one_group_exactly[not-from-a]` | 1.000 | 71 | 0 | 0 | yes |
| `tests/test_unicode_repair.py::TestCombiningAndDotless::test_idempotent` | `tests/test_unicode_repair.py::TestCombiningAndDotless::test_offsets_point_at_the_original_text` | 1.000 | 71 | 0 | 0 |  |
| `tests/test_xycut.py::TestReorder::test_inverted_boxes_are_still_ordered` | `tests/test_xycut.py::TestReorder::test_multicol_reorders_interleaved_columns` | 1.000 | 71 | 0 | 0 |  |
| `tests/test_unicode_repair.py::TestCombiningAndDotless::test_dificil` | `tests/test_unicode_repair.py::TestCombiningAndDotless::test_dotless_i_before_the_accent` | 1.000 | 68 | 0 | 0 |  |
| `tests/test_text_migration.py::TestCodeReflow::test_else_same_line` | `tests/test_text_migration.py::TestCodeReflow::test_reflow_java` | 1.000 | 64 | 0 | 0 |  |
| `tests/test_unicode_repair.py::TestCombiningAndDotless::test_calculo_in_nfd` | `tests/test_unicode_repair.py::TestCombiningAndDotless::test_cedilla_and_tilde_in_nfd` | 1.000 | 63 | 0 | 0 |  |
| `tests/test_unicode_repair.py::TestCombiningAndDotless::test_calculo_in_nfd` | `tests/test_unicode_repair.py::TestCombiningAndDotless::test_nfc_composes_a_decomposed_word` | 1.000 | 63 | 0 | 0 |  |
| `tests/test_unicode_repair.py::TestCombiningAndDotless::test_cedilla_and_tilde_in_nfd` | `tests/test_unicode_repair.py::TestCombiningAndDotless::test_nfc_composes_a_decomposed_word` | 1.000 | 63 | 0 | 0 |  |
| `tests/test_verse.py::TestVerseBlocks::test_metadados_do_bloco_original_sao_preservados` | `tests/test_verse.py::TestVerseBlocks::test_registros_sao_divididos` | 1.000 | 60 | 0 | 0 |  |
| `tests/test_verse.py::TestVerseBlocks::test_metadados_do_bloco_original_sao_preservados` | `tests/test_verse.py::TestVerseBlocks::test_texto_dos_pedacos_e_normalizado` | 1.000 | 60 | 0 | 0 |  |
| `tests/test_verse.py::TestVerseBlocks::test_registros_sao_divididos` | `tests/test_verse.py::TestVerseBlocks::test_texto_dos_pedacos_e_normalizado` | 1.000 | 60 | 0 | 0 |  |
| `tests/test_unicode_repair.py::TestProtectedContent::test_inline_code_is_protected` | `tests/test_unicode_repair.py::TestProtectedContent::test_url_is_protected` | 1.000 | 58 | 0 | 0 |  |
| `tests/test_blocks_lists.py::test_nothing_is_recovered_unless_one_source_fits_one_group_exactly[count]` | `tests/test_blocks_lists.py::test_nothing_is_recovered_unless_one_source_fits_one_group_exactly[prose]` | 1.000 | 57 | 0 | 0 | yes |
| `tests/test_line_numbers.py::TestExtractLineNumbers::test_bloco_sem_box_nao_quebra` | `tests/test_line_numbers.py::TestExtractLineNumbers::test_boxes_dos_numeros_derivam_do_bloco` | 1.000 | 51 | 0 | 0 |  |
| `tests/test_line_numbers.py::TestExtractLineNumbers::test_bloco_sem_box_nao_quebra` | `tests/test_line_numbers.py::TestExtractLineNumbers::test_metadados_do_bloco_original_sao_preservados` | 1.000 | 51 | 0 | 0 |  |
| `tests/test_line_numbers.py::TestExtractLineNumbers::test_bloco_sem_box_nao_quebra` | `tests/test_line_numbers.py::TestExtractLineNumbers::test_numeros_inline_sao_extraidos` | 1.000 | 51 | 0 | 0 |  |
| `tests/test_line_numbers.py::TestExtractLineNumbers::test_bloco_sem_box_nao_quebra` | `tests/test_line_numbers.py::TestExtractLineNumbers::test_numeros_viram_blocos_separados_apos_o_texto` | 1.000 | 51 | 0 | 0 |  |
| `tests/test_line_numbers.py::TestExtractLineNumbers::test_boxes_dos_numeros_derivam_do_bloco` | `tests/test_line_numbers.py::TestExtractLineNumbers::test_metadados_do_bloco_original_sao_preservados` | 1.000 | 51 | 0 | 0 |  |
| `tests/test_line_numbers.py::TestExtractLineNumbers::test_boxes_dos_numeros_derivam_do_bloco` | `tests/test_line_numbers.py::TestExtractLineNumbers::test_numeros_inline_sao_extraidos` | 1.000 | 51 | 0 | 0 |  |
| `tests/test_line_numbers.py::TestExtractLineNumbers::test_boxes_dos_numeros_derivam_do_bloco` | `tests/test_line_numbers.py::TestExtractLineNumbers::test_numeros_viram_blocos_separados_apos_o_texto` | 1.000 | 51 | 0 | 0 |  |
| `tests/test_line_numbers.py::TestExtractLineNumbers::test_metadados_do_bloco_original_sao_preservados` | `tests/test_line_numbers.py::TestExtractLineNumbers::test_numeros_inline_sao_extraidos` | 1.000 | 51 | 0 | 0 |  |
| `tests/test_line_numbers.py::TestExtractLineNumbers::test_metadados_do_bloco_original_sao_preservados` | `tests/test_line_numbers.py::TestExtractLineNumbers::test_numeros_viram_blocos_separados_apos_o_texto` | 1.000 | 51 | 0 | 0 |  |
| `tests/test_line_numbers.py::TestExtractLineNumbers::test_numeros_inline_sao_extraidos` | `tests/test_line_numbers.py::TestExtractLineNumbers::test_numeros_viram_blocos_separados_apos_o_texto` | 1.000 | 51 | 0 | 0 |  |
| `tests/test_fusion_payload.py::TestRoutePagesAndApplyPageRoutes::test_without_a_route_an_id_less_payload_is_returned_unchanged` | `tests/test_fusion_payload.py::TestRoutePagesAndApplyPageRoutes::test_without_routed_pages_primary_payload_identity_is_preserved` | 1.000 | 50 | 0 | 0 |  |
| `tests/test_fusion.py::TestHungarian::test_3x3` | `tests/test_fusion.py::TestHungarian::test_identidade` | 1.000 | 49 | 0 | 0 |  |
| `tests/test_fusion.py::TestHungarian::test_3x3` | `tests/test_fusion.py::TestHungarian::test_otimo_minimo` | 1.000 | 49 | 0 | 0 |  |
| `tests/test_fusion.py::TestHungarian::test_3x3` | `tests/test_fusion.py::TestHungarian::test_retangular` | 1.000 | 49 | 0 | 0 |  |
| `tests/test_fusion.py::TestHungarian::test_3x3` | `tests/test_fusion.py::TestHungarian::test_swapped` | 1.000 | 49 | 0 | 0 |  |
| `tests/test_fusion.py::TestHungarian::test_identidade` | `tests/test_fusion.py::TestHungarian::test_otimo_minimo` | 1.000 | 49 | 0 | 0 |  |
| `tests/test_fusion.py::TestHungarian::test_identidade` | `tests/test_fusion.py::TestHungarian::test_retangular` | 1.000 | 49 | 0 | 0 |  |
| `tests/test_fusion.py::TestHungarian::test_identidade` | `tests/test_fusion.py::TestHungarian::test_swapped` | 1.000 | 49 | 0 | 0 |  |
| `tests/test_fusion.py::TestHungarian::test_otimo_minimo` | `tests/test_fusion.py::TestHungarian::test_retangular` | 1.000 | 49 | 0 | 0 |  |
| `tests/test_fusion.py::TestHungarian::test_otimo_minimo` | `tests/test_fusion.py::TestHungarian::test_swapped` | 1.000 | 49 | 0 | 0 |  |
| `tests/test_fusion.py::TestHungarian::test_retangular` | `tests/test_fusion.py::TestHungarian::test_swapped` | 1.000 | 49 | 0 | 0 |  |
| `tests/test_metrics.py::TestTEDS::test_identical_tables` | `tests/test_metrics.py::TestTEDS::test_structural_difference_lower` | 1.000 | 46 | 0 | 0 |  |
| `tests/test_table_specialist.py::TestSelectTable::test_provider_medoid_selects_the_provider` | `tests/test_table_specialist.py::TestSelectTable::test_vlm_medoid_replaces` | 1.000 | 44 | 0 | 0 |  |
| `tests/test_latex.py::TestNormalizeLatex::test_greek_letters` | `tests/test_latex.py::TestNormalizeLatex::test_unicode_math_symbols` | 1.000 | 42 | 0 | 0 |  |
| `tests/test_latex.py::TestNormalizeLatex::test_ocr_wrapper_removal` | `tests/test_latex.py::TestNormalizeLatex::test_spacing_macros` | 1.000 | 41 | 0 | 0 |  |
| `tests/test_latex.py::TestNormalizeLatex::test_ocr_wrapper_removal` | `tests/test_latex.py::TestNormalizeLatex::test_superscript_subscript_normalization` | 1.000 | 41 | 0 | 0 |  |
| `tests/test_latex.py::TestNormalizeLatex::test_ocr_wrapper_removal` | `tests/test_latex.py::TestNormalizeLatex::test_unicode_minus_and_spaces` | 1.000 | 41 | 0 | 0 |  |
| `tests/test_latex.py::TestNormalizeLatex::test_spacing_macros` | `tests/test_latex.py::TestNormalizeLatex::test_superscript_subscript_normalization` | 1.000 | 41 | 0 | 0 |  |
| `tests/test_latex.py::TestNormalizeLatex::test_spacing_macros` | `tests/test_latex.py::TestNormalizeLatex::test_unicode_minus_and_spaces` | 1.000 | 41 | 0 | 0 |  |
| `tests/test_latex.py::TestNormalizeLatex::test_superscript_subscript_normalization` | `tests/test_latex.py::TestNormalizeLatex::test_unicode_minus_and_spaces` | 1.000 | 41 | 0 | 0 |  |
| `tests/test_fusion_payload.py::TestNormalizeElementIds::test_parent_references_follow_a_replaced_non_string_id` | `tests/test_fusion_payload.py::TestNormalizeElementIds::test_with_duplicate_non_string_ids_children_follow_the_last_one` | 1.000 | 40 | 0 | 0 |  |
| `tests/test_fusion_payload.py::TestNormalizeElementIds::test_a_zero_based_page_is_scoped_to_the_one_based_page` | `tests/test_fusion_payload.py::TestNormalizeElementIds::test_pages_are_not_added_when_the_document_has_none` | 1.000 | 38 | 0 | 0 |  |
| `tests/test_fusion_payload.py::TestNormalizeElementIds::test_malformed_pages_are_kept_for_the_model_to_reject[None]` | `tests/test_fusion_payload.py::TestNormalizeElementIds::test_malformed_pages_are_kept_for_the_model_to_reject[not-a-list]` | 1.000 | 37 | 0 | 0 | yes |
| `tests/test_fusion_payload.py::TestNormalizeElementIds::test_malformed_pages_are_kept_for_the_model_to_reject[None]` | `tests/test_fusion_payload.py::TestNormalizeElementIds::test_malformed_pages_are_kept_for_the_model_to_reject[pages2]` | 1.000 | 37 | 0 | 0 | yes |
| `tests/test_fusion_payload.py::TestNormalizeElementIds::test_malformed_pages_are_kept_for_the_model_to_reject[not-a-list]` | `tests/test_fusion_payload.py::TestNormalizeElementIds::test_malformed_pages_are_kept_for_the_model_to_reject[pages2]` | 1.000 | 37 | 0 | 0 | yes |
| `tests/test_page_select.py::TestFuse::test_modo_swap_toma_o_texto_de_b` | `tests/test_page_select.py::TestFuse::test_modo_swap_troca_tabelas_quando_habilitado` | 1.000 | 37 | 0 | 0 |  |
| `tests/test_xycut.py::TestXYCutOrder::test_three_columns` | `tests/test_xycut.py::TestXYCutOrder::test_two_columns_read_left_column_first` | 1.000 | 37 | 0 | 0 |  |
| `tests/test_xycut.py::TestColumnBalance::test_dominant_main_column_counts_as_single_column` | `tests/test_xycut.py::TestReorder::test_multicol_keeps_single_column_pages` | 1.000 | 34 | 0 | 0 |  |
| `tests/test_fusion_payload.py::TestBlockConversionAndSignatures::test_group_payload_by_page_keeps_empty_structural_elements[formula]` | `tests/test_fusion_payload.py::TestBlockConversionAndSignatures::test_group_payload_by_page_keeps_empty_structural_elements[picture]` | 1.000 | 32 | 0 | 0 | yes |
| `tests/test_fusion_payload.py::TestBlockConversionAndSignatures::test_group_payload_by_page_keeps_empty_structural_elements[formula]` | `tests/test_fusion_payload.py::TestBlockConversionAndSignatures::test_group_payload_by_page_keeps_empty_structural_elements[table]` | 1.000 | 32 | 0 | 0 | yes |
| `tests/test_fusion_payload.py::TestBlockConversionAndSignatures::test_group_payload_by_page_keeps_empty_structural_elements[picture]` | `tests/test_fusion_payload.py::TestBlockConversionAndSignatures::test_group_payload_by_page_keeps_empty_structural_elements[table]` | 1.000 | 32 | 0 | 0 | yes |
| `tests/test_holdout.py::TestEvaluateCandidate::test_improvement_on_both_subsets_is_accepted` | `tests/test_holdout.py::TestEvaluateCandidate::test_metric_deltas_are_reported` | 1.000 | 32 | 0 | 0 |  |
| `tests/test_holdout.py::TestEvaluateCandidate::test_improvement_on_both_subsets_is_accepted` | `tests/test_holdout.py::TestMissingMetrics::test_metric_without_values_does_not_block_a_real_gain` | 1.000 | 32 | 0 | 0 |  |
| `tests/test_holdout.py::TestEvaluateCandidate::test_metric_deltas_are_reported` | `tests/test_holdout.py::TestMissingMetrics::test_metric_without_values_does_not_block_a_real_gain` | 1.000 | 32 | 0 | 0 |  |
| `tests/test_holdout.py::TestMissingMetrics::test_disjoint_metrics_reject_without_crashing` | `tests/test_holdout.py::TestMissingMetrics::test_metric_that_vanishes_in_the_candidate_is_rejected` | 1.000 | 31 | 0 | 0 |  |
| `tests/test_regions_letterhead.py::test_a_logo_and_its_lines_are_one_group_in_reading_order` | `tests/test_regions_letterhead.py::test_reading_order_ties_keep_the_given_order` | 1.000 | 30 | 0 | 0 |  |
| `tests/test_regions_letterhead.py::test_a_logo_and_its_lines_are_one_group_in_reading_order` | `tests/test_regions_letterhead.py::test_two_institutions_stay_apart` | 1.000 | 30 | 0 | 0 |  |
| `tests/test_regions_letterhead.py::test_reading_order_ties_keep_the_given_order` | `tests/test_regions_letterhead.py::test_two_institutions_stay_apart` | 1.000 | 30 | 0 | 0 |  |
| `tests/test_inline_math_placement.py::test_a_span_centre_within_the_tolerance_is_kept` | `tests/test_inline_math_placement.py::test_only_the_spans_centred_in_the_box_are_the_element_s_lines` | 1.000 | 28 | 0 | 0 |  |
| `tests/test_xycut.py::TestColumnBalance::test_equal_columns_are_balanced` | `tests/test_xycut.py::TestColumnBalance::test_sidebar_is_unbalanced` | 1.000 | 28 | 0 | 0 |  |
| `tests/test_xycut.py::TestXYCutOrder::test_inverted_axes_are_normalised` | `tests/test_xycut.py::TestXYCutOrder::test_single_column_is_top_down` | 1.000 | 28 | 0 | 0 |  |
| `tests/test_export_page_text.py::test_the_page_heading_is_the_marker_merge_broken_paragraphs_keeps[10]` | `tests/test_export_page_text.py::test_the_page_heading_is_the_marker_merge_broken_paragraphs_keeps[125]` | 1.000 | 27 | 0 | 0 | yes |
| `tests/test_export_page_text.py::test_the_page_heading_is_the_marker_merge_broken_paragraphs_keeps[10]` | `tests/test_export_page_text.py::test_the_page_heading_is_the_marker_merge_broken_paragraphs_keeps[1]` | 1.000 | 27 | 0 | 0 | yes |
| `tests/test_export_page_text.py::test_the_page_heading_is_the_marker_merge_broken_paragraphs_keeps[10]` | `tests/test_export_page_text.py::test_the_page_heading_is_the_marker_merge_broken_paragraphs_keeps[9]` | 1.000 | 27 | 0 | 0 | yes |
| `tests/test_export_page_text.py::test_the_page_heading_is_the_marker_merge_broken_paragraphs_keeps[125]` | `tests/test_export_page_text.py::test_the_page_heading_is_the_marker_merge_broken_paragraphs_keeps[1]` | 1.000 | 27 | 0 | 0 | yes |
| `tests/test_export_page_text.py::test_the_page_heading_is_the_marker_merge_broken_paragraphs_keeps[125]` | `tests/test_export_page_text.py::test_the_page_heading_is_the_marker_merge_broken_paragraphs_keeps[9]` | 1.000 | 27 | 0 | 0 | yes |
| `tests/test_export_page_text.py::test_the_page_heading_is_the_marker_merge_broken_paragraphs_keeps[1]` | `tests/test_export_page_text.py::test_the_page_heading_is_the_marker_merge_broken_paragraphs_keeps[9]` | 1.000 | 27 | 0 | 0 | yes |
| `tests/test_region_grouping_regressions.py::test_unknown_gaps_never_overlap_known_content[covered1]` | `tests/test_region_grouping_regressions.py::test_unknown_gaps_never_overlap_known_content[covered2]` | 1.000 | 26 | 0 | 0 | yes |
| `tests/test_legitimate_text.py::test_accepts_legitimate_prose[This is a legitimate body paragraph extracted from a document.]` | `tests/test_legitimate_text.py::test_respects_custom_min_quality_threshold` | 1.000 | 25 | 0 | 0 |  |
| `tests/test_table_inline_math_detection.py::test_a_cell_that_is_the_run_comes_first` | `tests/test_table_inline_math_detection.py::test_identical_cells_take_the_occurrences_in_order` | 1.000 | 24 | 0 | 0 |  |
| `tests/test_unicode_repair.py::TestProtectedContent::test_code_is_not_touched` | `tests/test_unicode_repair.py::TestProtectedContent::test_formula_is_not_touched` | 1.000 | 23 | 0 | 0 |  |
| `tests/test_metrics.py::TestOverall::test_missing_component_excluded_from_denominator` | `tests/test_metrics.py::TestOverall::test_overall_means_components` | 1.000 | 22 | 0 | 0 |  |
| `tests/test_verse.py::TestVerseBlocks::test_pedaco_unico_e_mantido` | `tests/test_verse.py::TestVerseBlocks::test_verso_real_fica_inteiro_no_modo_records` | 1.000 | 22 | 0 | 0 |  |
| `tests/test_oracle.py::TestOraclePage::test_differ_no_oraculo_nao_tem_folga` | `tests/test_oracle.py::TestOraclePage::test_oracle_escolhe_o_melhor_provider` | 1.000 | 21 | 0 | 0 |  |

### Parametrized families with identical coverage

| Family | Variants | Lines |
|---|---:|---:|
| `tests/test_code_controls.py::test_code_removes_forbidden_controls_and_preserves_literal_content` | 29 | 4 |
| `tests/test_prose_tabs.py::test_block_titles_only_normalize_tabs` | 20 | 59 |
| `tests/test_named_operators.py::test_the_domain_operator_gets_one_canonical_spelling` | 13 | 8 |
| `tests/test_export_walk.py::test_each_known_type_has_its_own_callback` | 11 | 17 |
| `tests/test_fusion_page_numbers.py::test_a_bare_page_number_needs_no_position` | 10 | 3 |
| `tests/test_placeholder_heuristics.py::test_any_text_element_with_content_makes_a_document_not_mostly_visual` | 7 | 14 |
| `tests/test_boxes.py::test_box_distance` | 5 | 3 |
| `tests/test_export_walk.py::test_unknown_types_use_only_the_explicit_fallback` | 5 | 17 |
| `tests/test_implicit_products.py::test_less_common_relations_alone_do_not_establish_variables` | 5 | 12 |
| `tests/test_inline_math_detection.py::test_math_fonts` | 5 | 2 |
| `tests/test_inline_math_placement.py::test_a_point_held_by_a_box_and_its_margin` | 5 | 3 |
| `tests/test_named_operators.py::test_the_domain_operator_is_spoken_in_portuguese` | 5 | 7 |
| `tests/test_prose_tabs.py::test_prose_collapses_tab_runs_without_changing_other_spacing` | 5 | 34 |
| `tests/test_schema_validation.py::test_non_none_validator_results_are_not_silently_accepted` | 5 | 247 |
| `tests/test_similarity.py::test_deduplication_preserves_different_values_even_with_long_shared_context` | 5 | 5 |
| `tests/test_table_cell_sanitize.py::test_table_ast_cell_keeps_leading_marker_before_number` | 5 | 121 |
| `tests/test_boxes.py::test_page_fractions_need_a_page_size` | 4 | 2 |
| `tests/test_export_page_text.py::test_the_page_heading_is_the_marker_merge_broken_paragraphs_keeps` | 4 | 27 |
| `tests/test_similarity.py::test_punctuation_differences_do_not_make_distinct_texts_identical` | 4 | 13 |
| `tests/test_best_effort_clip.py::test_a_non_finite_box_is_the_whole_page` | 3 | 5 |
| `tests/test_boxes.py::test_box_contains_center` | 3 | 3 |
| `tests/test_boxes.py::test_spans_horizontally` | 3 | 1 |
| `tests/test_equation_numbers.py::test_recognized_label_replaces_missing_or_invalid_metadata` | 3 | 23 |
| `tests/test_fusion_payload.py::TestBlockConversionAndSignatures::test_group_payload_by_page_keeps_empty_structural_elements` | 3 | 32 |
| `tests/test_fusion_payload.py::TestNormalizeElementIds::test_malformed_pages_are_kept_for_the_model_to_reject` | 3 | 37 |
| `tests/test_html_accessibility_regressions.py::test_deduplicated_callout_titles_do_not_reappear_as_note` | 3 | 133 |
| `tests/test_html_accessibility_regressions.py::test_uncaptioned_scroll_region_uses_a_short_generic_label` | 3 | 208 |
| `tests/test_placeholder_heuristics.py::test_a_placeholder_label_makes_a_paragraph_a_visual_placeholder` | 3 | 13 |
| `tests/test_schema_validation.py::test_schema_rejects_invalid_root_values` | 3 | 3 |
| `tests/test_export_page_text.py::test_an_image_reads_its_alt_text_or_the_default` | 2 | 9 |
| `tests/test_export_walk.py::test_empty_documents_have_no_events` | 2 | 3 |

### Tests with no exclusive line

These tests cover no line that another test in the same report does not also cover. They are the strongest overlap candidates, not a verdict: they can still be the only one checking a contract or an error message.

| Test | Lines |
|---|---:|
| `tests/test_equation_numbers.py::test_number_survives_canonical_and_all_export_boundaries` | 494 |
| `tests/test_fusion_payload.py::TestPageSimilarity::test_fuse_extraction_payloads_matches_bit_for_bit_without_rapidfuzz` | 491 |
| `tests/test_fusion_payload.py::TestFuseExtractionPayloads::test_empty_secondary_structural_element_routes_as_superset_when_text_agrees[picture]` | 477 |
| `tests/test_fusion_payload.py::TestFuseExtractionPayloads::test_empty_secondary_structural_element_routes_as_superset_when_text_agrees[formula]` | 470 |
| `tests/test_fusion_payload.py::TestFuseExtractionPayloads::test_empty_secondary_structural_element_routes_as_superset_when_text_agrees[table]` | 470 |
| `tests/test_fusion_payload.py::TestFuseExtractionPayloads::test_primary_only_structure_keeps_primary_without_divergence` | 463 |
| `tests/test_fusion_payload.py::TestFuseExtractionPayloads::test_fuses_multiple_pages_preserving_page_numbers_and_reading_order` | 459 |
| `tests/test_fusion_payload.py::TestFuseExtractionPayloads::test_near_empty_decide_v1_route_takes_precedence_over_superset` | 458 |
| `tests/test_export_characterization.py::test_export_matches_frozen_baseline[blocks-html.html]` | 431 |
| `tests/test_export_walk_parity.py::test_characterized_export_uses_shared_traversal_and_typed_dispatch[blocks-html.html]` | 431 |
| `tests/test_export_characterization.py::test_export_matches_frozen_baseline[blocks-html-docx.html]` | 428 |
| `tests/test_export_characterization.py::test_export_matches_frozen_baseline[blocks-html-pdf.html]` | 428 |
| `tests/test_export_characterization.py::test_export_matches_frozen_baseline[blocks-html-pdf_ua.html]` | 428 |
| `tests/test_export_walk_parity.py::test_characterized_export_uses_shared_traversal_and_typed_dispatch[blocks-html-docx.html]` | 428 |
| `tests/test_export_walk_parity.py::test_characterized_export_uses_shared_traversal_and_typed_dispatch[blocks-html-pdf.html]` | 428 |
| `tests/test_export_walk_parity.py::test_characterized_export_uses_shared_traversal_and_typed_dispatch[blocks-html-pdf_ua.html]` | 428 |
| `tests/test_export_characterization.py::test_export_matches_frozen_baseline[blocks-html-txt.html]` | 422 |
| `tests/test_export_characterization.py::test_export_matches_frozen_baseline[blocks-html-unrecognized.html]` | 422 |
| `tests/test_export_walk_parity.py::test_characterized_export_uses_shared_traversal_and_typed_dispatch[blocks-html-txt.html]` | 422 |
| `tests/test_export_walk_parity.py::test_characterized_export_uses_shared_traversal_and_typed_dispatch[blocks-html-unrecognized.html]` | 422 |
| `tests/test_pandoc_ast_degrade.py::test_degrade_math_to_text_all_indices_matches_full_degradation` | 418 |
| `tests/test_pandoc_ast_degrade.py::test_degrade_math_to_text_selective_preserves_other_formulas_and_alt_spans` | 412 |
| `tests/test_pandoc_ast_degrade.py::test_degrade_math_to_text_empty_indices_keeps_ast_equal` | 402 |
| `tests/test_table_cell_sanitize.py::test_txt_reads_the_negative_cell` | 399 |
| `tests/test_export_characterization.py::test_export_matches_frozen_baseline[blocks-pandoc-docx.json]` | 385 |
| `tests/test_export_characterization.py::test_export_matches_frozen_baseline[blocks-pandoc-pdf-ua.json]` | 385 |
| `tests/test_export_walk_parity.py::test_characterized_export_uses_shared_traversal_and_typed_dispatch[blocks-pandoc-docx.json]` | 385 |
| `tests/test_export_walk_parity.py::test_characterized_export_uses_shared_traversal_and_typed_dispatch[blocks-pandoc-pdf-ua.json]` | 385 |
| `tests/test_pandoc_ast_degrade.py::test_count_math_nodes_covers_all_block_types` | 376 |
| `tests/test_equation_numbers.py::test_the_pdf_ua_text_fallback_shows_the_label_not_the_tag` | 371 |
| `tests/test_pandoc_ast_degrade.py::test_unconverted_math_indices_requires_target_format` | 367 |
| `tests/test_xycut.py::TestMergeBlocksOption::test_decor_tail_stays_at_the_end` | 361 |
| `tests/test_equation_numbers.py::test_numbered_formula_without_speech_keeps_expression_in_accessible_label` | 328 |
| `tests/test_export_characterization.py::test_export_matches_frozen_baseline[blocks-txt-docx.txt]` | 319 |
| `tests/test_export_characterization.py::test_export_matches_frozen_baseline[blocks-txt-html.txt]` | 319 |
| `tests/test_export_characterization.py::test_export_matches_frozen_baseline[blocks-txt-pdf.txt]` | 319 |
| `tests/test_export_characterization.py::test_export_matches_frozen_baseline[blocks-txt-pdf_ua.txt]` | 319 |
| `tests/test_export_characterization.py::test_export_matches_frozen_baseline[blocks-txt-unrecognized.txt]` | 319 |
| `tests/test_export_characterization.py::test_export_matches_frozen_baseline[blocks-txt.txt]` | 319 |
| `tests/test_export_walk_parity.py::test_characterized_export_uses_shared_traversal_and_typed_dispatch[blocks-txt-docx.txt]` | 319 |
| `tests/test_export_walk_parity.py::test_characterized_export_uses_shared_traversal_and_typed_dispatch[blocks-txt-html.txt]` | 319 |
| `tests/test_export_walk_parity.py::test_characterized_export_uses_shared_traversal_and_typed_dispatch[blocks-txt-pdf.txt]` | 319 |
| `tests/test_export_walk_parity.py::test_characterized_export_uses_shared_traversal_and_typed_dispatch[blocks-txt-pdf_ua.txt]` | 319 |
| `tests/test_export_walk_parity.py::test_characterized_export_uses_shared_traversal_and_typed_dispatch[blocks-txt-unrecognized.txt]` | 319 |
| `tests/test_export_walk_parity.py::test_characterized_export_uses_shared_traversal_and_typed_dispatch[blocks-txt.txt]` | 319 |
| `tests/test_manifest_cases.py::test_a_case_changes_the_document_it_is_given` | 319 |
| `tests/test_xycut.py::TestMergeBlocksOption::test_multicol_restores_column_order` | 308 |
| `tests/test_html_accessibility_regressions.py::test_uncaptioned_table_uses_a_consumer_supplied_region_label[Private cell content-Tabela {number}-Tabela 1]` | 279 |
| `tests/test_html_accessibility_regressions.py::test_uncaptioned_table_uses_a_consumer_supplied_region_label[Private cell content-Tabela-Tabela]` | 279 |
| `tests/test_html_accessibility_regressions.py::test_uncaptioned_table_uses_a_consumer_supplied_region_label[Private cell content-Tableau n\xb0 {number} < & "-Tableau n\xb0 1 < & "]` | 279 |
| `tests/test_html_accessibility_regressions.py::test_uncaptioned_table_uses_a_consumer_supplied_region_label[-Tabela {number}-Tabela 1]` | 275 |
| `tests/test_html_accessibility_regressions.py::test_uncaptioned_table_uses_a_consumer_supplied_region_label[-Tabela-Tabela]` | 275 |
| `tests/test_html_accessibility_regressions.py::test_uncaptioned_table_uses_a_consumer_supplied_region_label[-Tableau n\xb0 {number} < & "-Tableau n\xb0 1 < & "]` | 275 |
| `tests/test_html_accessibility_regressions.py::test_caption_ids_do_not_collide_with_existing_ids` | 272 |
| `tests/test_html_accessibility_regressions.py::test_table_numbers_and_caption_references_follow_document_order` | 271 |
| `tests/test_html_accessibility_regressions.py::test_a_numbered_caption_id_does_not_collide_with_another_tables_caption_id` | 270 |
| `tests/test_fusion.py::TestMergeBlocks::test_match_exato` | 267 |
| `tests/test_equation_numbers.py::test_unnumbered_block_is_unchanged_without_an_enricher` | 265 |
| `tests/test_fusion.py::TestMergeBlocks::test_decor_tail` | 257 |
| `tests/test_fusion.py::TestMergeBlocks::test_stats_retornadas` | 256 |
| `tests/test_fusion.py::test_mega_block_does_not_merge_separate_paragraphs` | 256 |
| `tests/test_fusion.py::TestMergeBlocks::test_esqueleto_mineru` | 252 |
| `tests/test_html_accessibility_regressions.py::test_scroll_region_uses_available_caption_without_mutating_the_table[ast]` | 249 |
| `tests/test_html_accessibility_regressions.py::test_scroll_region_uses_available_caption_without_mutating_the_table[caption]` | 248 |
| `tests/test_html_accessibility_regressions.py::test_scroll_region_uses_available_caption_without_mutating_the_table[title]` | 248 |
| `tests/test_schema_validation.py::test_non_none_validator_results_are_not_silently_accepted[False]` | 247 |
| `tests/test_schema_validation.py::test_non_none_validator_results_are_not_silently_accepted[True]` | 247 |
| `tests/test_schema_validation.py::test_non_none_validator_results_are_not_silently_accepted[result2]` | 247 |
| `tests/test_schema_validation.py::test_non_none_validator_results_are_not_silently_accepted[result3]` | 247 |
| `tests/test_schema_validation.py::test_non_none_validator_results_are_not_silently_accepted[result4]` | 247 |
| `tests/test_schema_validation.py::test_builder_contract_includes_multiple_nested_sections` | 246 |
| `tests/test_schema_validation.py::test_package_resource_does_not_depend_on_the_working_directory` | 246 |
| `tests/test_schema_validation.py::test_pure_builder_output_conforms_without_enabling_runtime_validation[# Main\n\nBody.\n\n## Child\n\nChild text.\n\n### Leaf\n\nLeaf text.]` | 246 |
| `tests/test_schema_validation.py::test_injected_errors_propagate_without_fallback[error0]` | 245 |
| `tests/test_schema_validation.py::test_injected_errors_propagate_without_fallback[error1]` | 245 |
| `tests/test_schema_validation.py::test_local_refs_validate_grandchildren_and_preserve_error_paths[level-7]` | 245 |
| `tests/test_schema_validation.py::test_local_refs_validate_grandchildren_and_preserve_error_paths[type-custom]` | 245 |
| `tests/test_fusion.py::TestMergeBlocks::test_junk_filter` | 242 |
| `tests/test_fusion.py::test_short_noise_filter_preserves_structured_content[heading-B-# B-True]` | 239 |
| `tests/test_fusion.py::test_short_noise_filter_preserves_structured_content[formula-y-$$y$$-True]` | 237 |
| `tests/test_fusion.py::test_short_noise_filter_preserves_structured_content[table-Q-<table><tr><td>Q</td></tr></table>-True]` | 237 |
| `tests/test_inline_math_detection.py::test_splice_writes_each_run_where_the_text_aligns` | 236 |
| `tests/test_xycut.py::TestMergeBlocksOption::test_default_keeps_mineru_skeleton` | 232 |
| `tests/test_inline_math_detection.py::test_splice_finds_a_single_letter_by_alignment_not_by_search` | 230 |
| `tests/test_html_accessibility_regressions.py::test_ast_caption_has_precedence_over_block_title_and_caption` | 229 |
| `tests/test_prose_tabs.py::test_canonical_titles_only_normalize_tabs[# Heading-# Heading]` | 229 |
| `tests/test_prose_tabs.py::test_canonical_titles_only_normalize_tabs[**Bold** title-**Bold** title]` | 229 |
| `tests/test_prose_tabs.py::test_canonical_titles_only_normalize_tabs[**Bold**\t\ttitle-**Bold** title]` | 229 |
| `tests/test_prose_tabs.py::test_canonical_titles_only_normalize_tabs[1. Introduction-1. Introduction]` | 229 |
| `tests/test_prose_tabs.py::test_canonical_titles_only_normalize_tabs[1.\tIntroduction-1. Introduction]` | 229 |
| `tests/test_prose_tabs.py::test_canonical_titles_only_normalize_tabs[2) Methods-2) Methods]` | 229 |
| `tests/test_prose_tabs.py::test_canonical_titles_only_normalize_tabs[2) \t Methods-2) Methods]` | 229 |
| `tests/test_prose_tabs.py::test_canonical_titles_only_normalize_tabs[`Code` title-`Code` title]` | 229 |
| `tests/test_prose_tabs.py::test_canonical_titles_only_normalize_tabs[Title\t-Title]` | 228 |
| `tests/test_prose_tabs.py::test_canonical_titles_only_normalize_tabs[\tTitle-Title]` | 228 |
| `tests/test_table_inline_math_detection.py::test_the_table_lines_give_each_cells_math` | 228 |
| `tests/test_manifest_cases.py::test_a_broken_case_breaks_exactly_its_rule[child parent reference disagrees with parent source reference-deeper hierarchy]` | 226 |
| `tests/test_manifest_cases.py::test_a_broken_case_breaks_exactly_its_rule[child parent reference disagrees with parent source reference-example]` | 226 |
| `tests/test_manifest_cases.py::test_a_broken_case_breaks_exactly_its_rule[child parent reference disagrees with parent source reference-one page]` | 226 |
| `tests/test_manifest_cases.py::test_a_broken_case_breaks_exactly_its_rule[child parent reference disagrees with parent source reference-flat]` | 225 |
