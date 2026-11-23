## Coverage overlap (#644)

3192 tests, 3559 executed lines, 83 pairs at Jaccard >= 0.8 with at least 5 shared lines.
246 parametrized families with identical line coverage; 3080 tests without an exclusive production line.

No test is removed by this report: high overlap is a review candidate.

| Test A | Test B | Jaccard | Shared | Only A | Only B | Param. |
|---|---|---:|---:|---:|---:|---|
| `tests/test_telegram_client.py::test_pdf_ua_warning_survives_worker_and_user_locales_differing[en_US-pt_BR]` | `tests/test_telegram_client.py::test_pdf_ua_warning_survives_worker_and_user_locales_differing[pt_BR-en_US]` | 0.853 | 279 | 24 | 24 | yes |
| `tests/test_telegram_client.py::test_document_does_not_consume_another_senders_preferences` | `tests/test_telegram_client.py::test_document_submits_with_mode_and_source` | 0.849 | 269 | 24 | 24 |  |
| `tests/test_telegram_client.py::test_document_flow_sends_the_download_link_in_the_user_locale` | `tests/test_telegram_client.py::test_pdf_ua_warning_survives_worker_and_user_locales_differing[en_US-pt_BR]` | 0.848 | 279 | 26 | 24 |  |
| `tests/test_telegram_client.py::test_document_flow_sends_the_download_link_in_the_user_locale` | `tests/test_telegram_client.py::test_pdf_ua_warning_survives_worker_and_user_locales_differing[pt_BR-en_US]` | 0.848 | 279 | 26 | 24 |  |
| `tests/test_telegram_client.py::test_document_does_not_consume_another_senders_preferences` | `tests/test_telegram_client.py::test_document_passes_email_and_notifies` | 0.843 | 269 | 24 | 26 |  |
| `tests/test_telegram_client.py::test_document_passes_email_and_notifies` | `tests/test_telegram_client.py::test_document_submits_with_mode_and_source` | 0.843 | 269 | 26 | 24 |  |
| `tests/test_telegram_client.py::test_document_flow_sends_download_link[True]` | `tests/test_telegram_client.py::test_pdf_ua_warning_survives_worker_and_user_locales_differing[en_US-pt_BR]` | 0.838 | 279 | 30 | 24 |  |
| `tests/test_telegram_client.py::test_document_flow_sends_download_link[True]` | `tests/test_telegram_client.py::test_pdf_ua_warning_survives_worker_and_user_locales_differing[pt_BR-en_US]` | 0.838 | 279 | 30 | 24 |  |
| `tests/test_telegram_client.py::test_document_flow_sends_download_link[True]` | `tests/test_telegram_client.py::test_document_flow_sends_the_download_link_in_the_user_locale` | 0.833 | 279 | 30 | 26 |  |
| `tests/test_telegram_client.py::test_document_does_not_consume_another_senders_preferences` | `tests/test_telegram_client.py::test_document_flow_sends_download_link[False]` | 0.833 | 269 | 24 | 30 |  |
| `tests/test_telegram_client.py::test_document_flow_sends_download_link[False]` | `tests/test_telegram_client.py::test_document_submits_with_mode_and_source` | 0.833 | 269 | 30 | 24 |  |
| `tests/test_telegram_client.py::test_document_flow_sends_download_link[False]` | `tests/test_telegram_client.py::test_document_passes_email_and_notifies` | 0.828 | 269 | 30 | 26 |  |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-failed-False-False]` | `tests/test_web_panel.py::test_receipt_recovers_result_after_refresh[failed]` | 0.826 | 171 | 18 | 18 |  |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-sent-False-False]` | `tests/test_web_panel.py::test_receipt_recovers_result_after_refresh[sent]` | 0.826 | 171 | 18 | 18 |  |
| `tests/test_telegram_client.py::test_document_flow_sends_download_link[False]` | `tests/test_telegram_client.py::test_document_flow_sends_download_link[True]` | 0.826 | 275 | 24 | 34 | yes |
| `tests/test_telegram_client.py::test_document_flow_sends_the_download_link_in_the_user_locale` | `tests/test_telegram_client.py::test_document_passes_email_and_notifies` | 0.824 | 271 | 34 | 24 |  |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[cancelled-None-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[error-None-False-False]` | 0.823 | 167 | 18 | 18 | yes |
| `tests/test_telegram_client.py::test_document_does_not_consume_another_senders_preferences` | `tests/test_telegram_client.py::test_pdf_ua_warning_survives_worker_and_user_locales_differing[en_US-pt_BR]` | 0.823 | 269 | 24 | 34 |  |
| `tests/test_telegram_client.py::test_document_does_not_consume_another_senders_preferences` | `tests/test_telegram_client.py::test_pdf_ua_warning_survives_worker_and_user_locales_differing[pt_BR-en_US]` | 0.823 | 269 | 24 | 34 |  |
| `tests/test_telegram_client.py::test_document_submits_with_mode_and_source` | `tests/test_telegram_client.py::test_pdf_ua_warning_survives_worker_and_user_locales_differing[en_US-pt_BR]` | 0.823 | 269 | 24 | 34 |  |
| `tests/test_telegram_client.py::test_document_submits_with_mode_and_source` | `tests/test_telegram_client.py::test_pdf_ua_warning_survives_worker_and_user_locales_differing[pt_BR-en_US]` | 0.823 | 269 | 24 | 34 |  |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-pending-True-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-None-True-False]` | 0.822 | 166 | 18 | 18 | yes |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-pending-True-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-pending-True-False]` | 0.822 | 166 | 18 | 18 | yes |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-pending-True-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[queued-None-True-False]` | 0.822 | 166 | 18 | 18 | yes |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-None-True-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-pending-True-False]` | 0.822 | 166 | 18 | 18 | yes |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-None-True-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[queued-None-True-False]` | 0.822 | 166 | 18 | 18 | yes |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-pending-True-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[queued-None-True-False]` | 0.822 | 166 | 18 | 18 | yes |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[cancelled-None-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-pending-True-False]` | 0.818 | 166 | 19 | 18 | yes |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[cancelled-None-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-None-True-False]` | 0.818 | 166 | 19 | 18 | yes |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[cancelled-None-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-pending-True-False]` | 0.818 | 166 | 19 | 18 | yes |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[cancelled-None-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[queued-None-True-False]` | 0.818 | 166 | 19 | 18 | yes |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-pending-True-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[error-None-False-False]` | 0.818 | 166 | 18 | 19 | yes |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[error-None-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-None-True-False]` | 0.818 | 166 | 19 | 18 | yes |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[error-None-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-pending-True-False]` | 0.818 | 166 | 19 | 18 | yes |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[error-None-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[queued-None-True-False]` | 0.818 | 166 | 19 | 18 | yes |
| `tests/test_telegram_client.py::test_document_does_not_consume_another_senders_preferences` | `tests/test_telegram_client.py::test_document_flow_sends_the_download_link_in_the_user_locale` | 0.818 | 269 | 24 | 36 |  |
| `tests/test_telegram_client.py::test_document_flow_sends_the_download_link_in_the_user_locale` | `tests/test_telegram_client.py::test_document_submits_with_mode_and_source` | 0.818 | 269 | 36 | 24 |  |
| `tests/test_telegram_client.py::test_document_passes_email_and_notifies` | `tests/test_telegram_client.py::test_pdf_ua_warning_survives_worker_and_user_locales_differing[en_US-pt_BR]` | 0.818 | 269 | 26 | 34 |  |
| `tests/test_telegram_client.py::test_document_passes_email_and_notifies` | `tests/test_telegram_client.py::test_pdf_ua_warning_survives_worker_and_user_locales_differing[pt_BR-en_US]` | 0.818 | 269 | 26 | 34 |  |
| `tests/test_telegram_client.py::test_document_does_not_consume_another_senders_preferences` | `tests/test_telegram_client.py::test_document_flow_sends_download_link[True]` | 0.808 | 269 | 24 | 40 |  |
| `tests/test_telegram_client.py::test_document_flow_sends_download_link[False]` | `tests/test_telegram_client.py::test_pdf_ua_warning_survives_worker_and_user_locales_differing[en_US-pt_BR]` | 0.808 | 269 | 30 | 34 |  |
| `tests/test_telegram_client.py::test_document_flow_sends_download_link[False]` | `tests/test_telegram_client.py::test_pdf_ua_warning_survives_worker_and_user_locales_differing[pt_BR-en_US]` | 0.808 | 269 | 30 | 34 |  |
| `tests/test_telegram_client.py::test_document_flow_sends_download_link[True]` | `tests/test_telegram_client.py::test_document_submits_with_mode_and_source` | 0.808 | 269 | 40 | 24 |  |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[cancelled-None-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[cancelling-None-False-True]` | 0.807 | 167 | 18 | 22 | yes |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[cancelled-None-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-failed-False-False]` | 0.807 | 167 | 18 | 22 | yes |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[cancelled-None-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-sent-False-False]` | 0.807 | 167 | 18 | 22 | yes |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[cancelled-None-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-unknown-False-False]` | 0.807 | 167 | 18 | 22 | yes |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[cancelled-None-False-False]` | `tests/test_web_panel.py::test_receipt_recovers_result_after_refresh[failed]` | 0.807 | 167 | 18 | 22 |  |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[cancelled-None-False-False]` | `tests/test_web_panel.py::test_receipt_recovers_result_after_refresh[sent]` | 0.807 | 167 | 18 | 22 |  |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[cancelling-None-False-True]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[error-None-False-False]` | 0.807 | 167 | 22 | 18 | yes |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-failed-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[error-None-False-False]` | 0.807 | 167 | 22 | 18 | yes |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-sent-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[error-None-False-False]` | 0.807 | 167 | 22 | 18 | yes |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-unknown-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[error-None-False-False]` | 0.807 | 167 | 22 | 18 | yes |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[error-None-False-False]` | `tests/test_web_panel.py::test_receipt_recovers_result_after_refresh[failed]` | 0.807 | 167 | 18 | 22 |  |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[error-None-False-False]` | `tests/test_web_panel.py::test_receipt_recovers_result_after_refresh[sent]` | 0.807 | 167 | 18 | 22 |  |
| `tests/test_telegram_client.py::test_document_does_not_consume_another_senders_preferences` | `tests/test_telegram_client.py::test_photo_flow` | 0.804 | 254 | 39 | 23 |  |
| `tests/test_telegram_client.py::test_document_submits_with_mode_and_source` | `tests/test_telegram_client.py::test_photo_flow` | 0.804 | 254 | 39 | 23 |  |
| `tests/test_telegram_client.py::test_document_flow_sends_download_link[False]` | `tests/test_telegram_client.py::test_document_flow_sends_the_download_link_in_the_user_locale` | 0.803 | 269 | 30 | 36 |  |
| `tests/test_telegram_client.py::test_document_flow_sends_download_link[True]` | `tests/test_telegram_client.py::test_document_passes_email_and_notifies` | 0.803 | 269 | 40 | 26 |  |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[cancelling-None-False-True]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-pending-True-False]` | 0.802 | 166 | 23 | 18 | yes |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[cancelling-None-False-True]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-None-True-False]` | 0.802 | 166 | 23 | 18 | yes |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[cancelling-None-False-True]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-pending-True-False]` | 0.802 | 166 | 23 | 18 | yes |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[cancelling-None-False-True]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[queued-None-True-False]` | 0.802 | 166 | 23 | 18 | yes |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-failed-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-pending-True-False]` | 0.802 | 166 | 23 | 18 | yes |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-failed-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-None-True-False]` | 0.802 | 166 | 23 | 18 | yes |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-failed-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-pending-True-False]` | 0.802 | 166 | 23 | 18 | yes |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-failed-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[queued-None-True-False]` | 0.802 | 166 | 23 | 18 | yes |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-pending-True-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-sent-False-False]` | 0.802 | 166 | 18 | 23 | yes |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-pending-True-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-unknown-False-False]` | 0.802 | 166 | 18 | 23 | yes |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-pending-True-False]` | `tests/test_web_panel.py::test_receipt_recovers_result_after_refresh[failed]` | 0.802 | 166 | 18 | 23 |  |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-pending-True-False]` | `tests/test_web_panel.py::test_receipt_recovers_result_after_refresh[sent]` | 0.802 | 166 | 18 | 23 |  |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-sent-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-None-True-False]` | 0.802 | 166 | 23 | 18 | yes |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-sent-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-pending-True-False]` | 0.802 | 166 | 23 | 18 | yes |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-sent-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[queued-None-True-False]` | 0.802 | 166 | 23 | 18 | yes |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-unknown-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-None-True-False]` | 0.802 | 166 | 23 | 18 | yes |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-unknown-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-pending-True-False]` | 0.802 | 166 | 23 | 18 | yes |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[done-unknown-False-False]` | `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[queued-None-True-False]` | 0.802 | 166 | 23 | 18 | yes |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-None-True-False]` | `tests/test_web_panel.py::test_receipt_recovers_result_after_refresh[failed]` | 0.802 | 166 | 18 | 23 |  |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-None-True-False]` | `tests/test_web_panel.py::test_receipt_recovers_result_after_refresh[sent]` | 0.802 | 166 | 18 | 23 |  |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-pending-True-False]` | `tests/test_web_panel.py::test_receipt_recovers_result_after_refresh[failed]` | 0.802 | 166 | 18 | 23 |  |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[processing-pending-True-False]` | `tests/test_web_panel.py::test_receipt_recovers_result_after_refresh[sent]` | 0.802 | 166 | 18 | 23 |  |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[queued-None-True-False]` | `tests/test_web_panel.py::test_receipt_recovers_result_after_refresh[failed]` | 0.802 | 166 | 18 | 23 |  |
| `tests/test_web_panel.py::test_receipt_close_info_only_while_the_email_promise_holds[queued-None-True-False]` | `tests/test_web_panel.py::test_receipt_recovers_result_after_refresh[sent]` | 0.802 | 166 | 18 | 23 |  |

### Parametrized families with identical coverage

| Family | Variants | Lines |
|---|---:|---:|
| `tests/test_toolbox_client_factory.py::test_the_sdk_factory_builds_the_client_the_core_used_to_build` | 408 | 78 |
| `tests/test_core_config.py::test_the_run_config_parameters_are_required` | 78 | 17 |
| `tests/test_manifest_semantic_contract.py::test_core_and_docstruct_reject_the_same_documents` | 46 | 17 |
| `tests/test_run_identity.py::test_a_field_left_out_does_not_change_the_identity` | 27 | 78 |
| `tests/test_run_identity.py::test_a_processing_field_changes_the_identity` | 26 | 78 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core` | 24 | 273 |
| `tests/test_core_config.py::test_the_internal_run_parameters_have_no_default` | 17 | 17 |
| `tests/test_docs_pr125.py::TestDocumentedModulesExist::test_module_is_importable` | 17 | 17 |
| `tests/test_judge_probability.py::test_judge_probability` | 17 | 17 |
| `tests/test_pddl_cache_contract.py::test_merged_cache_policy_requires_success_across_all_stages` | 16 | 17 |
| `tests/test_staging_update.py::test_production_update_accepts_only_verified_healthy_commit_images` | 15 | 17 |
| `tests/test_docstruct_readme_sync.py::TestModulesAreListed::test_english_lists_the_module` | 14 | 17 |
| `tests/test_docstruct_readme_sync.py::TestModulesAreListed::test_mirror_lists_the_module` | 14 | 17 |
| `tests/test_manifest_semantic_contract.py::test_core_reports_docstruct_invariants_in_the_active_locale` | 14 | 17 |
| `tests/test_sdk_result_schemas.py::test_nested_constraints_agree_with_published_schema` | 13 | 17 |
| `tests/test_docstruct_bridges.py::test_adapter_import_check_recognizes_only_absolute_docstruct` | 12 | 17 |
| `tests/test_formula_enrichment.py::test_plan_and_canonical_use_the_same_variable_sources` | 12 | 78 |
| `tests/test_math_case.py::test_structure_recall_normalizes_operatorname_named_operators` | 12 | 17 |
| `tests/test_pending_fixes.py::test_status_without_destination_is_rejected` | 12 | 56 |
| `tests/test_production_deploy.py::test_check_rejects_unsafe_configuration` | 12 | 17 |
| `tests/test_sdk_bindings.py::test_the_size_reader_agrees_with_draft_7` | 12 | 17 |
| `tests/test_sdk_dataset_schema.py::test_sync_discriminator_agrees_with_whole_published_array` | 12 | 17 |
| `tests/test_handler_contract.py::test_the_contract_rejects` | 11 | 17 |
| `tests/test_docstruct_bridges.py::test_the_reexport_check_finds_module_imports` | 10 | 17 |
| `tests/test_manifest_semantic_contract.py::test_core_and_docstruct_keep_the_same_documents` | 10 | 17 |
| `tests/test_n05_n09_n10_regressions.py::test_artifact_id_rejects_trailing_characters` | 10 | 17 |
| `tests/test_region_inspection.py::test_invalid_source_or_region_fails_without_model_call` | 10 | 78 |
| `tests/test_run_identity.py::test_a_processing_provider_changes_the_identity` | 10 | 78 |
| `tests/test_sdk_dataset_schema.py::test_bounds_nullability_and_nested_values` | 10 | 17 |
| `tests/test_sdk_result_schemas.py::test_unsupported_constraints_and_bad_references_fail_explicitly` | 10 | 17 |
| `tests/test_toolbox_math_tools.py::TestMathTools::test_an_answer_outside_the_contract_is_an_unavailable_capability` | 10 | 78 |
| `tests/test_bench_toolbox.py::test_the_guard_sees_every_form_of_a_forbidden_import` | 9 | 17 |
| `tests/test_followup_regressions.py::test_mathml_is_validated_before_html_rendering` | 9 | 17 |
| `tests/test_handler_contract.py::test_the_contract_accepts` | 9 | 17 |
| `tests/test_ops_script.py::test_check_reports_each_problem` | 9 | 17 |
| `tests/test_sdk_result_schemas.py::test_published_examples_and_required_fields` | 9 | 17 |
| `tests/test_region_inspection.py::test_rotated_picture_provenance_renders_only_source_region` | 8 | 78 |
| `tests/test_bench_toolbox.py::test_the_guard_leaves_other_imports_alone` | 7 | 17 |
| `tests/test_core_test_fixture_parity.py::test_the_core_copy_matches_the_service_fixture` | 7 | 17 |
| `tests/test_docs_pr125.py::TestDocPairsExist::test_both_languages_exist` | 7 | 17 |
| `tests/test_docs_pr125.py::TestDocPairsExist::test_language_links_are_bidirectional` | 7 | 17 |
| `tests/test_docs_pr125.py::TestDomainVersionIsConsistent::test_no_stale_domain_version` | 7 | 17 |
| `tests/test_math_case.py::test_non_item_content_ends_a_list_run` | 7 | 17 |
| `tests/test_pddl_cache_contract.py::test_execution_configuration_invalidates_document_cache` | 7 | 97 |
| `tests/test_pdf_ua_export.py::test_toolbox_pdf_ua_enabled_is_parsed_from_the_environment` | 7 | 212 |
| `tests/test_picture_without_page.py::test_only_an_embedded_raster_image_is_decoded` | 7 | 78 |
| `tests/test_run_identity.py::test_the_fusion_reuse_identity_follows_each_option` | 7 | 78 |
| `tests/test_sdk_layout_schema.py::test_mineru_nested_constraints` | 7 | 17 |
| `tests/test_toolbox_manifest_extractor.py::test_a_structure_answer_outside_the_contract_is_a_typed_failure` | 7 | 78 |
| `tests/test_docstruct_bridges.py::test_adapter_only_wraps` | 6 | 17 |
| `tests/test_docstruct_bridges.py::test_bridge_imports_from_docstruct` | 6 | 17 |
| `tests/test_followup_regressions.py::test_document_cache_changes_with_model_and_provider` | 6 | 97 |
| `tests/test_formula_crop.py::test_an_unusable_box_is_silent_whatever_the_source` | 6 | 78 |
| `tests/test_math_case.py::test_structure_recall_equates_trailing_quad_label_with_tag` | 6 | 17 |
| `tests/test_page_limit.py::test_unreliable_preflight_does_not_reject` | 6 | 78 |
| `tests/test_pddl_audit_fixes.py::test_unusable_table_does_not_satisfy_obligation` | 6 | 78 |
| `tests/test_pddl_cache_contract.py::test_a_run_the_vision_model_failed_is_not_cacheable` | 6 | 17 |
| `tests/test_pddl_payload_lists_and_callouts.py::test_empty_items_with_incompatible_markers_leave_sibling_text_alone` | 6 | 17 |
| `tests/test_sdk_dataset_schema.py::test_each_record_matches_its_source_schema` | 6 | 17 |
| `tests/test_slides.py::test_content_on_a_picture_that_is_not_a_label_stays` | 6 | 17 |
| `tests/test_trilha_a_regressions.py::test_pddl_cache_policy` | 6 | 17 |
| `tests/test_docstruct_bridges.py::test_the_reexport_check_keeps_adapters_and_other_imports` | 5 | 17 |
| `tests/test_docstruct_readme_sync.py::TestPresetsAreListed::test_english_lists_the_preset` | 5 | 17 |
| `tests/test_docstruct_readme_sync.py::TestPresetsAreListed::test_mirror_lists_the_preset` | 5 | 17 |
| `tests/test_docx_export.py::test_toolbox_docx_enabled_is_parsed_from_the_environment` | 5 | 212 |
| `tests/test_i18n.py::test_a_locale_variant_finds_its_catalog` | 5 | 17 |
| `tests/test_math_case.py::test_structure_recall_equates_equivalent_commands` | 5 | 17 |
| `tests/test_pddl_cache_contract.py::test_records_visual_failures` | 5 | 17 |
| `tests/test_provider_choice_methods.py::TestVlmPairwiseJudge::test_answer_without_valid_pb_fails_instead_of_keeping_the_primary` | 5 | 78 |
| `tests/test_run_identity.py::test_a_run_with_other_options_does_not_reuse_the_fusion` | 5 | 78 |
| `tests/test_sdk_bindings.py::test_a_root_constraint_the_reader_would_not_enforce_is_refused` | 5 | 17 |
| `tests/test_sdk_bindings.py::test_the_model_generator_refuses_what_it_cannot_express` | 5 | 17 |
| `tests/test_sdk_dataset_schema.py::test_precise_array_roots_including_empty_and_invalid` | 5 | 17 |
| `tests/test_slide_case.py::test_normalization_reads_scripts_dashes_and_broken_lines_alike` | 5 | 17 |
| `tests/test_slides.py::test_text_across_slides_without_usable_offsets_stays_whole` | 5 | 17 |
| `tests/test_toolbox_snapshot.py::test_live_capture_cannot_overwrite_any_fixture` | 5 | 17 |
| `tests/test_toolbox_snapshot.py::test_non_object_contract_is_a_cli_error_without_partial_writes` | 5 | 17 |
| `tests/test_vision_payload.py::test_non_positive_or_invalid_scale_returns_none_without_building_client` | 5 | 78 |
| `tests/test_api_client.py::test_non_object_http_error_preserves_api_error_status` | 4 | 43 |
| `tests/test_audit_export_regressions.py::test_complete_plan_repairs_invalid_heading_sequence` | 4 | 78 |
| `tests/test_checkpoint_identity.py::test_a_partial_or_unreadable_identity_is_not_a_match` | 4 | 78 |
| `tests/test_cleanup_service.py::test_age_cleanup_preserves_valid_download_references` | 4 | 124 |

### Tests with no exclusive line

These tests cover no line that another test in the same report does not also cover. They are the strongest overlap candidates, not a verdict: they can still be the only one checking a contract or an error message.

| Test | Lines |
|---|---:|
| `tests/test_long_output_filenames.py::test_long_filename_can_be_exported_and_downloaded[long-ascii]` | 605 |
| `tests/test_long_output_filenames.py::test_long_filename_can_be_exported_and_downloaded[long-cjk]` | 605 |
| `tests/test_long_output_filenames.py::test_long_filename_can_be_exported_and_downloaded[long-greek]` | 605 |
| `tests/test_long_output_filenames.py::test_long_filename_can_be_exported_and_downloaded[short]` | 599 |
| `tests/test_cancellation_queue.py::test_cancelled_extraction_advances_queue_and_reports_wait` | 571 |
| `tests/test_pending_fixes.py::test_email_delivery_status_does_not_lose_download[False]` | 455 |
| `tests/test_pending_fixes.py::test_email_delivery_status_does_not_lose_download[True]` | 454 |
| `tests/test_pending_fixes.py::test_result_email_reports_open_obligations_of_a_delivered_document` | 454 |
| `tests/test_object_markers.py::test_the_worker_marks_what_a_reader_gets_and_stores_the_document_unmarked` | 438 |
| `tests/test_job_progress.py::test_a_broken_failure_email_keeps_the_job_error_and_records_the_failure` | 429 |
| `tests/test_pddl_audit_fixes.py::test_failed_plan_marks_api_job_error_without_caching_or_download` | 426 |
| `tests/test_job_progress.py::test_pipeline_failure_names_the_stage_once_and_emails_the_user` | 417 |
| `tests/test_api.py::test_job_executor_reports_optional_export_failure[DOCX]` | 406 |
| `tests/test_api.py::test_job_executor_reports_optional_export_failure[MP3]` | 404 |
| `tests/test_worker_pipeline_failure.py::test_job_executor_does_not_export_pipeline_failure` | 403 |
| `tests/test_api.py::test_job_executor_reports_optional_export_failure[DOCX disabled]` | 400 |
| `tests/test_api.py::test_job_executor_reports_optional_export_failure[None]` | 398 |
| `tests/test_api.py::test_job_executor_reports_optional_export_failure[PDF/UA]` | 397 |
| `tests/test_pending_fixes.py::test_active_cancel_interrupts_pipeline_and_advances_queue` | 394 |
| `tests/test_trilha_a_regressions.py::test_pddl_recovery_policy_controls_real_cache_replay[completed-normalize-text-False-2]` | 390 |
| `tests/test_trilha_a_regressions.py::test_pddl_recovery_policy_controls_real_cache_replay[completed-recover-formula-True-2]` | 390 |
| `tests/test_trilha_a_regressions.py::test_pddl_recovery_policy_controls_real_cache_replay[failed-None-False-2]` | 390 |
| `tests/test_trilha_a_regressions.py::test_pddl_recovery_policy_controls_real_cache_replay[replan-required-None-False-2]` | 390 |
| `tests/test_trilha_a_regressions.py::test_pddl_recovery_policy_controls_real_cache_replay[completed-normalize-text-True-1]` | 384 |
| `tests/test_api.py::test_job_executor_reports_optional_export_failure[PDF/UA disabled]` | 383 |
| `tests/test_trilha_a_regressions.py::test_pddl_recovery_policy_controls_real_cache_replay[completed-None-False-1]` | 380 |
| `tests/test_api.py::test_job_executor_keeps_original_filename_in_status` | 378 |
| `tests/test_api.py::test_job_executor_marks_history_error_when_export_fails[zip]` | 378 |
| `tests/test_api.py::test_job_executor_marks_history_error_when_export_fails[html]` | 320 |
| `tests/test_api.py::test_job_executor_marks_history_error_when_export_fails[txt]` | 314 |
| `tests/test_telegram_client.py::test_document_flow_sends_download_link[True]` | 309 |
| `tests/test_telegram_client.py::test_document_flow_sends_the_download_link_in_the_user_locale` | 305 |
| `tests/test_pddl_cache_contract.py::test_cached_degraded_entry_is_ignored[single-provider-extraction-degraded-rerun]` | 303 |
| `tests/test_telegram_client.py::test_pdf_ua_warning_survives_worker_and_user_locales_differing[en_US-pt_BR]` | 303 |
| `tests/test_telegram_client.py::test_pdf_ua_warning_survives_worker_and_user_locales_differing[pt_BR-en_US]` | 303 |
| `tests/test_pddl_cache_contract.py::test_cached_degraded_entry_is_ignored[single-provider-extraction-clean-rerun]` | 302 |
| `tests/test_pddl_cache_contract.py::test_cached_degraded_entry_is_ignored[visual-failures-degraded-rerun]` | 302 |
| `tests/test_pddl_cache_contract.py::test_cached_degraded_entry_is_ignored[visual-failures-clean-rerun]` | 301 |
| `tests/test_pddl_cache_contract.py::test_degraded_processing_is_not_cached[False]` | 299 |
| `tests/test_telegram_client.py::test_document_flow_sends_download_link[False]` | 299 |
| `tests/test_pddl_cache_contract.py::test_cached_entry_with_failed_media_inspection_is_ignored` | 297 |
| `tests/test_telegram_client.py::test_document_passes_email_and_notifies` | 295 |
| `tests/test_telegram_client.py::test_concurrent_group_users_keep_preferences_and_tasks_isolated` | 293 |
| `tests/test_telegram_client.py::test_document_does_not_consume_another_senders_preferences` | 293 |
| `tests/test_telegram_client.py::test_document_submits_with_mode_and_source` | 293 |
| `tests/test_job_resume.py::test_a_resumed_run_restores_progress_and_skips_the_confirmation` | 290 |
| `tests/test_pddl_cache_contract.py::test_live_processing_rejects_incompatible_cached_execution[dry-run-completed]` | 287 |
| `tests/test_pddl_cache_contract.py::test_live_processing_rejects_incompatible_cached_execution[failed]` | 286 |
| `tests/test_pddl_cache_contract.py::test_live_processing_rejects_incompatible_cached_execution[replan-required]` | 286 |
| `tests/test_pddl_cache_contract.py::test_degraded_processing_is_not_cached[True]` | 285 |
| `tests/test_untitled_document_name.py::test_the_processing_cache_is_keyed_by_the_job_config` | 275 |
| `tests/test_untitled_document_name.py::test_without_an_uploaded_name_the_file_name_is_still_the_fallback` | 275 |
| `tests/test_untitled_document_name.py::test_a_client_path_in_the_uploaded_name_is_reduced_to_the_name[../../etc/relat\xf3rio.pdf]` | 274 |
| `tests/test_untitled_document_name.py::test_a_client_path_in_the_uploaded_name_is_reduced_to_the_name[..\\..\\etc\\relat\xf3rio.pdf]` | 274 |
| `tests/test_untitled_document_name.py::test_a_client_path_in_the_uploaded_name_is_reduced_to_the_name[..\\etc/relat\xf3rio.pdf]` | 274 |
| `tests/test_untitled_document_name.py::test_a_client_path_in_the_uploaded_name_is_reduced_to_the_name[C:\\fakepath\\relat\xf3rio.pdf]` | 274 |
| `tests/test_untitled_document_name.py::test_the_canonical_build_takes_the_job_toolbox_config[processed]` | 274 |
| `tests/test_untitled_document_name.py::test_untitled_document_takes_the_uploaded_name[processed]` | 274 |
| `tests/test_api.py::test_job_executor_records_early_process_failure` | 273 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxDatasetClient-budgets]` | 273 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxDatasetClient-defaults]` | 273 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxDatasetClient-empty provider]` | 273 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxDatasetClient-endpoints list wins]` | 273 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxDatasetClient-provider]` | 273 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxDatasetClient-single endpoint]` | 273 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxMathClient-budgets]` | 273 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxMathClient-defaults]` | 273 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxMathClient-empty provider]` | 273 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxMathClient-endpoints list wins]` | 273 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxMathClient-provider]` | 273 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxMathClient-single endpoint]` | 273 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxPdfClient-budgets]` | 273 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxPdfClient-defaults]` | 273 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxPdfClient-empty provider]` | 273 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxPdfClient-endpoints list wins]` | 273 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxPdfClient-provider]` | 273 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxPdfClient-single endpoint]` | 273 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxStructureClient-budgets]` | 273 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxStructureClient-defaults]` | 273 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxStructureClient-empty provider]` | 273 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxStructureClient-endpoints list wins]` | 273 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxStructureClient-provider]` | 273 |
| `tests/test_bench_toolbox.py::test_the_harness_configures_clients_like_the_core[ToolboxStructureClient-single endpoint]` | 273 |
| `tests/test_api.py::test_cancel_reports_a_requested_remote_cancellation` | 267 |
| `tests/test_job_resume.py::test_a_graceful_shutdown_keeps_the_operation_journal` | 267 |
| `tests/test_untitled_document_name.py::test_the_canonical_build_takes_the_job_toolbox_config[cache-hit]` | 224 |
| `tests/test_untitled_document_name.py::test_untitled_document_takes_the_uploaded_name[cache-hit]` | 224 |
| `tests/test_docx_export.py::test_toolbox_docx_enabled_is_parsed_from_the_environment[0-False]` | 212 |
| `tests/test_docx_export.py::test_toolbox_docx_enabled_is_parsed_from_the_environment[None-True]` | 212 |
| `tests/test_docx_export.py::test_toolbox_docx_enabled_is_parsed_from_the_environment[SIM-True]` | 212 |
| `tests/test_docx_export.py::test_toolbox_docx_enabled_is_parsed_from_the_environment[false-False]` | 212 |
| `tests/test_docx_export.py::test_toolbox_docx_enabled_is_parsed_from_the_environment[true-True]` | 212 |
| `tests/test_i18n_locales.py::test_settings_defaults_to_the_supported_locales` | 212 |
| `tests/test_i18n_locales.py::test_settings_reads_i18n_locales_active_with_the_shared_parser` | 212 |
| `tests/test_object_markers.py::test_markers_are_off_by_default` | 212 |
| `tests/test_page_limit.py::test_max_pages_is_read_from_the_environment` | 212 |
| `tests/test_pdf_ua_export.py::test_toolbox_pdf_ua_enabled_is_parsed_from_the_environment[0-False]` | 212 |
| `tests/test_pdf_ua_export.py::test_toolbox_pdf_ua_enabled_is_parsed_from_the_environment[1-True]` | 212 |
| `tests/test_pdf_ua_export.py::test_toolbox_pdf_ua_enabled_is_parsed_from_the_environment[None-True]` | 212 |
| `tests/test_pdf_ua_export.py::test_toolbox_pdf_ua_enabled_is_parsed_from_the_environment[SIM-True]` | 212 |
