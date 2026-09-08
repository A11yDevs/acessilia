"""Upload validation helpers plus their localized user-facing reason messages."""

from pathlib import Path

from backend.i18n import t
from backend.config.settings import settings

#: Canonical English msgid for the unsupported-format error shown to API and Telegram callers.
MSG_UNSUPPORTED_FORMAT: str = (
    "Unsupported file format. Send PDF, DOCX, HTML, PNG, JPG, TIFF, BMP or WEBP."
)
#: Canonical English msgid template for the oversized-file error; {limit} is substituted by callers after lookup.
MSG_FILE_TOO_LARGE: str = "File too large. Limit: {limit} MB."


def is_extension_allowed(filename: str) -> bool:
    """Check whether a filename's file extension belongs to the configured whitelist.

    Args:
        filename (str): Candidate filename whose lowercase suffix must appear in settings.allowed_extensions; no default (required).

    Returns:
        bool: True when the extension is whitelisted, False otherwise.
    """
    ext = Path(filename).suffix.lower()
    return ext in settings.allowed_extensions


def is_file_size_allowed(file_size: int) -> bool:
    """Check whether a file size stays within the configured byte limit.

    Args:
        file_size (int): Size in bytes compared against settings.max_file_size_bytes; no default (required).

    Returns:
        bool: True when the size is at or below the limit, False otherwise.
    """
    return file_size <= settings.max_file_size_bytes


def validate_file(filename: str, file_size: int) -> tuple[bool, str]:
    """Validate an upload against the extension whitelist and the configured size limit.

    Args:
        filename (str): Name of the incoming file whose suffix is checked; no default (required).
        file_size (int): Size in bytes compared with settings.max_file_size_bytes; no default (required).

    Returns:
        tuple[bool, str]: (True, "") when allowed; otherwise (False, reason) where reason is the localized message resolved from the active locale strings files via :func:`backend.i18n.t`.
    """
    if not is_extension_allowed(filename):
        return False, t(MSG_UNSUPPORTED_FORMAT)
    ext = Path(filename).suffix.lower()
    if settings.pipeline_engine.strip().lower() == "legacy" and ext in {".docx", ".html"}:
        return (
            False,
            "DOCX e HTML não são suportados no motor legacy. Use PDF ou imagem, ou altere PIPELINE_ENGINE.",
        )
    if not is_file_size_allowed(file_size):
        return False, t(MSG_FILE_TOO_LARGE).format(limit=settings.max_file_size_mb)
    return True, ""
