## Redundancy candidates (#644)

100 overlapping pairs; 1250 coverage-subset relations in total (showing 42 examples worth about 9.35s); 3085 tests without an exclusive production line (showing 100).

This is a review sheet, not a deletion list. "Coverage-subset" means only that the other test covers every measured line of the candidate; contracts, diagnostics and failure modes still have to be checked by hand. The candidate list is a presentation sample, not the complete relation set.

| Candidate | Covered by | Tests | Similarity | Shared | Seconds | Classification |
|---|---|---:|---:|---:|---:|---|
| `tests/test_long_output_filenames.py::test_long_filename_can_be_exported_and_downloaded[long-ascii]` | `tests/test_long_output_filenames.py::test_long_filename_can_be_exported_and_downloaded[long-cjk]` | 3 | 1.000 | 605 | 1.875 | identical-parameterization |
| `tests/test_pending_fixes.py::test_failed_enqueue_removes_durable_request_and_upload[persist_before]` | `tests/test_pending_fixes.py::test_failed_enqueue_removes_durable_request_and_upload[persist_after]` | 1 | 0.969 | 154 | 0.508 | identical-parameterization |
| `tests/test_trilha_a_regressions.py::test_pddl_recovery_policy_controls_real_cache_replay[completed-normalize-text-False-2]` | `tests/test_trilha_a_regressions.py::test_pddl_recovery_policy_controls_real_cache_replay[completed-recover-formula-True-2]` | 4 | 1.000 | 390 | 0.427 | identical-parameterization |
| `tests/test_pending_fixes.py::test_failed_enqueue_removes_durable_request_and_upload[persist_after]` | `tests/test_pending_fixes.py::test_failed_enqueue_removes_durable_request_and_upload[enqueue]` | 1 | 0.994 | 159 | 0.374 | identical-parameterization |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-sent-False-False]` | `tests/test_web_panel.py::test_receipt_recovers_result_after_refresh[sent]` | 2 | 1.000 | 189 | 0.367 | identical-coverage |
| `tests/test_untitled_document_name.py::test_api_keeps_only_the_uploaded_basename[../../etc/relat\xf3rio.pdf]` | `tests/test_untitled_document_name.py::test_api_keeps_only_the_uploaded_basename[..\\..\\etc\\relat\xf3rio.pdf]` | 3 | 1.000 | 177 | 0.334 | identical-parameterization |
| `tests/test_telegram_client.py::test_document_flow_sends_download_link[False]` | `tests/test_telegram_client.py::test_document_flow_sends_download_link[True]` | 1 | 0.968 | 299 | 0.333 | identical-parameterization |
| `tests/test_api.py::test_job_executor_marks_history_error_when_export_fails[txt]` | `tests/test_api.py::test_job_executor_marks_history_error_when_export_fails[html]` | 1 | 0.981 | 314 | 0.322 | identical-parameterization |
| `tests/test_api.py::test_job_executor_reports_optional_export_failure[None]` | `tests/test_api.py::test_job_executor_reports_optional_export_failure[DOCX disabled]` | 1 | 0.995 | 398 | 0.317 | identical-parameterization |
| `tests/test_trilha_a_regressions.py::test_pddl_recovery_policy_controls_real_cache_replay[completed-normalize-text-True-1]` | `tests/test_trilha_a_regressions.py::test_pddl_recovery_policy_controls_real_cache_replay[completed-normalize-text-False-2]` | 1 | 0.985 | 384 | 0.308 | identical-parameterization |
| `tests/test_object_markers.py::test_a_job_can_ask_for_markers_through_the_api[None-None]` | `tests/test_object_markers.py::test_a_job_can_ask_for_markers_through_the_api[false-False]` | 5 | 1.000 | 175 | 0.300 | identical-parameterization |
| `tests/test_untitled_document_name.py::test_a_client_path_in_the_uploaded_name_is_reduced_to_the_name[../../etc/relat\xf3rio.pdf]` | `tests/test_untitled_document_name.py::test_a_client_path_in_the_uploaded_name_is_reduced_to_the_name[..\\..\\etc\\relat\xf3rio.pdf]` | 6 | 1.000 | 274 | 0.293 | identical-parameterization |
| `tests/test_pending_fixes.py::test_email_delivery_status_does_not_lose_download[False]` | `tests/test_pending_fixes.py::test_email_delivery_status_does_not_lose_download[None]` | 1 | 0.993 | 455 | 0.281 | identical-parameterization |
| `tests/test_telegram_upload_paths.py::test_telegram_download_uses_generated_contained_filename[../victim.pdf-handler]` | `tests/test_telegram_upload_paths.py::test_telegram_download_uses_generated_contained_filename[..\\victim.pdf-handler]` | 5 | 1.000 | 150 | 0.278 | identical-parameterization |
| `tests/test_telegram_client.py::test_document_does_not_consume_another_senders_preferences` | `tests/test_telegram_client.py::test_document_submits_with_mode_and_source` | 2 | 1.000 | 293 | 0.185 | identical-coverage |
| `tests/test_model_call_executor.py::test_sync_call_returns_while_provider_stays_blocked[data-False]` | `tests/test_structured_agent_outputs.py::test_a_hung_model_call_is_abandoned_at_the_deadline` | 1 | 0.987 | 154 | 0.179 | coverage-subset |
| `tests/test_object_markers.py::test_the_worker_marks_what_a_reader_gets_and_stores_the_document_unmarked` | `tests/test_pending_fixes.py::test_email_delivery_status_does_not_lose_download[True]` | 1 | 0.965 | 438 | 0.177 | coverage-subset |
| `tests/test_pending_fixes.py::test_email_delivery_status_does_not_lose_download[True]` | `tests/test_pending_fixes.py::test_result_email_reports_open_obligations_of_a_delivered_document` | 2 | 1.000 | 454 | 0.171 | identical-coverage |
| `tests/test_telegram_client.py::test_document_passes_email_and_notifies` | `tests/test_telegram_client.py::test_document_flow_sends_the_download_link_in_the_user_locale` | 1 | 0.967 | 295 | 0.164 | coverage-subset |
| `tests/test_pending_fixes.py::test_submission_cancellation_does_not_leave_durable_request` | `tests/test_pending_fixes.py::test_failed_enqueue_removes_durable_request_and_upload[persist_after]` | 1 | 0.962 | 153 | 0.155 | coverage-subset |
| `tests/test_telegram_client.py::test_pdf_ua_warning_survives_worker_and_user_locales_differing[en_US-pt_BR]` | `tests/test_telegram_client.py::test_pdf_ua_warning_survives_worker_and_user_locales_differing[pt_BR-en_US]` | 2 | 1.000 | 303 | 0.151 | identical-parameterization |
| `tests/test_v2_security.py::test_valid_or_optional_recipient_is_accepted[ reader@example.test ]` | `tests/test_v2_security.py::test_valid_or_optional_recipient_is_accepted[reader+tag@example.test]` | 3 | 1.000 | 179 | 0.151 | identical-parameterization |
| `tests/test_model_call_executor.py::test_sync_call_returns_while_provider_stays_blocked[page-handler-False]` | `tests/test_model_call_executor.py::test_sync_call_returns_while_provider_stays_blocked[page-handler-True]` | 5 | 1.000 | 157 | 0.145 | identical-parameterization |
| `tests/test_api.py::test_job_executor_keeps_original_filename_in_status` | `tests/test_api.py::test_job_executor_reports_optional_export_failure[None]` | 1 | 0.960 | 382 | 0.135 | coverage-subset |
| `tests/test_untitled_document_name.py::test_the_processing_cache_is_keyed_by_the_job_config` | `tests/test_untitled_document_name.py::test_without_an_uploaded_name_the_file_name_is_still_the_fallback` | 2 | 1.000 | 275 | 0.131 | identical-coverage |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxDatasetClient-budgets]` | `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxDatasetClient-defaults]` | 24 | 1.000 | 273 | 0.129 | identical-parameterization |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[cancelled-None-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[error-None-False-False]` | 2 | 1.000 | 185 | 0.121 | identical-parameterization |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-failed-False-False]` | `tests/test_web_panel.py::test_receipt_recovers_result_after_refresh[failed]` | 2 | 1.000 | 189 | 0.114 | identical-coverage |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-pending-True-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-None-True-False]` | 4 | 1.000 | 184 | 0.107 | identical-parameterization |
| `tests/test_untitled_document_name.py::test_the_canonical_build_takes_the_job_toolbox_config[cache-hit]` | `tests/test_untitled_document_name.py::test_untitled_document_takes_the_uploaded_name[cache-hit]` | 2 | 1.000 | 224 | 0.100 | identical-coverage |
| `tests/test_pddl_cache_contract.py::test_degraded_processing_is_not_cached[True]` | `tests/test_pddl_cache_contract.py::test_cached_entry_with_failed_media_inspection_is_ignored` | 1 | 0.960 | 285 | 0.095 | coverage-subset |
| `tests/test_pddl_cache_contract.py::test_cached_entry_with_failed_media_inspection_is_ignored` | `tests/test_pddl_cache_contract.py::test_cached_degraded_entry_is_ignored[visual-failures-clean-rerun]` | 1 | 0.987 | 297 | 0.089 | coverage-subset |
| `tests/test_pddl_cache_contract.py::test_cached_degraded_entry_is_ignored[visual-failures-clean-rerun]` | `tests/test_pddl_cache_contract.py::test_cached_degraded_entry_is_ignored[single-provider-extraction-clean-rerun]` | 1 | 0.997 | 301 | 0.077 | identical-parameterization |
| `tests/test_pddl_cache_contract.py::test_live_processing_rejects_incompatible_cached_execution[failed]` | `tests/test_pddl_cache_contract.py::test_live_processing_rejects_incompatible_cached_execution[replan-required]` | 2 | 1.000 | 286 | 0.075 | identical-parameterization |
| `tests/test_pddl_cache_contract.py::test_cached_degraded_entry_is_ignored[visual-failures-degraded-rerun]` | `tests/test_pddl_cache_contract.py::test_cached_degraded_entry_is_ignored[single-provider-extraction-degraded-rerun]` | 1 | 0.997 | 302 | 0.071 | identical-parameterization |
| `tests/test_structured_agent_outputs.py::test_an_agent_without_the_region_cache_neither_reads_nor_writes_it` | `tests/test_structured_agent_outputs.py::test_an_identical_region_reuses_the_cached_description` | 1 | 0.962 | 177 | 0.070 | coverage-subset |
| `tests/test_remote_cancellation.py::test_cancel_summarizes_each_outcome[result0-requested]` | `tests/test_remote_cancellation.py::test_cancel_summarizes_each_outcome[result1-requested]` | 2 | 1.000 | 168 | 0.062 | identical-parameterization |
| `tests/test_docx_export.py::test_toolbox_docx_enabled_is_parsed_from_the_environment[0-False]` | `tests/test_docx_export.py::test_toolbox_docx_enabled_is_parsed_from_the_environment[None-True]` | 23 | 1.000 | 212 | 0.047 | identical-parameterization |
| `tests/test_remote_cancellation.py::test_cancel_summarizes_each_outcome[result4-failed]` | `tests/test_remote_cancellation.py::test_a_failure_is_not_hidden_by_another_operation` | 1 | 0.965 | 167 | 0.040 | coverage-subset |
| `tests/test_settings_runtime_providers.py::test_provider_environment_is_read_at_instantiation[fusion_hybrid_provider-FUSION_HYBRID_PROVIDER-mineru-hyb]` | `tests/test_settings_runtime_providers.py::test_provider_environment_is_read_at_instantiation[toolbox_adjudicate_provider-TOOLBOX_ADJUDICATE_PROVIDER-qwen3-vl-8b]` | 4 | 1.000 | 203 | 0.035 | identical-parameterization |
| `tests/test_slides.py::test_a_slide_visual_coverage_out_of_range_is_refused_at_startup[-0.1]` | `tests/test_slides.py::test_a_slide_visual_coverage_out_of_range_is_refused_at_startup[0]` | 3 | 1.000 | 212 | 0.029 | identical-parameterization |
| `tests/test_page_limit.py::test_a_non_positive_max_pages_is_refused_at_startup[-1]` | `tests/test_page_limit.py::test_a_non_positive_max_pages_is_refused_at_startup[0]` | 2 | 1.000 | 206 | 0.028 | identical-parameterization |

### Tests with no exclusive production line (examples)

Every measured line of these tests is also covered by another test. Coverage omits the test files themselves, so this does not say the assertions are redundant; it is the shortlist for the mutation experiment, where equal coverage can hide different detection.

| Test | Lines | Seconds |
|---|---:|---:|
| `tests/test_long_output_filenames.py::test_long_filename_can_be_exported_and_downloaded[long-ascii]` | 605 | 1.875 |
| `tests/test_cancellation_queue.py::test_cancelled_extraction_advances_queue_and_reports_wait` | 571 | 0.915 |
| `tests/test_trilha_a_regressions.py::test_pddl_recovery_policy_controls_real_cache_replay[replan-required-None-False-2]` | 390 | 0.687 |
| `tests/test_trilha_a_regressions.py::test_pddl_recovery_policy_controls_real_cache_replay[completed-recover-formula-True-2]` | 390 | 0.651 |
| `tests/test_long_output_filenames.py::test_long_filename_can_be_exported_and_downloaded[short]` | 599 | 0.569 |
| `tests/test_pddl_audit_fixes.py::test_failed_plan_marks_api_job_error_without_caching_or_download` | 426 | 0.448 |
| `tests/test_trilha_a_regressions.py::test_pddl_recovery_policy_controls_real_cache_replay[completed-normalize-text-False-2]` | 390 | 0.427 |
| `tests/test_pending_fixes.py::test_active_cancel_interrupts_pipeline_and_advances_queue` | 394 | 0.381 |
| `tests/test_long_output_filenames.py::test_long_filename_can_be_exported_and_downloaded[long-cjk]` | 605 | 0.376 |
| `tests/test_long_output_filenames.py::test_long_filename_can_be_exported_and_downloaded[long-greek]` | 605 | 0.357 |
| `tests/test_telegram_client.py::test_document_flow_sends_download_link[False]` | 299 | 0.333 |
| `tests/test_api.py::test_job_executor_marks_history_error_when_export_fails[txt]` | 314 | 0.322 |
| `tests/test_api.py::test_job_executor_reports_optional_export_failure[None]` | 398 | 0.317 |
| `tests/test_trilha_a_regressions.py::test_pddl_recovery_policy_controls_real_cache_replay[completed-normalize-text-True-1]` | 384 | 0.308 |
| `tests/test_trilha_a_regressions.py::test_pddl_recovery_policy_controls_real_cache_replay[completed-None-False-1]` | 380 | 0.295 |
| `tests/test_untitled_document_name.py::test_a_client_path_in_the_uploaded_name_is_reduced_to_the_name[../../etc/relat\xf3rio.pdf]` | 274 | 0.293 |
| `tests/test_trilha_a_regressions.py::test_pddl_recovery_policy_controls_real_cache_replay[failed-None-False-2]` | 390 | 0.285 |
| `tests/test_pending_fixes.py::test_email_delivery_status_does_not_lose_download[False]` | 455 | 0.281 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxStructureClient-provider]` | 273 | 0.266 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxDatasetClient-endpoints list wins]` | 273 | 0.264 |
| `tests/test_api.py::test_job_executor_marks_history_error_when_export_fails[html]` | 320 | 0.257 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxStructureClient-single endpoint]` | 273 | 0.249 |
| `tests/test_telegram_client.py::test_document_flow_sends_the_download_link_in_the_user_locale` | 305 | 0.246 |
| `tests/test_telegram_client.py::test_document_flow_sends_download_link[True]` | 309 | 0.240 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxStructureClient-endpoints list wins]` | 273 | 0.239 |
| `tests/test_api.py::test_job_executor_records_early_process_failure` | 277 | 0.233 |
| `tests/test_job_progress.py::test_a_broken_failure_email_keeps_the_job_error_and_records_the_failure` | 429 | 0.200 |
| `tests/test_worker_pipeline_failure.py::test_job_executor_does_not_export_pipeline_failure` | 403 | 0.200 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxMathClient-endpoints list wins]` | 273 | 0.199 |
| `tests/test_api.py::test_job_executor_marks_history_error_when_export_fails[zip]` | 378 | 0.198 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxPdfClient-endpoints list wins]` | 273 | 0.198 |
| `tests/test_pending_fixes.py::test_result_email_reports_open_obligations_of_a_delivered_document` | 454 | 0.194 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxStructureClient-empty provider]` | 273 | 0.189 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxMathClient-defaults]` | 273 | 0.186 |
| `tests/test_telegram_client.py::test_document_does_not_consume_another_senders_preferences` | 293 | 0.185 |
| `tests/test_object_markers.py::test_the_worker_marks_what_a_reader_gets_and_stores_the_document_unmarked` | 438 | 0.177 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxDatasetClient-single endpoint]` | 273 | 0.177 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxMathClient-empty provider]` | 273 | 0.173 |
| `tests/test_job_progress.py::test_pipeline_failure_names_the_stage_once_and_emails_the_user` | 417 | 0.172 |
| `tests/test_pending_fixes.py::test_email_delivery_status_does_not_lose_download[True]` | 454 | 0.171 |
| `tests/test_telegram_client.py::test_document_submits_with_mode_and_source` | 293 | 0.169 |
| `tests/test_untitled_document_name.py::test_a_client_path_in_the_uploaded_name_is_reduced_to_the_name[C:\\fakepath\\relat\xf3rio.pdf]` | 274 | 0.167 |
| `tests/test_telegram_client.py::test_document_passes_email_and_notifies` | 295 | 0.164 |
| `tests/test_telegram_client.py::test_pdf_ua_warning_survives_worker_and_user_locales_differing[pt_BR-en_US]` | 303 | 0.154 |
| `tests/test_untitled_document_name.py::test_without_an_uploaded_name_the_file_name_is_still_the_fallback` | 275 | 0.152 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxDatasetClient-defaults]` | 273 | 0.152 |
| `tests/test_telegram_client.py::test_pdf_ua_warning_survives_worker_and_user_locales_differing[en_US-pt_BR]` | 303 | 0.151 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxStructureClient-budgets]` | 273 | 0.145 |
| `tests/test_untitled_document_name.py::test_a_client_path_in_the_uploaded_name_is_reduced_to_the_name[..\\..\\etc\\relat\xf3rio.pdf]` | 274 | 0.139 |
| `tests/test_api.py::test_job_executor_keeps_original_filename_in_status` | 382 | 0.135 |
| `tests/test_untitled_document_name.py::test_the_processing_cache_is_keyed_by_the_job_config` | 275 | 0.131 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxDatasetClient-budgets]` | 273 | 0.129 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxPdfClient-defaults]` | 273 | 0.129 |
| `tests/test_untitled_document_name.py::test_a_client_path_in_the_uploaded_name_is_reduced_to_the_name[..\\etc/relat\xf3rio.pdf]` | 274 | 0.127 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxDatasetClient-empty provider]` | 273 | 0.127 |
| `tests/test_job_resume.py::test_a_resumed_run_restores_progress_and_skips_the_confirmation` | 290 | 0.123 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxStructureClient-defaults]` | 273 | 0.122 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxPdfClient-provider]` | 273 | 0.121 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxPdfClient-single endpoint]` | 273 | 0.120 |
| `tests/test_untitled_document_name.py::test_the_canonical_build_takes_the_job_toolbox_config[processed]` | 274 | 0.118 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxMathClient-budgets]` | 273 | 0.115 |
| `tests/test_untitled_document_name.py::test_untitled_document_takes_the_uploaded_name[processed]` | 274 | 0.112 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxDatasetClient-provider]` | 273 | 0.112 |
| `tests/test_telegram_client.py::test_concurrent_group_users_keep_preferences_and_tasks_isolated` | 293 | 0.111 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxPdfClient-budgets]` | 273 | 0.111 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxPdfClient-empty provider]` | 273 | 0.110 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxMathClient-provider]` | 273 | 0.104 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxMathClient-single endpoint]` | 273 | 0.102 |
| `tests/test_api.py::test_job_executor_reports_optional_export_failure[MP3]` | 408 | 0.100 |
| `tests/test_untitled_document_name.py::test_the_canonical_build_takes_the_job_toolbox_config[cache-hit]` | 224 | 0.100 |
| `tests/test_api.py::test_job_executor_reports_optional_export_failure[DOCX]` | 410 | 0.098 |
| `tests/test_api.py::test_job_executor_reports_optional_export_failure[DOCX disabled]` | 400 | 0.096 |
| `tests/test_pddl_cache_contract.py::test_degraded_processing_is_not_cached[True]` | 285 | 0.095 |
| `tests/test_api.py::test_job_executor_reports_optional_export_failure[PDF/UA disabled]` | 387 | 0.094 |
| `tests/test_pddl_cache_contract.py::test_degraded_processing_is_not_cached[False]` | 299 | 0.090 |
| `tests/test_pddl_cache_contract.py::test_cached_entry_with_failed_media_inspection_is_ignored` | 297 | 0.089 |
| `tests/test_untitled_document_name.py::test_untitled_document_takes_the_uploaded_name[cache-hit]` | 224 | 0.088 |
| `tests/test_api.py::test_job_executor_reports_optional_export_failure[PDF/UA]` | 397 | 0.086 |
| `tests/test_api.py::test_cancel_reports_a_requested_remote_cancellation` | 267 | 0.083 |
| `tests/test_pddl_cache_contract.py::test_cached_degraded_entry_is_ignored[single-provider-extraction-degraded-rerun]` | 303 | 0.082 |
| `tests/test_pddl_cache_contract.py::test_cached_degraded_entry_is_ignored[single-provider-extraction-clean-rerun]` | 302 | 0.080 |
| `tests/test_pddl_cache_contract.py::test_cached_degraded_entry_is_ignored[visual-failures-clean-rerun]` | 301 | 0.077 |
| `tests/test_pddl_cache_contract.py::test_live_processing_rejects_incompatible_cached_execution[failed]` | 286 | 0.075 |
| `tests/test_pddl_cache_contract.py::test_live_processing_rejects_incompatible_cached_execution[dry-run-completed]` | 287 | 0.074 |
| `tests/test_pddl_cache_contract.py::test_live_processing_rejects_incompatible_cached_execution[replan-required]` | 286 | 0.073 |
| `tests/test_pddl_cache_contract.py::test_cached_degraded_entry_is_ignored[visual-failures-degraded-rerun]` | 302 | 0.071 |
| `tests/test_job_resume.py::test_a_graceful_shutdown_keeps_the_operation_journal` | 267 | 0.056 |
| `tests/test_i18n_locales.py::test_settings_defaults_to_the_supported_locales` | 212 | 0.052 |
| `tests/test_docx_export.py::test_toolbox_docx_enabled_is_parsed_from_the_environment[0-False]` | 212 | 0.047 |
| `tests/test_object_markers.py::test_markers_are_off_by_default` | 212 | 0.045 |
| `tests/test_docx_export.py::test_toolbox_docx_enabled_is_parsed_from_the_environment[SIM-True]` | 212 | 0.042 |
| `tests/test_page_limit.py::test_max_pages_is_read_from_the_environment` | 212 | 0.042 |
| `tests/test_docx_export.py::test_toolbox_docx_enabled_is_parsed_from_the_environment[false-False]` | 212 | 0.041 |
| `tests/test_i18n_locales.py::test_settings_reads_i18n_locales_active_with_the_shared_parser` | 212 | 0.039 |
| `tests/test_pdf_ua_export.py::test_toolbox_pdf_ua_enabled_is_parsed_from_the_environment[None-True]` | 212 | 0.038 |
| `tests/test_docx_export.py::test_toolbox_docx_enabled_is_parsed_from_the_environment[true-True]` | 212 | 0.037 |
| `tests/test_docx_export.py::test_toolbox_docx_enabled_is_parsed_from_the_environment[None-True]` | 212 | 0.034 |
| `tests/test_pdf_ua_export.py::test_toolbox_pdf_ua_enabled_is_parsed_from_the_environment[0-False]` | 212 | 0.034 |
| `tests/test_pdf_ua_export.py::test_toolbox_pdf_ua_enabled_is_parsed_from_the_environment[1-True]` | 212 | 0.032 |
| `tests/test_pdf_ua_export.py::test_toolbox_pdf_ua_enabled_is_parsed_from_the_environment[SIM-True]` | 212 | 0.031 |

### Reviewed pairs

| Test A | Test B | Similarity | Shared | Only A | Only B | Classification |
|---|---|---:|---:|---:|---:|---|
| `tests/test_long_output_filenames.py::test_long_filename_can_be_exported_and_downloaded[long-ascii]` | `tests/test_long_output_filenames.py::test_long_filename_can_be_exported_and_downloaded[long-cjk]` | 1.000 | 605 | 0 | 0 | identical-parameterization |
| `tests/test_long_output_filenames.py::test_long_filename_can_be_exported_and_downloaded[long-ascii]` | `tests/test_long_output_filenames.py::test_long_filename_can_be_exported_and_downloaded[long-greek]` | 1.000 | 605 | 0 | 0 | identical-parameterization |
| `tests/test_long_output_filenames.py::test_long_filename_can_be_exported_and_downloaded[long-cjk]` | `tests/test_long_output_filenames.py::test_long_filename_can_be_exported_and_downloaded[long-greek]` | 1.000 | 605 | 0 | 0 | identical-parameterization |
| `tests/test_model_call_executor.py::test_sync_call_returns_while_provider_stays_blocked[page-handler-False]` | `tests/test_model_call_executor.py::test_sync_call_returns_while_provider_stays_blocked[page-handler-True]` | 1.000 | 157 | 0 | 0 | identical-parameterization |
| `tests/test_model_call_executor.py::test_sync_call_returns_while_provider_stays_blocked[page-handler-False]` | `tests/test_model_call_executor.py::test_sync_call_returns_while_provider_stays_blocked[region-handler-False]` | 1.000 | 157 | 0 | 0 | identical-parameterization |
| `tests/test_model_call_executor.py::test_sync_call_returns_while_provider_stays_blocked[page-handler-False]` | `tests/test_model_call_executor.py::test_sync_call_returns_while_provider_stays_blocked[region-handler-True]` | 1.000 | 157 | 0 | 0 | identical-parameterization |
| `tests/test_model_call_executor.py::test_sync_call_returns_while_provider_stays_blocked[page-handler-False]` | `tests/test_model_call_executor.py::test_sync_call_returns_while_provider_stays_blocked[vision-False]` | 1.000 | 157 | 0 | 0 | identical-parameterization |
| `tests/test_model_call_executor.py::test_sync_call_returns_while_provider_stays_blocked[page-handler-True]` | `tests/test_model_call_executor.py::test_sync_call_returns_while_provider_stays_blocked[region-handler-False]` | 1.000 | 157 | 0 | 0 | identical-parameterization |
| `tests/test_model_call_executor.py::test_sync_call_returns_while_provider_stays_blocked[page-handler-True]` | `tests/test_model_call_executor.py::test_sync_call_returns_while_provider_stays_blocked[region-handler-True]` | 1.000 | 157 | 0 | 0 | identical-parameterization |
| `tests/test_model_call_executor.py::test_sync_call_returns_while_provider_stays_blocked[page-handler-True]` | `tests/test_model_call_executor.py::test_sync_call_returns_while_provider_stays_blocked[vision-False]` | 1.000 | 157 | 0 | 0 | identical-parameterization |
| `tests/test_model_call_executor.py::test_sync_call_returns_while_provider_stays_blocked[region-handler-False]` | `tests/test_model_call_executor.py::test_sync_call_returns_while_provider_stays_blocked[region-handler-True]` | 1.000 | 157 | 0 | 0 | identical-parameterization |
| `tests/test_model_call_executor.py::test_sync_call_returns_while_provider_stays_blocked[region-handler-False]` | `tests/test_model_call_executor.py::test_sync_call_returns_while_provider_stays_blocked[vision-False]` | 1.000 | 157 | 0 | 0 | identical-parameterization |
| `tests/test_model_call_executor.py::test_sync_call_returns_while_provider_stays_blocked[region-handler-True]` | `tests/test_model_call_executor.py::test_sync_call_returns_while_provider_stays_blocked[vision-False]` | 1.000 | 157 | 0 | 0 | identical-parameterization |
| `tests/test_object_markers.py::test_a_job_can_ask_for_markers_through_the_api[None-None]` | `tests/test_object_markers.py::test_a_job_can_ask_for_markers_through_the_api[false-False]` | 1.000 | 175 | 0 | 0 | identical-parameterization |
| `tests/test_object_markers.py::test_a_job_can_ask_for_markers_through_the_api[None-None]` | `tests/test_object_markers.py::test_a_job_can_ask_for_markers_through_the_api[true-True]` | 1.000 | 175 | 0 | 0 | identical-parameterization |
| `tests/test_object_markers.py::test_a_job_can_ask_for_markers_through_the_api[None-None]` | `tests/test_v2_security.py::test_valid_or_optional_recipient_is_accepted[   ]` | 1.000 | 175 | 0 | 0 | near-identical |
| `tests/test_object_markers.py::test_a_job_can_ask_for_markers_through_the_api[None-None]` | `tests/test_v2_security.py::test_valid_or_optional_recipient_is_accepted[]` | 1.000 | 175 | 0 | 0 | near-identical |
| `tests/test_object_markers.py::test_a_job_can_ask_for_markers_through_the_api[false-False]` | `tests/test_object_markers.py::test_a_job_can_ask_for_markers_through_the_api[true-True]` | 1.000 | 175 | 0 | 0 | identical-parameterization |
| `tests/test_object_markers.py::test_a_job_can_ask_for_markers_through_the_api[false-False]` | `tests/test_v2_security.py::test_valid_or_optional_recipient_is_accepted[   ]` | 1.000 | 175 | 0 | 0 | near-identical |
| `tests/test_object_markers.py::test_a_job_can_ask_for_markers_through_the_api[false-False]` | `tests/test_v2_security.py::test_valid_or_optional_recipient_is_accepted[]` | 1.000 | 175 | 0 | 0 | near-identical |
| `tests/test_object_markers.py::test_a_job_can_ask_for_markers_through_the_api[true-True]` | `tests/test_v2_security.py::test_valid_or_optional_recipient_is_accepted[   ]` | 1.000 | 175 | 0 | 0 | near-identical |
| `tests/test_object_markers.py::test_a_job_can_ask_for_markers_through_the_api[true-True]` | `tests/test_v2_security.py::test_valid_or_optional_recipient_is_accepted[]` | 1.000 | 175 | 0 | 0 | near-identical |
| `tests/test_page_limit.py::test_a_non_positive_max_pages_is_refused_at_startup[-1]` | `tests/test_page_limit.py::test_a_non_positive_max_pages_is_refused_at_startup[0]` | 1.000 | 206 | 0 | 0 | identical-parameterization |
| `tests/test_pddl_cache_contract.py::test_live_processing_rejects_incompatible_cached_execution[failed]` | `tests/test_pddl_cache_contract.py::test_live_processing_rejects_incompatible_cached_execution[replan-required]` | 1.000 | 286 | 0 | 0 | identical-parameterization |
| `tests/test_pending_fixes.py::test_email_delivery_status_does_not_lose_download[True]` | `tests/test_pending_fixes.py::test_result_email_reports_open_obligations_of_a_delivered_document` | 1.000 | 454 | 0 | 0 | near-identical |
| `tests/test_remote_cancellation.py::test_cancel_summarizes_each_outcome[result0-requested]` | `tests/test_remote_cancellation.py::test_cancel_summarizes_each_outcome[result1-requested]` | 1.000 | 168 | 0 | 0 | identical-parameterization |
| `tests/test_slides.py::test_a_slide_visual_coverage_out_of_range_is_refused_at_startup[-0.1]` | `tests/test_slides.py::test_a_slide_visual_coverage_out_of_range_is_refused_at_startup[0]` | 1.000 | 212 | 0 | 0 | identical-parameterization |
| `tests/test_slides.py::test_a_slide_visual_coverage_out_of_range_is_refused_at_startup[-0.1]` | `tests/test_slides.py::test_a_slide_visual_coverage_out_of_range_is_refused_at_startup[1.5]` | 1.000 | 212 | 0 | 0 | identical-parameterization |
| `tests/test_slides.py::test_a_slide_visual_coverage_out_of_range_is_refused_at_startup[0]` | `tests/test_slides.py::test_a_slide_visual_coverage_out_of_range_is_refused_at_startup[1.5]` | 1.000 | 212 | 0 | 0 | identical-parameterization |
| `tests/test_structured_agent_outputs.py::test_a_call_that_keeps_timing_out_reports_the_error` | `tests/test_structured_agent_outputs.py::test_a_provider_timeout_is_not_rewritten_as_the_deadline` | 1.000 | 139 | 0 | 0 | near-identical |
| `tests/test_structured_agent_outputs.py::test_a_description_cut_off_in_a_later_field_is_salvaged` | `tests/test_structured_agent_outputs.py::test_a_failed_toolbox_render_lets_the_context_error_stand` | 1.000 | 134 | 0 | 0 | near-identical |
| `tests/test_structured_agent_outputs.py::test_a_description_cut_off_in_a_later_field_is_salvaged` | `tests/test_structured_agent_outputs.py::test_a_looping_description_is_salvaged_without_the_loop` | 1.000 | 134 | 0 | 0 | near-identical |
| `tests/test_structured_agent_outputs.py::test_a_description_cut_off_in_a_later_field_is_salvaged` | `tests/test_structured_agent_outputs.py::test_a_region_on_the_general_budget_is_never_truncated` | 1.000 | 134 | 0 | 0 | near-identical |
| `tests/test_structured_agent_outputs.py::test_a_description_cut_off_in_a_later_field_is_salvaged` | `tests/test_structured_agent_outputs.py::test_an_answer_malformed_before_its_end_is_not_salvaged[inner-quote]` | 1.000 | 134 | 0 | 0 | near-identical |
| `tests/test_structured_agent_outputs.py::test_a_description_cut_off_in_a_later_field_is_salvaged` | `tests/test_structured_agent_outputs.py::test_an_answer_malformed_before_its_end_is_not_salvaged[invalid-escape]` | 1.000 | 134 | 0 | 0 | near-identical |
| `tests/test_structured_agent_outputs.py::test_a_description_cut_off_in_a_later_field_is_salvaged` | `tests/test_structured_agent_outputs.py::test_an_incomplete_run_rejected_as_a_rate_limit_is_retried` | 1.000 | 134 | 0 | 0 | near-identical |
| `tests/test_structured_agent_outputs.py::test_a_description_cut_off_in_a_later_field_is_salvaged` | `tests/test_structured_agent_outputs.py::test_completed_content_mentioning_429_is_not_mistaken_for_a_rate_limit` | 1.000 | 134 | 0 | 0 | near-identical |
| `tests/test_structured_agent_outputs.py::test_a_description_cut_off_in_a_later_field_is_salvaged` | `tests/test_structured_agent_outputs.py::test_context_overflow_from_the_run_status_is_recovered[cancelled]` | 1.000 | 134 | 0 | 0 | near-identical |
| `tests/test_structured_agent_outputs.py::test_a_description_cut_off_in_a_later_field_is_salvaged` | `tests/test_structured_agent_outputs.py::test_context_overflow_from_the_run_status_is_recovered[error]` | 1.000 | 134 | 0 | 0 | near-identical |
| `tests/test_structured_agent_outputs.py::test_a_description_cut_off_in_a_later_field_is_salvaged` | `tests/test_structured_agent_outputs.py::test_data_agent_rejects_output_for_the_wrong_region_kind` | 1.000 | 134 | 0 | 0 | near-identical |
| `tests/test_structured_agent_outputs.py::test_a_description_cut_off_in_a_later_field_is_salvaged` | `tests/test_structured_agent_outputs.py::test_data_agent_uses_larger_token_budget_for_tables` | 1.000 | 134 | 0 | 0 | near-identical |
| `tests/test_structured_agent_outputs.py::test_a_description_cut_off_in_a_later_field_is_salvaged` | `tests/test_structured_agent_outputs.py::test_each_vision_call_takes_its_model_and_deadline_from_the_agent_models[describe_region]` | 1.000 | 134 | 0 | 0 | near-identical |
| `tests/test_structured_agent_outputs.py::test_a_rate_limit_budget_exhausted_degrades_the_region` | `tests/test_structured_agent_outputs.py::test_context_overflow_is_critical_only_after_the_smaller_request_fails` | 1.000 | 138 | 0 | 0 | near-identical |
| `tests/test_structured_agent_outputs.py::test_a_rate_limit_budget_exhausted_degrades_the_region` | `tests/test_structured_agent_outputs.py::test_vision_agent_does_not_retry_a_provider_failure` | 1.000 | 138 | 0 | 0 | near-identical |
| `tests/test_structured_agent_outputs.py::test_a_rate_limited_region_waits_and_is_retried` | `tests/test_structured_agent_outputs.py::test_context_overflow_retries_full_page_with_smaller_image_and_token_cap` | 1.000 | 139 | 0 | 0 | near-identical |
| `tests/test_structured_agent_outputs.py::test_a_rate_limited_region_waits_and_is_retried` | `tests/test_structured_agent_outputs.py::test_context_retry_does_not_consume_a_region_answer_attempt` | 1.000 | 139 | 0 | 0 | near-identical |
| `tests/test_structured_agent_outputs.py::test_a_salvaged_description_is_not_cached` | `tests/test_structured_agent_outputs.py::test_a_truncated_description_is_not_cached` | 1.000 | 145 | 0 | 0 | near-identical |
| `tests/test_structured_agent_outputs.py::test_context_overflow_is_critical_only_after_the_smaller_request_fails` | `tests/test_structured_agent_outputs.py::test_vision_agent_does_not_retry_a_provider_failure` | 1.000 | 138 | 0 | 0 | near-identical |
| `tests/test_structured_agent_outputs.py::test_context_overflow_retries_full_page_with_smaller_image_and_token_cap` | `tests/test_structured_agent_outputs.py::test_context_retry_does_not_consume_a_region_answer_attempt` | 1.000 | 139 | 0 | 0 | near-identical |
| `tests/test_telegram_client.py::test_document_does_not_consume_another_senders_preferences` | `tests/test_telegram_client.py::test_document_submits_with_mode_and_source` | 1.000 | 293 | 0 | 0 | near-identical |
| `tests/test_telegram_client.py::test_pdf_ua_warning_survives_worker_and_user_locales_differing[en_US-pt_BR]` | `tests/test_telegram_client.py::test_pdf_ua_warning_survives_worker_and_user_locales_differing[pt_BR-en_US]` | 1.000 | 303 | 0 | 0 | identical-parameterization |
| `tests/test_telegram_upload_paths.py::test_telegram_download_uses_generated_contained_filename[../victim.pdf-handler]` | `tests/test_telegram_upload_paths.py::test_telegram_download_uses_generated_contained_filename[..\\victim.pdf-handler]` | 1.000 | 150 | 0 | 0 | identical-parameterization |
| `tests/test_telegram_upload_paths.py::test_telegram_download_uses_generated_contained_filename[../victim.pdf-handler]` | `tests/test_telegram_upload_paths.py::test_telegram_download_uses_generated_contained_filename[C:\\outside\\victim.pdf-handler]` | 1.000 | 150 | 0 | 0 | identical-parameterization |
| `tests/test_telegram_upload_paths.py::test_telegram_download_uses_generated_contained_filename[../victim.pdf-handler]` | `tests/test_telegram_upload_paths.py::test_telegram_download_uses_generated_contained_filename[absolute-handler]` | 1.000 | 150 | 0 | 0 | identical-parameterization |
| `tests/test_telegram_upload_paths.py::test_telegram_download_uses_generated_contained_filename[../victim.pdf-handler]` | `tests/test_telegram_upload_paths.py::test_telegram_download_uses_generated_contained_filename[documento \xe7.pdf-handler]` | 1.000 | 150 | 0 | 0 | identical-parameterization |
| `tests/test_telegram_upload_paths.py::test_telegram_download_uses_generated_contained_filename[..\\victim.pdf-handler]` | `tests/test_telegram_upload_paths.py::test_telegram_download_uses_generated_contained_filename[C:\\outside\\victim.pdf-handler]` | 1.000 | 150 | 0 | 0 | identical-parameterization |
| `tests/test_telegram_upload_paths.py::test_telegram_download_uses_generated_contained_filename[..\\victim.pdf-handler]` | `tests/test_telegram_upload_paths.py::test_telegram_download_uses_generated_contained_filename[absolute-handler]` | 1.000 | 150 | 0 | 0 | identical-parameterization |
| `tests/test_telegram_upload_paths.py::test_telegram_download_uses_generated_contained_filename[..\\victim.pdf-handler]` | `tests/test_telegram_upload_paths.py::test_telegram_download_uses_generated_contained_filename[documento \xe7.pdf-handler]` | 1.000 | 150 | 0 | 0 | identical-parameterization |
| `tests/test_telegram_upload_paths.py::test_telegram_download_uses_generated_contained_filename[C:\\outside\\victim.pdf-handler]` | `tests/test_telegram_upload_paths.py::test_telegram_download_uses_generated_contained_filename[absolute-handler]` | 1.000 | 150 | 0 | 0 | identical-parameterization |
| `tests/test_telegram_upload_paths.py::test_telegram_download_uses_generated_contained_filename[C:\\outside\\victim.pdf-handler]` | `tests/test_telegram_upload_paths.py::test_telegram_download_uses_generated_contained_filename[documento \xe7.pdf-handler]` | 1.000 | 150 | 0 | 0 | identical-parameterization |
| `tests/test_telegram_upload_paths.py::test_telegram_download_uses_generated_contained_filename[absolute-handler]` | `tests/test_telegram_upload_paths.py::test_telegram_download_uses_generated_contained_filename[documento \xe7.pdf-handler]` | 1.000 | 150 | 0 | 0 | identical-parameterization |
| `tests/test_trilha_a_regressions.py::test_pddl_recovery_policy_controls_real_cache_replay[completed-normalize-text-False-2]` | `tests/test_trilha_a_regressions.py::test_pddl_recovery_policy_controls_real_cache_replay[completed-recover-formula-True-2]` | 1.000 | 390 | 0 | 0 | identical-parameterization |
| `tests/test_trilha_a_regressions.py::test_pddl_recovery_policy_controls_real_cache_replay[completed-normalize-text-False-2]` | `tests/test_trilha_a_regressions.py::test_pddl_recovery_policy_controls_real_cache_replay[failed-None-False-2]` | 1.000 | 390 | 0 | 0 | identical-parameterization |
| `tests/test_trilha_a_regressions.py::test_pddl_recovery_policy_controls_real_cache_replay[completed-normalize-text-False-2]` | `tests/test_trilha_a_regressions.py::test_pddl_recovery_policy_controls_real_cache_replay[replan-required-None-False-2]` | 1.000 | 390 | 0 | 0 | identical-parameterization |
| `tests/test_trilha_a_regressions.py::test_pddl_recovery_policy_controls_real_cache_replay[completed-recover-formula-True-2]` | `tests/test_trilha_a_regressions.py::test_pddl_recovery_policy_controls_real_cache_replay[failed-None-False-2]` | 1.000 | 390 | 0 | 0 | identical-parameterization |
| `tests/test_trilha_a_regressions.py::test_pddl_recovery_policy_controls_real_cache_replay[completed-recover-formula-True-2]` | `tests/test_trilha_a_regressions.py::test_pddl_recovery_policy_controls_real_cache_replay[replan-required-None-False-2]` | 1.000 | 390 | 0 | 0 | identical-parameterization |
| `tests/test_trilha_a_regressions.py::test_pddl_recovery_policy_controls_real_cache_replay[failed-None-False-2]` | `tests/test_trilha_a_regressions.py::test_pddl_recovery_policy_controls_real_cache_replay[replan-required-None-False-2]` | 1.000 | 390 | 0 | 0 | identical-parameterization |
| `tests/test_untitled_document_name.py::test_a_client_path_in_the_uploaded_name_is_reduced_to_the_name[../../etc/relat\xf3rio.pdf]` | `tests/test_untitled_document_name.py::test_a_client_path_in_the_uploaded_name_is_reduced_to_the_name[..\\..\\etc\\relat\xf3rio.pdf]` | 1.000 | 274 | 0 | 0 | identical-parameterization |
| `tests/test_untitled_document_name.py::test_a_client_path_in_the_uploaded_name_is_reduced_to_the_name[../../etc/relat\xf3rio.pdf]` | `tests/test_untitled_document_name.py::test_a_client_path_in_the_uploaded_name_is_reduced_to_the_name[..\\etc/relat\xf3rio.pdf]` | 1.000 | 274 | 0 | 0 | identical-parameterization |
| `tests/test_untitled_document_name.py::test_a_client_path_in_the_uploaded_name_is_reduced_to_the_name[../../etc/relat\xf3rio.pdf]` | `tests/test_untitled_document_name.py::test_a_client_path_in_the_uploaded_name_is_reduced_to_the_name[C:\\fakepath\\relat\xf3rio.pdf]` | 1.000 | 274 | 0 | 0 | identical-parameterization |
| `tests/test_untitled_document_name.py::test_a_client_path_in_the_uploaded_name_is_reduced_to_the_name[../../etc/relat\xf3rio.pdf]` | `tests/test_untitled_document_name.py::test_the_canonical_build_takes_the_job_toolbox_config[processed]` | 1.000 | 274 | 0 | 0 | near-identical |
| `tests/test_untitled_document_name.py::test_a_client_path_in_the_uploaded_name_is_reduced_to_the_name[../../etc/relat\xf3rio.pdf]` | `tests/test_untitled_document_name.py::test_untitled_document_takes_the_uploaded_name[processed]` | 1.000 | 274 | 0 | 0 | near-identical |
| `tests/test_untitled_document_name.py::test_a_client_path_in_the_uploaded_name_is_reduced_to_the_name[..\\..\\etc\\relat\xf3rio.pdf]` | `tests/test_untitled_document_name.py::test_a_client_path_in_the_uploaded_name_is_reduced_to_the_name[..\\etc/relat\xf3rio.pdf]` | 1.000 | 274 | 0 | 0 | identical-parameterization |
| `tests/test_untitled_document_name.py::test_a_client_path_in_the_uploaded_name_is_reduced_to_the_name[..\\..\\etc\\relat\xf3rio.pdf]` | `tests/test_untitled_document_name.py::test_a_client_path_in_the_uploaded_name_is_reduced_to_the_name[C:\\fakepath\\relat\xf3rio.pdf]` | 1.000 | 274 | 0 | 0 | identical-parameterization |
| `tests/test_untitled_document_name.py::test_a_client_path_in_the_uploaded_name_is_reduced_to_the_name[..\\..\\etc\\relat\xf3rio.pdf]` | `tests/test_untitled_document_name.py::test_the_canonical_build_takes_the_job_toolbox_config[processed]` | 1.000 | 274 | 0 | 0 | near-identical |
| `tests/test_untitled_document_name.py::test_a_client_path_in_the_uploaded_name_is_reduced_to_the_name[..\\..\\etc\\relat\xf3rio.pdf]` | `tests/test_untitled_document_name.py::test_untitled_document_takes_the_uploaded_name[processed]` | 1.000 | 274 | 0 | 0 | near-identical |
| `tests/test_untitled_document_name.py::test_a_client_path_in_the_uploaded_name_is_reduced_to_the_name[..\\etc/relat\xf3rio.pdf]` | `tests/test_untitled_document_name.py::test_a_client_path_in_the_uploaded_name_is_reduced_to_the_name[C:\\fakepath\\relat\xf3rio.pdf]` | 1.000 | 274 | 0 | 0 | identical-parameterization |
| `tests/test_untitled_document_name.py::test_a_client_path_in_the_uploaded_name_is_reduced_to_the_name[..\\etc/relat\xf3rio.pdf]` | `tests/test_untitled_document_name.py::test_the_canonical_build_takes_the_job_toolbox_config[processed]` | 1.000 | 274 | 0 | 0 | near-identical |
| `tests/test_untitled_document_name.py::test_a_client_path_in_the_uploaded_name_is_reduced_to_the_name[..\\etc/relat\xf3rio.pdf]` | `tests/test_untitled_document_name.py::test_untitled_document_takes_the_uploaded_name[processed]` | 1.000 | 274 | 0 | 0 | near-identical |
| `tests/test_untitled_document_name.py::test_a_client_path_in_the_uploaded_name_is_reduced_to_the_name[C:\\fakepath\\relat\xf3rio.pdf]` | `tests/test_untitled_document_name.py::test_the_canonical_build_takes_the_job_toolbox_config[processed]` | 1.000 | 274 | 0 | 0 | near-identical |
| `tests/test_untitled_document_name.py::test_a_client_path_in_the_uploaded_name_is_reduced_to_the_name[C:\\fakepath\\relat\xf3rio.pdf]` | `tests/test_untitled_document_name.py::test_untitled_document_takes_the_uploaded_name[processed]` | 1.000 | 274 | 0 | 0 | near-identical |
| `tests/test_untitled_document_name.py::test_api_keeps_only_the_uploaded_basename[../../etc/relat\xf3rio.pdf]` | `tests/test_untitled_document_name.py::test_api_keeps_only_the_uploaded_basename[..\\..\\etc\\relat\xf3rio.pdf]` | 1.000 | 177 | 0 | 0 | identical-parameterization |
| `tests/test_untitled_document_name.py::test_api_keeps_only_the_uploaded_basename[../../etc/relat\xf3rio.pdf]` | `tests/test_untitled_document_name.py::test_api_keeps_only_the_uploaded_basename[C:\\fakepath\\relat\xf3rio.pdf]` | 1.000 | 177 | 0 | 0 | identical-parameterization |
| `tests/test_untitled_document_name.py::test_api_keeps_only_the_uploaded_basename[..\\..\\etc\\relat\xf3rio.pdf]` | `tests/test_untitled_document_name.py::test_api_keeps_only_the_uploaded_basename[C:\\fakepath\\relat\xf3rio.pdf]` | 1.000 | 177 | 0 | 0 | identical-parameterization |
| `tests/test_untitled_document_name.py::test_the_canonical_build_takes_the_job_toolbox_config[cache-hit]` | `tests/test_untitled_document_name.py::test_untitled_document_takes_the_uploaded_name[cache-hit]` | 1.000 | 224 | 0 | 0 | near-identical |
| `tests/test_untitled_document_name.py::test_the_canonical_build_takes_the_job_toolbox_config[processed]` | `tests/test_untitled_document_name.py::test_untitled_document_takes_the_uploaded_name[processed]` | 1.000 | 274 | 0 | 0 | near-identical |
| `tests/test_untitled_document_name.py::test_the_processing_cache_is_keyed_by_the_job_config` | `tests/test_untitled_document_name.py::test_without_an_uploaded_name_the_file_name_is_still_the_fallback` | 1.000 | 275 | 0 | 0 | near-identical |
| `tests/test_v2_security.py::test_valid_or_optional_recipient_is_accepted[   ]` | `tests/test_v2_security.py::test_valid_or_optional_recipient_is_accepted[]` | 1.000 | 175 | 0 | 0 | identical-parameterization |
| `tests/test_v2_security.py::test_valid_or_optional_recipient_is_accepted[ reader@example.test ]` | `tests/test_v2_security.py::test_valid_or_optional_recipient_is_accepted[reader+tag@example.test]` | 1.000 | 179 | 0 | 0 | identical-parameterization |
| `tests/test_v2_security.py::test_valid_or_optional_recipient_is_accepted[ reader@example.test ]` | `tests/test_v2_security.py::test_valid_or_optional_recipient_is_accepted[reader@example.test]` | 1.000 | 179 | 0 | 0 | identical-parameterization |
| `tests/test_v2_security.py::test_valid_or_optional_recipient_is_accepted[reader+tag@example.test]` | `tests/test_v2_security.py::test_valid_or_optional_recipient_is_accepted[reader@example.test]` | 1.000 | 179 | 0 | 0 | identical-parameterization |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[cancelled-None-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[error-None-False-False]` | 1.000 | 185 | 0 | 0 | identical-parameterization |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-failed-False-False]` | `tests/test_web_panel.py::test_receipt_recovers_result_after_refresh[failed]` | 1.000 | 189 | 0 | 0 | near-identical |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-pending-True-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-None-True-False]` | 1.000 | 184 | 0 | 0 | identical-parameterization |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-pending-True-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-pending-True-False]` | 1.000 | 184 | 0 | 0 | identical-parameterization |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-pending-True-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[queued-None-True-False]` | 1.000 | 184 | 0 | 0 | identical-parameterization |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-sent-False-False]` | `tests/test_web_panel.py::test_receipt_recovers_result_after_refresh[sent]` | 1.000 | 189 | 0 | 0 | near-identical |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-None-True-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-pending-True-False]` | 1.000 | 184 | 0 | 0 | identical-parameterization |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-None-True-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[queued-None-True-False]` | 1.000 | 184 | 0 | 0 | identical-parameterization |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-pending-True-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[queued-None-True-False]` | 1.000 | 184 | 0 | 0 | identical-parameterization |
