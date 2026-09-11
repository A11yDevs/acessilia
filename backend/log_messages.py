"""Canonical English msgids for runtime log messages.

These constants hold the canonical English texts emitted by the server's own
loggers (startup, queue worker, cleanup, cache, API lifespan, email). Callers
resolve them at log time through :func:`backend.i18n.t` so the log output is
displayed in the server-side locale detected from the shell environment
(then the .env LOCALE value, then en_US), while the msgids themselves stay
stable English identifiers across every supported locale.
"""

#: Emitted by setup_logger once the root logger sinks are registered; {level} is the active level name.
LOG_LOGGER_CONFIGURED: str = "Logger configured - level: {level}"
#: Critical message logged when the startup lock file names a live PID already running the bot.
LOG_BOT_ALREADY_RUNNING: str = "Another instance of the bot is already running (PID={pid})"
#: Warning logged when a stale lock file whose PID no longer exists is detected and removed.
LOG_LOCK_FILE_STALE: str = "Lock file stale (PID {pid} does not exist), removing..."
#: Info logged once the startup lock file is written with the current process PID.
LOG_LOCK_ACQUIRED: str = "Lock acquired (PID={pid})"
#: Info logged when the startup lock file is removed during graceful shutdown.
LOG_LOCK_RELEASED: str = "Lock released"
#: Info logged when the API interface is enabled at startup; {port} is the bound listen port.
LOG_API_INTERFACE_ENABLED: str = "API interface enabled (http://localhost:{port})"
#: Info logged when the Telegram interface is enabled at startup.
LOG_TELEGRAM_INTERFACE_ENABLED: str = "Telegram interface enabled"
#: Warning logged when the Telegram interface is enabled in settings but no bot token has been configured.
LOG_TELEGRAM_INTERFACE_NO_TOKEN: str = (
    "Telegram interface enabled but BOT_TOKEN not configured"
)
#: Info logged when the Web interface is enabled at startup; {port} is the bound listen port.
LOG_WEB_INTERFACE_ENABLED: str = "Web interface enabled (http://localhost:{port})"
#: Critical message logged when no interface is enabled in ENABLED_INTERFACES; process exits.
LOG_NO_INTERFACE_ENABLED: str = (
    "No interface enabled. Configure ENABLED_INTERFACES in the .env file"
)
#: Info logged just before the started interface tasks are run; {interfaces} lists the enabled names.
LOG_STARTING_INTERFACES: str = "Starting with interfaces: {interfaces}"
#: Info logged when the startup run loop is interrupted by the user (Ctrl+C).
LOG_BOT_INTERRUPTED_BY_USER: str = "Bot interrupted by the user"
#: Exception-level message logged for any unexpected fatal error in the bot run loop.
LOG_FATAL_ERROR_IN_BOT: str = "Fatal error in the bot"
#: Info logged by the Telegram bot once it has started and registered its routers.
LOG_BOT_STARTED: str = "Bot started (Acessilia API client)"
#: Info logged while the Telegram bot dispatcher tears down on shutdown.
LOG_BOT_SHUTTING_DOWN: str = "Bot shutting down"
#: Critical message logged when the bot token is missing or invalid, before the process exits.
LOG_BOT_TOKEN_NOT_CONFIGURED: str = "BOT_TOKEN not configured"
#: Info logged just before the Telegram bot begins long-polling.
LOG_BOT_STARTING_POLLING: str = "Starting polling"
#: Info logged by the Unified Queue worker task when it begins servicing the queue.
LOG_WORKER_STARTED: str = "Unified Queue worker started."
#: Info logged by the Unified Queue when an item is enqueued; {filename} is the source file name, {source} the channel, {position} the queue slot.
LOG_QUEUE_ITEM_ENQUEUED: str = (
    "Unified Queue: {filename} enqueued from {source} (Position: {position})"
)
#: Info logged by the Unified Queue worker when it dequeues an item and processing begins.
LOG_WORKER_TASK_STARTING: str = "Worker: starting task {filename} from {source}"
#: Error logged by the Unified Queue worker when a task callback raised an exception.
LOG_WORKER_TASK_ERROR: str = "Worker error while processing {filename}: {error}"
#: Info logged by the Unified Queue worker once a task finishes, before waiting for the next item.
LOG_WORKER_TASK_COMPLETED: str = (
    "Worker: task completed: {filename}. Waiting for the next..."
)
#: Info logged by the API lifespan once the queue worker and periodic cleanup tasks are active.
LOG_API_STARTED: str = "Acessilia API started (queue worker + cleanup active)"
#: Exception-level message logged by the API global exception handler; {error} is the exception, {path} the request path.
LOG_API_ERROR: str = "Error in the API: {error} | Path: {path}"
#: Info logged by the API jobs route once an uploaded file has been accepted and placed in the unified queue; {task_id} is the new job id, {source} the submitting channel.
LOG_API_JOB_ENQUEUED: str = "API: job {task_id} enqueued (source={source})"
#: Warning logged by the periodic cleanup when an item could not be removed; {name} is the item name, {error} the reason.
LOG_CLEANUP_ITEM_FAILED: str = "Failed to remove {name}: {error}"
#: Exception-level message logged by the periodic cleanup loop on an unexpected failure.
LOG_CLEANUP_PERIODIC_ERROR: str = "Error in the periodic cleanup"
#: Debug logged by the periodic cleanup when a temporary file is removed; {name} is the file name.
LOG_TEMP_FILE_REMOVED: str = "Temporary file removed: {name}"
#: Debug logged by the periodic cleanup when a temporary directory is removed; {name} is the directory name.
LOG_TEMP_DIR_REMOVED: str = "Temporary directory removed: {name}"
#: Debug logged by the output cleanup when an expired output directory is removed; {name} is the directory name.
LOG_OUTPUT_DIR_REMOVED: str = "Output directory removed: {name}"
#: Warning logged by the output cleanup when an output directory could not be removed; {name} is the name, {error} the reason.
LOG_CLEANUP_OUTPUT_FAILED: str = "Failed to remove output {name}: {error}"
#: Warning logged when SMTP credentials are missing, so a pending notification email is not sent; {to_email} is the recipient.
LOG_SMTP_NOT_CONFIGURED: str = (
    "SMTP not configured. E-mail to {to_email} not sent."
)
#: Info logged after a notification email has been delivered; {to_email} is the recipient.
LOG_EMAIL_SENT: str = "E-mail sent successfully to {to_email}."
#: Error logged after a notification email delivery attempt failed; {to_email} is the recipient, {error} the reason.
LOG_EMAIL_SEND_ERROR: str = "Error sending e-mail to {to_email}: {error}"
#: Subject line of the confirmation email sent when a source document has been received.
EMAIL_CONFIRMATION_SUBJECT: str = "We received your file - Acessilia"
#: Body of the confirmation email sent when a source document has been received; {filename} is the submitted file name.
EMAIL_CONFIRMATION_BODY: str = (
    "Hello!\n\n"
    "We received the file '{filename}' and we are already working to make it accessible.\n"
    "This process involves analysis by artificial intelligence and generation of an audio description.\n\n"
    "As soon as it is ready, you will receive a new e-mail with the accessible package attached.\n\n"
    "Best regards,\nThe Acessilia Team"
)
#: Subject line of the result email sent when the accessible package is ready.
EMAIL_RESULT_SUBJECT: str = "Your accessible file is ready! - Acessilia"
#: Body of the result email when a download link is available; {filename} the source file name, {download_url} the URL, {formats} the localized comma-separated list of completed formats, {warnings} the optional localized warning block (or empty text when there are no warnings).
EMAIL_RESULT_BODY_WITH_LINK: str = (
    "Hello!\n\n"
    "The processing of the file '{filename}' has completed successfully.\n\n"
    "Access the link below to view and download the available formats:\n\n"
    "{download_url}\n\n"
    "Available formats: {formats}."
    "{warnings}\n\n"
    "The link expires in 7 days.\n\n"
    "Best regards,\nThe Acessilia Team"
)
#: Body of the result email when the accessible package is attached as a ZIP; {filename} the source file name, {formats} the localized newline-separated bullet list of completed formats, {warnings} the optional localized warning block (or empty text when there are no warnings).
EMAIL_RESULT_BODY_ATTACHED: str = (
    "Hello!\n\n"
    "The processing of the file '{filename}' has completed successfully.\n"
    "Attached, you will find a ZIP package containing the following formats:\n"
    "{formats}"
    "{warnings}\n\n"
    "Best regards,\nThe Acessilia Team"
)
#: Localized display name of the plain-text (TXT) output artifact, listed in the result email's completed-formats block.
EMAIL_FORMAT_TXT: str = "Plain Text (TXT)"
#: Localized display name of the Word (DOCX) output artifact, listed in the result email's completed-formats block.
EMAIL_FORMAT_DOCX: str = "Word Document (DOCX)"
#: Localized display name of the non-tagged PDF output artifact, listed in the result email's completed-formats block.
EMAIL_FORMAT_PDF: str = "PDF"
#: Localized display name of the tagged PDF/UA output artifact, listed in the result email's completed-formats block.
EMAIL_FORMAT_PDF_UA: str = "PDF/UA"
#: Localized display name of the web-page (HTML) output artifact, listed in the result email's completed-formats block.
EMAIL_FORMAT_HTML: str = "Web Page (HTML)"
#: Localized display name of the spoken-audio (MP3) output artifact, listed in the result email's completed-formats block.
EMAIL_FORMAT_MP3: str = "Audio Description (MP3)"
#: Localized display name of the bundled ZIP package output artifact, listed in the result email's completed-formats block.
EMAIL_FORMAT_ZIP: str = "ZIP Package"
#: Intro line of the optional warning block appended to the result email body when one or more optional export formats failed; has no placeholders.
EMAIL_RESULT_WARNINGS_HEADER: str = "Some optional formats were not generated:"
#: Info logged when a canonical-JSON persistence attempt raised; the exception text follows.
LOG_CANONICAL_JSON_SAVE_FAILED: str = "Could not save the canonical JSON: {error}"
#: Info logged when a processing job is cancelled by the user; {task_id} identifies the job.
LOG_TASK_CANCELLED_BY_USER: str = "Task {task_id} cancelled by the user"
#: Error logged when the processing pipeline raised an unhandled exception; {error_type} is the class name, {error} the text.
LOG_PIPELINE_ERROR: str = "Pipeline error: {error_type}: {error}"
#: Info logged when a canonical-document lookup in the cache hit; {name} is the source file name.
LOG_CACHE_HIT: str = "Cache hit for {name}"
#: Debug logged when the structured-output cache lookup hit; {key} is the cache key.
LOG_CACHE_DEBUG_HIT: str = "Cache hit: {key}"
#: Debug logged when a new cache entry is stored; {key} is the cache key.
LOG_CACHE_DEBUG_SET: str = "Cache set: {key}"
#: Warning logged when writing a cache entry failed; {error} is the reason.
LOG_CACHE_SAVE_FAILED: str = "Failed to save cache: {error}"
#: Info logged once the cache is emptied; {count} is the number of entries removed.
LOG_CACHE_CLEARED: str = "Cache cleared: {count} files removed"
#: Info logged when stale processing records are marked as errors; the message has no placeholders.
LOG_ORPHAN_TASKS_CLEANED: str = "Orphan tasks cleaned"
#: Warning logged when cleaning stale processing records failed; {error} is the reason.
LOG_ORPHAN_TASKS_CLEANUP_FAILED: str = "Failed to clean orphan tasks: {error}"
#: User-facing error value stored in the conversion-history record of a stale task that cleanup marked as failed; no placeholders.
LOG_STALE_PROCESS_INTERRUPTED: str = "Stale: process interrupted"
#: Debug logged when a download token is created; {token} is the new token, {filename} its source file name.
LOG_DOWNLOAD_TOKEN_CREATED: str = "Download token created: {token} -> {filename}"
#: Warning logged when a download token lookup misses; {token} is the unknown token.
LOG_DOWNLOAD_TOKEN_NOT_FOUND: str = "Download token not found: {token}"
#: Warning logged when a known token's stored output directory no longer exists on disk; {token} is the token, {output_dir} its path.
LOG_DOWNLOAD_TOKEN_DIR_MISSING: str = (
    "Download token output directory missing: {token} -> {output_dir}"
)
#: Debug logged by the Telegram file service while downloading an uploaded file; {file_path} is the Telegram file path, {filename} the destination file name.
LOG_TELEGRAM_FILE_DOWNLOADING: str = "Downloading file: {file_path} -> {filename}"
#: Info logged by the Telegram file service once the uploaded file finished downloading; {filename} the file name, {size} its size in bytes.
LOG_TELEGRAM_FILE_DOWNLOADED: str = "File downloaded: {filename} ({size} bytes)"
#: Warning logged by the API worker when PDF/UA export failed; {error} is the reason.
LOG_PDF_UA_GENERATION_FAILED: str = "Failed to generate PDF/UA: {error}"
#: Error logged by the API worker when MP3 audio export failed; {error} is the reason.
LOG_MP3_GENERATION_FAILED: str = "Failed to generate MP3: {error}"
#: Info logged when a job has finished processing and exporting; {task_id} identifies the job, {source} the channel.
LOG_JOB_COMPLETED: str = "Job {task_id} completed (source={source})"
#: Info logged when a job was cancelled before finishing; {task_id} identifies the job.
LOG_JOB_CANCELLED: str = "Job {task_id} cancelled"
#: Exception-level message logged by the API worker when a job raised unexpectedly; {task_id} identifies the job.
LOG_JOB_EXECUTOR_ERROR: str = "Error in JobExecutor for {task_id}"
#: Exception-level message logged by the Telegram error handler for any unhandled exception; {error} is the exception.
LOG_TELEGRAM_UNHANDLED_ERROR: str = "Unhandled error: {error}"
#: Info logged when a user submits feedback on processing quality via Telegram; {user_info} the user's id or username, {feedback} the free text.
LOG_TELEGRAM_FEEDBACK_RECEIVED: str = "FEEDBACK from {user_info}: {feedback}"
#: Warning logged when a Telegram send is throttled and the handler waits before retrying; {wait} the seconds to wait, {preview} a short preview of the message text.
LOG_TELEGRAM_RATE_LIMIT_WAIT: str = "Telegram rate limit, waiting {wait}s: {preview}"
#: Error logged when sending a Telegram message still failed after all retry attempts; {attempts} the number of attempts made.
LOG_TELEGRAM_SEND_FAILED_AFTER_RETRIES: str = (
    "Failed after {attempts} attempts to send message"
)
#: Warning logged when the API rejected a job submitted from Telegram; {status_code} the HTTP code, {detail} the server detail.
LOG_TELEGRAM_API_JOB_REJECTED: str = (
    "API rejected the Telegram job: {status_code} - {detail}"
)
#: Exception-level message logged when contacting the API from the Telegram handler raised unexpectedly.
LOG_TELEGRAM_API_CONTACT_FAILED: str = "Failure contacting API via Telegram"
#: Exception-level message logged when an unexpected error aborted a file submission from Telegram.
LOG_TELEGRAM_FILE_PROCESSING_ERROR: str = "Error processing file via Telegram"
#: Warning logged when a poll of a Telegram job's status from the API failed; {task_id} the job id, {error} the reason.
LOG_TELEGRAM_JOB_STATUS_QUERY_FAILED: str = (
    "Error querying job {task_id} status: {error}"
)
#: Error logged by the web panel global exception handler; {error} the exception, {path} the request path.
LOG_WEB_GLOBAL_ERROR: str = "Global error in the Web Panel: {error} | Path: {path}"
#: Error logged when a web upload fails; {error} is the reason.
LOG_WEB_UPLOAD_ERROR: str = "Error in the web upload: {error}"
#: Warning logged when the web panel query for download info on the API failed; {status_code} the HTTP code, {detail} the server detail.
LOG_WEB_DOWNLOAD_QUERY_FAILED: str = (
    "Failed to query the API for the download: {status_code} - {detail}"
)
#: Warning logged by the web panel HTTP exception handler for non-global HTTP errors; {error} is the detail text, {path} the request path.
LOG_WEB_HTTP_EXCEPTION: str = (
    "HTTP exception in the Web Panel: {error} | Path: {path}"
)
#: Warning logged by the web panel rate-limit handler when a client exceeds its request budget; {ip} is the client address, {path} the request path.
LOG_WEB_RATE_LIMIT_EXCEEDED: str = (
    "Rate limit exceeded in the Web Panel: ip={ip} | Path: {path}"
)
#: Warning logged by the web panel upload path when the API submit job call rejected the file with an HTTP error; {status_code} the HTTP code, {detail} the API detail text.
LOG_WEB_API_UPLOAD_ERROR: str = (
    "API upload error in the Web Panel: {status_code} - {detail}"
)
#: Warning logged when sending a job status message to Telegram failed; {error} is the reason.
LOG_STATUS_MESSAGE_SEND_FAILED: str = "Failed to send the status message: {error}"
#: Debug logged when editing a previously sent status message to Telegram failed; {error} is the reason.
LOG_STATUS_MESSAGE_EDIT_FAILED: str = (
    "Failed to edit the status message: {error}"
)
#: Warning logged for an unexpected error while editing a status message; {error} is the reason.
LOG_STATUS_EDIT_UNEXPECTED: str = (
    "Unexpected error while editing the status: {error}"
)
#: Info logged when the granular MP3 audio export finished; {path} is the output file path.
LOG_AUDIO_EXPORTED: str = "Spoken audio (MP3) granularly exported successfully: {path}"
#: Audio MP3 export failed; {error} is the reason.
LOG_AUDIO_EXPORT_ERROR: str = "Error exporting granular MP3: {error}"
#: Debug logged before the granular MP3 audio export begins TTS generation; {voice} is the TTS voice name, {path} the output file path.
LOG_AUDIO_EXPORT_START: str = "Starting granular audio (TTS) generation: {voice} -> {path}"
#: Info logged each time one TTS chunk finishes during the granular MP3 export; {completed} and {total} are the finished and total chunk counts, {percent} the finished percentage.
LOG_AUDIO_EXPORT_PROGRESS: str = (
    "Generating audio (TTS): {completed}/{total} chunks done ({percent}%)"
)
#: Rate limit (HTTP 429) detail body returned by the API when too many requests arrive in a window.
API_RATE_LIMIT_DETAIL: str = (
    "Too many requests. Please wait a moment and try again."
)
#: HTTP 500 detail body returned by the API global exception handler.
API_INTERNAL_ERROR_DETAIL: str = "Internal server error"
#: Debug logged by the orchestrator when a page is served straight from the cache, skipping the AI pass; {page_num} is the page index.
LOG_ORCHESTRATOR_PAGE_CACHE_SKIP: str = "[page {page_num}] Cache hit (skipping AI)"
#: Warning logged when a mode prompt file is missing on disk and the loader falls back to the medio prompt; {path} is the missing prompt file path.
LOG_PROMPT_FILE_NOT_FOUND: str = (
    "Prompt file not found at {path}, falling back to medio"
)
#: Warning logged by the data agent when a region prompt key has no matching prompt, so the region falls back to the previously extracted text; {page_num} is the page number, {type} the region classification.
LOG_DATA_AGENT_PROMPT_NOT_FOUND: str = (
    "[page {page_num}] Prompt not found for type={type}, using fallback"
)
#: Debug logged by the data agent just before the vision model processes a region; {page_num} is the page number, {size} the region image size in bytes, {type} the region classification.
LOG_DATA_AGENT_PROCESSING_REGION: str = (
    "[page {page_num}] DataAgent processing region ({size} bytes, type={type})"
)
#: Critical error logged by the data agent when an unhandled exception occurs while processing a region; {page_num} is the page number, {type} the region classification, {error} the exception.
LOG_DATA_AGENT_REGION_ERROR: str = (
    "[page {page_num}] DataAgent error in region {type}: {error} | Traceback:\n{tb}"
)
#: Debug logged by the vision agent just before it sends a region image to the vision model; {page_num} is the page number, {size} the region image size in bytes, {type} the region classification.
LOG_VISION_AGENT_SENDING_REGION: str = (
    "[page {page_num}] Sending region to vision ({size} bytes, type={type})"
)
#: Critical error logged by the vision agent when an unhandled exception occurs while describing a region; {page_num} is the page number, {type} the region classification, {error} the exception, {tb} the traceback text.
LOG_VISION_AGENT_REGION_ERROR: str = (
    "[page {page_num}] VisionAgent error in region {type}: {error} | Traceback:\n{tb}"
)
#: Warning logged by the editor agent when a page produced no consolidated text; {page_num} is the page number.
LOG_EDITOR_PAGE_EMPTY: str = "[page {page_num}] EditorAgent: no consolidated text"
#: Info logged by the editor agent after consolidating a page; {page_num} is the page number, {count} the number of text parts kept.
LOG_EDITOR_PAGE_CONSOLIDATED: str = (
    "[page {page_num}] EditorAgent: {count} text parts consolidated"
)
#: Critical message logged when cropping a manifest region from a page image fails; {error} is the exception text.
LOG_REGION_CROP_FAILED: str = "Failed to crop the region: {error}"
#: Debug logged by the exporters adapter wrapper just before a plain-text export runs; {path} is the output file path.
LOG_EXPORT_TXT_START: str = "Exporting TXT to {path}"
#: Debug logged by the exporters adapter wrapper just before a DOCX export runs; {path} is the output file path.
LOG_EXPORT_DOCX_START: str = "Exporting DOCX to {path}"
#: Debug logged by the exporters adapter wrapper just before a PDF export runs; {path} is the output file path.
LOG_EXPORT_PDF_START: str = "Exporting PDF to {path}"
#: Debug logged by the exporters adapter wrapper just before a PDF/UA export runs; {path} is the output file path.
LOG_EXPORT_PDF_UA_START: str = "Exporting PDF/UA to {path}"
#: Debug logged by the exporters adapter wrapper just before an MP3 audio export runs; {path} is the output file path.
LOG_EXPORT_MP3_START: str = "Exporting MP3 to {path}"
#: Debug logged after a PDF page rasterizes to PNG; {size} is the resulting PNG payload size in bytes.
LOG_PAGE_CONVERTED_TO_PNG: str = "Page converted to PNG: {size} bytes"
#: Info logged before a PDF is split into per-page files; {total} is the document's full page count, {limit} the number of pages that will be extracted.
LOG_PDF_PAGE_COUNT_LOGGED: str = "PDF has {total} pages, processing {limit}"
#: Debug logged each time one page of the source PDF is written to a standalone per-page file during the split.
LOG_PDF_PAGE_SAVED: str = "Page {page} saved: {name}"
#: Info logged once a PDF has been split into standalone per-page files; {count} is the number of pages extracted, {tmpdir} the destination directory name.
LOG_PDF_PAGES_EXTRACTED: str = "{count} pages extracted to {tmpdir}"
#: Debug logged when an image is shrunk to fit the vision model's maximum dimension; {old_width} and {old_height} are the original pixel dimensions, {new_width} and {new_height} the resized ones.
LOG_IMAGE_RESIZED: str = "Image resized: {old_width}x{old_height} -> {new_width}x{new_height}"
#: Debug logged during OCR pre-processing when the image is deskewed; {angle:.2f} is the detected correction angle in degrees.
LOG_IMAGE_ROTATED: str = "Image rotated by {angle:.2f} degrees"
#: Error logged when OCR image pre-processing fails; {error} is the exception text.
LOG_IMAGE_PREPROCESS_FAILED: str = "Image pre-processing error: {error}"
#: Error raised when the language-agent returns an empty result for a document; no placeholders.
LOG_ORCHESTRATOR_EMPTY_AGENT_RESPONSE: str = "Empty response from the agent"
#: Warning logged when a page is processed but the model returns no usable text for it.
LOG_ORCHESTRATOR_EMPTY_PAGE_RESPONSE: str = "Empty response for page {page_num}"
#: Info logged after a processed page's response text is written to its temporary output file; {page_num} is the page number, {file_name} the output file name.
LOG_ORCHESTRATOR_PAGE_RESPONSE_SAVED: str = (
    "Response for page {page_num} saved to {file_name}"
)
#: Info logged once the full workflow finishes, summarizing how many pages were processed and the total character count.
LOG_ORCHESTRATOR_WORKFLOW_SUMMARY: str = (
    "AccessibilityWorkflow: {total_pages} pages processed, {total_chars} chars in total"
)
#: Info logged when a workflow run begins, naming the page count, source file, structurer, and effective mode.
LOG_ORCHESTRATOR_WORKFLOW_START: str = (
    "AccessibilityWorkflow: processing {page_count} page(s) for {file_name} "
    "(reader={reader}, mode={mode})"
)
#: Info logged before the orchestrator awaits a page's parallel AI tasks; {page_num} is the page number, {count} the number of pending tasks.
LOG_ORCHESTRATOR_WAITING_TASKS: str = (
    "[page {page_num}] Waiting for {count} AI task(s) in parallel..."
)
#: Error logged when one of a page's parallel AI tasks fails; {page_num} is the page number, {idx} the failed task's index, {error} the exception.
LOG_ORCHESTRATOR_TASK_FAILED: str = (
    "[page {page_num}] Task {idx} failed: {error}"
)
#: Warning logged by the PDDL pipeline when a caller passes custom_prompt or thinking_mode, which the deterministic manifest/planning/execution flow does not use.
LOG_PDDL_IGNORED_OPTIONS: str = (
    "PDDL pipeline ignores custom_prompt/thinking_mode; only the deterministic "
    "manifest/planning/execution flow runs"
)
#: Info logged by the PDDL pipeline after enriching manifest elements with AI-generated visual descriptions; {count} is the number of elements enriched.
LOG_PDDL_IMAGES_ENRICHED: str = (
    "Pipeline PDDL: {count} image(s) enriched with visual description"
)
#: Info logged by the PDDL pipeline after enriching manifest table elements via OCR/reconstruction; {count} is the number of tables enriched.
LOG_PDDL_TABLES_ENRICHED: str = (
    "Pipeline PDDL: {count} table(s) enriched with OCR/reconstruction"
)
#: Exception logged when extracting an element's image clip from the source PDF for the PDDL pipeline fails; {element_id} is the failing element's id.
LOG_PDDL_ELEMENT_CROP_FAILED: str = (
    "Failed to extract the image clip for element {element_id}"
)
#: Error raised when the PDDL pipeline is configured with an invalid extractor backend value; no placeholders.
LOG_PDDL_EXTRACTOR_BACKEND_INVALID: str = (
    "Invalid extractor_backend; use 'docling' or 'pymupdf'"
)
#: Error raised when the preferred planner backend produced no valid plan in both mode; {backend} is the preferred backend's name.
LOG_PDDL_PREFERRED_PLAN_MISSING: str = (
    "Preferred planner backend {backend} did not produce a valid plan in both mode"
)
#: Error raised when validating a nominal plan whose problem.pddl hash does not match the compiled problem; no placeholders.
LOG_PDDL_PROBLEM_HASH_MISMATCH: str = (
    "The problem.pddl hash diverges from the plan"
)
#: Error raised when validating a nominal plan whose domain.pddl hash does not match the domain bundle; no placeholders.
LOG_PDDL_DOMAIN_HASH_MISMATCH: str = (
    "The domain.pddl hash diverges from the plan"
)
#: Error raised when validating a nominal plan whose domain description hash does not match the domain bundle; no placeholders.
LOG_PDDL_DOMAIN_DESCRIPTION_HASH_MISMATCH: str = (
    "The domain description hash diverges from the plan"
)
#: Error raised when validating a nominal plan whose selected obligation closure does not match the compiled problem's; no placeholders.
LOG_PDDL_SELECTED_CLOSURE_MISMATCH: str = (
    "The selected closure diverges from the compiled problem"
)
#: Info logged by the reader agent after extracting regions from a PDF page; {page_num} is the page number, {count} the number of regions found, {structurer} the structurer's name.
LOG_READER_PDF_REGIONS_EXTRACTED: str = (
    "[page {page_num}] Extracted {count} region(s) on the page (structurer={structurer})"
)
#: Info logged by the reader agent when every region on a page is clean text sent straight to the editor agent without a vision pass; {page_num} is the page number, {count} the number of such regions.
LOG_READER_CLEAN_TEXT_REGIONS: str = (
    "[page {page_num}] {count} clean-text region(s) (no vision AI)"
)
#: Info logged by the reader agent for each vision/data region task it creates; {page_num} is the page number, {idx} the task sequence number, {type} the region classification, {bbox} the region bounding box, {target} the agent that will process the task.
LOG_READER_REGION_TASK: str = (
    "[page {page_num}] Region {idx} - type={type}, bbox={bbox}, target={target}"
)
#: Warning logged by the reader agent when no text could be extracted from any region on a page, so the whole page is sent to the vision agent; {page_num} is the page number.
LOG_READER_FULL_PAGE_FALLBACK: str = (
    "[page {page_num}] No text extracted by regions, fallback to the full page"
)
#: Info logged by the reader agent after it has built all region tasks for a page; {page_num} is the page number, {count} the total task count, {text_count} the tasks sent to the editor, {vision_count} the tasks sent to the vision/data agents.
LOG_PDF_EXPORTED: str = "PDF exported with bookmarks and page numbering: {output_path}"
LOG_PDF_UA_EXPORTED: str = "PDF/UA exported: {output_path}"
LOG_TXT_EXPORTED: str = "TXT exported: {output_path}"
LOG_DOCX_EXPORTED: str = "DOCX exported: {output_path}"
LOG_READER_TASKS_SUMMARY: str = (
    "[page {page_num}] {count} task(s) ({text_count} text, {vision_count} vision)"
)
#: Debug logged by the reader agent for each image page before reading its bytes; {page_num} is the page number, {path} the per-page image file path.
LOG_READER_IMAGE_READING: str = "[page {page_num}] reading image: {path}"
#: Info logged after Docling finishes converting a document; {filename} is the source file name, {elapsed:.1f} the conversion duration in seconds.
LOG_DOCLING_PROCESSED: str = "Docling processed {filename} in {elapsed:.1f}s"
#: Warning logged when Docling fails to extract one page's regions, so the PyMuPDF fallback runs; {page} is the 1-based page number, {error} the reason.
LOG_DOCLING_PAGE_FAILED: str = "Docling failed on page {page} ({error}), fallback PyMuPDF"
#: Info logged when RapidOCR model files are copied back from the local model cache before use; {count} is the number of model files restored.
LOG_RAPIDOCR_MODELS_RESTORED: str = "RapidOCR: {count} model(s) restored from local cache"
#: Info logged when RapidOCR model files are copied into the local model cache after a page run; {count} is the number of model files persisted.
LOG_RAPIDOCR_MODELS_PERSISTED: str = "RapidOCR: {count} model(s) persisted to local cache"
#: Error raised when a Docling converter is requested but the Docling stack is not importable in the current environment.
LOG_DOCLING_NOT_AVAILABLE: str = "Docling is not available in the current environment."
#: Error raised when a PyMuPDF page being routed to Docling has no parent document to extract.
LOG_DOCLING_PAGE_NO_PARENT: str = "Page has no parent document for Docling processing"
#: Warning logged when STRUCTURER=docling is configured but the Docling package is absent, so the PyMuPDF structurer is used instead.
LOG_STRUCTURER_DOCLING_NOT_INSTALLED: str = (
    "STRUCTURER=docling is set but docling is not installed. "
    "Run: pip install docling. Falling back to PyMuPDF."
)
#: Warning logged at service level when the configured docling structurer is unavailable and the PyMuPDF structurer is resolved instead.
LOG_STRUCTURER_FALLBACK_PYMUPDF: str = (
    "STRUCTURER=docling is set but docling is not installed. Using PyMuPDF."
)
#: Info logged when the Docling document structurer is selected, with PyMuPDF as the fallback engine.
LOG_STRUCTURER_DOCLING: str = "Using structurer: Docling (with PyMuPDF fallback)"
#: Info logged when the PyMuPDF document structurer is selected directly.
LOG_STRUCTURER_PYMUPDF: str = "Using structurer: PyMuPDF"
#: Error raised when the optional Agno agent stack is absent and a workflow class import is required; no placeholders.
LOG_AGNO_NOT_INSTALLED: str = (
    "Agno is not installed. Run `poetry install` before using the workflow Executor."
)
