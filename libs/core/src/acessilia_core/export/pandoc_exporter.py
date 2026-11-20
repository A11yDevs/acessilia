"""Export of a canonical document to the target format.

Renders the normalized canonical document after the existing audit, strict schema
validation and export-profile check. HTML and TXT render in-process; DOCX and
PDF/UA are rendered from the Pandoc AST by the Toolbox, which pins
Pandoc in its own image (docs/adr/0003). Every user-visible error string is resolved through the
active locale strings files via :func:`acessilia_core.i18n.t`, with the canonical English msgid
constants below acting as the single source of truth consumed by scripts/gen_locale_catalogs
for catalog generation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jsonschema import ValidationError, validate
from docstruct.validation import validate_against_schema

from docstruct.export.filters import strip_internal_audit_blocks
from docstruct.export.pandoc_ast import build_pandoc_ast
from docstruct.export.pandoc_ast import count_math_nodes
from docstruct.export.pandoc_ast import degrade_math_to_text
from docstruct.export.pandoc_ast import unconverted_math_indices

from acessilia_core.config import ExportConfig, ToolboxConfig
from acessilia_core.export.catalog import DOCX, HTML, PDF_UA, TXT
from acessilia_core.i18n import t
from acessilia_core.i18n.log_messages import LOG_DOCX_TOOLBOX_EXPORTED
from acessilia_core.i18n.log_messages import LOG_PDF_UA_MATH_DEGRADED
from acessilia_core.i18n.log_messages import LOG_PDF_UA_MATH_PARTIALLY_DEGRADED
from acessilia_core.i18n.log_messages import LOG_PDF_UA_TOOLBOX_EXPORTED
from acessilia_core.export.messages import (
    MSG_AUDIT_FAILED,
    MSG_CANONICAL_SCHEMA_FAILED,
    MSG_DEFAULT_ACCESSIBLE_TITLE,
    MSG_DOCX_DISABLED,
    MSG_PDF_UA_DISABLED,
    MSG_UNSUPPORTED_EXPORT_FORMAT,
)
from acessilia_core.pipeline.canonical_builder import build_canonical_document
from acessilia_core.pipeline.canonical_builder import sanitize_canonical_document
from acessilia_core.pipeline.validators import audit_canonical_document
from acessilia_core.pipeline.validators import validate_export_profile
from acessilia_core.logger import logger


#: BCP 47 language for the document metadata when the document declares none.
DEFAULT_EXPORT_LANG = "pt-BR"
#: Upper bound on Toolbox retry renders spent bisecting failing PDF/UA formulas (#258).
_MAX_MATH_BISECT_ATTEMPTS = 16


def _toolbox_export(
    client_cls: Any, ast: dict[str, Any], output_path: Path, *, lang: str, toolbox: ToolboxConfig
) -> dict[str, Any]:
    """Render ``ast`` on the Toolbox with ``client_cls`` and write it to ``output_path``.

    Returns the export document (artifact id, size, toolchain). The client is
    created and closed inside the coroutine: ``run_sync`` may run it on a fresh
    event loop, and the HTTP connections must not outlive it.
    """
    from acessilia_sdk.runtime import run_sync

    from acessilia_core.toolbox.toolbox_client import make_toolbox_client

    async def export() -> dict[str, Any]:
        client = make_toolbox_client(client_cls, toolbox)
        try:
            return await client.export(
                ast,
                output_path,
                lang=lang,
                use_remote_cache=toolbox.use_remote_cache,
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
    ast: dict[str, Any], output_path: Path, *, toolbox: ToolboxConfig, lang: str = "pt-BR"
) -> dict[str, Any]:
    """Render ``ast`` as PDF/UA on the Toolbox; returns the ``artifact/pdf-export@1`` document."""
    from acessilia_sdk.toolbox.clients import ToolboxPdfUaClient

    return _toolbox_export(ToolboxPdfUaClient, ast, output_path, lang=lang, toolbox=toolbox)


def toolbox_export_docx(
    ast: dict[str, Any], output_path: Path, *, toolbox: ToolboxConfig, lang: str = "pt-BR"
) -> dict[str, Any]:
    """Render ``ast`` as DOCX on the Toolbox; returns the ``artifact/docx-export@1`` document."""
    from acessilia_sdk.toolbox.clients import ToolboxDocxClient

    return _toolbox_export(ToolboxDocxClient, ast, output_path, lang=lang, toolbox=toolbox)


def _render_docx(
    ast: dict[str, Any],
    output_path: Path,
    *,
    enabled: bool,
    toolbox: ToolboxConfig,
    lang: str = DEFAULT_EXPORT_LANG,
) -> Path:
    """Renders DOCX on the Toolbox, which pins Pandoc in its image.

    There is no local fallback (docs/adr/0003): a Toolbox failure propagates
    so the caller can report it, and ``enabled`` false (the run's
    ``ExportConfig.toolbox_docx_enabled``) makes the format unavailable.

    Raises:
        RuntimeError: When TOOLBOX_DOCX_ENABLED is false.
        acessilia_sdk.toolbox.errors.ToolboxError: When the Toolbox cannot render or deliver the DOCX.
    """
    if not enabled:
        raise RuntimeError(t(MSG_DOCX_DISABLED))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    toolbox_export_docx(ast, output_path, lang=lang, toolbox=toolbox)
    logger.info(t(LOG_DOCX_TOOLBOX_EXPORTED).format(output_path=output_path))
    return output_path


def _render_pdf_ua(
    ast: dict[str, Any],
    output_path: Path,
    *,
    enabled: bool,
    toolbox: ToolboxConfig,
    lang: str = DEFAULT_EXPORT_LANG,
) -> Path:
    """Renders PDF/UA on the Toolbox, which pins Pandoc and TeX Live in its image.

    There is no local fallback (docs/adr/0003): a Toolbox failure propagates
    so the caller can report it, and ``enabled`` false (the run's
    ``ExportConfig.toolbox_pdf_ua_enabled``) makes the format unavailable.

    Args:
        ast (dict): Pandoc JSON AST mapping for the canonical document.
        output_path (Path): Destination PDF file path.
        lang (str): BCP 47 tag written to the PDF metadata.

    Returns:
        Path: The output_path where the PDF/UA file was written.

    Raises:
        RuntimeError: When TOOLBOX_PDF_UA_ENABLED is false.
        acessilia_sdk.toolbox.errors.ToolboxError: When the Toolbox cannot render or deliver the PDF. An input
            rejection (``ToolboxInvalidInput``) degrades only the offending math formulas to literal text
            (trying formulas ``math.convert`` did not convert first, then bounded bisection, falling back to
            degrading all math only when needed); a rejection not caused by math propagates.
    """
    if not enabled:
        raise RuntimeError(t(MSG_PDF_UA_DISABLED))
    from acessilia_sdk.toolbox.errors import ToolboxInvalidInput
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        toolbox_export_pdf_ua(ast, output_path, lang=lang, toolbox=toolbox)
    except ToolboxInvalidInput as exc:
        _recover_pdf_ua_math(
            ast, output_path, lang=lang, toolbox=toolbox, initial_error=exc,
        )
    logger.info(t(LOG_PDF_UA_TOOLBOX_EXPORTED).format(output_path=output_path))
    return output_path


def _recover_pdf_ua_math(
    ast: dict[str, Any],
    output_path: Path,
    *,
    lang: str,
    toolbox: ToolboxConfig,
    initial_error: Exception,
    max_bisect_attempts: int = _MAX_MATH_BISECT_ATTEMPTS,
) -> None:
    """Retry PDF/UA rendering by degrading only the formulas the renderer rejects (#258).

    ``ToolboxInvalidInput`` means the request reached a healthy renderer and
    the AST itself is the problem — often a single formula with a macro the
    template does not load (e.g. ``\\chemfig``). Rather than degrading every
    formula in the document:

    1. When the AST has no ``Math`` inline, re-raise ``initial_error`` without retrying.
    2. With a single formula, degrade it and retry once (a second rejection propagates).
    3. With several formulas, isolate the offending ones with bounded bisection,
       using formulas that ``math.convert`` did not convert (when others did) as
       the first partition so a known-bad formula costs a single retry. Non-math
       rejections fail when all math is degraded and propagate immediately.
    """
    from acessilia_sdk.toolbox.errors import ToolboxInvalidInput

    total = count_math_nodes(ast)
    if total == 0:
        raise initial_error

    if total == 1:
        logger.warning(t(LOG_PDF_UA_MATH_DEGRADED).format(error=initial_error))
        toolbox_export_pdf_ua(degrade_math_to_text(ast), output_path, lang=lang, toolbox=toolbox)
        return

    all_indices = frozenset(range(total))
    attempts = 0
    best_degraded: frozenset[int] | None = None
    last_succeeded: frozenset[int] | None = None
    last_error: Exception = initial_error

    def try_render(degraded: frozenset[int], *, count_against_budget: bool = True) -> bool:
        nonlocal attempts, best_degraded, last_succeeded, last_error
        if count_against_budget:
            attempts += 1
        candidate_ast = degrade_math_to_text(ast, indices=degraded)
        try:
            toolbox_export_pdf_ua(candidate_ast, output_path, lang=lang, toolbox=toolbox)
        except ToolboxInvalidInput as exc:
            last_error = exc
            return False
        last_succeeded = degraded
        if best_degraded is None or len(degraded) < len(best_degraded):
            best_degraded = degraded
        return True

    def isolate(
        candidates: list[int],
        fixed_degraded: frozenset[int],
        *,
        all_degraded_verified: bool,
        first_right: list[int] | None = None,
    ) -> frozenset[int]:
        if len(candidates) == 1:
            single = frozenset(candidates)
            if all_degraded_verified:
                return single
            if try_render(fixed_degraded | single):
                return single
            raise last_error

        if attempts >= max_bisect_attempts:
            return frozenset(candidates)

        if first_right:
            right = first_right
            right_set = frozenset(right)
            left = [idx for idx in candidates if idx not in right_set]
        else:
            mid = len(candidates) // 2
            left = candidates[:mid]
            right = candidates[mid:]

        left_set = frozenset(left)
        right_set = frozenset(right)

        # Probe 1: degrade right (keep left active).
        if try_render(fixed_degraded | right_set):
            return isolate(right, fixed_degraded, all_degraded_verified=True)

        if attempts >= max_bisect_attempts:
            return frozenset(candidates)

        # Probe 2: degrade left (keep right active).
        if try_render(fixed_degraded | left_set):
            return isolate(left, fixed_degraded, all_degraded_verified=True)

        # Both halves failed: verify degrading every remaining candidate succeeds
        # before spending more renders (a non-math rejection fails here too).
        if not all_degraded_verified:
            if not try_render(fixed_degraded | left_set | right_set):
                raise last_error
            all_degraded_verified = True

        left_bad = isolate(left, fixed_degraded | right_set, all_degraded_verified=True)
        right_bad = isolate(right, fixed_degraded | left_bad, all_degraded_verified=True)
        return left_bad | right_bad

    suspects = unconverted_math_indices(ast, target_format="pdf_ua")
    first_right = sorted(suspects) if 0 < len(suspects) < total else None

    degraded_indices = isolate(
        list(range(total)),
        frozenset(),
        all_degraded_verified=False,
        first_right=first_right,
    )

    if best_degraded is None:
        if not try_render(all_indices, count_against_budget=False):
            raise last_error
        degraded_indices = all_indices
    elif len(best_degraded) < len(degraded_indices):
        degraded_indices = best_degraded

    if last_succeeded != degraded_indices:
        if not try_render(degraded_indices, count_against_budget=False):
            degraded_indices = best_degraded
            if last_succeeded != degraded_indices:
                if not try_render(degraded_indices, count_against_budget=False):
                    raise last_error

    if len(degraded_indices) == total:
        logger.warning(t(LOG_PDF_UA_MATH_DEGRADED).format(error=initial_error))
    else:
        logger.warning(
            t(LOG_PDF_UA_MATH_PARTIALLY_DEGRADED).format(
                degraded=len(degraded_indices), total=total, error=initial_error
            )
        )


def _validate_export_schema(document: dict[str, Any]) -> None:
    """Validate normalized, audited input before selection or renderer side effects.

    The packaged schema remains owned by docstruct; Core injects its engine.
    Diagnostics expose the JSON Pointer and keyword, not the document value or
    jsonschema's verbose exception (which embeds the document).
    """
    try:
        validate_against_schema(document, validate)
    except ValidationError as exc:
        pointer = "/" + "/".join(
            str(part).replace("~", "~0").replace("/", "~1") for part in exc.absolute_path
        )
        raise ValueError(t(MSG_CANONICAL_SCHEMA_FAILED).format(
            path=pointer, rule=exc.validator,
        )) from None


def export_accessible_document(
    source_text_or_document: str | dict[str, Any],
    output_path: Path,
    *,
    format_name: str,
    title: str | None = None,
    profile_name: str | None = None,
    export: ExportConfig | None = None,
    toolbox: ToolboxConfig | None = None,
) -> Path:
    """Exports a canonical document (or raw markdown/text) to the named format.

    Args:
        source_text_or_document (str | dict): Raw markdown/text or an already-built canonical document mapping to export.
        output_path (Path): Destination file path for the rendered output.
        format_name (str): Target format key: "html", "docx", "pdf_ua" or "txt".
        title (str | None): Document title override; when None the localized default title from MSG_DEFAULT_ACCESSIBLE_TITLE is used.
        profile_name (str | None): Export verbosity profile applied to block filtering and validation; falls back to format_name when None.
        export (ExportConfig | None): The run's export configuration; required for "docx" and "pdf_ua", whose Toolbox rendering it enables.
        toolbox (ToolboxConfig | None): The run's Toolbox configuration; required for "docx" and "pdf_ua", which the Toolbox renders, and for text, whose formulas it enriches.

    Returns:
        Path: The output_path where the formatted document was written.

    Raises:
        ValueError: When the deterministic audit reports BLOCKER findings, when the normalized document fails its JSON Schema, when the export profile forbids any block, or when format_name is not a recognized export format; the messages are localized.
        RuntimeError: When format_name is "pdf_ua" or "docx" and the run's ExportConfig disables it.
        TypeError: When format_name is "pdf_ua" or "docx" and no ExportConfig or ToolboxConfig is given, or when text is given without a ToolboxConfig (its formulas are enriched on the Toolbox).
        acessilia_sdk.toolbox.errors.ToolboxError: When format_name is "pdf_ua" or "docx" and the Toolbox cannot render or deliver the file.
    """
    document = _ensure_document(
        source_text_or_document, title=title or t(MSG_DEFAULT_ACCESSIBLE_TITLE), toolbox=toolbox
    )

    # Deterministic structural audit before any rendering takes place.
    audit_report = audit_canonical_document(document)
    if audit_report["BLOCKER"]:
        raise ValueError(
            t(MSG_AUDIT_FAILED).format(findings="; ".join(audit_report["BLOCKER"]))
        )

    _validate_export_schema(document)

    profile = profile_name or format_name
    filtered = strip_internal_audit_blocks(document, profile)
    profile_errors = validate_export_profile(profile, filtered)
    if profile_errors:
        raise ValueError("; ".join(profile_errors))
    from acessilia_core.export.renderers.html_renderer import render_html
    from acessilia_core.export.renderers.txt_renderer import render_txt

    # Preserve the existing AST/error boundary: HTML bypasses AST construction;
    # TXT and unsupported format requests still build it after the audit gate.
    ast = None if format_name == HTML.spec.id else build_pandoc_ast(filtered, target_format=format_name)
    lang = filtered.get("language") or DEFAULT_EXPORT_LANG
    renderers = {
        HTML.spec.id: lambda: render_html(filtered, output_path, profile_name=profile),
        TXT.spec.id: lambda: render_txt(filtered, output_path, profile_name=profile),
        DOCX.spec.id: lambda: _render_docx(
            ast, output_path, enabled=_export_config(export, format_name).toolbox_docx_enabled,
            toolbox=_toolbox_config(toolbox, format_name), lang=lang,
        ),
        PDF_UA.spec.id: lambda: _render_pdf_ua(
            ast, output_path, enabled=_export_config(export, format_name).toolbox_pdf_ua_enabled,
            toolbox=_toolbox_config(toolbox, format_name), lang=lang,
        ),
    }
    render = renderers.get(format_name)
    if render is None:
        raise ValueError(t(MSG_UNSUPPORTED_EXPORT_FORMAT).format(format_name=format_name))
    return render()


def _export_config(export: ExportConfig | None, format_name: str) -> ExportConfig:
    """The run's ``ExportConfig``, which a Toolbox-rendered format cannot do without."""
    if export is None:
        raise TypeError(f"exporting {format_name} needs the run's ExportConfig")
    return export


def _toolbox_config(toolbox: ToolboxConfig | None, format_name: str) -> ToolboxConfig:
    """The run's ``ToolboxConfig``, which a Toolbox-rendered format cannot do without."""
    if toolbox is None:
        raise TypeError(f"exporting {format_name} needs the run's ToolboxConfig")
    return toolbox


def _ensure_document(
    source_text_or_document: str | dict[str, Any],
    *,
    title: str,
    toolbox: ToolboxConfig | None,
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
    return build_canonical_document(source_text_or_document, title=title, toolbox=toolbox)
