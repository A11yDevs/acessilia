#!/usr/bin/env python3
"""Generate Babel locale string catalogs (.po sources and .mo binaries) for every supported runtime locale.

Catalogs are written to ``backend/locales/<LOCALE>/LC_MESSAGES/messages.po`` (human-editable translation source)
after compiling each into the matching ``messages.mo`` consumed at runtime by :mod:`backend.i18n`. Adding a new
locale later only requires extending TRANSLATIONS with its mapping and rerunning this script, which matches the
project i18n goal of requiring zero or minimal code changes per added language.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from backend.core.execution.messages import (
    EXE_COMPLETED_OBLIGATIONS_UNSATISFIED,
    EXE_DRY_RUN_SIMULATED,
    EXE_DOMAIN_DESCRIPTION_CHANGED,
    EXE_DOMAIN_PDDL_CHANGED,
    EXE_JOB_NOT_PROCESSING,
    EXE_MANIFEST_CHANGED_AFTER_PLANNING,
    EXE_METHOD_ALREADY_TRIED,
    EXE_METHOD_NAME_REQUIRED,
    EXE_METHOD_NOT_ADMISSIBLE,
    EXE_NO_HANDLER_REGISTERED,
    EXE_OBLIGATION_ALREADY_SATISFIED,
    EXE_OBLIGATION_KIND_MISMATCH,
    EXE_OBLIGATION_NOT_FOUND,
    EXE_OBLIGATION_NOT_SELECTED,
    EXE_PLAN_DIFFERENT_DOMAIN,
    EXE_PLAN_DOMAIN_VERSION_INCOMPATIBLE,
    EXE_PLAN_OTHER_MANIFEST,
    EXE_PLAN_REVISION_MISMATCH,
    EXE_PLAN_UNKNOWN_OBLIGATIONS,
    EXE_PREDECESSORS_UNSATISFIED,
    EXE_RESULT_REJECTED,
    EXE_START_JOB_INVALID_STATE,
    EXE_UNKNOWN_ACTION,
)
from backend.core.manifest.docling_extractor import (
    MSG_DOCLING_MISSING,
    MSG_INCOMPATIBLE_STRUCTURER,
    MSG_SOURCE_NOT_FOUND,
)
from backend.log_messages import (
    API_INTERNAL_ERROR_DETAIL,
    API_RATE_LIMIT_DETAIL,
    EMAIL_CONFIRMATION_BODY,
    EMAIL_CONFIRMATION_SUBJECT,
    EMAIL_FORMAT_DOCX,
    EMAIL_FORMAT_HTML,
    EMAIL_FORMAT_MP3,
    EMAIL_FORMAT_PDF,
    EMAIL_FORMAT_PDF_UA,
    EMAIL_FORMAT_TXT,
    EMAIL_FORMAT_ZIP,
    EMAIL_RESULT_BODY_ATTACHED,
    EMAIL_RESULT_BODY_WITH_LINK,
    EMAIL_RESULT_SUBJECT,
    EMAIL_RESULT_WARNINGS_HEADER,
    LOG_AGNO_NOT_INSTALLED,
    LOG_API_ERROR,
    LOG_API_INTERFACE_ENABLED,
    LOG_API_JOB_ENQUEUED,
    LOG_API_STARTED,
    LOG_AUDIO_EXPORTED,
    LOG_AUDIO_EXPORT_ERROR,
    LOG_AUDIO_EXPORT_PROGRESS,
    LOG_AUDIO_EXPORT_START,
    LOG_BOT_ALREADY_RUNNING,
    LOG_BOT_INTERRUPTED_BY_USER,
    LOG_BOT_SHUTTING_DOWN,
    LOG_BOT_STARTED,
    LOG_BOT_STARTING_POLLING,
    LOG_BOT_TOKEN_NOT_CONFIGURED,
    LOG_CANONICAL_JSON_SAVE_FAILED,
    LOG_CACHE_CLEARED,
    LOG_CACHE_DEBUG_HIT,
    LOG_CACHE_DEBUG_SET,
    LOG_CACHE_HIT,
    LOG_CACHE_SAVE_FAILED,
    LOG_DATA_AGENT_PROMPT_NOT_FOUND,
    LOG_DATA_AGENT_PROCESSING_REGION,
    LOG_DATA_AGENT_REGION_ERROR,
    LOG_VISION_AGENT_REGION_ERROR,
    LOG_VISION_AGENT_SENDING_REGION,
    LOG_EDITOR_PAGE_EMPTY,
    LOG_EDITOR_PAGE_CONSOLIDATED,
    LOG_CLEANUP_ITEM_FAILED,
    LOG_CLEANUP_OUTPUT_FAILED,
    LOG_CLEANUP_PERIODIC_ERROR,
    LOG_DOCLING_NOT_AVAILABLE,
    LOG_DOCLING_PAGE_FAILED,
    LOG_DOCLING_PAGE_NO_PARENT,
    LOG_DOCLING_PROCESSED,
    LOG_DOWNLOAD_TOKEN_CREATED,
    LOG_DOWNLOAD_TOKEN_DIR_MISSING,
    LOG_DOWNLOAD_TOKEN_NOT_FOUND,
    LOG_EMAIL_SEND_ERROR,
    LOG_EMAIL_SENT,
    LOG_EXPORT_DOCX_START,
    LOG_EXPORT_MP3_START,
    LOG_EXPORT_PDF_START,
    LOG_EXPORT_PDF_UA_START,
    LOG_EXPORT_TXT_START,
    LOG_PAGE_CONVERTED_TO_PNG,
    LOG_FATAL_ERROR_IN_BOT,
    LOG_IMAGE_PREPROCESS_FAILED,
    LOG_IMAGE_RESIZED,
    LOG_IMAGE_ROTATED,
    LOG_JOB_CANCELLED,
    LOG_JOB_COMPLETED,
    LOG_JOB_EXECUTOR_ERROR,
    LOG_LOCK_ACQUIRED,
    LOG_LOCK_FILE_STALE,
    LOG_LOCK_RELEASED,
    LOG_LOGGER_CONFIGURED,
    LOG_MP3_GENERATION_FAILED,
    LOG_NO_INTERFACE_ENABLED,
    LOG_ORCHESTRATOR_EMPTY_AGENT_RESPONSE,
    LOG_ORCHESTRATOR_EMPTY_PAGE_RESPONSE,
    LOG_ORCHESTRATOR_PAGE_CACHE_SKIP,
    LOG_ORCHESTRATOR_PAGE_RESPONSE_SAVED,
    LOG_ORCHESTRATOR_WAITING_TASKS,
    LOG_ORCHESTRATOR_TASK_FAILED,
    LOG_ORCHESTRATOR_WORKFLOW_START,
    LOG_ORCHESTRATOR_WORKFLOW_SUMMARY,
    LOG_ORPHAN_TASKS_CLEANED,
    LOG_ORPHAN_TASKS_CLEANUP_FAILED,
    LOG_OUTPUT_DIR_REMOVED,
    LOG_PAGE_CONVERTED_TO_PNG,
    LOG_PDDL_IGNORED_OPTIONS,
    LOG_PDDL_IMAGES_ENRICHED,
    LOG_PDDL_TABLES_ENRICHED,
    LOG_PDDL_ELEMENT_CROP_FAILED,
    LOG_PDDL_EXTRACTOR_BACKEND_INVALID,
    LOG_PDDL_PREFERRED_PLAN_MISSING,
    LOG_PDDL_PROBLEM_HASH_MISMATCH,
    LOG_PDDL_DOMAIN_HASH_MISMATCH,
    LOG_PDDL_DOMAIN_DESCRIPTION_HASH_MISMATCH,
    LOG_PDDL_SELECTED_CLOSURE_MISMATCH,
    LOG_PDF_PAGE_COUNT_LOGGED,
    LOG_PDF_PAGE_SAVED,
    LOG_PDF_PAGES_EXTRACTED,
    LOG_PDF_UA_GENERATION_FAILED,
    LOG_PDF_EXPORTED,
    LOG_PDF_UA_EXPORTED,
    LOG_TXT_EXPORTED,
    LOG_DOCX_EXPORTED,
    LOG_PIPELINE_ERROR,
    LOG_REGION_CROP_FAILED,
    LOG_PROMPT_FILE_NOT_FOUND,
    LOG_READER_PDF_REGIONS_EXTRACTED,
    LOG_READER_CLEAN_TEXT_REGIONS,
    LOG_READER_REGION_TASK,
    LOG_READER_FULL_PAGE_FALLBACK,
    LOG_READER_TASKS_SUMMARY,
    LOG_READER_IMAGE_READING,
    LOG_QUEUE_ITEM_ENQUEUED,
    LOG_RAPIDOCR_MODELS_PERSISTED,
    LOG_RAPIDOCR_MODELS_RESTORED,
    LOG_STRUCTURER_DOCLING,
    LOG_STRUCTURER_DOCLING_NOT_INSTALLED,
    LOG_STRUCTURER_FALLBACK_PYMUPDF,
    LOG_STRUCTURER_PYMUPDF,
    LOG_SMTP_NOT_CONFIGURED,
    LOG_STARTING_INTERFACES,
    LOG_STALE_PROCESS_INTERRUPTED,
    LOG_STATUS_EDIT_UNEXPECTED,
    LOG_STATUS_MESSAGE_EDIT_FAILED,
    LOG_STATUS_MESSAGE_SEND_FAILED,
    LOG_TASK_CANCELLED_BY_USER,
    LOG_TEMP_DIR_REMOVED,
    LOG_TEMP_FILE_REMOVED,
    LOG_TELEGRAM_FILE_DOWNLOADING,
    LOG_TELEGRAM_FILE_DOWNLOADED,
    LOG_TELEGRAM_API_JOB_REJECTED,
    LOG_TELEGRAM_API_CONTACT_FAILED,
    LOG_TELEGRAM_FILE_PROCESSING_ERROR,
    LOG_TELEGRAM_JOB_STATUS_QUERY_FAILED,
    LOG_TELEGRAM_RATE_LIMIT_WAIT,
    LOG_TELEGRAM_SEND_FAILED_AFTER_RETRIES,
    LOG_TELEGRAM_FEEDBACK_RECEIVED,
    LOG_TELEGRAM_UNHANDLED_ERROR,
    LOG_TELEGRAM_INTERFACE_ENABLED,
    LOG_TELEGRAM_INTERFACE_NO_TOKEN,
    LOG_WEB_API_UPLOAD_ERROR,
    LOG_WEB_DOWNLOAD_QUERY_FAILED,
    LOG_WEB_GLOBAL_ERROR,
    LOG_WEB_HTTP_EXCEPTION,
    LOG_WEB_INTERFACE_ENABLED,
    LOG_WEB_RATE_LIMIT_EXCEEDED,
    LOG_WEB_UPLOAD_ERROR,
    LOG_WORKER_STARTED,
    LOG_WORKER_TASK_COMPLETED,
    LOG_WORKER_TASK_ERROR,
    LOG_WORKER_TASK_STARTING,
)
from backend.pipeline.validators import (
    MSG_BLOCK_NOT_ALLOWED_IN_PROFILE,
    MSG_CANONICAL_DOC_NOT_OBJECT,
    MSG_DOCUMENT_NO_SECTIONS,
    MSG_DUPLICATE_ID,
    MSG_FIELD_MISSING,
    MSG_HEADING_LEVELS_SKIPPED,
    MSG_IMAGE_MISSING_ALT,
    MSG_INCONSISTENT_CODE_INDENT,
    MSG_INTERNAL_LINK_BROKEN,
    MSG_MARKDOWN_IN_BLOCK,
    MSG_MARKDOWN_IN_OUTPUT,
    MSG_MISSING_FIRST_H1,
    MSG_MULTIPLE_H1,
    MSG_NO_ID_PLACEHOLDER,
    MSG_PROMPT_LEAK_IN_BLOCK,
    MSG_PROMPT_LEAK_IN_OUTPUT,
    MSG_SECTIONS_NOT_LIST,
    MSG_TABLE_AST_CELL_INVALID,
    MSG_TABLE_AST_CELL_NO_TEXT,
    MSG_TABLE_AST_INVALID,
    MSG_TABLE_AST_NO_BODY,
    MSG_TABLE_AST_ROW_INVALID,
    MSG_TABLE_AST_ROW_NO_CELLS,
    MSG_TABLE_AST_SECTION_INVALID,
    MSG_TABLE_AST_WIDTH_INCONSISTENT,
    MSG_TABLE_CELL_EMPTY,
    MSG_TABLE_CELL_NOT_TEXT,
    MSG_TABLE_COLUMNS_INCONSISTENT,
    MSG_TABLE_EMPTY,
    MSG_TABLE_LEGACY_FALLBACK,
    MSG_TABLE_MISSING_HEADER,
    MSG_TABLE_ROW_INVALID,
    MSG_TABLE_ROWS_INVALID,
    MSG_TECHNICAL_METADATA_IN_TXT,
    MSG_UNKNOWN_EXPORT_PROFILE,
)
from backend.export.pandoc_exporter import (
    MSG_AUDIT_FAILED,
    MSG_DEFAULT_ACCESSIBLE_TITLE,
    MSG_LATEX_ENGINE_NOT_FOUND,
    MSG_PANDOC_FAILED,
    MSG_PANDOC_NOT_FOUND,
    MSG_PANDOC_REQUIRED_FOR_PDF_UA,
    MSG_PDF_UA_TEMPLATE_NOT_FOUND,
    MSG_UNSUPPORTED_EXPORT_FORMAT,
)
from backend.export.renderers.html_renderer import (
    MSG_HTML_IMAGE_DESCRIPTION,
    MSG_HTML_TABLE_OF_CONTENTS,
    MSG_HTML_TECHNICAL_METADATA,
)
from backend.export.renderers.pdf_renderer import (
    MSG_PDF_NOTE_LABEL,
    MSG_PDF_TABLE_OF_CONTENTS,
    MSG_PDF_WARNING_LABEL,
)
from backend.pipeline.table_ast import (
    MSG_TABLE_TEXT_CAPTION,
    MSG_TABLE_TEXT_FOOTER,
    MSG_TABLE_TEXT_ROW,
)
from backend.stage_messages import (
    STAGE_ANALYZING_FILE,
    STAGE_ANALYZING_STRUCTURAL,
    STAGE_CANCELLED_BY_USER,
    STAGE_CANCELLED_IN_QUEUE,
    STAGE_ENQUEUED_WAITING,
    STAGE_ENRICHING_IMAGE_DESCRIPTIONS,
    STAGE_ENRICHING_TABLES_OCR,
    STAGE_EXPORTING_DOCX,
    STAGE_EXPORTING_HTML,
    STAGE_EXPORTING_PDF,
    STAGE_EXPORTING_PDF_UA,
    STAGE_EXPORTING_TXT,
    STAGE_GENERATING_AUDIO,
    STAGE_GENERATING_PDDL_PLAN,
    STAGE_PREPARING_FILE,
    STAGE_PREPARING_IMAGE,
    STAGE_PROCESSING_COMPLETED,
    STAGE_PROCESSING_FAILED_LABEL,
    STAGE_PROCESSING_FAILURE,
    STAGE_PROCESSING_FINISHED,
    STAGE_PROCESSING_PAGE,
    STAGE_PROCESSING_WITH_AI,
    STAGE_QUEUE_WAITING_POSITION,
    STAGE_SPLITTING_PDF_PAGES,
    STAGE_VALIDATING_PLAN_DRY_RUN,
)
from backend.tools.validators import MSG_FILE_TOO_LARGE, MSG_UNSUPPORTED_FORMAT
from frontend.web.messages import (
    WEB_AGENT_DATA_DESCRIPTION,
    WEB_AGENT_DATA_INSTRUCTIONS_FALLBACK,
    WEB_AGENT_OS_DESCRIPTION,
    WEB_AGENT_VISION_DESCRIPTION,
    WEB_ADVANCED_BACK_LINK,
    WEB_ADVANCED_HEADLINE,
    WEB_ADVANCED_INTRO,
    WEB_ADVANCED_PROMPT_HELP,
    WEB_ADVANCED_PROMPT_LABEL,
    WEB_ADVANCED_PROMPT_PLACEHOLDER,
    WEB_ADVANCED_SUBHEAD,
    WEB_ADVANCED_THINKING_LABEL,
    WEB_ADVANCED_TITLE,
    WEB_DOWNLOAD_HEADLINE,
    WEB_DOWNLOAD_NO_FORMATS,
    WEB_DOWNLOAD_SUBHEAD,
    WEB_DOWNLOAD_TITLE,
    WEB_DOWNLOAD_VALID_NOTE,
    WEB_ERROR_API_UPLOAD,
    WEB_ERROR_DOWNLOAD_INVALID,
    WEB_ERROR_DOWNLOAD_UNAVAILABLE,
    WEB_ERROR_INTERNAL,
    WEB_ERROR_PROMPT_TOO_LONG,
    WEB_ERROR_UPLOAD_GENERIC,
    WEB_FORMAT_DOCX,
    WEB_FORMAT_HTML,
    WEB_FORMAT_MP3,
    WEB_FORMAT_PDF,
    WEB_FORMAT_TXT,
    WEB_FORMAT_ZIP,
    WEB_FOOTER,
    WEB_INDEX_ADVANCED_LINK,
    WEB_INDEX_DOC_LABEL,
    WEB_INDEX_EMAIL_HELP,
    WEB_INDEX_EMAIL_LABEL,
    WEB_INDEX_HEADLINE,
    WEB_INDEX_INTRO,
    WEB_INDEX_SUBMIT_BUTTON,
    WEB_INDEX_TITLE,
    WEB_LOGO_ALT,
    WEB_RATE_LIMIT_EXCEEDED,
    WEB_SUCCESS_QUEUED,
)
from frontend.telegram.messages import (
    MSG_ACCESSIBLE_PACKAGE_READY,
    MSG_API_FILE_NOT_FOUND,
    MSG_API_FORMAT_INVALID,
    MSG_API_JOB_QUEUED,
    MSG_API_LINK_INVALID,
    MSG_API_PROMPT_TOO_LONG,
    MSG_API_TASK_NOT_FOUND,
    MSG_ACTION_REJECTS_EXECUTION_PARAMETERS,
    MSG_BOT_PAUSED,
    MSG_BOT_RESUMED,
    MSG_CACHE_CLEARED,
    MSG_CANCEL_NO_TASK,
    MSG_COMPARISON_OUTCOME_KEY_MISMATCH,
    MSG_COMPARISON_REQUIRES_BOTH_BACKENDS,
    MSG_CONTACT_SERVER_FAILED,
    MSG_DOWNLOADING_FILE,
    MSG_DOWNLOAD_LINK_EMAILED,
    MSG_EMAIL_CONFIGURED,
    MSG_EMAIL_HINT,
    MSG_EXECUTION_REPORT_SCHEMA_DESCRIPTION,
    MSG_EXPECTED_TOTAL_COST_MISMATCH,
    MSG_EXECUTE_OBLIGATION_MISSING_FIELDS,
    MSG_FEEDBACK_PROMPT,
    MSG_FEEDBACK_THANKS,
    MSG_FILE_RECEIVED,
    MSG_FORMATS_TEXT,
    MSG_HEALTH_ACTIVE_MODEL,
    MSG_HEALTH_DISK_FREE,
    MSG_HEALTH_TEMP_MISSING,
    MSG_HEALTH_TEMP_OK,
    MSG_HELP_TEXT,
    MSG_HEADING_GAP,
    MSG_METHOD_RESULT_DUPLICATE_ARTIFACT_IDS,
    MSG_METHOD_RESULT_SUCCESS_REQUIRES_VALIDATION,
    MSG_MODE_BAIXO_ON,
    MSG_MODE_DETAILED_ON,
    MSG_MODE_MEDIO_ON,
    MSG_MODE_NORMAL_ON,
    MSG_MODE_OCR_ON,
    MSG_NOMINAL_PLAN_MUST_END_COMPLETE_JOB,
    MSG_NOMINAL_PLAN_SCHEMA_DESCRIPTION,
    MSG_NO_TASK_REGISTERED,
    MSG_OBLIGATION_CODE,
    MSG_OBLIGATION_FORMULA,
    MSG_OBLIGATION_IMAGE,
    MSG_OBLIGATION_TABLE,
    MSG_OBLIGATION_UNKNOWN,
    MSG_OLLAMA_OFFLINE,
    MSG_OLLAMA_ONLINE,
    MSG_OLLAMA_UNEXPECTED,
    MSG_PHOTO_RECEIVED,
    MSG_PLAN_CONTAINS_UNSELECTED_OBLIGATION,
    MSG_PLAN_INDICES_CONSECUTIVE_FROM_ZERO,
    MSG_PLANNER_NOT_STARTED,
    MSG_PLANNER_OUTCOME_FAILED_MUST_NOT_PASS_VALIDATION,
    MSG_PLANNER_OUTCOME_FAILED_REQUIRES_ERROR,
    MSG_PLANNER_OUTCOME_MUST_PASS_VALIDATION,
    MSG_PLANNER_OUTCOME_SOLVED_MUST_NOT_CARRY_ERROR,
    MSG_PLANNER_OUTCOME_SOLVED_REQUIRES_FIELDS,
    MSG_PLANNING_COMPARISON_SCHEMA_DESCRIPTION,
    MSG_PROCESS_FAILED_BASE,
    MSG_PROCESSING_ERROR_GENERIC,
    MSG_PROCESSING_TIMEOUT,
    MSG_QUEUE_POSITION,
    MSG_SOURCE_FILE_MISSING,
    MSG_START_TEXT,
    MSG_STATUS_CONVERSION_DONE,
    MSG_STATUS_NO_TASK,
    MSG_STATUS_PROCESSING_FAILED,
    MSG_STATUS_SUMMARY,
    MSG_STATUS_TASK_NOT_FOUND,
    MSG_SUBMIT_FAILED,
    MSG_TASK_CANCELLED,
    MSG_TASK_CANCEL_DONE,
    MSG_TASK_CANCEL_FAILED,
    MSG_TASK_ENQUEUED,
    MSG_WAITING_IN_QUEUE,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCALES_DIR: Path = PROJECT_ROOT / "backend" / "locales"
SUPPORTED_LOCALES: tuple[str, ...] = ("en_US", "pt_BR")
#: Locale whose strings act as canonical English identity lookups.
DEFAULT_LOCALE: str = "en_US"

#: Canonical English msgids surfaced to end users at runtime; every id must carry a non-blank pt_BR translation in
#: TRANSLATIONS before catalogs are allowed to be written out, per the module's completeness-validation contract.
MESSAGES: tuple[str, ...] = (
    "Processing your document…",
    "Job complete: your file is ready for download",
    MSG_UNSUPPORTED_FORMAT,
    MSG_FILE_TOO_LARGE,
    # Pipeline processing-stage labels surfaced to end users as live progress
    # (backend/service.py, backend/agents/*, backend/api/worker.py).
    STAGE_QUEUE_WAITING_POSITION,
    STAGE_CANCELLED_IN_QUEUE,
    STAGE_ENQUEUED_WAITING,
    STAGE_PREPARING_FILE,
    STAGE_ANALYZING_FILE,
    STAGE_PROCESSING_WITH_AI,
    STAGE_PROCESSING_FINISHED,
    STAGE_PROCESSING_FAILED_LABEL,
    STAGE_EXPORTING_TXT,
    STAGE_EXPORTING_DOCX,
    STAGE_EXPORTING_PDF,
    STAGE_EXPORTING_PDF_UA,
    STAGE_EXPORTING_HTML,
    STAGE_GENERATING_AUDIO,
    STAGE_PROCESSING_COMPLETED,
    STAGE_PROCESSING_FAILURE,
    STAGE_CANCELLED_BY_USER,
    STAGE_SPLITTING_PDF_PAGES,
    STAGE_PREPARING_IMAGE,
    STAGE_PROCESSING_PAGE,
    STAGE_ANALYZING_STRUCTURAL,
    STAGE_ENRICHING_IMAGE_DESCRIPTIONS,
    STAGE_ENRICHING_TABLES_OCR,
    STAGE_GENERATING_PDDL_PLAN,
    STAGE_VALIDATING_PLAN_DRY_RUN,
    # Telegram bot command responses (frontend/telegram/handlers/start.py).
    MSG_EMAIL_HINT,
    MSG_EMAIL_CONFIGURED,
    MSG_START_TEXT,
    MSG_HELP_TEXT,
    MSG_FORMATS_TEXT,
    # Telegram file/photo processing lifecycle replies (frontend/telegram/handlers/document.py).
    MSG_FILE_RECEIVED,
    MSG_PHOTO_RECEIVED,
    MSG_DOWNLOADING_FILE,
    MSG_SUBMIT_FAILED,
    MSG_CONTACT_SERVER_FAILED,
    MSG_TASK_ENQUEUED,
    MSG_QUEUE_POSITION,
    MSG_WAITING_IN_QUEUE,
    MSG_DOWNLOAD_LINK_EMAILED,
    MSG_ACCESSIBLE_PACKAGE_READY,
    MSG_PROCESSING_ERROR_GENERIC,
    MSG_PROCESS_FAILED_BASE,
    MSG_TASK_CANCELLED,
    MSG_PROCESSING_TIMEOUT,
    # Telegram start.py command replies (frontend/telegram/handlers/start.py).
    MSG_MODE_OCR_ON,
    MSG_MODE_DETAILED_ON,
    MSG_MODE_MEDIO_ON,
    MSG_MODE_BAIXO_ON,
    MSG_MODE_NORMAL_ON,
    MSG_NO_TASK_REGISTERED,
    MSG_STATUS_NO_TASK,
    MSG_STATUS_SUMMARY,
    MSG_STATUS_TASK_NOT_FOUND,
    MSG_OLLAMA_ONLINE,
    MSG_OLLAMA_UNEXPECTED,
    MSG_OLLAMA_OFFLINE,
    MSG_HEALTH_ACTIVE_MODEL,
    MSG_HEALTH_TEMP_OK,
    MSG_HEALTH_TEMP_MISSING,
    MSG_CACHE_CLEARED,
    MSG_HEALTH_DISK_FREE,
    # Telegram start.py command response ids: task cancel/result receipts, bot pause/resume confirmations, feedback prompt+thanks.
    MSG_CANCEL_NO_TASK,
    MSG_TASK_CANCEL_DONE,
    MSG_TASK_CANCEL_FAILED,
    MSG_BOT_PAUSED,
    MSG_BOT_RESUMED,
    MSG_FEEDBACK_PROMPT,
    MSG_FEEDBACK_THANKS,
    # Backend API HTTP detail/receipt bodies surfaced verbatim to chat and web clients.
    MSG_API_TASK_NOT_FOUND,
    MSG_API_JOB_QUEUED,
    MSG_API_PROMPT_TOO_LONG,
    MSG_API_LINK_INVALID,
    MSG_API_FORMAT_INVALID,
    MSG_API_FILE_NOT_FOUND,
    # Manifest/planner internal diagnostic strings surfaced in logs or model validation errors.
    MSG_OBLIGATION_IMAGE,
    MSG_OBLIGATION_TABLE,
    MSG_OBLIGATION_FORMULA,
    MSG_OBLIGATION_CODE,
    MSG_OBLIGATION_UNKNOWN,
    MSG_HEADING_GAP,
    MSG_SOURCE_FILE_MISSING,
    # Docling-structural-attachment extraction diagnostics (backend/core/manifest/docling_extractor.py),
    # surfaced as RuntimeError/ValueError text when the optional Docling stack is absent or its document
    # structurer is incompatible; {source_path} substituted at call time via .format().
    MSG_SOURCE_NOT_FOUND,
    MSG_DOCLING_MISSING,
    MSG_INCOMPATIBLE_STRUCTURER,
    # Nominal-plan executor error and status messages (backend/core/execution/messages.py),
    # raised or recorded by ExecutorAgent/MethodRegistry; placeholders substituted at call time.
    EXE_METHOD_NAME_REQUIRED,
    EXE_PLAN_DIFFERENT_DOMAIN,
    EXE_PLAN_DOMAIN_VERSION_INCOMPATIBLE,
    EXE_DOMAIN_PDDL_CHANGED,
    EXE_DOMAIN_DESCRIPTION_CHANGED,
    EXE_PLAN_OTHER_MANIFEST,
    EXE_PLAN_REVISION_MISMATCH,
    EXE_MANIFEST_CHANGED_AFTER_PLANNING,
    EXE_PLAN_UNKNOWN_OBLIGATIONS,
    EXE_START_JOB_INVALID_STATE,
    EXE_OBLIGATION_NOT_FOUND,
    EXE_DRY_RUN_SIMULATED,
    EXE_NO_HANDLER_REGISTERED,
    EXE_RESULT_REJECTED,
    EXE_COMPLETED_OBLIGATIONS_UNSATISFIED,
    EXE_UNKNOWN_ACTION,
    EXE_JOB_NOT_PROCESSING,
    EXE_OBLIGATION_NOT_SELECTED,
    EXE_OBLIGATION_ALREADY_SATISFIED,
    EXE_OBLIGATION_KIND_MISMATCH,
    EXE_METHOD_NOT_ADMISSIBLE,
    EXE_METHOD_ALREADY_TRIED,
    EXE_PREDECESSORS_UNSATISFIED,
    MSG_PLANNER_NOT_STARTED,
    MSG_EXECUTE_OBLIGATION_MISSING_FIELDS,
    MSG_ACTION_REJECTS_EXECUTION_PARAMETERS,
    MSG_PLAN_INDICES_CONSECUTIVE_FROM_ZERO,
    MSG_NOMINAL_PLAN_MUST_END_COMPLETE_JOB,
    MSG_EXPECTED_TOTAL_COST_MISMATCH,
    MSG_PLAN_CONTAINS_UNSELECTED_OBLIGATION,
    MSG_PLANNER_OUTCOME_SOLVED_REQUIRES_FIELDS,
    MSG_PLANNER_OUTCOME_MUST_PASS_VALIDATION,
    MSG_PLANNER_OUTCOME_SOLVED_MUST_NOT_CARRY_ERROR,
    MSG_PLANNER_OUTCOME_FAILED_REQUIRES_ERROR,
    MSG_PLANNER_OUTCOME_FAILED_MUST_NOT_PASS_VALIDATION,
    MSG_COMPARISON_REQUIRES_BOTH_BACKENDS,
    MSG_COMPARISON_OUTCOME_KEY_MISMATCH,
    MSG_PLANNING_COMPARISON_SCHEMA_DESCRIPTION,
    MSG_NOMINAL_PLAN_SCHEMA_DESCRIPTION,
    # Execution-model validation/schema strings consumed by backend/core/execution/models.py.
    MSG_METHOD_RESULT_SUCCESS_REQUIRES_VALIDATION,
    MSG_METHOD_RESULT_DUPLICATE_ARTIFACT_IDS,
    MSG_EXECUTION_REPORT_SCHEMA_DESCRIPTION,
    # Tracker finish receipts shown when editing the live progress message at job end.
    MSG_STATUS_CONVERSION_DONE,
    MSG_STATUS_PROCESSING_FAILED,
    # Canonical-document / export-profile / output-text validation findings
    # (backend/pipeline/validators.py), surfaced in audit reports and ValueError
    # messages raised by backend/export/pandoc_exporter.py.
    MSG_CANONICAL_DOC_NOT_OBJECT,
    MSG_FIELD_MISSING,
    MSG_SECTIONS_NOT_LIST,
    MSG_DUPLICATE_ID,
    MSG_PROMPT_LEAK_IN_BLOCK,
    MSG_MARKDOWN_IN_BLOCK,
    MSG_INCONSISTENT_CODE_INDENT,
    MSG_MULTIPLE_H1,
    MSG_MISSING_FIRST_H1,
    MSG_HEADING_LEVELS_SKIPPED,
    MSG_INTERNAL_LINK_BROKEN,
    MSG_UNKNOWN_EXPORT_PROFILE,
    MSG_BLOCK_NOT_ALLOWED_IN_PROFILE,
    MSG_PROMPT_LEAK_IN_OUTPUT,
    MSG_MARKDOWN_IN_OUTPUT,
    MSG_TECHNICAL_METADATA_IN_TXT,
    MSG_IMAGE_MISSING_ALT,
    MSG_TABLE_MISSING_HEADER,
    MSG_TABLE_LEGACY_FALLBACK,
    MSG_DOCUMENT_NO_SECTIONS,
    MSG_NO_ID_PLACEHOLDER,
    MSG_TABLE_EMPTY,
    MSG_TABLE_ROWS_INVALID,
    MSG_TABLE_ROW_INVALID,
    MSG_TABLE_COLUMNS_INCONSISTENT,
    MSG_TABLE_CELL_NOT_TEXT,
    MSG_TABLE_CELL_EMPTY,
    MSG_TABLE_AST_INVALID,
    MSG_TABLE_AST_NO_BODY,
    MSG_TABLE_AST_SECTION_INVALID,
    MSG_TABLE_AST_ROW_INVALID,
    MSG_TABLE_AST_ROW_NO_CELLS,
    MSG_TABLE_AST_CELL_INVALID,
    MSG_TABLE_AST_CELL_NO_TEXT,
    MSG_TABLE_AST_WIDTH_INCONSISTENT,
    # Pandoc exporter runtime errors and default document title
    # (backend/export/pandoc_exporter.py), surfaced as RuntimeError/ValueError
    # text in logs and HTTP error details.
    MSG_DEFAULT_ACCESSIBLE_TITLE,
    MSG_PANDOC_NOT_FOUND,
    MSG_PANDOC_FAILED,
    MSG_PANDOC_REQUIRED_FOR_PDF_UA,
    MSG_LATEX_ENGINE_NOT_FOUND,
    MSG_PDF_UA_TEMPLATE_NOT_FOUND,
    MSG_AUDIT_FAILED,
    MSG_UNSUPPORTED_EXPORT_FORMAT,
    # HTML renderer UI chrome (backend/export/renderers/html_renderer.py).
    MSG_HTML_TABLE_OF_CONTENTS,
    MSG_HTML_TECHNICAL_METADATA,
    MSG_HTML_IMAGE_DESCRIPTION,
    # PDF renderer UI chrome (backend/export/renderers/pdf_renderer.py).
    MSG_PDF_TABLE_OF_CONTENTS,
    MSG_PDF_NOTE_LABEL,
    MSG_PDF_WARNING_LABEL,
    # TXT table line templates (backend/pipeline/table_ast.py).
    MSG_TABLE_TEXT_CAPTION,
    MSG_TABLE_TEXT_ROW,
    MSG_TABLE_TEXT_FOOTER,
    # Web upload panel user-facing strings (frontend/web/app.py + templates).
    WEB_INDEX_TITLE,
    WEB_INDEX_HEADLINE,
    WEB_INDEX_INTRO,
    WEB_INDEX_EMAIL_LABEL,
    WEB_INDEX_EMAIL_HELP,
    WEB_INDEX_DOC_LABEL,
    WEB_INDEX_SUBMIT_BUTTON,
    WEB_INDEX_ADVANCED_LINK,
    WEB_ADVANCED_TITLE,
    WEB_ADVANCED_HEADLINE,
    WEB_ADVANCED_SUBHEAD,
    WEB_ADVANCED_INTRO,
    WEB_ADVANCED_PROMPT_LABEL,
    WEB_ADVANCED_PROMPT_PLACEHOLDER,
    WEB_ADVANCED_PROMPT_HELP,
    WEB_ADVANCED_THINKING_LABEL,
    WEB_ADVANCED_BACK_LINK,
    WEB_DOWNLOAD_TITLE,
    WEB_DOWNLOAD_HEADLINE,
    WEB_DOWNLOAD_SUBHEAD,
    WEB_DOWNLOAD_NO_FORMATS,
    WEB_DOWNLOAD_VALID_NOTE,
    WEB_FORMAT_TXT,
    WEB_FORMAT_DOCX,
    WEB_FORMAT_PDF,
    WEB_FORMAT_HTML,
    WEB_FORMAT_MP3,
    WEB_FORMAT_ZIP,
    WEB_LOGO_ALT,
    WEB_FOOTER,
    WEB_AGENT_OS_DESCRIPTION,
    WEB_AGENT_VISION_DESCRIPTION,
    WEB_AGENT_DATA_DESCRIPTION,
    WEB_AGENT_DATA_INSTRUCTIONS_FALLBACK,
    WEB_ERROR_INTERNAL,
    WEB_ERROR_API_UPLOAD,
    WEB_ERROR_UPLOAD_GENERIC,
    WEB_ERROR_PROMPT_TOO_LONG,
    WEB_ERROR_DOWNLOAD_INVALID,
    WEB_ERROR_DOWNLOAD_UNAVAILABLE,
    WEB_RATE_LIMIT_EXCEEDED,
    WEB_SUCCESS_QUEUED,
    # Server-side runtime log and e-mail message ids (backend/log_messages.py),
    # resolved at log time through t() so local logs and outgoing e-mail content
    # follow the server-side detected locale (shell locale, then .env LOCALE,
    # then en_US) per the project i18n goal for operator-facing output.
    LOG_LOGGER_CONFIGURED,
    LOG_BOT_ALREADY_RUNNING,
    LOG_LOCK_FILE_STALE,
    LOG_LOCK_ACQUIRED,
    LOG_LOCK_RELEASED,
    LOG_API_INTERFACE_ENABLED,
    LOG_TELEGRAM_INTERFACE_ENABLED,
    LOG_TELEGRAM_INTERFACE_NO_TOKEN,
    LOG_WEB_INTERFACE_ENABLED,
    LOG_NO_INTERFACE_ENABLED,
    LOG_STARTING_INTERFACES,
    LOG_BOT_INTERRUPTED_BY_USER,
    LOG_BOT_SHUTTING_DOWN,
    LOG_BOT_STARTED,
    LOG_BOT_STARTING_POLLING,
    LOG_BOT_TOKEN_NOT_CONFIGURED,
    LOG_FATAL_ERROR_IN_BOT,
    LOG_WORKER_STARTED,
    LOG_QUEUE_ITEM_ENQUEUED,
    LOG_WORKER_TASK_STARTING,
    LOG_WORKER_TASK_ERROR,
    LOG_WORKER_TASK_COMPLETED,
    LOG_API_STARTED,
    LOG_API_ERROR,
    LOG_API_JOB_ENQUEUED,
    LOG_CLEANUP_ITEM_FAILED,
    LOG_CLEANUP_PERIODIC_ERROR,
    LOG_TEMP_FILE_REMOVED,
    LOG_TEMP_DIR_REMOVED,
    LOG_TELEGRAM_FILE_DOWNLOADING,
    LOG_TELEGRAM_FILE_DOWNLOADED,
    LOG_TELEGRAM_API_JOB_REJECTED,
    LOG_TELEGRAM_API_CONTACT_FAILED,
    LOG_TELEGRAM_FILE_PROCESSING_ERROR,
    LOG_TELEGRAM_JOB_STATUS_QUERY_FAILED,
    LOG_TELEGRAM_RATE_LIMIT_WAIT,
    LOG_TELEGRAM_SEND_FAILED_AFTER_RETRIES,
    LOG_TELEGRAM_UNHANDLED_ERROR,
    LOG_TELEGRAM_FEEDBACK_RECEIVED,
    LOG_OUTPUT_DIR_REMOVED,
    LOG_CLEANUP_OUTPUT_FAILED,
    LOG_SMTP_NOT_CONFIGURED,
    LOG_EMAIL_SENT,
    LOG_EMAIL_SEND_ERROR,
    LOG_EXPORT_TXT_START,
    LOG_EXPORT_DOCX_START,
    LOG_EXPORT_PDF_START,
    LOG_EXPORT_PDF_UA_START,
    LOG_EXPORT_MP3_START,
    LOG_PAGE_CONVERTED_TO_PNG,
    LOG_PDDL_IGNORED_OPTIONS,
    LOG_PDDL_IMAGES_ENRICHED,
    LOG_PDDL_TABLES_ENRICHED,
    LOG_PDF_PAGE_COUNT_LOGGED,
    LOG_PDF_PAGE_SAVED,
    LOG_PDF_PAGES_EXTRACTED,
    LOG_PDDL_ELEMENT_CROP_FAILED,
    LOG_PDDL_EXTRACTOR_BACKEND_INVALID,
    LOG_PDDL_PREFERRED_PLAN_MISSING,
    LOG_PDDL_PROBLEM_HASH_MISMATCH,
    LOG_PDDL_DOMAIN_HASH_MISMATCH,
    LOG_PDDL_DOMAIN_DESCRIPTION_HASH_MISMATCH,
    LOG_PDDL_SELECTED_CLOSURE_MISMATCH,
    LOG_READER_PDF_REGIONS_EXTRACTED,
    LOG_READER_CLEAN_TEXT_REGIONS,
    LOG_READER_REGION_TASK,
    LOG_READER_FULL_PAGE_FALLBACK,
    LOG_READER_TASKS_SUMMARY,
    LOG_READER_IMAGE_READING,
    LOG_PDF_EXPORTED,
    LOG_PDF_UA_EXPORTED,
    LOG_TXT_EXPORTED,
    LOG_DOCX_EXPORTED,
    EMAIL_CONFIRMATION_SUBJECT,
    EMAIL_CONFIRMATION_BODY,
    EMAIL_RESULT_SUBJECT,
    EMAIL_RESULT_BODY_WITH_LINK,
    EMAIL_RESULT_BODY_ATTACHED,
    EMAIL_FORMAT_TXT,
    EMAIL_FORMAT_DOCX,
    EMAIL_FORMAT_PDF,
    EMAIL_FORMAT_PDF_UA,
    EMAIL_FORMAT_HTML,
    EMAIL_FORMAT_MP3,
    EMAIL_FORMAT_ZIP,
    EMAIL_RESULT_WARNINGS_HEADER,
    LOG_CANONICAL_JSON_SAVE_FAILED,
    LOG_TASK_CANCELLED_BY_USER,
    LOG_PIPELINE_ERROR,
    LOG_PROMPT_FILE_NOT_FOUND,
    LOG_DATA_AGENT_PROMPT_NOT_FOUND,
    LOG_DATA_AGENT_PROCESSING_REGION,
    LOG_DATA_AGENT_REGION_ERROR,
    LOG_VISION_AGENT_REGION_ERROR,
    LOG_VISION_AGENT_SENDING_REGION,
    LOG_EDITOR_PAGE_EMPTY,
    LOG_EDITOR_PAGE_CONSOLIDATED,
    LOG_REGION_CROP_FAILED,
    LOG_CACHE_HIT,
    LOG_CACHE_DEBUG_HIT,
    LOG_CACHE_DEBUG_SET,
    LOG_CACHE_SAVE_FAILED,
    LOG_CACHE_CLEARED,
    LOG_ORPHAN_TASKS_CLEANED,
    LOG_ORPHAN_TASKS_CLEANUP_FAILED,
    LOG_DOCLING_NOT_AVAILABLE,
    LOG_DOCLING_PAGE_FAILED,
    LOG_DOCLING_PAGE_NO_PARENT,
    LOG_DOCLING_PROCESSED,
    LOG_DOWNLOAD_TOKEN_CREATED,
    LOG_DOWNLOAD_TOKEN_NOT_FOUND,
    LOG_DOWNLOAD_TOKEN_DIR_MISSING,
    LOG_PDF_UA_GENERATION_FAILED,
    LOG_MP3_GENERATION_FAILED,
    LOG_JOB_COMPLETED,
    LOG_JOB_CANCELLED,
    LOG_JOB_EXECUTOR_ERROR,
    LOG_IMAGE_PREPROCESS_FAILED,
    LOG_IMAGE_RESIZED,
    LOG_IMAGE_ROTATED,
    LOG_WEB_GLOBAL_ERROR,
    LOG_WEB_UPLOAD_ERROR,
    LOG_WEB_DOWNLOAD_QUERY_FAILED,
    LOG_WEB_HTTP_EXCEPTION,
    LOG_WEB_RATE_LIMIT_EXCEEDED,
    LOG_WEB_API_UPLOAD_ERROR,
    LOG_STATUS_MESSAGE_SEND_FAILED,
    LOG_STATUS_MESSAGE_EDIT_FAILED,
    LOG_STATUS_EDIT_UNEXPECTED,
    LOG_AUDIO_EXPORTED,
    LOG_AUDIO_EXPORT_ERROR,
    LOG_AUDIO_EXPORT_PROGRESS,
    LOG_AUDIO_EXPORT_START,
    API_RATE_LIMIT_DETAIL,
    API_INTERNAL_ERROR_DETAIL,
    LOG_ORCHESTRATOR_EMPTY_AGENT_RESPONSE,
    LOG_ORCHESTRATOR_EMPTY_PAGE_RESPONSE,
    LOG_ORCHESTRATOR_PAGE_CACHE_SKIP,
    LOG_ORCHESTRATOR_PAGE_RESPONSE_SAVED,
    LOG_ORCHESTRATOR_WAITING_TASKS,
    LOG_ORCHESTRATOR_TASK_FAILED,
    LOG_ORCHESTRATOR_WORKFLOW_START,
    LOG_ORCHESTRATOR_WORKFLOW_SUMMARY,
    LOG_RAPIDOCR_MODELS_RESTORED,
    LOG_RAPIDOCR_MODELS_PERSISTED,
    LOG_STRUCTURER_DOCLING,
    LOG_STRUCTURER_DOCLING_NOT_INSTALLED,
    LOG_STRUCTURER_FALLBACK_PYMUPDF,
    LOG_STRUCTURER_PYMUPDF,
    LOG_STALE_PROCESS_INTERRUPTED,
    LOG_AGNO_NOT_INSTALLED,
)

#: msgid -> localized text mappings per non-default locale; every id in MESSAGES must appear for each such locale.
TRANSLATIONS: dict[str, dict[str, str]] = {
    "pt_BR": {
        "Processing your document…": "Processando seu documento…",
        "Job complete: your file is ready for download": "Tarefa concluída: o arquivo está pronto para download",
        MSG_UNSUPPORTED_FORMAT: ("Formato de arquivo não suportado. Envie PDF, DOCX, HTML, PNG, JPG, " +
                                "TIFF, BMP ou WEBP."),
        MSG_FILE_TOO_LARGE: "Arquivo muito grande. Limite: {limit} MB.",
        # Pipeline processing-stage labels (pt-BR mirrors of the stage msgids
        # declared above), surfaced as the live progress text of each job.
        STAGE_QUEUE_WAITING_POSITION: "Aguardando na fila (Posição: {position})",
        STAGE_CANCELLED_IN_QUEUE: "Cancelado antes de entrar na fila de processamento",
        STAGE_ENQUEUED_WAITING: "Enfileirado, aguardando...",
        STAGE_PREPARING_FILE: "Preparando o seu arquivo...",
        STAGE_ANALYZING_FILE: "📄 Analisando o seu documento...",
        STAGE_PROCESSING_WITH_AI: "Processando o seu arquivo com a IA...",
        STAGE_PROCESSING_FINISHED: "✅ Processamento concluído com sucesso!",
        STAGE_PROCESSING_FAILED_LABEL: "❌ Não foi possível processar o arquivo.",
        STAGE_EXPORTING_TXT: ("Exportando a versão em texto puro (TXT)..."),
        STAGE_EXPORTING_DOCX: ("Exportando o documento Word acessível (DOCX)..."),
        STAGE_EXPORTING_PDF: "Exportando o PDF...",
        STAGE_EXPORTING_PDF_UA: ("Exportando o PDF/UA acessível com marcações..."),
        STAGE_EXPORTING_HTML: ("Exportando a versão em HTML semântico..."),
        STAGE_GENERATING_AUDIO: (
            "Gerando a versão em áudio falado... {percent}%"
        ),
        STAGE_PROCESSING_COMPLETED: "Processamento concluído",
        STAGE_PROCESSING_FAILURE: "Falha no processamento",
        STAGE_CANCELLED_BY_USER: "Cancelado pelo usuário",
        STAGE_SPLITTING_PDF_PAGES: "📄 Separando o PDF em páginas...",
        STAGE_PREPARING_IMAGE: "🖼️ Preparando a imagem...",
        STAGE_PROCESSING_PAGE: "📷 Processando a página {page_num} de {total_pages}...",
        STAGE_ANALYZING_STRUCTURAL: (
            "Analisando o documento com o agente estrutural..."
        ),
        STAGE_ENRICHING_IMAGE_DESCRIPTIONS: ("Enriquecendo as descrições de imagens..."),
        STAGE_ENRICHING_TABLES_OCR: ("Enriquecendo as tabelas com OCR (fallback)..."),
        STAGE_GENERATING_PDDL_PLAN: ("Gerando o plano nominal com PDDL..."),
        STAGE_VALIDATING_PLAN_DRY_RUN: (
            "Validando o plano em modo dry-run..."
        ),
        MSG_EMAIL_HINT: "Por favor, informe o e-mail: /email seu@email.com",
        MSG_EMAIL_CONFIGURED:
            "E-mail {email} configurado! Agora envie o documento para ser enviado para este e-mail.",
        MSG_START_TEXT: (
            "Olá! Envie um PDF, imagem ou documento escaneado."
            "\n\nEnviarei de volta uma versão acessível para leitores de tela."
            "\n\nFormatos aceitos: PDF, PNG, JPG, TIFF, BMP, WEBP"
        ),
        MSG_HELP_TEXT: (
            "Comandos disponíveis:"
            "\n\n🔧 Gerais:"
            "\n/start - Iniciar o bot"
            "\n/ajuda ou /help - Mostrar esta mensagem"
            "\n/formatos - Listar formatos de entrada e saída suportados"
            "\n\n🎨 Modos de Descrição:"
            "\n/detalhado - Máximo detalhe: tipografia, cores, layout, posição de elementos"
            "\n/medio - Texto completo + descrição clara de imagens (padrão)"
            "\n/baixo - Foco no conteúdo: texto + descrição concisa (mais rápido)"
            "\n/normal - Equivalente ao /medio"
            "\n/ocr - Apenas extração de texto, sem descrição visual"
            "\n\n⚙️ Controle:"
            "\n/status - Mostra o andamento da tarefa em processamento"
            "\n/cancelar - Cancelar tarefa em andamento"
            "\n/desativar - Desativar o bot neste chat"
            "\n/ativar - Reativar o bot neste chat"
            "\n/health - Verificar status do sistema (servidor, modelo, disco)"
            "\n/feedback - Enviar opinião sobre a qualidade do processamento"
            "\n\nBasta enviar um arquivo que eu processo automaticamente."
        ),
        MSG_FORMATS_TEXT: (
            "Formatos de entrada aceitos:"
            "\n• PDF (escaneado ou digital)"
            "\n• PNG, JPG, JPEG"
            "\n• TIFF, TIF"
            "\n• BMP"
            "\n• WEBP"
            "\n\nFormatos de saída disponíveis:"
            "\n• TXT estruturado"
            "\n• DOCX acessível"
            "\n• HTML semântico"
            "\n• Markdown"
            "\n• PDF pesquisável"
        ),
        # Docling extractor diagnostics (backend/core/manifest/docling_extractor.py).
        MSG_SOURCE_NOT_FOUND: "Arquivo de origem não encontrado: {source_path}",
        MSG_DOCLING_MISSING: (
            "Docling não está instalado. Execute `poetry install` ou " +
            "`pip install docling`."
        ),
        MSG_INCOMPATIBLE_STRUCTURER: (
            "Structurer incompatível: esperado convert_document() ou _process_document()."
        ),
        # Nominal-plan executor diagnostics (backend/core/execution/messages.py): pt-BR mirror preserving the original wording.
        EXE_METHOD_NAME_REQUIRED: "O nome do método não pode ser vazio",
        EXE_PLAN_DIFFERENT_DOMAIN: "O plano usa outro domínio PDDL",
        EXE_PLAN_DOMAIN_VERSION_INCOMPATIBLE: (
            "A versão do domínio do plano é incompatível"
        ),
        EXE_DOMAIN_PDDL_CHANGED: "O domain.pddl foi alterado depois do planejamento",
        EXE_DOMAIN_DESCRIPTION_CHANGED: (
            "A descrição do domínio foi alterada depois do planejamento"
        ),
        EXE_PLAN_OTHER_MANIFEST: "O plano pertence a outro manifesto",
        EXE_PLAN_REVISION_MISMATCH: (
            "Revisão divergente entre plano e manifesto: "
            "{plan_revision} != {manifest_revision}"
        ),
        EXE_MANIFEST_CHANGED_AFTER_PLANNING: (
            "O manifesto foi alterado depois da geração do plano"
        ),
        EXE_PLAN_UNKNOWN_OBLIGATIONS: (
            "O plano seleciona obrigações inexistentes: {unknown}"
        ),
        EXE_START_JOB_INVALID_STATE: "start-job inválido no estado {status}",
        EXE_OBLIGATION_NOT_FOUND: "Obrigação inexistente: {obligation_id}",
        EXE_DRY_RUN_SIMULATED: (
            "Execução simulada; nenhum efeito foi persistido"
        ),
        EXE_NO_HANDLER_REGISTERED: "Nenhum handler registrado para {method}",
        EXE_RESULT_REJECTED: "Resultado rejeitado pelo validador",
        EXE_COMPLETED_OBLIGATIONS_UNSATISFIED: (
            "Obrigações selecionadas não satisfeitas: {unsatisfied}"
        ),
        EXE_UNKNOWN_ACTION: "Ação desconhecida: {action}",
        EXE_JOB_NOT_PROCESSING: "O job não está em processamento",
        EXE_OBLIGATION_NOT_SELECTED: "Obrigação não selecionada: {obligation_id}",
        EXE_OBLIGATION_ALREADY_SATISFIED: (
            "Obrigação já satisfeita: {obligation_id}"
        ),
        EXE_OBLIGATION_KIND_MISMATCH: "Tipo da obrigação diverge do plano",
        EXE_METHOD_NOT_ADMISSIBLE: "Método não admissível: {method}",
        EXE_METHOD_ALREADY_TRIED: "Método já tentado: {method}",
        EXE_PREDECESSORS_UNSATISFIED: (
            "Predecessoras não satisfeitas para {obligation_id}: {unsatisfied}"
        ),
        # Telegram file/photo processing lifecycle replies (pt-BR mirror of the english ids above).
        MSG_FILE_RECEIVED: "📄 Arquivo recebido!",
        MSG_PHOTO_RECEIVED: "📷 Foto recebida!",
        MSG_DOWNLOADING_FILE: "Baixando arquivo...",
        MSG_SUBMIT_FAILED: (
            "❌ Erro ao enviar o arquivo para processamento ({status_code}): {detail}"
        ),
        MSG_CONTACT_SERVER_FAILED: (
            "❌ Não foi possível contatar o servidor de processamento. Tente novamente."
        ),
        MSG_TASK_ENQUEUED: "Tarefa {task_id} enfileirada...",
        MSG_QUEUE_POSITION: "⏳ Você está na fila única (Posição: {position}).",
        MSG_WAITING_IN_QUEUE: "Aguardando na fila... {step}",
        MSG_DOWNLOAD_LINK_EMAILED: "✅ Link de download enviado para {email}!",
        MSG_ACCESSIBLE_PACKAGE_READY: (
            "✅ Pacote acessível gerado!\n\n📥 Link para download (válido por 7 dias):\n{url}"
        ),
        MSG_PROCESSING_ERROR_GENERIC: "❌ Erro ao processar o arquivo. Tente novamente.",
        MSG_PROCESS_FAILED_BASE: "❌ Erro no processamento.",
        MSG_TASK_CANCELLED: "🚫 Tarefa cancelada.",
        MSG_PROCESSING_TIMEOUT: (
            "⏰ O processamento demorou mais que o esperado. Use /status para acompanhar."
        ),
        # Telegram start.py command replies (frontend/telegram/handlers/start.py pt-BR mirrors).
        MSG_MODE_OCR_ON: ("📄 Modo OCR ativado!\n\nEnvie um PDF ou imagem e extrairei APENAS o texto, "
                         + "sem descrição visual. Ideal para documentos de texto puro."),
        MSG_MODE_DETAILED_ON: (
            "🔍 Modo Detalhado ativado!\n\n"
            "Descrição no maior nível de detalhe: tipografia, espaçamento, cores, layout, posição dos elementos e uma descrição profissional das imagens."
        ),
        # Medium mode (/medio) confirmation.
        MSG_MODE_MEDIO_ON: (
            "📋 Modo Médio ativado!\n\nTexto completo com descrições claras de imagens. Ideal para a maioria dos documentos."
        ),
        # Low mode (/baixo) confirmation.
        MSG_MODE_BAIXO_ON: (
            "⚡ Modo Baixo ativado!\n\nFocado no conteúdo: texto integral extraído e descrição concisa das imagens. Mais rápido."
        ),
        # Normal mode (/normal) confirmation, equivalent to medium.
        MSG_MODE_NORMAL_ON: (
            "📋 Modo Normal ativado (equivalente ao Médio).\n\nTexto completo com descrições claras de imagens."
        ),
        # /status reply when the chat has no task recorded yet.
        MSG_NO_TASK_REGISTERED: "Nenhuma tarefa registrada neste chat ainda.",
        # /status reply when there is no task to show.
        MSG_STATUS_NO_TASK: "Nenhuma tarefa neste chat.",
        # /cancel reply when there is nothing to cancel in this chat.
        MSG_CANCEL_NO_TASK: "Nenhuma tarefa ativa neste chat para cancelar.",
        # /status successful summary template; {icon}/{task_id}/{filename}/{pct}/{stage} substituted at call time.
        MSG_STATUS_SUMMARY: ("{icon} Tarefa `{task_id}` - {filename}\n{pct}% - {stage}"),
        # /status error reply when the API reports the task as unknown; {status_code} is the rejected HTTP code.
        MSG_STATUS_TASK_NOT_FOUND: "❌ Tarefa não encontrada na API ({status_code}).",
        # Ollama online line from /health; {model_count} is how many local models are loaded.
        MSG_OLLAMA_ONLINE: "✅ Ollama: online ({model_count} modelo(s))",
        # Ollama answering something other than expected HTTP 200; observed {code} inserted at call time.
        MSG_OLLAMA_UNEXPECTED: "⚠️ Ollama: resposta inesperada ({code})",
        # Ollama unreachable line from /health; probe error text is localized client-side and shown via {error}.
        MSG_OLLAMA_OFFLINE: "❌ Ollama: offline ({error})",
        # Active LLM model line from /health; {model} named in config injected at call time.
        MSG_HEALTH_ACTIVE_MODEL: "🤖 Modelo: {model}",
        # Temp-directory check passes (settings.temp_dir exists).
        MSG_HEALTH_TEMP_OK: "✅ Pasta temporária: ok",
        # Missing temp directory reported as a warning; operator should recreate settings.temp_dir.
        MSG_HEALTH_TEMP_MISSING: "⚠️ Pasta temporária: ausente",
        # Cache clearing receipt; {count} is how many files were removed from the cache store.
        MSG_CACHE_CLEARED: "🧹 Cache limpo! {count} arquivo(s) removido(s).",
        # Free disk space reported with one decimal in GB units (see /health disk probe).
        MSG_HEALTH_DISK_FREE: "💾 Disco livre: {free_gb:.1f} GB",
        # Confirmation receipt after successful cancellation of the user's task; {task_id} of the cancelled job.
        MSG_TASK_CANCEL_DONE: "✅ Tarefa {task_id} cancelada.",
        # Failure notice when the API returns non-success on the cancel call; {status_code}/{detail} injected at runtime.
        MSG_TASK_CANCEL_FAILED: "❌ Não foi possível cancelar a tarefa ({status_code}): {detail}",
        # Bot pause/resume receipts for /desativar and /ativar.
        MSG_BOT_PAUSED: "Bot desativado neste chat. Use /ativar para reativá-lo.",
        MSG_BOT_RESUMED: "Bot reativado! Envie um documento para começar.",
        # /feedback invitation text; mirrors en_US structure including the example line.
        MSG_FEEDBACK_PROMPT: (
            "📝 **Enviar Feedback**\n\n"
            "Digite sua opinião sobre a qualidade do processamento, sugestões de melhoria ou problemas encontrados.\n\n"
            "Exemplo:\n"
            "“A descrição da imagem ficou ótima mas o texto extraído teve alguns erros.”\n\n"
            "Seu feedback é muito importante para nós!"
        ),
        # Thanks receipt once the user's feedback message has been recorded.
        MSG_FEEDBACK_THANKS: "✅ Feedback recebido! Obrigado pela contribuição.",
        # Localized variant of the 404 API detail body for jobs task endpoints (surfaces via ApiError.detail).
        MSG_API_TASK_NOT_FOUND: "Tarefa não encontrada",
        # 202 API upload receipt returned when a job has been enqueued; {position} is substituted at call time.
        MSG_API_JOB_QUEUED: "Arquivo na fila (Posição: {position}).",
        # 400 API detail body for over-limit custom prompts; {limit} is the maximum accepted character count.
        MSG_API_PROMPT_TOO_LONG: (
            "Prompt personalizado excede o limite de {limit} caracteres."
        ),
        # 404 API detail body when a download token lookup misses.
        MSG_API_LINK_INVALID: "Link inválido ou expirado",
        # 400 API detail body when a download request names an unsupported format.
        MSG_API_FORMAT_INVALID: "Formato inválido",
        # 404 API detail body when a known token's artifact file is missing on disk.
        MSG_API_FILE_NOT_FOUND: "Arquivo não encontrado",
        # Manifest processing-needs rationale texts used in LLM prompt obligations per element type.
        MSG_OBLIGATION_IMAGE: ("A imagem deve receber descrição ou ser marcada como decorativa."),
        MSG_OBLIGATION_TABLE: (
            "A tabela deve ter cabeçalhos e ordem de leitura verificáveis."
        ),
        MSG_OBLIGATION_FORMULA: (
            "A fórmula deve possuir representação matemática acessível e verbalização."
        ),
        MSG_OBLIGATION_CODE: (
            "O bloco de código deve preservar indentação, linguagem e leitura literal."
        ),
        MSG_OBLIGATION_UNKNOWN: ("O elemento não classificado requer inspeção estrutural."),
        # Observation message for heading-level skips found while validating the manifest; {previous}/{level} injected at call time.
        MSG_HEADING_GAP: (
            "A hierarquia de títulos salta do nível {previous} para o nível {level}."
        ),
        # PyMuPDF extraction fallback when the source file is missing on disk at lookup time; substituted at call time via .format().
        MSG_SOURCE_FILE_MISSING: ("Documento não encontrado: {source_path}"),
        # Model validation failure text for a planner outcome recorded before execution actually began.
        MSG_PLANNER_NOT_STARTED: ("A tentativa terminou antes de começar"),
        # Failure for execute-obligation steps missing required execution parameters in NominalPlan validation of PlanSteps.
        MSG_EXECUTE_OBLIGATION_MISSING_FIELDS: (
            "execute-obligation exige obligation_id, obligation_kind e method"
        ),
        # {action} rejecting parameter values that only belong to execute-obligation steps.
        MSG_ACTION_REJECTS_EXECUTION_PARAMETERS: (
            "{action} não aceita parâmetros de obrigação ou método"
        ),
        # Contiguity requirement on plan step index sequences for NominalPlan validation failure text.
        MSG_PLAN_INDICES_CONSECUTIVE_FROM_ZERO: (
            "Índices do plano devem ser contíguos e iniciar em zero"
        ),
        # Termination guard requiring the last nominal-plan step to be complete-job action.
        MSG_NOMINAL_PLAN_MUST_END_COMPLETE_JOB: ("O plano nominal deve terminar com complete-job"),
        # Cost sum consistency check comparing stored expected total against recalculated per-step totals.
        MSG_EXPECTED_TOTAL_COST_MISMATCH: (
            "expected_total_cost={declared}; o custo somado das etapas do plano é {calculated}"
        ),
        # Unselected obligation detection when a planned execution step references no selected manifest obligation.
        MSG_PLAN_CONTAINS_UNSELECTED_OBLIGATION: ("O plano contém obrigação não selecionada"),
        # Solved-outcome completeness requirement on all plan artifacts plus statistics being present.
        MSG_PLANNER_OUTCOME_SOLVED_REQUIRES_FIELDS: (
            "Um resultado marcado como resolvido exige plano completo com identidade de documento"
        ),
        # Validation approval requirement on successful runs marking planner outcomes that reached a solution.
        MSG_PLANNER_OUTCOME_MUST_PASS_VALIDATION: (
            "Um resultado definido como resolvido deve ter a validação aprovada"
        ),
        # Prohibiting any error descriptor fields from coexisting with successful solver results.
        MSG_PLANNER_OUTCOME_SOLVED_MUST_NOT_CARRY_ERROR: (
            "Um resultado definido como resolvido não pode conter valores de erro preenchidos"
        ),
        # Failure marker completeness requirement on unsuccessful runs: error type and message must both be present.
        MSG_PLANNER_OUTCOME_FAILED_REQUIRES_ERROR: (
            "Um resultado marcado como falha exige um tipo de erro junto com sua mensagem descritiva"
        ),
        # Symmetry guard preventing contradictory validation-pass flags on failures.
        MSG_PLANNER_OUTCOME_FAILED_MUST_NOT_PASS_VALIDATION: (
            "Um resultado marcado como falha não pode passar na validação à mesma tempo"
        ),
        # Comparison completeness check requiring both planned solver backends to hold matching result records.
        MSG_COMPARISON_REQUIRES_BOTH_BACKENDS: (
            "A comparação deve conter os resultados de ambos os planejadores, interno e Fast Downward"
        ),
        # Divergent planner-backend label guard on one side vs. its key in the outcome mapping.
        MSG_COMPARISON_OUTCOME_KEY_MISMATCH: (
            "A chave {key} diverge do backend registrado como {backend} "
            "nesse par de resultados"
        ),
        # Normalized description for the planning-comparison JSON schema document in pt_BR.
        MSG_PLANNING_COMPARISON_SCHEMA_DESCRIPTION: (
            "Comparação normalizada entre as execuções do planejador interno e o Fast Downward de um único problema"
        ),
        # Normalized description for the nominal-plan JSON schema document in pt_BR.
        MSG_NOMINAL_PLAN_SCHEMA_DESCRIPTION: (
            "Plano nominal derivado do manifesto de processamento e o domínio PDDL do Acessilia"
        ),
        # Execution model guard: a result claiming success must have passed validation.
        MSG_METHOD_RESULT_SUCCESS_REQUIRES_VALIDATION: (
            "Um resultado de método reivindicado como bem-sucedido também deve ter passado na sua validação"
        ),
        # Duplicate artifact identifier guard on MethodResult artifacts mapping.
        MSG_METHOD_RESULT_DUPLICATE_ARTIFACT_IDS: (
            "O resultado do método contém identificadores de artefatos duplicados"
        ),
        # Execution report JSON schema document description in pt_BR.
        MSG_EXECUTION_REPORT_SCHEMA_DESCRIPTION: (
            "Relatório da execução de um plano nominal sobre um manifesto, com resultados por passo e artefatos coletados"
        ),
        # Tracker finish receipts mirroring the progress message end states edited in status_tracker.
        MSG_STATUS_CONVERSION_DONE: "✅ Conversão concluída!",
        MSG_STATUS_PROCESSING_FAILED: ("❌ Erro durante o processamento."),
        # Canonical-document / export-profile / output-text validation findings
        # (pt-BR mirrors of the backend/pipeline/validators.py ids above).
        MSG_CANONICAL_DOC_NOT_OBJECT: (
            "Documento canônico deve ser um objeto JSON."
        ),
        MSG_FIELD_MISSING: "Campo obrigatório ausente: {field}",
        MSG_SECTIONS_NOT_LIST: "Campo sections deve ser uma lista.",
        MSG_DUPLICATE_ID: "ID interno duplicado: {block_id}",
        MSG_PROMPT_LEAK_IN_BLOCK: "Possível vazamento de prompt em {block_id}",
        MSG_MARKDOWN_IN_BLOCK: "Markdown indevido em {block_id}",
        MSG_INCONSISTENT_CODE_INDENT: (
            "Indentação de código inconsistente em {block_id}"
        ),
        MSG_MULTIPLE_H1: "O documento deve ter apenas um H1 principal.",
        MSG_MISSING_FIRST_H1: (
            "O documento deve começar com um H1 principal."
        ),
        MSG_HEADING_LEVELS_SKIPPED: (
            "Hierarquia de headings salta níveis indevidamente."
        ),
        MSG_INTERNAL_LINK_BROKEN: (
            "Link interno aponta para ID inexistente: {link}"
        ),
        MSG_UNKNOWN_EXPORT_PROFILE: (
            "Perfil de exportação desconhecido: {profile_name}"
        ),
        MSG_BLOCK_NOT_ALLOWED_IN_PROFILE: (
            "Bloco {block_id} não permitido no perfil {profile_name}"
        ),
        MSG_PROMPT_LEAK_IN_OUTPUT: (
            "Possível vazamento de prompt na saída final."
        ),
        MSG_MARKDOWN_IN_OUTPUT: "Markdown indevido na saída final.",
        MSG_TECHNICAL_METADATA_IN_TXT: (
            "Metadados técnicos não devem aparecer no TXT."
        ),
        MSG_IMAGE_MISSING_ALT: "Imagem {block_id} sem alt-text.",
        MSG_TABLE_MISSING_HEADER: (
            "Tabela {table_id} sem header explícito; revisar inferência de cabeçalhos."
        ),
        MSG_TABLE_LEGACY_FALLBACK: (
            "Tabela {table_id} sem table_ast; usando fallback legado por linhas."
        ),
        MSG_DOCUMENT_NO_SECTIONS: "Documento sem seções.",
        MSG_NO_ID_PLACEHOLDER: "(sem-id)",
        MSG_TABLE_EMPTY: "Tabela vazia em {block_id}",
        MSG_TABLE_ROWS_INVALID: "Tabela com rows inválidas em {block_id}",
        MSG_TABLE_ROW_INVALID: (
            "Tabela com linha inválida em {block_id} (row {row_index})"
        ),
        MSG_TABLE_COLUMNS_INCONSISTENT: (
            "Tabela com colunas inconsistentes em {block_id} (row {row_index})"
        ),
        MSG_TABLE_CELL_NOT_TEXT: (
            "Tabela com célula não textual em {block_id} (row {row_index}, col {col_index})"
        ),
        MSG_TABLE_CELL_EMPTY: (
            "Tabela com célula vazia em {block_id} (row {row_index}, col {col_index})"
        ),
        MSG_TABLE_AST_INVALID: "table_ast inválido em {block_id}",
        MSG_TABLE_AST_NO_BODY: "table_ast sem body em {block_id}",
        MSG_TABLE_AST_SECTION_INVALID: (
            "table_ast.{section_name} inválido em {block_id}"
        ),
        MSG_TABLE_AST_ROW_INVALID: (
            "table_ast.{section_name}[{row_index}] inválido em {block_id}"
        ),
        MSG_TABLE_AST_ROW_NO_CELLS: (
            "table_ast.{section_name}[{row_index}] sem cells em {block_id}"
        ),
        MSG_TABLE_AST_CELL_INVALID: (
            "table_ast célula inválida em {block_id} ({section_name} {row_index}:{col_index})"
        ),
        MSG_TABLE_AST_CELL_NO_TEXT: (
            "table_ast célula sem texto em {block_id} ({section_name} {row_index}:{col_index})"
        ),
        MSG_TABLE_AST_WIDTH_INCONSISTENT: (
            "table_ast.{section_name} com largura inconsistente em {block_id} (row {row_index})"
        ),
        # Pandoc exporter runtime errors and default document title
        # (pt-BR mirrors of the backend/export/pandoc_exporter.py ids above).
        MSG_DEFAULT_ACCESSIBLE_TITLE: "Documento acessível",
        MSG_PANDOC_NOT_FOUND: "pandoc não encontrado no PATH",
        MSG_PANDOC_FAILED: "pandoc falhou ({to_format}): {stderr}",
        MSG_PANDOC_REQUIRED_FOR_PDF_UA: (
            "pandoc não encontrado no PATH. O formato pdf_ua exige pandoc + engine LaTeX."
        ),
        MSG_LATEX_ENGINE_NOT_FOUND: (
            "Nenhuma engine LaTeX encontrada no PATH. O formato pdf_ua exige lualatex ou xelatex."
        ),
        MSG_PDF_UA_TEMPLATE_NOT_FOUND: (
            "Template PDF/UA não encontrado: {template_path}"
        ),
        MSG_AUDIT_FAILED: "Auditoria falhou: {findings}",
        MSG_UNSUPPORTED_EXPORT_FORMAT: (
            "Formato de exportação não suportado: {format_name}"
        ),
        # HTML renderer UI chrome (pt-BR mirrors of the MSG_HTML_* ids above).
        MSG_HTML_TABLE_OF_CONTENTS: "Sumário",
        MSG_HTML_TECHNICAL_METADATA: "Metadados técnicos",
        MSG_HTML_IMAGE_DESCRIPTION: "Descrição da imagem",
        # PDF renderer UI chrome (pt-BR mirrors of the MSG_PDF_* ids above).
        MSG_PDF_TABLE_OF_CONTENTS: "Sumário",
        MSG_PDF_NOTE_LABEL: "Nota",
        MSG_PDF_WARNING_LABEL: "Aviso",
        # TXT table line templates (pt-BR mirrors of the MSG_TABLE_TEXT_* ids above).
        MSG_TABLE_TEXT_CAPTION: "Tabela: {caption}",
        MSG_TABLE_TEXT_ROW: "Linha {row_index}: {joined}",
        MSG_TABLE_TEXT_FOOTER: "Rodapé: {footer_text}",
        # Web upload panel user-facing strings (pt-BR mirrors of WEB_* ids above).
        WEB_INDEX_TITLE: "Painel de Acessibilidade - Acessilia",
        WEB_INDEX_HEADLINE: "Bot Acess - Gerador de Acessibilidade",
        WEB_INDEX_INTRO: (
            "Converta seus documentos em formatos acessíveis e receba-os por e-mail."
        ),
        WEB_INDEX_EMAIL_LABEL: "Seu E-mail",
        WEB_INDEX_EMAIL_HELP: "Enviaremos o arquivo final para este endereço.",
        WEB_INDEX_DOC_LABEL: "Anexar Documento (PDF ou Imagem)",
        WEB_INDEX_SUBMIT_BUTTON: "Tornar Acessível",
        WEB_INDEX_ADVANCED_LINK: "Modo Avançado",
        WEB_ADVANCED_TITLE: "Modo Avançado - Acessilia",
        WEB_ADVANCED_HEADLINE: "Modo Avançado",
        WEB_ADVANCED_SUBHEAD: "Prompt personalizado",
        WEB_ADVANCED_INTRO: "Personalize o prompt enviado ao modelo de IA.",
        WEB_ADVANCED_PROMPT_LABEL: "Prompt Personalizado",
        WEB_ADVANCED_PROMPT_PLACEHOLDER: (
            "Digite seu prompt personalizado aqui. Ele substituirá completamente o prompt padrão do sistema."
        ),
        WEB_ADVANCED_PROMPT_HELP: (
            "Máximo de 6000 caracteres. Texto puro apenas (sem formatação). "
            "Este prompt substitui o prompt padrão do sistema para todas as páginas."
        ),
        WEB_ADVANCED_THINKING_LABEL: (
            "Ativar Modo Pensamento (raciocínio interno do modelo)"
        ),
        WEB_ADVANCED_BACK_LINK: "Voltar ao modo normal",
        WEB_DOWNLOAD_TITLE: "Download - Acessilia",
        WEB_DOWNLOAD_HEADLINE: "Download",
        WEB_DOWNLOAD_SUBHEAD: "Escolha o formato desejado",
        WEB_DOWNLOAD_NO_FORMATS: (
            "Nenhum formato disponível para este documento. O link pode ter expirado."
        ),
        WEB_DOWNLOAD_VALID_NOTE: "Link válido por 7 dias.",
        WEB_FORMAT_TXT: "Texto (TXT)",
        WEB_FORMAT_DOCX: "Documento Word (DOCX)",
        WEB_FORMAT_PDF: "PDF Acessível",
        WEB_FORMAT_HTML: "Página Web (HTML)",
        WEB_FORMAT_MP3: "Audiodescrição (MP3)",
        WEB_FORMAT_ZIP: "Pacote completo (ZIP)",
        WEB_LOGO_ALT: (
            "Logotipo com o nome \"acessilia\" em destaque na parte superior. "
            "Acima do nome, um círculo em tons de azul mistura duas imagens: à esquerda, um "
            "documento com bordas arredondadas contendo um ícone de foto no topo e uma grade "
            "tipo planilha na parte inferior; à direita, o perfil de uma cabeça humana voltado "
            "para a direita, também em azul. Três linhas curvas saem da região da boca, "
            "sugerindo fala ou som. À esquerda do documento, fileiras de pequenos pontos "
            "circulares em degradê de azul dão sensação de movimento ou textura digital. Abaixo "
            "do símbolo está a palavra \"acessilia\": \"acess\" em azul escuro e \"ilia\" em "
            "verde-água. Sob o nome, uma linha fina azul com um ponto em cada ponta. Mais "
            "abaixo, o texto \"TRANSFORMANDO DOCUMENTOS. GERANDO ACESSIBILIDADE.\" No rodapé "
            "aparecem quatro ícones em azul escuro, separados por pequenos traços: um quadrado "
            "com seis pontos em relevo (símbolo que lembra braille), um alto-falante, um olho "
            "estilizado e um retângulo que representa um documento ou página."
        ),
        WEB_FOOTER: "Tecnologia para Inclusão",
        WEB_ERROR_INTERNAL: "Erro interno no servidor: {error}",
        WEB_ERROR_API_UPLOAD: "Erro da API ({status_code}): {detail}",
        WEB_ERROR_UPLOAD_GENERIC: (
            "Ocorreu um erro ao enviar o arquivo para a API. Tente novamente."
        ),
        WEB_ERROR_PROMPT_TOO_LONG: (
            "Prompt personalizado excede o limite de 6000 caracteres."
        ),
        WEB_ERROR_DOWNLOAD_INVALID: "Link inválido ou expirado",
        WEB_ERROR_DOWNLOAD_UNAVAILABLE: "Serviço de download indisponível",
        WEB_RATE_LIMIT_EXCEEDED: (
            "Muitas requisições. Aguarde um momento antes de tentar novamente."
        ),
        WEB_SUCCESS_QUEUED: (
            "Sucesso! Seu arquivo entrou na fila (Posição: {position}). "
            "O resultado será enviado para {email}."
        ),
        WEB_AGENT_OS_DESCRIPTION: "Vitrine dos agentes de acessibilidade do Acessília.",
        WEB_AGENT_VISION_DESCRIPTION: (
            "Gera audiodescrições acessíveis de imagens e páginas escaneadas."
        ),
        WEB_AGENT_DATA_DESCRIPTION: (
            "Converte tabelas e fórmulas matemáticas em texto estruturado."
        ),
        WEB_AGENT_DATA_INSTRUCTIONS_FALLBACK: (
            "Converta tabelas e fórmulas matemáticas de imagens em texto estruturado "
            "acessível (Markdown para tabelas, LaTeX para fórmulas)."
        ),
        # Server-side runtime log messages (pt-BR mirrors of backend/log_messages.py),
        # resolved at log time through t() so operator logs follow the server locale.
        LOG_LOGGER_CONFIGURED: "Logger configurado - nível: {level}",
        LOG_BOT_ALREADY_RUNNING: "Outra instância do bot já está em execução (PID={pid})",
        LOG_LOCK_FILE_STALE: (
            "Arquivo de lock obsoleto (PID {pid} não existe), removendo..."
        ),
        LOG_LOCK_ACQUIRED: "Lock adquirido (PID={pid})",
        LOG_LOCK_RELEASED: "Lock liberado",
        LOG_API_INTERFACE_ENABLED: "Interface API habilitada (http://localhost:{port})",
        LOG_TELEGRAM_INTERFACE_ENABLED: "Interface Telegram habilitada",
        LOG_TELEGRAM_INTERFACE_NO_TOKEN: (
            "Interface Telegram habilitada, mas BOT_TOKEN não configurado"
        ),
        LOG_WEB_INTERFACE_ENABLED: "Interface Web habilitada (http://localhost:{port})",
        LOG_NO_INTERFACE_ENABLED: (
            "Nenhuma interface habilitada. Configure ENABLED_INTERFACES no arquivo .env"
        ),
        LOG_STARTING_INTERFACES: "Iniciando com as interfaces: {interfaces}",
        LOG_BOT_INTERRUPTED_BY_USER: "Bot interrompido pelo usuário",
        LOG_BOT_SHUTTING_DOWN: "Bot encerrando",
        LOG_BOT_STARTED: "Bot iniciado (cliente da API Acessilia)",
        LOG_BOT_STARTING_POLLING: "Iniciando polling",
        LOG_BOT_TOKEN_NOT_CONFIGURED: "BOT_TOKEN não configurado",
        LOG_FATAL_ERROR_IN_BOT: "Erro fatal no bot",
        LOG_WORKER_STARTED: "Worker da Fila Unificada iniciado.",
        LOG_QUEUE_ITEM_ENQUEUED: (
            "Fila Unificada: {filename} enfileirado de {source} (Posição: {position})"
        ),
        LOG_WORKER_TASK_STARTING: "Worker: iniciando tarefa {filename} de {source}",
        LOG_WORKER_TASK_ERROR: (
            "Erro no worker ao processar {filename}: {error}"
        ),
        LOG_WORKER_TASK_COMPLETED: (
            "Worker: tarefa concluída: {filename}. Aguardando pela próxima..."
        ),
        LOG_API_STARTED: "Acessilia API iniciada (worker da fila + limpeza ativos)",
        LOG_API_ERROR: "Erro na API: {error} | Caminho: {path}",
        LOG_API_JOB_ENQUEUED: "API: job {task_id} enfileirado (source={source})",
        LOG_CLEANUP_ITEM_FAILED: "Falha ao remover {name}: {error}",
        LOG_CLEANUP_PERIODIC_ERROR: "Erro na limpeza periódica",
        LOG_TEMP_FILE_REMOVED: "Arquivo temporário removido: {name}",
        LOG_TEMP_DIR_REMOVED: "Diretório temporário removido: {name}",
        LOG_TELEGRAM_FILE_DOWNLOADING: "Baixando arquivo: {file_path} -> {filename}",
        LOG_TELEGRAM_FILE_DOWNLOADED: "Arquivo baixado: {filename} ({size} bytes)",
        LOG_TELEGRAM_API_JOB_REJECTED: (
            "API rejeitou a tarefa do Telegram: {status_code} - {detail}"
        ),
        LOG_TELEGRAM_API_CONTACT_FAILED: "Falha ao contatar a API via Telegram",
        LOG_TELEGRAM_FILE_PROCESSING_ERROR: "Erro ao processar arquivo via Telegram",
        LOG_TELEGRAM_JOB_STATUS_QUERY_FAILED: (
            "Erro ao consultar o status da tarefa {task_id}: {error}"
        ),
        LOG_TELEGRAM_RATE_LIMIT_WAIT: (
            "Limite de requisições do Telegram, aguardando {wait}s: {preview}"
        ),
        LOG_TELEGRAM_SEND_FAILED_AFTER_RETRIES: (
            "Falha ao enviar mensagem após {attempts} tentativas"
        ),
        LOG_TELEGRAM_UNHANDLED_ERROR: "Erro não tratado: {error}",
        LOG_TELEGRAM_FEEDBACK_RECEIVED: "FEEDBACK de {user_info}: {feedback}",
        LOG_OUTPUT_DIR_REMOVED: "Diretório de saída removido: {name}",
        LOG_CLEANUP_OUTPUT_FAILED: "Falha ao remover saída {name}: {error}",
        LOG_SMTP_NOT_CONFIGURED: (
            "SMTP não configurado. E-mail para {to_email} não enviado."
        ),
        LOG_EMAIL_SENT: "E-mail enviado com sucesso para {to_email}.",
        LOG_EMAIL_SEND_ERROR: "Erro ao enviar e-mail para {to_email}: {error}",
        LOG_EXPORT_TXT_START: "Exportando TXT para {path}",
        LOG_EXPORT_DOCX_START: "Exportando DOCX para {path}",
        LOG_EXPORT_PDF_START: "Exportando PDF para {path}",
        LOG_EXPORT_PDF_UA_START: "Exportando PDF/UA para {path}",
        LOG_EXPORT_MP3_START: "Exportando MP3 para {path}",
        LOG_PAGE_CONVERTED_TO_PNG: "Página convertida para PNG: {size} bytes",
        LOG_PDDL_IGNORED_OPTIONS: (
            "Pipeline PDDL ignora custom_prompt/thinking_mode; "
            "apenas fluxo deterministico de manifesto/planejamento/execucao"
        ),
        LOG_PDDL_IMAGES_ENRICHED: (
            "Pipeline PDDL: {count} imagem(ns) enriquecida(s) com descrição visual"
        ),
        LOG_PDDL_TABLES_ENRICHED: (
            "Pipeline PDDL: {count} tabela(s) enriquecida(s) com OCR/reconstrução"
        ),
        LOG_PDDL_ELEMENT_CROP_FAILED: (
            "Falha ao extrair recorte de imagem para elemento {element_id}"
        ),
        # raised when the PDDL pipeline is configured with an invalid extractor backend value.
        LOG_PDDL_EXTRACTOR_BACKEND_INVALID: (
            "extractor_backend inválido; use 'docling' ou 'pymupdf'"
        ),
        # raised when the preferred planner backend produced no valid plan in both mode; {backend} is the preferred backend's name.
        LOG_PDDL_PREFERRED_PLAN_MISSING: (
            "Backend preferido {backend} não gerou plano válido no modo both"
        ),
        # raised when validating a nominal plan whose problem.pddl hash does not match the compiled problem.
        LOG_PDDL_PROBLEM_HASH_MISMATCH: "Hash do problem.pddl diverge do plano",
        # raised when validating a nominal plan whose domain.pddl hash does not match the domain bundle.
        LOG_PDDL_DOMAIN_HASH_MISMATCH: "Hash do domain.pddl diverge do plano",
        # raised when validating a nominal plan whose domain description hash does not match the domain bundle.
        LOG_PDDL_DOMAIN_DESCRIPTION_HASH_MISMATCH: (
            "Hash da descrição do domínio diverge do plano"
        ),
        # raised when validating a nominal plan whose selected obligation closure does not match the compiled problem's.
        LOG_PDDL_SELECTED_CLOSURE_MISMATCH: (
            "Fechamento selecionado diverge do problema compilado"
        ),
        LOG_READER_PDF_REGIONS_EXTRACTED: (
            "[página {page_num}] Extraídas {count} região(ns) na página (structurer={structurer})"
        ),
        LOG_READER_CLEAN_TEXT_REGIONS: (
            "[página {page_num}] {count} região(ns) de texto limpo (sem IA de visão)"
        ),
        LOG_READER_REGION_TASK: (
            "[página {page_num}] Região {idx} - tipo={type}, bbox={bbox}, target={target}"
        ),
        # reader full-page fallback warning; {page_num} the page number.
        LOG_READER_FULL_PAGE_FALLBACK: (
            "[página {page_num}] Nenhum texto extraído por regiões, fallback para a página completa"
        ),
        # reader per-page task summary line; {page_num} the page number, {count} total tasks, {text_count} editor-bound, {vision_count} vision-bound.
        LOG_READER_TASKS_SUMMARY: (
            "[página {page_num}] {count} tarefas ({text_count} texto, {vision_count} visão)"
        ),
        # reader image-page debug line; {page_num} the page number, {path} the per-page image file path.
        LOG_READER_IMAGE_READING: "[página {page_num}] lendo imagem: {path}",

        LOG_PDF_PAGE_COUNT_LOGGED: (
            "PDF tem {total} páginas, processando {limit}"
        ),
        LOG_PDF_PAGE_SAVED: "Página {page} salva: {name}",
        # PDF export wrapper debug line; {output_path} the destination file path.
        LOG_PDF_EXPORTED: (
            "PDF exportado com marcadores e numeração de páginas: {output_path}"
        ),
        # PDF/UA export wrapper debug line; {output_path} the destination file path.
        LOG_PDF_UA_EXPORTED: "PDF/UA exportado: {output_path}",
        # TXT export wrapper debug line; {output_path} the destination file path.
        LOG_TXT_EXPORTED: "TXT exportado: {output_path}",
        # DOCX export wrapper debug line; {output_path} the destination file path.
        LOG_DOCX_EXPORTED: "DOCX exportado: {output_path}",
        LOG_PDF_PAGES_EXTRACTED: "{count} páginas extraídas para {tmpdir}",
        # Confirmation/result e-mail subjects and bodies (pt-BR mirrors).
        EMAIL_CONFIRMATION_SUBJECT: "Recebemos o seu arquivo - Acessilia",
        EMAIL_CONFIRMATION_BODY: (
            "Olá!\n\n"
            "Recebemos o arquivo '{filename}' e já estamos trabalhando para torná-lo acessível.\n"
            "Esse processo envolve análise por inteligência artificial e geração de uma descrição em áudio.\n\n"
            "Assim que estiver pronto, você receberá um novo e-mail com o pacote acessível em anexo.\n\n"
            "Atenciosamente,\nA equipe Acessilia"
        ),
        EMAIL_RESULT_SUBJECT: "Seu arquivo acessível está pronto! - Acessilia",
        EMAIL_RESULT_BODY_WITH_LINK: (
            "Olá!\n\n"
            "O processamento do arquivo '{filename}' foi concluído com sucesso.\n\n"
            "Acesse o link abaixo para visualizar e baixar os formatos disponíveis:\n\n"
            "{download_url}\n\n"
            "Formatos disponíveis: {formats}."
            "{warnings}\n\n"
            "O link expira em 7 dias.\n\n"
            "Atenciosamente,\nA equipe Acessilia"
        ),
        # Attached-body mirrors the msgid's bullet-list + warnings placeholders;
        # {formats} receives one "- <label>" line per completed format.
        EMAIL_RESULT_BODY_ATTACHED: (
            "Olá!\n\n"
            "O processamento do arquivo '{filename}' foi concluído com sucesso.\n"
            "Em anexo, você encontrará um pacote ZIP contendo os seguintes formatos:\n"
            "{formats}"
            "{warnings}\n\n"
            "Atenciosamente,\nA equipe Acessilia"
        ),
        EMAIL_FORMAT_TXT: "Texto Puro (TXT)",
        EMAIL_FORMAT_DOCX: "Documento Word (DOCX)",
        EMAIL_FORMAT_PDF: "PDF Acessível",
        EMAIL_FORMAT_PDF_UA: "PDF/UA",
        EMAIL_FORMAT_HTML: "Página Web (HTML)",
        EMAIL_FORMAT_MP3: "Audiodescrição (MP3)",
        EMAIL_FORMAT_ZIP: "Pacote ZIP",
        EMAIL_RESULT_WARNINGS_HEADER: (
            "Alguns formatos opcionais não foram gerados:"
        ),
        LOG_CANONICAL_JSON_SAVE_FAILED: (
            "Não foi possível salvar o JSON canônico: {error}"
        ),
        LOG_TASK_CANCELLED_BY_USER: "Tarefa {task_id} cancelada pelo usuário",
        LOG_PIPELINE_ERROR: "Erro no pipeline: {error_type}: {error}",
        LOG_PROMPT_FILE_NOT_FOUND: (
            "Arquivo de prompt não encontrado em {path}, usando o fallback para medio"
        ),
        LOG_DATA_AGENT_PROMPT_NOT_FOUND: (
            "[página {page_num}] Prompt não encontrado para tipo={type}, usando fallback"
        ),
        LOG_DATA_AGENT_PROCESSING_REGION: (
            "[página {page_num}] DataAgent processando região ({size} bytes, tipo={type})"
        ),
        LOG_DATA_AGENT_REGION_ERROR: (
            "[página {page_num}] DataAgent erro na região {type}: {error} | Traceback:\n{tb}"
        ),
        LOG_VISION_AGENT_SENDING_REGION: (
            "[página {page_num}] Enviando região para visão ({size} bytes, tipo={type})"
        ),
        LOG_VISION_AGENT_REGION_ERROR: (
            "[página {page_num}] Erro na região {type}: {error} | Traceback:\n{tb}"
        ),
        LOG_EDITOR_PAGE_EMPTY: "[página {page_num}] EditorAgent: nenhum texto consolidado",
        LOG_EDITOR_PAGE_CONSOLIDATED: (
            "[página {page_num}] EditorAgent: {count} partes de texto consolidadas"
        ),
        LOG_REGION_CROP_FAILED: "Falha ao recortar a região: {error}",
        LOG_CACHE_HIT: "Cache: item existente para {name}",
        LOG_CACHE_DEBUG_HIT: "Cache: item existente: {key}",
        LOG_CACHE_DEBUG_SET: "Cache: item gravado: {key}",
        LOG_CACHE_SAVE_FAILED: "Falha ao salvar no cache: {error}",
        LOG_CACHE_CLEARED: "Cache limpo: {count} arquivo(s) removido(s)",
        LOG_ORPHAN_TASKS_CLEANED: "Tarefas órfãs limpas",
        LOG_ORPHAN_TASKS_CLEANUP_FAILED: (
            "Falha ao limpar tarefas órfãs: {error}"
        ),
        LOG_DOCLING_NOT_AVAILABLE: "Docling não está disponível no ambiente atual.",
        LOG_DOCLING_PAGE_NO_PARENT: (
            "Página sem documento pai para processamento Docling"
        ),
        LOG_DOCLING_PAGE_FAILED: (
            "Docling falhou na página {page} ({error}), fallback PyMuPDF"
        ),
        LOG_DOCLING_PROCESSED: "Docling processou {filename} em {elapsed:.1f}s",
        LOG_DOWNLOAD_TOKEN_CREATED: "Token de download criado: {token} -> {filename}",
        LOG_DOWNLOAD_TOKEN_NOT_FOUND: "Token de download não encontrado: {token}",
        LOG_DOWNLOAD_TOKEN_DIR_MISSING: (
            "Diretório de saída do token de download ausente: {token} -> {output_dir}"
        ),
        LOG_PDF_UA_GENERATION_FAILED: (
            "Falha ao gerar o PDF/UA: {error}"
        ),
        LOG_MP3_GENERATION_FAILED: "Falha ao gerar o MP3: {error}",
        LOG_JOB_COMPLETED: "Job {task_id} concluído (source={source})",
        LOG_JOB_CANCELLED: "Job {task_id} cancelado",
        LOG_JOB_EXECUTOR_ERROR: "Erro no JobExecutor para {task_id}",
        LOG_IMAGE_PREPROCESS_FAILED: "Erro no pré-processamento de imagem: {error}",
        LOG_IMAGE_RESIZED: (
            "Imagem redimensionada: {old_width}x{old_height} -> {new_width}x{new_height}"
        ),
        LOG_IMAGE_ROTATED: "Imagem rotacionada em {angle:.2f} graus",
        LOG_WEB_GLOBAL_ERROR: (
            "Erro global no Painel Web: {error} | Caminho: {path}"
        ),
        LOG_WEB_UPLOAD_ERROR: "Erro no upload da web: {error}",
        LOG_WEB_DOWNLOAD_QUERY_FAILED: (
            "Falha ao consultar a API para o download: {status_code} - {detail}"
        ),
        LOG_WEB_HTTP_EXCEPTION: (
            "Exceção HTTP no Painel Web: {error} | Caminho: {path}"
        ),
        LOG_WEB_RATE_LIMIT_EXCEEDED: (
            "Limite de requisições excedido no Painel Web: ip={ip} | Caminho: {path}"
        ),
        LOG_WEB_API_UPLOAD_ERROR: (
            "Erro de upload na API no Painel Web: {status_code} - {detail}"
        ),
        LOG_STATUS_MESSAGE_SEND_FAILED: (
            "Falha ao enviar a mensagem de status: {error}"
        ),
        LOG_STATUS_MESSAGE_EDIT_FAILED: (
            "Falha ao editar a mensagem de status: {error}"
        ),
        LOG_STATUS_EDIT_UNEXPECTED: (
            "Erro inesperado ao editar o status: {error}"
        ),
        LOG_AUDIO_EXPORTED: (
            "Áudio falado (MP3) exportado em detalhes com sucesso: {path}"
        ),
        LOG_AUDIO_EXPORT_ERROR: "Erro ao exportar o MP3 em detalhes: {error}",
        LOG_AUDIO_EXPORT_START: (
            "Iniciando geração de áudio granular (TTS): {voice} -> {path}"
        ),
        LOG_AUDIO_EXPORT_PROGRESS: (
            "Gerando áudio (TTS): {completed}/{total} blocos concluídos "
            "({percent}%)"
        ),
        API_RATE_LIMIT_DETAIL: (
            "Muitas requisições. Aguarde um momento e tente novamente."
        ),
        API_INTERNAL_ERROR_DETAIL: "Erro interno no servidor",
        # raised when the language-agent returns an empty result for a document.
        LOG_ORCHESTRATOR_EMPTY_AGENT_RESPONSE: "Resposta vazia do agente",
        # orchestrator empty model-response warning; {page_num} is the page number.
        LOG_ORCHESTRATOR_EMPTY_PAGE_RESPONSE: (
            "Resposta vazia para página {page_num}"
        ),
        # orchestrator page-response saved info line; {page_num} is the page number, {file_name} the output file name.
        LOG_ORCHESTRATOR_PAGE_RESPONSE_SAVED: (
            "Resposta da página {page_num} salva em {file_name}"
        ),
        # orchestrator parallel-task wait line; {page_num} is the page number, {count} the number of pending AI tasks.
        LOG_ORCHESTRATOR_WAITING_TASKS: (
            "[página {page_num}] Aguardando {count} tarefa(s) de IA em paralelo..."
        ),
        # orchestrator failed-task error line; {page_num} is the page number, {idx} the failed task's index, {error} the exception.
        LOG_ORCHESTRATOR_TASK_FAILED: (
            "[página {page_num}] Tarefa {idx} falhou: {error}"
        ),
        # orchestrator workflow start line; {page_count} the page count, {file_name} the source file name, {reader} the structurer, {mode} the effective mode.
        LOG_ORCHESTRATOR_WORKFLOW_START: (
            "AccessibilityWorkflow: processando {page_count} página(s) para {file_name} "
            "(reader={reader}, mode={mode})"
        ),
        # orchestrator workflow summary line; {total_pages} and {total_chars} are the run totals.
        LOG_ORCHESTRATOR_WORKFLOW_SUMMARY: (
            "AccessibilityWorkflow: {total_pages} páginas processadas, {total_chars} chars no total"
        ),
        # orchestrator page-cache debug line; {page_num} is the page index.
        LOG_ORCHESTRATOR_PAGE_CACHE_SKIP: (
            "[página {page_num}] Cache: item existente (pulando IA)"
        ),
        # RapidOCR local model cache restore line (pt-BR mirror); {count} is the number of model files restored.
        LOG_RAPIDOCR_MODELS_RESTORED: (
            "RapidOCR: {count} modelo(s) restaurado(s) do cache local"
        ),
        # RapidOCR local model cache persist line (pt-BR mirror); {count} is the number of model files persisted.
        LOG_RAPIDOCR_MODELS_PERSISTED: (
            "RapidOCR: {count} modelo(s) persistido(s) no cache local"
        ),
        # Document structurer selection lines (pt-BR mirrors of the LOG_STRUCTURER_* ids above).
        LOG_STRUCTURER_DOCLING: (
            "Usando structurer: Docling (com fallback PyMuPDF)"
        ),
        LOG_STRUCTURER_DOCLING_NOT_INSTALLED: (
            "STRUCTURER=docling está definido mas docling não está instalado. "
            "Execute: pip install docling. Usando PyMuPDF."
        ),
        LOG_STRUCTURER_FALLBACK_PYMUPDF: (
            "STRUCTURER=docling mas docling nao instalado. Usando PyMuPDF."
        ),
        LOG_STRUCTURER_PYMUPDF: "Usando structurer: PyMuPDF",
        LOG_STALE_PROCESS_INTERRUPTED: "Obsoleta: processo interrompido",
        LOG_AGNO_NOT_INSTALLED: (
            "Agno não está instalado. Execute `poetry install` antes de usar "
            "o workflow Executor."
        ),
    },
}

#: Canonical English singular/plural msgid pair, then a per-locale mapping of localized pairs with the same index ordering.
PLURAL_MESSAGES: tuple[tuple[str, str], dict[str, tuple[str, str]]] = (
    ("document", "documents"),
    {"pt_BR": ("documento", "documentos")},
)


def _validate(translations: dict[str, dict[str, str]], locales: tuple[str, ...]) -> list[str]:
    """Cross-check translation tables for completeness before any file is written.

    Args:
        translations (dict): msgid-to-localized-text mapping per locale as passed via :data:`TRANSLATIONS` at call time.
        locales (tuple): Every supported locale identifier under validation, e.g. the default :data:`SUPPORTED_LOCALES` or an alternate tuple injected by tests.

    Returns:
        list: Problem descriptions, empty when every non-default locale covers all MESSAGES ids with non-blank values.
    """
    problems: list[str] = []
    for locale in locales:
        if locale == DEFAULT_LOCALE:
            continue
        table = translations.get(locale)
        missing = (
            [f"locale {locale!r} has no translation table"]
            if not isinstance(table, dict)
            else [msgid for msgid in MESSAGES if msgid not in table or not str(table[msgid]).strip()]
        )
        problems.extend(f"missing or blank entry: {x!r}" for x in missing)
    return problems


def _write_catalog(locale: str, catalog, locales_dir: Path) -> tuple[Path, Path]:
    """Write one Babel catalog's .po source and compiled .mo binary under a locale directory tree.

    Args:
        locale (str): Target runtime locale name; the locale/<locale>/LC_MESSAGES structure is created as necessary before writing both files there.
        catalog (babel.messages.catalog.Catalog): Message catalog for the locale, already populated with MESSAGES/PLURAL_MESSAGES entries by callers before this write-out.
        locales_dir (Path): Root directory holding one subdirectory per locale; tests may inject a temporary root instead of :data:`DEFAULT_LOCALES_DIR` so verification never touches repository files.

    Returns:
        tuple: (po_path, mo_path) pair of files written for this locale.
    """
    lmessages = locales_dir / locale / "LC_MESSAGES"
    lmessages.mkdir(parents=True, exist_ok=True)
    po_path = lmessages / "messages.po"
    mo_path = lmessages / "messages.mo"
    from babel.messages.mofile import write_mo
    from babel.messages.pofile import write_po
    with open(po_path, "wb") as source_stream:
        write_po(source_stream, catalog)
    with open(mo_path, "wb") as mo_stream:
        write_mo(mo_stream, catalog)
    return po_path, mo_path


def build_locales(locales_dir: Path = DEFAULT_LOCALES_DIR) -> dict[str, tuple[Path, Path]]:
    """Build every supported locale's .po/.mo pair after validating translation tables are complete.

    Args:
        locales_dir (Path): Output root receiving one directory per locale; tests pass a temporary directory outside the repo so generated artifacts never land inside the checked-in backend/locales production layout. Defaults to :data:`DEFAULT_LOCALES_DIR`.

    Returns:
        dict: locale name mapped to its (po_path, mo_path) artifact pair written by this pass for that locale's LC_MESSAGES tree.
    """
    problems = _validate(TRANSLATIONS, SUPPORTED_LOCALES)
    if problems:
        raise ValueError("incomplete locale translations: " + "; ".join(problems))
    from babel.messages.catalog import Catalog

    result: dict[str, tuple[Path, Path]] = {}
    for locale in SUPPORTED_LOCALES:
        catalog = Catalog(locale=locale)
        if locale == DEFAULT_LOCALE:
            for msgid in MESSAGES:
                catalog.add(msgid, msgid)
            (singular_en, plural_en) = PLURAL_MESSAGES[0]
            catalog.add((singular_en, plural_en), [singular_en, plural_en])
        else:
            table = TRANSLATIONS[locale]
            for msgid in MESSAGES:
                catalog.add(msgid, table[msgid])
            (localized_sing, localized_plur) = PLURAL_MESSAGES[1][locale]
            catalog.add(PLURAL_MESSAGES[0], [localized_sing, localized_plur])
        result[locale] = _write_catalog(locale, catalog, locales_dir)
    return result


def build_parser() -> argparse.ArgumentParser:
    """Construct the CLI argument parser for this generator script.

    Returns:
        argparse.ArgumentParser: Argument parser accepting an optional --locales-dir flag whose default is :data:`DEFAULT_LOCALES_DIR` when omitted.
    """
    parser = argparse.ArgumentParser(prog="gen-locale-catalogs", description=__doc__)
    parser.add_argument("--locales-dir", type=Path, default=None, help="output root directory for locale catalogs (default: backend/locales).")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entrypoint validating tables then building all configured locale catalog files.

    Args:
        argv (Sequence|None): Optional argument vector for tests; defaults to sys.argv when omitted during manual invocation. Defaults to None.

    Returns:
        int: 0 on success, 2 when validation or a write step fails.
    """
    args = build_parser().parse_args(argv)
    try:
        written = build_locales(args.locales_dir or DEFAULT_LOCALES_DIR)
    except Exception as exc:  # noqa: BLE001 - single broad catch keeps CLI failure messages terse
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for locale, (po_path, mo_path) in sorted(written.items()):
        try:
            display = mo_path.relative_to(PROJECT_ROOT)
        except ValueError:
            display = mo_path
        print(f"{locale}: {display}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
