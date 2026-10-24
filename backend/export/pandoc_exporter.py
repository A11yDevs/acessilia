"""Export of a canonical document to the target format.

Renders the canonical document after a deterministic structural audit and an export-profile
verbosity check, so that only compliant documents ever reach the exporter. HTML, PDF and TXT
render in-process; DOCX and PDF/UA are rendered from the Pandoc AST by the Toolbox, which pins
Pandoc in its own image (docs/adr/0003). Every user-visible error string is resolved through the
active locale strings files via :func:`backend.i18n.t`, with the canonical English msgid
constants below acting as the single source of truth consumed by scripts/gen_locale_catalogs
for catalog generation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.config.settings import settings
from backend.export.filters.pandoc_filters import strip_internal_audit_blocks
from backend.i18n import t
from backend.log_messages import LOG_DOCX_TOOLBOX_EXPORTED
from backend.log_messages import LOG_PDF_UA_MATH_DEGRADED
from backend.log_messages import LOG_PDF_UA_TOOLBOX_EXPORTED
from backend.pipeline.canonical_builder import build_canonical_document
from backend.pipeline.canonical_builder import sanitize_canonical_document
from backend.pipeline.pandoc_ast_builder import build_pandoc_ast
from backend.pipeline.pandoc_ast_builder import degrade_math_to_text
from backend.pipeline.validators import audit_canonical_document
from backend.pipeline.validators import validate_export_profile
from backend.tools.logger import logger

#: Canonical English msgid for a default document title used when the caller passes none.
MSG_DEFAULT_ACCESSIBLE_TITLE: str = "Accessible document"
#: Canonical English msgid for a docx export requested while TOOLBOX_DOCX_ENABLED is false.
MSG_DOCX_DISABLED: str = "DOCX export is disabled (TOOLBOX_DOCX_ENABLED=false)"
#: Canonical English msgid for a pdf_ua export requested while TOOLBOX_PDF_UA_ENABLED is false.
MSG_PDF_UA_DISABLED: str = "PDF/UA export is disabled (TOOLBOX_PDF_UA_ENABLED=false)"
#: Canonical English msgid template for an audit failure; {findings} is substituted by callers after lookup.
MSG_AUDIT_FAILED: str = "Audit failed: {findings}"
#: Canonical English msgid template for an unsupported export format; {format_name} is substituted by callers after lookup.
MSG_UNSUPPORTED_EXPORT_FORMAT: str = "Unsupported export format: {format_name}"


#: BCP 47 language for the document metadata when the document declares none.
DEFAULT_EXPORT_LANG = "pt-BR"


def _toolbox_export(
    client_cls: Any, ast: dict[str, Any], output_path: Path, *, lang: str
) -> dict[str, Any]:
    """Render ``ast`` on the Toolbox with ``client_cls`` and write it to ``output_path``.

    Returns the export document (artifact id, size, toolchain). The client is
    created and closed inside the coroutine: ``run_sync`` may run it on a fresh
    event loop, and the HTTP connections must not outlive it.
    """
    from backend.tools.toolbox_client import make_toolbox_client, run_sync

    async def export() -> dict[str, Any]:
        client = make_toolbox_client(client_cls)
        try:
            return await client.export(
                ast,
                output_path,
                lang=lang,
                use_remote_cache=settings.toolbox_use_remote_cache,
            )
        finally:
            await client.close()

    result = run_sync(export())
    document = result.get("document", {})
    provenance = result.get("provenance")
    provenance = provenance if isinstance(provenance, dict) else {}
    logger.info(
        "Toolbox: {} finished ({} bytes, cache_hit={}, {} ms)",
        client_cls.capability,
        document.get("size_bytes", "?"),
        provenance.get("cache_hit", False),
        provenance.get("duration_ms", "?"),
    )
    return document


def toolbox_export_pdf_ua(
    ast: dict[str, Any], output_path: Path, *, lang: str = "pt-BR"
) -> dict[str, Any]:
    """Render ``ast`` as PDF/UA on the Toolbox; returns the ``artifact/pdf-export@1`` document."""
    from acessilia_sdk.toolbox.clients import ToolboxPdfUaClient

    return _toolbox_export(ToolboxPdfUaClient, ast, output_path, lang=lang)


def toolbox_export_docx(
    ast: dict[str, Any], output_path: Path, *, lang: str = "pt-BR"
) -> dict[str, Any]:
    """Render ``ast`` as DOCX on the Toolbox; returns the ``artifact/docx-export@1`` document."""
    from acessilia_sdk.toolbox.clients import ToolboxDocxClient

    return _toolbox_export(ToolboxDocxClient, ast, output_path, lang=lang)


def _render_docx(
    ast: dict[str, Any], output_path: Path, *, lang: str = DEFAULT_EXPORT_LANG
) -> Path:
    """Renders DOCX on the Toolbox, which pins Pandoc in its image.

    There is no local fallback (docs/adr/0003): a Toolbox failure propagates
    so the caller can report it, and TOOLBOX_DOCX_ENABLED=false makes the
    format unavailable.

    Raises:
        RuntimeError: When TOOLBOX_DOCX_ENABLED is false.
        acessilia_sdk.toolbox.errors.ToolboxError: When the Toolbox cannot render or deliver the DOCX.
    """
    if not settings.toolbox_docx_enabled:
        raise RuntimeError(t(MSG_DOCX_DISABLED))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    toolbox_export_docx(ast, output_path, lang=lang)
    logger.info(t(LOG_DOCX_TOOLBOX_EXPORTED).format(output_path=output_path))
    return output_path


def _render_pdf_ua(
    ast: dict[str, Any], output_path: Path, *, lang: str = DEFAULT_EXPORT_LANG
) -> Path:
    """Renders PDF/UA on the Toolbox, which pins Pandoc and TeX Live in its image.

    There is no local fallback (docs/adr/0003): a Toolbox failure propagates
    so the caller can report it, and TOOLBOX_PDF_UA_ENABLED=false makes the
    format unavailable.

    Args:
        ast (dict): Pandoc JSON AST mapping for the canonical document.
        output_path (Path): Destination PDF file path.
        lang (str): BCP 47 tag written to the PDF metadata.

    Returns:
        Path: The output_path where the PDF/UA file was written.

    Raises:
        RuntimeError: When TOOLBOX_PDF_UA_ENABLED is false.
        acessilia_sdk.toolbox.errors.ToolboxError: When the Toolbox cannot render or deliver the PDF. An input
            rejection (``ToolboxInvalidInput``) gets one retry with the math exported as literal text, so a
            formula the LaTeX compiler rejects cannot lose the whole document; a second rejection propagates.
    """
    if not settings.toolbox_pdf_ua_enabled:
        raise RuntimeError(t(MSG_PDF_UA_DISABLED))
    from acessilia_sdk.toolbox.errors import ToolboxInvalidInput
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        toolbox_export_pdf_ua(ast, output_path, lang=lang)
    except ToolboxInvalidInput as exc:
        # ToolboxInvalidInput means the request reached a healthy renderer and
        # the AST itself is the problem — but not every rejection is about
        # math. When the AST carries no Math inline left (the builder guard
        # already exports the dangerous ones as text), the degradation changes
        # nothing and a retry would resend the identical request, so the
        # rejection propagates instead.
        degraded = degrade_math_to_text(ast)
        if degraded == ast:
            raise
        # Math the renderer's LaTeX compiler rejects, e.g. \chemfig from a
        # chemical structure a vision model classified as a formula. The retry
        # is a deterministic degradation, not a failover — the formulas go as
        # literal text, the way the HTML and TXT renderers already show them.
        logger.warning(t(LOG_PDF_UA_MATH_DEGRADED).format(error=exc))
        toolbox_export_pdf_ua(degraded, output_path, lang=lang)
    logger.info(t(LOG_PDF_UA_TOOLBOX_EXPORTED).format(output_path=output_path))
    return output_path


def export_accessible_document(
    source_text_or_document: str | dict[str, Any],
    output_path: Path,
    *,
    format_name: str,
    title: str | None = None,
    profile_name: str | None = None,
) -> Path:
    """Exports a canonical document (or raw markdown/text) to the named format.

    Args:
        source_text_or_document (str | dict): Raw markdown/text or an already-built canonical document mapping to export.
        output_path (Path): Destination file path for the rendered output.
        format_name (str): Target format key: "html", "docx", "pdf_ua" or "txt".
        title (str | None): Document title override; when None the localized default title from MSG_DEFAULT_ACCESSIBLE_TITLE is used.
        profile_name (str | None): Export verbosity profile applied to block filtering and validation; falls back to format_name when None.

    Returns:
        Path: The output_path where the formatted document was written.

    Raises:
        ValueError: When the deterministic audit reports BLOCKER findings, when the export profile forbids any block, or when format_name is not a recognized export format; the messages are localized.
        RuntimeError: When format_name is "pdf_ua" or "docx" and its TOOLBOX_*_ENABLED setting is false.
        acessilia_sdk.toolbox.errors.ToolboxError: When format_name is "pdf_ua" or "docx" and the Toolbox cannot render or deliver the file.
    """
    document = _ensure_document(
        source_text_or_document, title=title or t(MSG_DEFAULT_ACCESSIBLE_TITLE)
    )

    # Deterministic structural audit before any rendering takes place.
    audit_report = audit_canonical_document(document)
    if audit_report["BLOCKER"]:
        raise ValueError(
            t(MSG_AUDIT_FAILED).format(findings="; ".join(audit_report["BLOCKER"]))
        )

    profile = profile_name or format_name
    filtered = strip_internal_audit_blocks(document, profile)
    profile_errors = validate_export_profile(profile, filtered)
    if profile_errors:
        raise ValueError("; ".join(profile_errors))
    if format_name == "html":
        from backend.export.renderers.html_renderer import render_html

        return render_html(filtered, output_path, profile_name=profile)
    ast = build_pandoc_ast(filtered)
    lang = filtered.get("language") or DEFAULT_EXPORT_LANG
    if format_name == "docx":
        return _render_docx(ast, output_path, lang=lang)
    if format_name == "pdf_ua":
        return _render_pdf_ua(ast, output_path, lang=lang)
    if format_name == "txt":
        from backend.export.renderers.txt_renderer import render_txt

        return render_txt(filtered, output_path, profile_name=profile)
    raise ValueError(t(MSG_UNSUPPORTED_EXPORT_FORMAT).format(format_name=format_name))


def _ensure_document(
    source_text_or_document: str | dict[str, Any],
    *,
    title: str,
) -> dict[str, Any]:
    """Normalizes the export input into a sanitized canonical document mapping.

    Args:
        source_text_or_document (str | dict): Raw markdown/text or a canonical document mapping passed by the caller.
        title (str): Document title applied when the input is plain text.

    Returns:
        dict: Sanitized canonical document mapping ready for auditing and rendering.
    """
    if isinstance(source_text_or_document, dict):
        return sanitize_canonical_document(source_text_or_document)
    return build_canonical_document(source_text_or_document, title=title)
