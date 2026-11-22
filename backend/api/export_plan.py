"""The worker's existing export order, failure policy and progress messages."""

from dataclasses import dataclass

from acessilia_core.export.catalog import DOCX, DRBENCH_MD, HTML, MP3, PDF_UA, TXT, ZIP
from acessilia_core.i18n.stage_messages import (
    STAGE_EXPORTING_DOCX,
    STAGE_EXPORTING_DRBENCH_MD,
    STAGE_EXPORTING_HTML,
    STAGE_EXPORTING_PDF_UA,
    STAGE_EXPORTING_TXT,
    STAGE_GENERATING_AUDIO,
)


@dataclass(frozen=True)
class ExportStep:
    format_id: str
    optional: bool
    requires_flag: str | None
    stage_msgid: str | None
    progress: float | None


SERIAL_EXPORT_STEPS = (
    ExportStep(TXT.spec.id, False, None, STAGE_EXPORTING_TXT, 0.85),
    ExportStep(DRBENCH_MD.spec.id, True, None, STAGE_EXPORTING_DRBENCH_MD, 0.86),
    ExportStep(HTML.spec.id, False, None, STAGE_EXPORTING_HTML, 0.90),
    ExportStep(DOCX.spec.id, True, "toolbox_docx_enabled", STAGE_EXPORTING_DOCX, 0.92),
    ExportStep(PDF_UA.spec.id, True, "toolbox_pdf_ua_enabled", STAGE_EXPORTING_PDF_UA, 0.93),
)
AUDIO_STEP = ExportStep(MP3.spec.id, True, None, STAGE_GENERATING_AUDIO, 0.95)
# Packaging emits no additional stage/progress update today.
PACKAGE_STEP = ExportStep(ZIP.spec.id, False, None, None, None)
EXPORT_STEPS = (*SERIAL_EXPORT_STEPS, AUDIO_STEP, PACKAGE_STEP)

# Archive order differs from production order; keep the current public package.
PACKAGE_ORDER = (TXT.spec.id, HTML.spec.id, DOCX.spec.id, MP3.spec.id, PDF_UA.spec.id)
