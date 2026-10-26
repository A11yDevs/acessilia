"""Upload validation helpers plus their localized user-facing reason messages."""

from pathlib import Path
from email.headerregistry import Address
from email.errors import HeaderParseError

from backend.i18n import t
from backend.config.settings import settings

#: Canonical English msgid for the unsupported-format error shown to API and Telegram callers.
MSG_UNSUPPORTED_FORMAT: str = (
    "Unsupported file format. Send PDF, DOCX, HTML, PNG, JPG, TIFF, BMP or WEBP."
)
#: Canonical English msgid template for the oversized-file error; {limit} is substituted by callers after lookup.
MSG_FILE_TOO_LARGE: str = "File too large. Limit: {limit} MB."


def is_email_address_allowed(address: str) -> bool:
    """Validate one mailbox address without display names or header controls.

    Internationalized email addresses are not fully supported: non-ASCII
    local parts (before the @) are rejected. Some Unicode domains may be
    accepted by the parser, but this helper does not perform IDNA conversion
    or verify SMTPUTF8 support in the delivery service.

    Args:
        address (str): Mailbox address to validate, without surrounding whitespace.

    Returns:
        bool: Whether the address has a valid mailbox structure and domain.
            This does not check DNS or whether the mailbox exists.
    """
    if any(character in address for character in "\r\n\x00"):
        return False
    try:
        mailbox = Address(addr_spec=address)
    # Python 3.12's parser can raise AttributeError for incomplete domain
    # literals such as a@[. Treat that parser failure as invalid input too.
    except (ValueError, HeaderParseError, AttributeError):
        return False
    return bool(mailbox.username and mailbox.domain)


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
    if not is_file_size_allowed(file_size):
        return False, t(MSG_FILE_TOO_LARGE).format(limit=settings.max_file_size_mb)
    return True, ""
