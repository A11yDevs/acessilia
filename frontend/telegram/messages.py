"""
What this module provides: canonical English message ids (msgids) covering every user-facing text emitted by the
Telegram bot's general command handlers and the document/photo processing lifecycle handlers, a pt_BR translation
table mirroring each msgid for locale catalog generation,
and a per-locale mapping builder that scripts/gen_locale_catalogs consumes so adding another supported language later only
requires one additional entry in BOT_PT_TRANSLATIONS-style tables plus re-running catalog generation. Module-level constants
doube as the single source of truth that frontend/telegram/handlers/start.py formats at runtime through acessilia_core.i18n.t().
"""

from __future__ import annotations

#: Hint shown when /email is invoked without an address argument.
MSG_EMAIL_HINT: str = "Please provide an e-mail address: /email you@example.com"
#: Confirmation returned by /email once the deliver-to address has been recorded; {email} is substituted at call time.
MSG_EMAIL_CONFIGURED: str = (
    "E-mail {email} configured! Now send your document and it will be delivered to this e-mail address."
)
#: Welcome text emitted on /start explaining what the bot does and which formats are accepted.
MSG_START_TEXT: str = (
    "Hello! Send a PDF, image or scanned document."
    "\n\nYou'll get back an accessible version for screen readers."
    "\n\nAccepted formats:\n{input_formats}"
)
#: Full catalog of bot commands emitted on /ajuda and /help; command tokens stay localized-independent per Telegram's locale-agnostic slash-command behavior.
MSG_HELP_TEXT: str = (
    "Available commands:"
    "\n\n🔧 General:"
    "\n/start - Start the bot"
    "\n/help - Show this message"
    "\n/formats - List supported input and output formats"
    "\n/email &lt;address&gt; - Also send the next file's result to that address"
    "\n\n🎨 Description modes:"
    "\n/detailed - Maximum detail: typography, colors, layout, element positions"
    "\n/medium - Full text + clear image descriptions (default)"
    "\n/low - Content focused: full text extraction + concise image description (faster)"
    "\n/normal - Equivalent to /medium"
    "\n/ocr - Text extraction only, no visual description"
    "\n\n⚙️ Control:"
    "\n/status - Inspect processing queue and in-progress task progress"
    "\n/cancel - Cancel a running task"
    "\n/deactivate - Disable the bot for this chat"
    "\n/activate - Re-enable the bot for this chat"
    "\n/health - Check system health (server, model, disk)"
    "\n/feedback - Send your opinion about processing quality"
    "\n\nJust send a file and I'll process it automatically."
)
#: /formatos answer listing accepted input containers plus every generated output format.
MSG_FORMATS_TEXT: str = (
    "Accepted input formats:"
    "\n{input_formats}"
    "\n\n"
    "Output formats available:"
    "\n• Structured TXT"
    "\n• Accessible DOCX"
    "\n• PDF/UA"
    "\n• Semantic HTML"
    "\n• Audio description (MP3)"
)

# --- File/photo processing lifecycle messages (frontend/telegram/handlers/document.py) ---
#: Confirmation shown right after the user sends a document file.
MSG_FILE_RECEIVED: str = "📄 File received!"
#: Confirmation shown right after the user sends a photo.
MSG_PHOTO_RECEIVED: str = "📷 Photo received!"
#: Progress line emitted while the bot downloads the attachment from Telegram servers into local storage.
MSG_DOWNLOADING_FILE: str = "Downloading file..."
#: Error reply when a file exceeds Telegram's own download limit; {limit}/{web_url} substituted at call time.
MSG_TELEGRAM_FILE_TOO_LARGE: str = (
    "❌ Telegram accepts files up to {limit} MB. For larger files, use the web panel: {web_url}"
)
#: Error reply returned when the processing API rejects the submitted job; {status_code}/{detail} substituted at call time.
MSG_SUBMIT_FAILED: str = (
    "❌ Error submitting the file for processing ({status_code}): {detail}"
)
#: Reply sent when the local bot cannot reach the processing server at all (network or start-up failure).
MSG_CONTACT_SERVER_FAILED: str = "❌ Could not contact the processing server. Try again."
#: Progress line emitted once a job has been accepted by the API and is waiting in the queue; {task_id} substituted at call time.
MSG_TASK_ENQUEUED: str = "Task {task_id} queued..."
#: Reply emitted when the job lands behind other jobs in the single processing lane; {position} substituted at call time.
MSG_QUEUE_POSITION: str = "⏳ You are in the queue (Position: {position})."
#: Polling progress line shown while a job is still queued; {step} is the current pipeline stage label reported by the API and may be empty.
MSG_WAITING_IN_QUEUE: str = "Waiting in queue... {step}"
#: Receipt emitted when the download link has also been e-mailed to the address stored via /email; {email} substituted at call time.
MSG_DOWNLOAD_LINK_EMAILED: str = "✅ Download link sent to {email}!"
#: Completion reply carrying the 7-day download URL; {url} is appended by the caller after lookup and locale selection so each language can localize surrounding wording independently.
MSG_ACCESSIBLE_PACKAGE_READY: str = (
    "✅ Accessible package generated!\n\n📥 Download link (valid for 7 days):\n{url}"
)
#: Warning appended to the completion reply when the package has no PDF because PDF/UA failed.
MSG_PACKAGE_PDF_UA_MISSING: str = (
    "⚠️ The PDF/UA could not be generated, the package's only PDF: "
    "the package continues without a PDF."
)
#: Line appended to the completion reply naming the address the package was e-mailed to; {email} substituted at call time.
MSG_PACKAGE_EMAIL_CONFIGURED: str = "E-mail configured: {email}"
#: Generic error reply returned when an unexpected exception interrupts file processing mid-flight.
MSG_PROCESSING_ERROR_GENERIC: str = "❌ Error processing the file. Try again."
#: Base text used for API-reported job failures; localized failure detail lines are appended by the caller after lookup so each language keeps its own wording around them.
MSG_PROCESS_FAILED_BASE: str = "❌ Processing error."
#: Reply emitted when a running job is cancelled (e.g., via /cancel).
MSG_TASK_CANCELLED: str = "🚫 Task cancelled."
#: Time-out reply shown when the bot waited through settings.request_timeout without completing; directs users to /status to check progress.
MSG_PROCESSING_TIMEOUT: str = (
    "⏰ Processing took longer than expected. Use /status to follow progress."
)

# --- start.py command responses (frontend/telegram/handlers/start.py) ---
#: Reply for /ocr; confirms text-only extraction mode is active.
MSG_MODE_OCR_ON: str = (
    "📄 OCR Mode On!\n\nSend a PDF or image and I shall extract ONLY the written text, without visual description."
)
#: Reply for /detalhado (detailed); confirms maximum-detail description mode is active.
MSG_MODE_DETAILED_ON: str = (
    "🔍 Detailed Mode On!\n\n" +
    "Description at the highest detail level: typography, spacing, colors, layout, element positions and a professional image description."
)
#: Reply for /medium; confirms standard mode.
MSG_MODE_MEDIO_ON: str = (
    "📋 Medium Mode on!\n\nFull text plus clear image descriptions. Ideal for most documents."
)
#: Reply for /low; confirms content-focused, faster mode.
MSG_MODE_BAIXO_ON: str = (
    "⚡ Low Mode on!\n\nFocused on content: the full text extracted and a concise description of images. Faster."
)
#: Reply for /normal; confirms equivalence to medium mode.
MSG_MODE_NORMAL_ON: str = (
    "📋 Normal Mode on (equivalent to Medium).\n\nFull text plus clear image descriptions."
)
#: Status reply when no job has been recorded in this chat yet (/status, /cancelar).
MSG_NO_TASK_REGISTERED: str = "No task registered in this chat yet."
#: Status error reply; {status_code} is the rejected HTTP code.
MSG_STATUS_TASK_NOT_FOUND: str = "❌ Task not found in API ({status_code})."
#: Successful status summary template for /status rendering; {icon} maps to queued/processing/done/error/canceled states; {task_id}, {filename}, {pct}/{stage} are fetched from the API response.
MSG_STATUS_SUMMARY: str = ("{icon} Task `{task_id}` - {filename}\n{pct}% - {stage}")
#: Health check line for Ollama online state; {model_count} is the number of locally loaded models.
MSG_OLLAMA_ONLINE: str = "✅ Ollama: online ({model_count} model(s))"
#: Health warning when Ollama answered off nominal HTTP 200; {code} substituted at call time with observed code.
MSG_OLLAMA_UNEXPECTED: str = "⚠️ Ollama: unexpected answer ({code})"
#: Health check line for Ollama being unreachable; {error} substituted with exception text from the health probe.
MSG_OLLAMA_OFFLINE: str = "❌ Ollama: offline ({error})"
#: Health check line stating which llm model is active; {model} substituted at call time.
MSG_HEALTH_ACTIVE_MODEL: str = "🤖 Model: {model}"
#: Health check line for the API status; {icon} is the state emoji and {status} the reported status.
MSG_HEALTH_API: str = "{icon} API: {status}"
#: Health check line naming the configured provider; {icon} is the state emoji and {provider} the client name.
MSG_HEALTH_PROVIDER: str = "{icon} Provider: {provider}"
#: Health check line when the API answers with an HTTP error; {status_code}/{detail} substituted at call time.
MSG_HEALTH_API_ERROR: str = "❌ API: error {status_code} ({detail})"
#: Health check line when the API is unreachable; {error} is the probe exception text.
MSG_HEALTH_API_OFFLINE: str = "❌ API: offline ({error})"
#: Fallback shown in /health when the API omits a status or model field.
MSG_HEALTH_UNKNOWN: str = "unknown"
#: Temp directory health probe result when the settings.temp_dir path exists.
MSG_HEALTH_TEMP_OK: str = "✅ Temp dir: ok"
#: Temp directory health probe notice when the settings.temp_dir path does not exist.
MSG_HEALTH_TEMP_MISSING: str = "⚠️ Temp dir: missing"

#: Tracker progress message displayed when document conversion finishes successfully.
MSG_STATUS_CONVERSION_DONE: str = "✅ Conversion complete!"
#: Tracker fallback text shown when the processing job ends in an error; generic wording intentionally avoids leaking exception details to chat users.
MSG_STATUS_PROCESSING_FAILED: str = ("❌ Error during processing.")


#: Reply to an operator-only command from a user who is not in TELEGRAM_ADMIN_IDS.
MSG_ADMIN_ONLY: str = "⛔ This command is restricted to operators."
#: Cache cleared reply; {count} is the number of files deleted from cache storage.
MSG_CACHE_CLEARED: str = ("🧹 Cache cleared! {count} file(s) removed.")
#: Failure reply when the operations API refuses the cache clear; {status_code}/{detail} are the API fields.
MSG_CACHE_CLEAR_FAILED: str = (
    "❌ Could not clear the server cache ({status_code}): {detail}"
)
#: Disk free space probe line; {free_gb} is formatted at call time with one decimal.
MSG_HEALTH_DISK_FREE: str = "💾 Free disk: {free_gb:.1f} GB"
#: /status reply when the chat has no recorded processing task yet.
MSG_STATUS_NO_TASK: str = "No task in this chat."
#: /cancelar reply when there is nothing to cancel in this chat.
MSG_CANCEL_NO_TASK: str = "No active task in this chat to cancel."
#: Reply emitted after a successful job cancellation; {task_id} substituted at call time with the cancelled job's id.
MSG_TASK_CANCEL_DONE: str = "✅ Task {task_id} cancelled."
#: /cancelar error reply when the API rejects the cancellation request; {status_code}/{detail} are the API response fields, substituted at call time.
MSG_TASK_CANCEL_FAILED: str = ("❌ Could not cancel the task ({status_code}): {detail}")
#: Reply shown by /deactivate confirming the bot is paused for this chat.
MSG_BOT_PAUSED: str = "Bot disabled in this chat. Use /activate to re-enable it."
#: Reply shown by /activate confirming the bot has been re-enabled for this chat; invites user to send a document.
MSG_BOT_RESUMED: str = ("Bot re-enabled! Send me a document to get started.")
#: Prompt text emitted when the user invokes /feedback, instructing them how to write their opinion of processing quality before entering input state.
MSG_FEEDBACK_PROMPT: str = (
    "📝 **Send Feedback**\n\n"
    "Type your opinion on processing quality, improvement suggestions or issues you encountered.\n\n"
    "Example:\n"
    '\"The image description came out great but the extracted text had a few errors."\n\n'
    "Your feedback is very important to us!"
)
#: Confirmation emitted once the user's feedback message has been recorded and logged; thanks them for contributing.
MSG_FEEDBACK_THANKS: str = ("✅ Feedback received! Thanks for your contribution.")
