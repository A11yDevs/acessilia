"""Object markers in the delivered formats (OBJECT_MARKERS_ENABLED).

``docstruct.export.markers`` encloses each transformed object in ``[label]``
and ``[/label]`` paragraphs; this module gives it the labels in the active
locale and decides, per job, whether to apply it.
"""
from __future__ import annotations

from typing import Any

from acessilia_core.config import ExportConfig
from acessilia_core.i18n import t
from docstruct.export.markers import wrap_object_markers

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


def object_markers_enabled(enabled: bool | None, export: ExportConfig) -> bool:
    """Whether markers apply: the job's choice, or the run's default when None.

    One resolver for the delivery and the effective-configuration record
    (#380), so the recorded value cannot disagree with the delivered one.
    """
    return export.object_markers_enabled if enabled is None else enabled


def with_object_markers(
    document: dict[str, Any], enabled: bool | None, export: ExportConfig
) -> dict[str, Any]:
    """``document`` with its objects enclosed in markers when ``enabled``.

    ``enabled`` is the job's own choice; None falls back to the run's
    ``ExportConfig.object_markers_enabled``. The document is returned
    unchanged when off.
    """
    if object_markers_enabled(enabled, export):
        return wrap_object_markers(document, object_marker_labels())
    return document
