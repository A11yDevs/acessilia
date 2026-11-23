## Redundancy candidates (#644)

83 overlapping pairs; 0 pairwise coverage-subsumed candidates with about 0.00s of measured time; 100 tests without an exclusive production line.

This is a review sheet, not a deletion list. "Coverage-subsumed" means only that the other test covers every measured line of the candidate; contracts, diagnostics and failure modes still have to be checked by hand.

| Candidate | Covered by | Similarity | Shared | Seconds | Classification |
|---|---|---:|---:|---:|---|
| — | — | — | — | — | — |

### Tests with no exclusive production line

Every measured line of these tests is also covered by another test. Coverage omits the test files themselves, so this does not say the assertions are redundant; it is the shortlist for the mutation experiment, where equal coverage can hide different detection.

| Test | Lines | Seconds |
|---|---:|---:|
| `tests/test_cancellation_queue.py::test_cancelled_extraction_advances_queue_and_reports_wait` | 571 | 0.347 |
| `tests/test_long_output_filenames.py::test_long_filename_can_be_exported_and_downloaded[short]` | 599 | 0.167 |
| `tests/test_telegram_client.py::test_document_flow_sends_download_link[False]` | 299 | 0.148 |
| `tests/test_long_output_filenames.py::test_long_filename_can_be_exported_and_downloaded[long-cjk]` | 605 | 0.130 |
| `tests/test_long_output_filenames.py::test_long_filename_can_be_exported_and_downloaded[long-ascii]` | 605 | 0.126 |
| `tests/test_long_output_filenames.py::test_long_filename_can_be_exported_and_downloaded[long-greek]` | 605 | 0.120 |
| `tests/test_pddl_audit_fixes.py::test_failed_plan_marks_api_job_error_without_caching_or_download` | 426 | 0.120 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxPdfClient-endpoints list wins]` | 273 | 0.088 |
| `tests/test_telegram_client.py::test_document_does_not_consume_another_senders_preferences` | 293 | 0.083 |
| `tests/test_job_progress.py::test_a_broken_failure_email_keeps_the_job_error_and_records_the_failure` | 429 | 0.081 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxStructureClient-endpoints list wins]` | 273 | 0.081 |
| `tests/test_telegram_client.py::test_document_flow_sends_download_link[True]` | 309 | 0.080 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxMathClient-endpoints list wins]` | 273 | 0.079 |
| `tests/test_pending_fixes.py::test_active_cancel_interrupts_pipeline_and_advances_queue` | 394 | 0.076 |
| `tests/test_telegram_client.py::test_document_passes_email_and_notifies` | 295 | 0.076 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxDatasetClient-endpoints list wins]` | 273 | 0.076 |
| `tests/test_telegram_client.py::test_document_flow_sends_the_download_link_in_the_user_locale` | 305 | 0.074 |
| `tests/test_telegram_client.py::test_pdf_ua_warning_survives_worker_and_user_locales_differing[pt_BR-en_US]` | 303 | 0.073 |
| `tests/test_telegram_client.py::test_document_submits_with_mode_and_source` | 293 | 0.073 |
| `tests/test_worker_pipeline_failure.py::test_job_executor_does_not_export_pipeline_failure` | 403 | 0.072 |
| `tests/test_job_progress.py::test_pipeline_failure_names_the_stage_once_and_emails_the_user` | 417 | 0.071 |
| `tests/test_telegram_client.py::test_pdf_ua_warning_survives_worker_and_user_locales_differing[en_US-pt_BR]` | 303 | 0.068 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxStructureClient-provider]` | 273 | 0.067 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxMathClient-defaults]` | 273 | 0.057 |
| `tests/test_pending_fixes.py::test_email_delivery_status_does_not_lose_download[False]` | 455 | 0.055 |
| `tests/test_trilha_a_regressions.py::test_pddl_recovery_policy_controls_real_cache_replay[completed-normalize-text-False-2]` | 390 | 0.055 |
| `tests/test_api.py::test_job_executor_marks_history_error_when_export_fails[txt]` | 314 | 0.054 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxStructureClient-defaults]` | 273 | 0.054 |
| `tests/test_pending_fixes.py::test_email_delivery_status_does_not_lose_download[True]` | 454 | 0.053 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxDatasetClient-defaults]` | 273 | 0.052 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxStructureClient-budgets]` | 273 | 0.052 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxStructureClient-single endpoint]` | 273 | 0.052 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxDatasetClient-budgets]` | 273 | 0.051 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxDatasetClient-empty provider]` | 273 | 0.051 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxPdfClient-empty provider]` | 273 | 0.050 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxStructureClient-empty provider]` | 273 | 0.050 |
| `tests/test_api.py::test_job_executor_marks_history_error_when_export_fails[zip]` | 378 | 0.049 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxPdfClient-defaults]` | 273 | 0.049 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxPdfClient-provider]` | 273 | 0.049 |
| `tests/test_trilha_a_regressions.py::test_pddl_recovery_policy_controls_real_cache_replay[completed-None-False-1]` | 380 | 0.048 |
| `tests/test_api.py::test_job_executor_marks_history_error_when_export_fails[html]` | 320 | 0.048 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxDatasetClient-provider]` | 273 | 0.048 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxDatasetClient-single endpoint]` | 273 | 0.048 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxMathClient-provider]` | 273 | 0.048 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxPdfClient-budgets]` | 273 | 0.048 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxPdfClient-single endpoint]` | 273 | 0.048 |
| `tests/test_pending_fixes.py::test_result_email_reports_open_obligations_of_a_delivered_document` | 454 | 0.047 |
| `tests/test_object_markers.py::test_the_worker_marks_what_a_reader_gets_and_stores_the_document_unmarked` | 438 | 0.047 |
| `tests/test_trilha_a_regressions.py::test_pddl_recovery_policy_controls_real_cache_replay[completed-recover-formula-True-2]` | 390 | 0.047 |
| `tests/test_trilha_a_regressions.py::test_pddl_recovery_policy_controls_real_cache_replay[replan-required-None-False-2]` | 390 | 0.047 |
| `tests/test_trilha_a_regressions.py::test_pddl_recovery_policy_controls_real_cache_replay[completed-normalize-text-True-1]` | 384 | 0.047 |
| `tests/test_pddl_cache_contract.py::test_degraded_processing_is_not_cached[False]` | 299 | 0.047 |
| `tests/test_pddl_cache_contract.py::test_cached_entry_with_failed_media_inspection_is_ignored` | 297 | 0.046 |
| `tests/test_job_resume.py::test_a_resumed_run_restores_progress_and_skips_the_confirmation` | 290 | 0.046 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxMathClient-budgets]` | 273 | 0.046 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxMathClient-empty provider]` | 273 | 0.046 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxMathClient-single endpoint]` | 273 | 0.046 |
| `tests/test_pddl_cache_contract.py::test_cached_degraded_entry_is_ignored[visual-failures-degraded-rerun]` | 302 | 0.045 |
| `tests/test_trilha_a_regressions.py::test_pddl_recovery_policy_controls_real_cache_replay[failed-None-False-2]` | 390 | 0.043 |
| `tests/test_telegram_client.py::test_concurrent_group_users_keep_preferences_and_tasks_isolated` | 293 | 0.041 |
| `tests/test_api.py::test_job_executor_reports_optional_export_failure[None]` | 398 | 0.040 |
| `tests/test_pddl_cache_contract.py::test_cached_degraded_entry_is_ignored[visual-failures-clean-rerun]` | 301 | 0.040 |
| `tests/test_pddl_cache_contract.py::test_live_processing_rejects_incompatible_cached_execution[dry-run-completed]` | 287 | 0.040 |
| `tests/test_api.py::test_cancel_reports_a_requested_remote_cancellation` | 267 | 0.039 |
| `tests/test_pddl_cache_contract.py::test_cached_degraded_entry_is_ignored[single-provider-extraction-clean-rerun]` | 302 | 0.038 |
| `tests/test_api.py::test_job_executor_records_early_process_failure` | 273 | 0.038 |
| `tests/test_untitled_document_name.py::test_the_processing_cache_is_keyed_by_the_job_config` | 275 | 0.035 |
| `tests/test_pddl_cache_contract.py::test_live_processing_rejects_incompatible_cached_execution[replan-required]` | 286 | 0.034 |
| `tests/test_untitled_document_name.py::test_without_an_uploaded_name_the_file_name_is_still_the_fallback` | 275 | 0.034 |
| `tests/test_pddl_cache_contract.py::test_degraded_processing_is_not_cached[True]` | 285 | 0.032 |
| `tests/test_pddl_cache_contract.py::test_cached_degraded_entry_is_ignored[single-provider-extraction-degraded-rerun]` | 303 | 0.031 |
| `tests/test_untitled_document_name.py::test_untitled_document_takes_the_uploaded_name[processed]` | 274 | 0.031 |
| `tests/test_api.py::test_job_executor_reports_optional_export_failure[DOCX]` | 406 | 0.029 |
| `tests/test_api.py::test_job_executor_reports_optional_export_failure[DOCX disabled]` | 400 | 0.029 |
| `tests/test_api.py::test_job_executor_reports_optional_export_failure[PDF/UA]` | 397 | 0.029 |
| `tests/test_pddl_cache_contract.py::test_live_processing_rejects_incompatible_cached_execution[failed]` | 286 | 0.029 |
| `tests/test_untitled_document_name.py::test_the_canonical_build_takes_the_job_toolbox_config[processed]` | 274 | 0.029 |
| `tests/test_job_resume.py::test_a_graceful_shutdown_keeps_the_operation_journal` | 267 | 0.029 |
| `tests/test_untitled_document_name.py::test_untitled_document_takes_the_uploaded_name[cache-hit]` | 224 | 0.029 |
| `tests/test_api.py::test_job_executor_reports_optional_export_failure[MP3]` | 404 | 0.028 |
| `tests/test_api.py::test_job_executor_reports_optional_export_failure[PDF/UA disabled]` | 383 | 0.028 |
| `tests/test_untitled_document_name.py::test_a_client_path_in_the_uploaded_name_is_reduced_to_the_name[..\\..\\etc\\relat\xf3rio.pdf]` | 274 | 0.028 |
| `tests/test_untitled_document_name.py::test_a_client_path_in_the_uploaded_name_is_reduced_to_the_name[..\\etc/relat\xf3rio.pdf]` | 274 | 0.028 |
| `tests/test_untitled_document_name.py::test_a_client_path_in_the_uploaded_name_is_reduced_to_the_name[../../etc/relat\xf3rio.pdf]` | 274 | 0.027 |
| `tests/test_api.py::test_job_executor_keeps_original_filename_in_status` | 378 | 0.026 |
| `tests/test_untitled_document_name.py::test_a_client_path_in_the_uploaded_name_is_reduced_to_the_name[C:\\fakepath\\relat\xf3rio.pdf]` | 274 | 0.026 |
| `tests/test_untitled_document_name.py::test_the_canonical_build_takes_the_job_toolbox_config[cache-hit]` | 224 | 0.026 |
| `tests/test_pdf_ua_export.py::test_toolbox_pdf_ua_enabled_is_parsed_from_the_environment[None-True]` | 212 | 0.017 |
| `tests/test_docx_export.py::test_toolbox_docx_enabled_is_parsed_from_the_environment[0-False]` | 212 | 0.015 |
| `tests/test_docx_export.py::test_toolbox_docx_enabled_is_parsed_from_the_environment[None-True]` | 212 | 0.014 |
| `tests/test_docx_export.py::test_toolbox_docx_enabled_is_parsed_from_the_environment[true-True]` | 212 | 0.014 |
| `tests/test_docx_export.py::test_toolbox_docx_enabled_is_parsed_from_the_environment[false-False]` | 212 | 0.013 |
| `tests/test_page_limit.py::test_max_pages_is_read_from_the_environment` | 212 | 0.013 |
| `tests/test_pdf_ua_export.py::test_toolbox_pdf_ua_enabled_is_parsed_from_the_environment[1-True]` | 212 | 0.013 |
| `tests/test_pdf_ua_export.py::test_toolbox_pdf_ua_enabled_is_parsed_from_the_environment[SIM-True]` | 212 | 0.012 |
| `tests/test_docx_export.py::test_toolbox_docx_enabled_is_parsed_from_the_environment[SIM-True]` | 212 | 0.011 |
| `tests/test_i18n_locales.py::test_settings_defaults_to_the_supported_locales` | 212 | 0.011 |
| `tests/test_pdf_ua_export.py::test_toolbox_pdf_ua_enabled_is_parsed_from_the_environment[0-False]` | 212 | 0.011 |
| `tests/test_i18n_locales.py::test_settings_reads_i18n_locales_active_with_the_shared_parser` | 212 | 0.010 |
| `tests/test_object_markers.py::test_markers_are_off_by_default` | 212 | 0.010 |

### Reviewed pairs

| Test A | Test B | Similarity | Only A | Only B | Candidate | Saved (s) |
|---|---|---:|---:|---:|---|---:|
| `tests/test_telegram_client.py::test_pdf_ua_warning_survives_worker_and_user_locales_differing[en_US-pt_BR]` | `tests/test_telegram_client.py::test_pdf_ua_warning_survives_worker_and_user_locales_differing[pt_BR-en_US]` | 0.853 | 24 | 24 | `—` | 0.000 |
| `tests/test_telegram_client.py::test_document_does_not_consume_another_senders_preferences` | `tests/test_telegram_client.py::test_document_submits_with_mode_and_source` | 0.849 | 24 | 24 | `—` | 0.000 |
| `tests/test_telegram_client.py::test_document_flow_sends_the_download_link_in_the_user_locale` | `tests/test_telegram_client.py::test_pdf_ua_warning_survives_worker_and_user_locales_differing[en_US-pt_BR]` | 0.848 | 26 | 24 | `—` | 0.000 |
| `tests/test_telegram_client.py::test_document_flow_sends_the_download_link_in_the_user_locale` | `tests/test_telegram_client.py::test_pdf_ua_warning_survives_worker_and_user_locales_differing[pt_BR-en_US]` | 0.848 | 26 | 24 | `—` | 0.000 |
| `tests/test_telegram_client.py::test_document_does_not_consume_another_senders_preferences` | `tests/test_telegram_client.py::test_document_passes_email_and_notifies` | 0.843 | 24 | 26 | `—` | 0.000 |
| `tests/test_telegram_client.py::test_document_passes_email_and_notifies` | `tests/test_telegram_client.py::test_document_submits_with_mode_and_source` | 0.843 | 26 | 24 | `—` | 0.000 |
| `tests/test_telegram_client.py::test_document_flow_sends_download_link[True]` | `tests/test_telegram_client.py::test_pdf_ua_warning_survives_worker_and_user_locales_differing[en_US-pt_BR]` | 0.838 | 30 | 24 | `—` | 0.000 |
| `tests/test_telegram_client.py::test_document_flow_sends_download_link[True]` | `tests/test_telegram_client.py::test_pdf_ua_warning_survives_worker_and_user_locales_differing[pt_BR-en_US]` | 0.838 | 30 | 24 | `—` | 0.000 |
| `tests/test_telegram_client.py::test_document_does_not_consume_another_senders_preferences` | `tests/test_telegram_client.py::test_document_flow_sends_download_link[False]` | 0.833 | 24 | 30 | `—` | 0.000 |
| `tests/test_telegram_client.py::test_document_flow_sends_download_link[False]` | `tests/test_telegram_client.py::test_document_submits_with_mode_and_source` | 0.833 | 30 | 24 | `—` | 0.000 |
| `tests/test_telegram_client.py::test_document_flow_sends_download_link[True]` | `tests/test_telegram_client.py::test_document_flow_sends_the_download_link_in_the_user_locale` | 0.833 | 30 | 26 | `—` | 0.000 |
| `tests/test_telegram_client.py::test_document_flow_sends_download_link[False]` | `tests/test_telegram_client.py::test_document_passes_email_and_notifies` | 0.828 | 30 | 26 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-failed-False-False]` | `tests/test_web_panel.py::test_receipt_recovers_result_after_refresh[failed]` | 0.826 | 18 | 18 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-sent-False-False]` | `tests/test_web_panel.py::test_receipt_recovers_result_after_refresh[sent]` | 0.826 | 18 | 18 | `—` | 0.000 |
| `tests/test_telegram_client.py::test_document_flow_sends_download_link[False]` | `tests/test_telegram_client.py::test_document_flow_sends_download_link[True]` | 0.826 | 24 | 34 | `—` | 0.000 |
| `tests/test_telegram_client.py::test_document_flow_sends_the_download_link_in_the_user_locale` | `tests/test_telegram_client.py::test_document_passes_email_and_notifies` | 0.824 | 34 | 24 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[cancelled-None-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[error-None-False-False]` | 0.823 | 18 | 18 | `—` | 0.000 |
| `tests/test_telegram_client.py::test_document_does_not_consume_another_senders_preferences` | `tests/test_telegram_client.py::test_pdf_ua_warning_survives_worker_and_user_locales_differing[en_US-pt_BR]` | 0.823 | 24 | 34 | `—` | 0.000 |
| `tests/test_telegram_client.py::test_document_does_not_consume_another_senders_preferences` | `tests/test_telegram_client.py::test_pdf_ua_warning_survives_worker_and_user_locales_differing[pt_BR-en_US]` | 0.823 | 24 | 34 | `—` | 0.000 |
| `tests/test_telegram_client.py::test_document_submits_with_mode_and_source` | `tests/test_telegram_client.py::test_pdf_ua_warning_survives_worker_and_user_locales_differing[en_US-pt_BR]` | 0.823 | 24 | 34 | `—` | 0.000 |
| `tests/test_telegram_client.py::test_document_submits_with_mode_and_source` | `tests/test_telegram_client.py::test_pdf_ua_warning_survives_worker_and_user_locales_differing[pt_BR-en_US]` | 0.823 | 24 | 34 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-pending-True-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-None-True-False]` | 0.822 | 18 | 18 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-pending-True-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-pending-True-False]` | 0.822 | 18 | 18 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-pending-True-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[queued-None-True-False]` | 0.822 | 18 | 18 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-None-True-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-pending-True-False]` | 0.822 | 18 | 18 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-None-True-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[queued-None-True-False]` | 0.822 | 18 | 18 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-pending-True-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[queued-None-True-False]` | 0.822 | 18 | 18 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[cancelled-None-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-pending-True-False]` | 0.818 | 19 | 18 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[cancelled-None-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-None-True-False]` | 0.818 | 19 | 18 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[cancelled-None-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-pending-True-False]` | 0.818 | 19 | 18 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[cancelled-None-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[queued-None-True-False]` | 0.818 | 19 | 18 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-pending-True-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[error-None-False-False]` | 0.818 | 18 | 19 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[error-None-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-None-True-False]` | 0.818 | 19 | 18 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[error-None-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-pending-True-False]` | 0.818 | 19 | 18 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[error-None-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[queued-None-True-False]` | 0.818 | 19 | 18 | `—` | 0.000 |
| `tests/test_telegram_client.py::test_document_does_not_consume_another_senders_preferences` | `tests/test_telegram_client.py::test_document_flow_sends_the_download_link_in_the_user_locale` | 0.818 | 24 | 36 | `—` | 0.000 |
| `tests/test_telegram_client.py::test_document_flow_sends_the_download_link_in_the_user_locale` | `tests/test_telegram_client.py::test_document_submits_with_mode_and_source` | 0.818 | 36 | 24 | `—` | 0.000 |
| `tests/test_telegram_client.py::test_document_passes_email_and_notifies` | `tests/test_telegram_client.py::test_pdf_ua_warning_survives_worker_and_user_locales_differing[en_US-pt_BR]` | 0.818 | 26 | 34 | `—` | 0.000 |
| `tests/test_telegram_client.py::test_document_passes_email_and_notifies` | `tests/test_telegram_client.py::test_pdf_ua_warning_survives_worker_and_user_locales_differing[pt_BR-en_US]` | 0.818 | 26 | 34 | `—` | 0.000 |
| `tests/test_telegram_client.py::test_document_does_not_consume_another_senders_preferences` | `tests/test_telegram_client.py::test_document_flow_sends_download_link[True]` | 0.808 | 24 | 40 | `—` | 0.000 |
| `tests/test_telegram_client.py::test_document_flow_sends_download_link[False]` | `tests/test_telegram_client.py::test_pdf_ua_warning_survives_worker_and_user_locales_differing[en_US-pt_BR]` | 0.808 | 30 | 34 | `—` | 0.000 |
| `tests/test_telegram_client.py::test_document_flow_sends_download_link[False]` | `tests/test_telegram_client.py::test_pdf_ua_warning_survives_worker_and_user_locales_differing[pt_BR-en_US]` | 0.808 | 30 | 34 | `—` | 0.000 |
| `tests/test_telegram_client.py::test_document_flow_sends_download_link[True]` | `tests/test_telegram_client.py::test_document_submits_with_mode_and_source` | 0.808 | 40 | 24 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[cancelled-None-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[cancelling-None-False-True]` | 0.807 | 18 | 22 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[cancelled-None-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-failed-False-False]` | 0.807 | 18 | 22 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[cancelled-None-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-sent-False-False]` | 0.807 | 18 | 22 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[cancelled-None-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-unknown-False-False]` | 0.807 | 18 | 22 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[cancelled-None-False-False]` | `tests/test_web_panel.py::test_receipt_recovers_result_after_refresh[failed]` | 0.807 | 18 | 22 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[cancelled-None-False-False]` | `tests/test_web_panel.py::test_receipt_recovers_result_after_refresh[sent]` | 0.807 | 18 | 22 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[cancelling-None-False-True]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[error-None-False-False]` | 0.807 | 22 | 18 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-failed-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[error-None-False-False]` | 0.807 | 22 | 18 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-sent-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[error-None-False-False]` | 0.807 | 22 | 18 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-unknown-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[error-None-False-False]` | 0.807 | 22 | 18 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[error-None-False-False]` | `tests/test_web_panel.py::test_receipt_recovers_result_after_refresh[failed]` | 0.807 | 18 | 22 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[error-None-False-False]` | `tests/test_web_panel.py::test_receipt_recovers_result_after_refresh[sent]` | 0.807 | 18 | 22 | `—` | 0.000 |
| `tests/test_telegram_client.py::test_document_does_not_consume_another_senders_preferences` | `tests/test_telegram_client.py::test_photo_flow` | 0.804 | 39 | 23 | `—` | 0.000 |
| `tests/test_telegram_client.py::test_document_submits_with_mode_and_source` | `tests/test_telegram_client.py::test_photo_flow` | 0.804 | 39 | 23 | `—` | 0.000 |
| `tests/test_telegram_client.py::test_document_flow_sends_download_link[False]` | `tests/test_telegram_client.py::test_document_flow_sends_the_download_link_in_the_user_locale` | 0.803 | 30 | 36 | `—` | 0.000 |
| `tests/test_telegram_client.py::test_document_flow_sends_download_link[True]` | `tests/test_telegram_client.py::test_document_passes_email_and_notifies` | 0.803 | 40 | 26 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[cancelling-None-False-True]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-pending-True-False]` | 0.802 | 23 | 18 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[cancelling-None-False-True]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-None-True-False]` | 0.802 | 23 | 18 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[cancelling-None-False-True]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-pending-True-False]` | 0.802 | 23 | 18 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[cancelling-None-False-True]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[queued-None-True-False]` | 0.802 | 23 | 18 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-failed-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-pending-True-False]` | 0.802 | 23 | 18 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-failed-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-None-True-False]` | 0.802 | 23 | 18 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-failed-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-pending-True-False]` | 0.802 | 23 | 18 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-failed-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[queued-None-True-False]` | 0.802 | 23 | 18 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-pending-True-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-sent-False-False]` | 0.802 | 18 | 23 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-pending-True-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-unknown-False-False]` | 0.802 | 18 | 23 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-pending-True-False]` | `tests/test_web_panel.py::test_receipt_recovers_result_after_refresh[failed]` | 0.802 | 18 | 23 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-pending-True-False]` | `tests/test_web_panel.py::test_receipt_recovers_result_after_refresh[sent]` | 0.802 | 18 | 23 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-sent-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-None-True-False]` | 0.802 | 23 | 18 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-sent-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-pending-True-False]` | 0.802 | 23 | 18 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-sent-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[queued-None-True-False]` | 0.802 | 23 | 18 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-unknown-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-None-True-False]` | 0.802 | 23 | 18 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-unknown-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-pending-True-False]` | 0.802 | 23 | 18 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-unknown-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[queued-None-True-False]` | 0.802 | 23 | 18 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-None-True-False]` | `tests/test_web_panel.py::test_receipt_recovers_result_after_refresh[failed]` | 0.802 | 18 | 23 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-None-True-False]` | `tests/test_web_panel.py::test_receipt_recovers_result_after_refresh[sent]` | 0.802 | 18 | 23 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-pending-True-False]` | `tests/test_web_panel.py::test_receipt_recovers_result_after_refresh[failed]` | 0.802 | 18 | 23 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-pending-True-False]` | `tests/test_web_panel.py::test_receipt_recovers_result_after_refresh[sent]` | 0.802 | 18 | 23 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[queued-None-True-False]` | `tests/test_web_panel.py::test_receipt_recovers_result_after_refresh[failed]` | 0.802 | 18 | 23 | `—` | 0.000 |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[queued-None-True-False]` | `tests/test_web_panel.py::test_receipt_recovers_result_after_refresh[sent]` | 0.802 | 18 | 23 | `—` | 0.000 |
