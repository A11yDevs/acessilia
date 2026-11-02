"""Object markers in the delivered formats (OBJECT_MARKERS_ENABLED).

``docstruct.export.markers`` encloses each transformed object in ``[label]``
and ``[/label]`` paragraphs; this module gives it the labels in the active
locale and decides, per job, whether to apply it.
"""
from __future__ import annotations

from typing import Any

from docstruct.export.markers import wrap_object_markers

from backend.i18n import t

#: Canonical English msgid for the marker word of a described picture.
MSG_OBJECT_MARKER_IMAGE: str = "image"
#: Canonical English msgid for the marker word of a table.
MSG_OBJECT_MARKER_TABLE: str = "table"
#: Canonical English msgid for the marker word of a formula.
MSG_OBJECT_MARKER_FORMULA: str = "formula"


def object_marker_labels() -> dict[str, str]:
    """Marker word per canonical block type, in the active locale."""
    return {
        "image": t(MSG_OBJECT_MARKER_IMAGE),
        "table": t(MSG_OBJECT_MARKER_TABLE),
        "math": t(MSG_OBJECT_MARKER_FORMULA),
    }


def with_object_markers(document: dict[str, Any], enabled: bool | None) -> dict[str, Any]:
    """``document`` with its objects enclosed in markers when ``enabled``.

    ``enabled`` is the job's own choice; None falls back to
    OBJECT_MARKERS_ENABLED. The document is returned unchanged when off.
    """
    from backend.config.settings import settings

    if enabled is None:
        enabled = settings.object_markers_enabled
    return wrap_object_markers(document, object_marker_labels()) if enabled else document
