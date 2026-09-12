"""Pipeline processing-stage labels surfaced to end users as live progress.

Each msgid is the canonical English stage label the bot displays while a job
moves through the queue, per-format exports, audio generation and completion.
Callers resolve them at display time through :func:`backend.i18n.t` so a
portuguese-speaking Telegram user sees the stage text in their own locale,
while the server's own locale is used for local logging.
"""

#: Live stage shown while a newly queued job waits ahead of earlier jobs; {position} substituted at call time.
STAGE_QUEUE_WAITING_POSITION: str = "Waiting in the queue (Position: {position})"
#: Live stage set on a queued job that is cancelled before execution starts.
STAGE_CANCELLED_IN_QUEUE: str = "Cancelled before it reached the processing queue"
#: Live stage reported right after the job is dequeued and processing has begun.
STAGE_ENQUEUED_WAITING: str = "Queued and waiting..."
#: Live stage for the initial upload validation and setup of the source file.
STAGE_PREPARING_FILE: str = "Preparing your file..."
#: Live stage emitted while the document is being analyzed and split into pages/regions.
STAGE_ANALYZING_FILE: str = "📄 Analyzing your document..."
#: Live stage while the accessibility AI pass is running inside the pipeline.
STAGE_PROCESSING_WITH_AI: str = "Processing your file with the AI..."
#: Final stage confirmation emitted when the whole pipeline finished successfully.
STAGE_PROCESSING_FINISHED: str = "✅ Processing finished successfully!"
#: Live stage emitted when pipeline processing could not complete for the source file.
STAGE_PROCESSING_FAILED_LABEL: str = "❌ Could not process the file."
#: Live stage while the exported result files are being rendered as plain text (TXT).
STAGE_EXPORTING_TXT: str = "Exporting the plain text version (TXT)..."
#: Live stage while the exported result files are being rendered as an accessible Word document (DOCX).
STAGE_EXPORTING_DOCX: str = "Exporting the accessible Word document (DOCX)..."
#: Live stage while the exported result files are being rendered as a standard PDF.
STAGE_EXPORTING_PDF: str = "Exporting the PDF..."
#: Live stage while the exported result files are being rendered as a tagged accessible PDF/UA.
STAGE_EXPORTING_PDF_UA: str = "Exporting the tagged accessible PDF/UA..."
#: Live stage while the exported result files are being rendered as semantic HTML.
STAGE_EXPORTING_HTML: str = "Exporting the semantic HTML version..."
#: Live stage while the spoken-audio (MP3) rendition of the extracted text is being generated; {percent} substituted at call time.
STAGE_GENERATING_AUDIO: str = "Generating the spoken audio version... {percent}%"
#: Live stage marking the successful end of the whole processing job, including exports.
STAGE_PROCESSING_COMPLETED: str = "Processing completed"
#: Live stage marking that the processing job ended in a failure.
STAGE_PROCESSING_FAILURE: str = "Processing failed"
#: Live stage set the moment the user's cancellation request is honored mid-execution.
STAGE_CANCELLED_BY_USER: str = "Cancelled by the user"
#: Legacy-pipeline stage while a PDF is split into individual page images for per-page analysis.
STAGE_SPLITTING_PDF_PAGES: str = "📄 Splitting the PDF into pages..."
#: Legacy-pipeline stage while a standalone image file is prepared for analysis.
STAGE_PREPARING_IMAGE: str = "🖼️ Preparing the image..."
#: Legacy-pipeline per-page progress line while a page is being processed; {page_num} and {total_pages} substituted at call time.
STAGE_PROCESSING_PAGE: str = "📷 Processing page {page_num} of {total_pages}..."
#: PDDL-pipeline stage while the document is analyzed by the informational-structural agent.
STAGE_ANALYZING_STRUCTURAL: str = "Analyzing the document with the structural agent..."
#: PDDL-pipeline stage while image descriptions are being enriched with the vision model.
STAGE_ENRICHING_IMAGE_DESCRIPTIONS: str = "Enriching the image descriptions..."
#: PDDL-pipeline stage while tables are being enriched with OCR as a fallback.
STAGE_ENRICHING_TABLES_OCR: str = "Enriching the tables with OCR (fallback)..."
#: PDDL-pipeline stage while the nominal PDDL plan is being generated from the manifest.
STAGE_GENERATING_PDDL_PLAN: str = "Generating the nominal PDDL plan..."
#: PDDL-pipeline stage while the generated plan is validated in dry-run mode before execution.
STAGE_VALIDATING_PLAN_DRY_RUN: str = "Validating the plan in dry-run mode..."
