"""Canonical English message ids for the web upload panel's user-facing text.

The web panel (frontend/web/app.py) renders HTML responses whose error and
success notices were previously hardcoded in Portuguese. Each id below is the
canonical English string; callers resolve it at render time through
:func:`backend.i18n.t` so the panel output follows the active locale, exactly
like the Telegram and API surfaces.
"""

#: Shown when the global exception handler renders a 500 response; {error} carries the exception text.
WEB_ERROR_INTERNAL: str = "Internal server error: {error}"
#: Shown when the API rejects a web upload with a non-success code; {status_code} and {detail} replaced at render time.
WEB_ERROR_API_UPLOAD: str = "API error ({status_code}): {detail}"
#: Shown when an unexpected exception interrupts the web upload flow before the API is even contacted.
WEB_ERROR_UPLOAD_GENERIC: str = "An error occurred sending the file to the API. Please try again."
#: Shown when a web upload was accepted and placed in the processing queue; {position} is the queue slot and {email} the deliver-to address.
WEB_SUCCESS_QUEUED: str = (
    "Success! Your file has been added to the queue (Position: {position}). "
    "The result will be sent to {email}."
)
#: Shown when a custom prompt on the advanced panel exceeds the accepted length.
WEB_ERROR_PROMPT_TOO_LONG: str = (
    "The custom prompt exceeds the limit of 6000 characters."
)
#: Shown when a download link is unknown, already expired, or otherwise invalid.
WEB_ERROR_DOWNLOAD_INVALID: str = "The download link is invalid or has expired"
#: Shown when a download link is well-formed but the download service cannot be reached.
WEB_ERROR_DOWNLOAD_UNAVAILABLE: str = "The download service is temporarily unavailable"
#: Shown when a request exceeds the panel's per-address rate limit; prompts the user to wait and retry.
WEB_RATE_LIMIT_EXCEEDED: str = (
    "Too many requests. Please wait a moment before trying again."
)

# --- Main upload panel (templates/index.html) ---
#: Browser tab title for the main accessibility panel.
WEB_INDEX_TITLE: str = "Accessibility Panel - Acessilia"
#: Card heading shown at the top of the main panel.
WEB_INDEX_HEADLINE: str = "Acessia Bot - Accessibility Generator"
#: Intro paragraph describing what the panel does.
WEB_INDEX_INTRO: str = (
    "Convert your documents into accessible formats and receive them by e-mail."
)
#: Form-field label for the e-mail input.
WEB_INDEX_EMAIL_LABEL: str = "Your E-mail"
#: Helper text under the e-mail field explaining the deliver-to address.
WEB_INDEX_EMAIL_HELP: str = "We will send the final files to this address."
#: Form-field label for the document attachment control.
WEB_INDEX_DOC_LABEL: str = "Attach a Document (PDF or Image)"
#: Primary action button text on the upload form.
WEB_INDEX_SUBMIT_BUTTON: str = "Make Accessible"
#: Secondary link navigating to the advanced panel.
WEB_INDEX_ADVANCED_LINK: str = "Advanced Mode"
#: Copyright footer line rendered on every panel page.
WEB_FOOTER: str = "Technology for Inclusion"
#: Accessible alt text describing the brand logo rendered in the panel headers.
WEB_LOGO_ALT: str = (
    "Logo featuring the name \"acessilia\" prominently at the top. "
    "Above the wordmark a blue circle blends two images: on the left a rounded document "
    "carrying a photo icon at its top and a spreadsheet-style grid at its bottom; on the right a "
    "human head profile facing right, also blue. Three curved lines leave the mouth area, "
    "suggesting speech or sound. To the left of the document, rows of small circular dots in "
    "shades of blue give a sense of motion or a digital texture. Below the symbol is the word "
    "\"acessilia\": \"acess\" in dark blue and \"ilia\" in teal. Under the name, a thin blue line "
    "with a dot at each end. Further down, the tagline reads \"TRANSFORMING DOCUMENTS. "
    "GENERATING ACCESSIBILITY.\" At the very bottom four dark-blue icons are separated by small "
    "dashes: a square with six raised dots (a braille-like symbol), a loudspeaker, a stylized "
    "eye, and a rectangle representing a document or page."
)

# --- Advanced panel (templates/advanced.html) ---
#: Browser tab title for the advanced panel.
WEB_ADVANCED_TITLE: str = "Advanced Mode - Acessilia"
#: Card heading for the advanced panel.
WEB_ADVANCED_HEADLINE: str = "Advanced Mode"
#: Sub-heading under the card heading explaining the purpose.
WEB_ADVANCED_SUBHEAD: str = "Custom Prompt"
#: Intro paragraph for the advanced panel.
WEB_ADVANCED_INTRO: str = "Customize the prompt sent to the AI model."
#: Form-field label for the custom prompt textarea.
WEB_ADVANCED_PROMPT_LABEL: str = "Custom Prompt"
#: Placeholder text inside the custom prompt textarea.
WEB_ADVANCED_PROMPT_PLACEHOLDER: str = (
    "Type your custom prompt here. It will completely replace the system's default prompt."
)
#: Helper text under the prompt field describing limits and effect.
WEB_ADVANCED_PROMPT_HELP: str = (
    "Up to 6000 characters. Plain text only (no formatting). "
    "This prompt replaces the system's default prompt on every page."
)
#: Checkbox label enabling the model's internal reasoning mode.
WEB_ADVANCED_THINKING_LABEL: str = (
    "Enable Thinking Mode (the model's internal reasoning)"
)
#: Link returning to the normal upload panel.
WEB_ADVANCED_BACK_LINK: str = "Back to normal mode"

# --- Download page (templates/download.html) ---
#: Browser tab title for the download page.
WEB_DOWNLOAD_TITLE: str = "Download - Acessilia"
#: Card heading for the download page.
WEB_DOWNLOAD_HEADLINE: str = "Download"
#: Sub-heading under the download card heading.
WEB_DOWNLOAD_SUBHEAD: str = "Choose the format you want"
#: Warning shown when a download link has no available formats (expired or empty).
WEB_DOWNLOAD_NO_FORMATS: str = (
    "No formats available for this document. The link may have expired."
)
#: Footnote stating how long a download link stays active.
WEB_DOWNLOAD_VALID_NOTE: str = "Link valid for 7 days."
#: File-type label for the plain-text (TXT) rendition.
WEB_FORMAT_TXT: str = "Text (TXT)"
#: File-type label for the accessible Word document (DOCX) rendition.
WEB_FORMAT_DOCX: str = "Word Document (DOCX)"
#: File-type label for the accessible PDF rendition.
WEB_FORMAT_PDF: str = "Accessible PDF"
#: File-type label for the semantic HTML page rendition.
WEB_FORMAT_HTML: str = "Web Page (HTML)"
#: File-type label for the audio-description (MP3) rendition.
WEB_FORMAT_MP3: str = "Audio Description (MP3)"
#: File-type label for the full package (ZIP) rendition.
WEB_FORMAT_ZIP: str = "Complete Package (ZIP)"

# --- Agent showcase server (frontend/agent_os.py, panel at os.agno.com) ---
#: Description line for the AgentOS instance itself shown in the showcase panel.
WEB_AGENT_OS_DESCRIPTION: str = "Acessilia accessibility agent showcase."
#: Description of the vision agent shown in the showcase panel.
WEB_AGENT_VISION_DESCRIPTION: str = (
    "Generates accessible audio descriptions of images and scanned pages."
)
#: Description of the data agent shown in the showcase panel.
WEB_AGENT_DATA_DESCRIPTION: str = (
    "Converts tables and mathematical formulas into structured text."
)
#: Fallback instructions applied to the data agent when no table/formula region prompt is configured.
WEB_AGENT_DATA_INSTRUCTIONS_FALLBACK: str = (
    "Convert tables and mathematical formulas from images into accessible "
    "structured text (Markdown for tables, LaTeX for formulas)."
)
