"""Pandoc-based export of a canonical document to the target format.

Renders the canonical document through pandoc (or a pure-Python fallback renderer) after a
deterministic structural audit and an export-profile verbosity check, so that only compliant
documents ever reach the exporter. Every user-visible error string is resolved through the
active locale strings files via :func:`backend.i18n.t`, with the canonical English msgid
constants below acting as the single source of truth consumed by scripts/gen_locale_catalogs
for catalog generation.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from backend.config.settings import settings
from backend.export.filters.pandoc_filters import strip_internal_audit_blocks
from backend.i18n import t
from backend.log_messages import LOG_PDF_UA_TOOLBOX_EXPORTED
from backend.pipeline.canonical_builder import build_canonical_document
from backend.pipeline.canonical_builder import sanitize_canonical_document
from backend.pipeline.pandoc_ast_builder import build_pandoc_ast
from backend.pipeline.validators import audit_canonical_document
from backend.pipeline.validators import validate_export_profile
from backend.tools.logger import logger

#: Canonical English msgid for a default document title used when the caller passes none.
MSG_DEFAULT_ACCESSIBLE_TITLE: str = "Accessible document"
#: Canonical English msgid for a pandoc binary not found on the PATH.
MSG_PANDOC_NOT_FOUND: str = "pandoc not found on PATH"
#: Canonical English msgid template for a failed pandoc invocation; {to_format} and {stderr} are substituted by callers after lookup.
MSG_PANDOC_FAILED: str = "pandoc failed ({to_format}): {stderr}"
#: Canonical English msgid for a pdf_ua export requested while TOOLBOX_PDF_UA_ENABLED is false.
MSG_PDF_UA_DISABLED: str = "PDF/UA export is disabled (TOOLBOX_PDF_UA_ENABLED=false)"
#: Canonical English msgid template for an audit failure; {findings} is substituted by callers after lookup.
MSG_AUDIT_FAILED: str = "Audit failed: {findings}"
#: Canonical English msgid template for an unsupported export format; {format_name} is substituted by callers after lookup.
MSG_UNSUPPORTED_EXPORT_FORMAT: str = "Unsupported export format: {format_name}"


def _pandoc_bin() -> str | None:
    """Returns the pandoc binary path, or None if it is not available on PATH.

    Returns:
        str | None: Absolute path of the pandoc executable when found on PATH, else None.
    """
    return shutil.which("pandoc")


def _render_with_pandoc(
    ast: dict[str, Any],
    output_path: Path,
    to_format: str,
    extra_args: list[str] | None = None,
) -> Path:
    """Converts the pandoc JSON AST to the target format by invoking the pandoc binary.

    Args:
        ast (dict): Pandoc JSON AST mapping produced by build_pandoc_ast for the canonical document.
        output_path (Path): Destination file path; the parent directory is created when missing.
        to_format (str): pandoc output format token (e.g. "html5", "docx", "pdf").
        extra_args (list[str] | None): Optional extra pandoc command-line arguments appended after the base command (default None).

    Returns:
        Path: The output_path where pandoc wrote the rendered document.

    Raises:
        RuntimeError: When pandoc is missing from PATH or exits with a nonzero status; the message is localized through backend.i18n.t.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ast_json = json.dumps(ast).encode()
    pandoc = _pandoc_bin()
    if pandoc is None:
        raise RuntimeError(t(MSG_PANDOC_NOT_FOUND))
    cmd = [pandoc, "--from", "json", "--to", to_format, "-o", str(output_path)]
    if extra_args:
        cmd.extend(extra_args)
    result = subprocess.run(  # noqa: S603
        cmd,
        input=ast_json,
        capture_output=True,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(
            t(MSG_PANDOC_FAILED).format(
                to_format=to_format, stderr=result.stderr.decode()
            )
        )
    return output_path


#: BCP 47 language for PDF/UA metadata when the document declares none.
DEFAULT_PDF_UA_LANG = "pt-BR"


def toolbox_export_pdf_ua(
    ast: dict[str, Any], output_path: Path, *, lang: str = "pt-BR"
) -> dict[str, Any]:
    """Render ``ast`` as PDF/UA on the Toolbox and write it to ``output_path``.

    Returns the ``artifact/pdf-export@1`` document. The client is created and
    closed inside the coroutine: ``run_sync`` may run it on a fresh event
    loop, and the HTTP connections must not outlive it.
    """
    from acessilia_sdk.toolbox.clients import ToolboxPdfUaClient

    from backend.tools.toolbox_client import make_toolbox_client, run_sync

    async def export() -> dict[str, Any]:
        client = make_toolbox_client(ToolboxPdfUaClient)
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
        "Toolbox: document.export.pdf_ua finished ({} bytes, cache_hit={}, {} ms)",
        document.get("size_bytes", "?"),
        provenance.get("cache_hit", False),
        provenance.get("duration_ms", "?"),
    )
    return document


def _render_pdf_ua(
    ast: dict[str, Any], output_path: Path, *, lang: str = DEFAULT_PDF_UA_LANG
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
        ToolboxError: When the Toolbox cannot render or deliver the PDF.
    """
    if not settings.toolbox_pdf_ua_enabled:
        raise RuntimeError(t(MSG_PDF_UA_DISABLED))
    toolbox_export_pdf_ua(ast, output_path, lang=lang)
    logger.info(t(LOG_PDF_UA_TOOLBOX_EXPORTED).format(output_path=output_path))
    return output_path


def export_accessible_document(
    source_text_or_document: str | dict[str, Any],
    output_path: Path,
    *,
    format_name: str,
    title: str | None = None,
    profile_name: str | None = None,
    filename: str = "",
) -> Path:
    """Exports a canonical document (or raw markdown/text) to the named format.

    Args:
        source_text_or_document (str | dict): Raw markdown/text or an already-built canonical document mapping to export.
        output_path (Path): Destination file path for the rendered output.
        format_name (str): Target format key: "html", "docx", "pdf", "pdf_ua" or "txt".
        title (str | None): Document title override; when None the localized default title from MSG_DEFAULT_ACCESSIBLE_TITLE is used.
        profile_name (str | None): Export verbosity profile applied to block filtering and validation; falls back to format_name when None.
        filename (str): Optional output filename hint used by the docx fallback renderer (default "").

    Returns:
        Path: The output_path where the formatted document was written.

    Raises:
        ValueError: When the deterministic audit reports BLOCKER findings or when the export profile forbids any block; both messages are localized.

    Raises:
        ValueError: When format_name is not a recognized export format.
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
    pandoc = _pandoc_bin()
    if format_name == "docx":
        if pandoc:
            return _render_with_pandoc(ast, output_path, "docx")
        from backend.export.renderers.docx_renderer import render_docx

        return render_docx(
            filtered,
            output_path,
            profile_name=profile,
            filename=filename,
        )
    if format_name == "pdf":
        from backend.export.renderers.pdf_renderer import render_pdf

        return render_pdf(
            filtered,
            output_path,
            profile_name=profile,
            title=title or "",
        )
    if format_name == "pdf_ua":
        return _render_pdf_ua(
            ast, output_path, lang=filtered.get("language") or DEFAULT_PDF_UA_LANG
        )
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
