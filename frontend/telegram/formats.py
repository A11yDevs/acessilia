"""Input format labels for the Telegram messages, derived from the validator.

The bot must advertise exactly what ``settings.allowed_extensions`` accepts, so
adding or removing a format in the validator changes the user-facing list with
no second table to keep in sync.
"""

from __future__ import annotations

from backend.config.settings import settings

#: Extension -> label shown to the user.
_FORMAT_LABELS: dict[str, str] = {
    ".pdf": "PDF",
    ".png": "PNG",
    ".jpg": "JPG",
    ".jpeg": "JPEG",
    ".tiff": "TIFF",
    ".tif": "TIF",
    ".docx": "DOCX",
    ".html": "HTML",
}

#: Extensions that share one bullet, in presentation order.
_FORMAT_GROUPS: tuple[tuple[str, ...], ...] = (
    (".pdf",),
    (".png",),
    (".jpg", ".jpeg"),
    (".tiff", ".tif"),
    (".docx",),
    (".html",),
)


def input_formats_text() -> str:
    """Bullet list of the extensions the bot accepts, one line per group.

    A group is rendered only with the extensions actually allowed, so a
    deployment that keeps only ``.jpg`` does not claim to accept ``.jpeg``.
    Extensions unknown to the label table still appear, using their upper-case
    suffix, so a new validator entry is never silently hidden.
    """
    allowed = set(settings.allowed_extensions)
    lines: list[str] = []
    rendered: set[str] = set()
    for group in _FORMAT_GROUPS:
        labels = [
            _FORMAT_LABELS[extension]
            for extension in group
            if extension in allowed
        ]
        if labels:
            lines.append("• " + ", ".join(labels))
            rendered.update(group)
    for extension in sorted(allowed - rendered):
        lines.append("• " + extension.lstrip(".").upper())
    return "\n".join(lines)


__all__ = ["input_formats_text"]
