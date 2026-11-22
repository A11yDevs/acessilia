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

from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from jsonschema import ValidationError, validate

from acessilia_core.config import ExportConfig, ToolboxConfig
from acessilia_core.export.catalog import DOCX, HTML, PDF_UA, TXT
from acessilia_core.export.messages import (
    MSG_AUDIT_FAILED,
    MSG_CANONICAL_SCHEMA_FAILED,
    MSG_DEFAULT_ACCESSIBLE_TITLE,
    MSG_DOCX_DISABLED,
    MSG_PDF_UA_DISABLED,
    MSG_UNSUPPORTED_EXPORT_FORMAT,
)
from acessilia_core.i18n import t
from acessilia_core.i18n.log_messages import (
    LOG_DOCX_TOOLBOX_EXPORTED,
    LOG_PDF_UA_MATH_DEGRADED,
    LOG_PDF_UA_MATH_ISOLATION_EXHAUSTED,
    LOG_PDF_UA_MATH_PARTIALLY_DEGRADED,
    LOG_PDF_UA_TOOLBOX_EXPORTED,
)
from acessilia_core.logger import logger
from acessilia_core.pipeline.canonical_builder import (
    build_canonical_document,
    sanitize_canonical_document,
)
from acessilia_core.pipeline.validators import (
    audit_canonical_document,
    validate_export_profile,
)
from acessilia_sdk.toolbox.errors import ToolboxInvalidInput
from docstruct.export.filters import strip_internal_audit_blocks
from docstruct.export.pandoc_ast import (
    build_pandoc_ast,
    count_math_nodes,
    degrade_math_to_text,
    unconverted_math_indices,
)
from docstruct.validation import validate_against_schema

#: BCP 47 language for the document metadata when the document declares none.
DEFAULT_EXPORT_LANG = "pt-BR"
#: Default upper bound on Toolbox retry renders spent isolating failing PDF/UA
#: formulas (#258). Each retry is a full remote PDF/UA render, so worst-case
#: wall time is ``(1 + budget) * TOOLBOX_PDF_UA_TIMEOUT_SECONDS`` (~45 min at
#: budget=8 and 300s timeout, though rejected LaTeX renders typically fail fast
#: and a timeout immediately aborts without retrying). Deployments tune this via
#: ``ExportConfig.toolbox_pdf_ua_math_bisect_budget`` (``TOOLBOX_PDF_UA_MATH_BISECT_BUDGET``).
_MAX_MATH_BISECT_ATTEMPTS = 8


def _toolbox_export(
    client_cls: Any, ast: dict[str, Any], output_path: Path, *, lang: str, toolbox: ToolboxConfig
) -> dict[str, Any]:
    """Render ``ast`` on the Toolbox with ``client_cls`` and write it to ``output_path``.

    Returns the export document (artifact id, size, toolchain). The client is
    created and closed inside the coroutine: ``run_sync`` may run it on a fresh
    event loop, and the HTTP connections must not outlive it.
    """
    from acessilia_core.toolbox.toolbox_client import make_toolbox_client
    from acessilia_sdk.runtime import run_sync

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
    max_bisect_attempts: int | None = None,
    check_cancelled: Callable[[], None] | None = None,
) -> Path:
    """Renders PDF/UA on the Toolbox, which pins Pandoc and TeX Live in its image.

    There is no local fallback (docs/adr/0003): a Toolbox failure propagates
    so the caller can report it, and ``enabled`` false (the run's
    ``ExportConfig.toolbox_pdf_ua_enabled``) makes the format unavailable.

    Args:
        ast (dict): Pandoc JSON AST mapping for the canonical document.
        output_path (Path): Destination PDF file path.
        lang (str): BCP 47 tag written to the PDF metadata.
        max_bisect_attempts (int | None): Cap on retry renders for per-formula math
            isolation; ``None`` reads ``_MAX_MATH_BISECT_ATTEMPTS``.
        check_cancelled (Callable[[], None] | None): Optional callback checked before
            each retry render; raising aborts isolation immediately.

    Returns:
        Path: The output_path where the PDF/UA file was written.

    Raises:
        RuntimeError: When TOOLBOX_PDF_UA_ENABLED is false.
        acessilia_sdk.toolbox.errors.ToolboxError: When the Toolbox cannot render or deliver the PDF. An input
            rejection (``ToolboxInvalidInput``) degrades only the offending math formulas to literal text
            (trying formulas ``math.convert`` did not convert first when focused, then bounded
            largest-chunk-first bisection, falling back to a verified degraded subset when the budget
            runs out); a rejection not caused by math propagates.
    """
    if not enabled:
        raise RuntimeError(t(MSG_PDF_UA_DISABLED))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        toolbox_export_pdf_ua(ast, output_path, lang=lang, toolbox=toolbox)
    except ToolboxInvalidInput as exc:
        _recover_pdf_ua_math(
            ast,
            output_path,
            lang=lang,
            toolbox=toolbox,
            initial_error=exc,
            max_bisect_attempts=max_bisect_attempts,
            check_cancelled=check_cancelled,
        )
    logger.info(t(LOG_PDF_UA_TOOLBOX_EXPORTED).format(output_path=output_path))
    return output_path


class _PdfUaMathBisector:
    """Bounded largest-chunk-first bisector isolating rejected PDF/UA math nodes."""

    def __init__(
        self,
        ast: dict[str, Any],
        output_path: Path,
        *,
        lang: str,
        toolbox: ToolboxConfig,
        initial_error: Exception,
        budget: int,
        total: int,
        check_cancelled: Callable[[], None] | None,
    ) -> None:
        self.ast = ast
        self.output_path = output_path
        self.lang = lang
        self.toolbox = toolbox
        self.initial_error = initial_error
        self.budget = budget
        self.total = total
        self.check_cancelled = check_cancelled
        self.all_indices = frozenset(range(total))
        self.attempts = 0
        self.last_error: Exception = initial_error
        self.proven_bad: set[int] = set()
        self.pending: list[list[int]] = []

    def try_render(self, degraded: frozenset[int]) -> bool:
        if self.check_cancelled is not None:
            self.check_cancelled()
        self.attempts += 1
        candidate_ast = degrade_math_to_text(self.ast, indices=degraded)
        try:
            toolbox_export_pdf_ua(
                candidate_ast, self.output_path, lang=self.lang, toolbox=self.toolbox
            )
        except ToolboxInvalidInput as exc:
            self.last_error = exc
            return False
        return True

    def _enqueue(self, chunk: list[int]) -> None:
        if len(chunk) == 1:
            self.proven_bad.add(chunk[0])
        elif chunk:
            self.pending.append(chunk)

    def _initial_partition(self) -> tuple[list[int], list[int]]:
        # Re-walks source_document once per rejected PDF/UA export to build the
        # suspect ordering hint. Only used when at most half the formulas lack
        # MathML, so a transient math.convert outage falls back to a balanced split.
        suspects = unconverted_math_indices(self.ast, target_format=PDF_UA.spec.id)
        if 0 < len(suspects) <= self.total // 2:
            right = sorted(suspects)
            left = [idx for idx in range(self.total) if idx not in suspects]
            return left, right
        mid = self.total // 2
        return list(range(mid)), list(range(mid, self.total))

    def _establish_verified_pdf(self, left: list[int], right: list[int]) -> None:
        # Establish a verified working PDF on disk before refining chunks.
        if self.try_render(frozenset(right)):
            self._enqueue(right)
        elif self.budget - self.attempts >= 2 and self.try_render(frozenset(left)):
            self._enqueue(left)
        else:
            both_halves_probed = self.attempts >= 2
            if not self.try_render(self.all_indices):
                raise self.last_error
            if both_halves_probed:
                self._enqueue(left)
                self._enqueue(right)
            else:
                self.pending.append(list(range(self.total)))

    def _refine_pending_chunks(self) -> None:
        # Refine the largest unresolved chunk first so each successful probe rescues
        # the biggest possible block of valid formulas within the retry budget.
        # Invariant: output_path always holds the verified PDF for
        # ``proven_bad | union(pending)``.
        while self.pending and self.attempts < self.budget:
            chunk_pos = max(
                range(len(self.pending)),
                key=lambda i: (len(self.pending[i]), -self.pending[i][0]),
            )
            chunk = self.pending.pop(chunk_pos)
            mid = len(chunk) // 2
            left, right = chunk[:mid], chunk[mid:]
            other = frozenset(
                self.proven_bad | {idx for rest in self.pending for idx in rest}
            )
            if self.try_render(other | frozenset(right)):
                self._enqueue(right)
                continue
            if self.attempts >= self.budget:
                self.pending.append(chunk)
                break
            if self.try_render(other | frozenset(left)):
                self._enqueue(left)
                continue
            self._enqueue(left)
            self._enqueue(right)

    def _log_outcome(self) -> None:
        degraded_indices = frozenset(
            self.proven_bad | {idx for rest in self.pending for idx in rest}
        )
        if self.pending:
            logger.warning(
                t(LOG_PDF_UA_MATH_ISOLATION_EXHAUSTED).format(
                    attempts=self.attempts,
                    degraded=len(degraded_indices),
                    total=self.total,
                    error=self.initial_error,
                )
            )
        elif len(degraded_indices) == self.total:
            logger.warning(t(LOG_PDF_UA_MATH_DEGRADED).format(error=self.initial_error))
        else:
            logger.warning(
                t(LOG_PDF_UA_MATH_PARTIALLY_DEGRADED).format(
                    degraded=len(degraded_indices),
                    total=self.total,
                    error=self.initial_error,
                )
            )

    def run(self) -> None:
        if self.total == 1 or self.budget == 1:
            if not self.try_render(self.all_indices):
                raise self.last_error
            if self.total == 1:
                logger.warning(
                    t(LOG_PDF_UA_MATH_DEGRADED).format(error=self.initial_error)
                )
            else:
                logger.warning(
                    t(LOG_PDF_UA_MATH_ISOLATION_EXHAUSTED).format(
                        attempts=self.attempts,
                        degraded=self.total,
                        total=self.total,
                        error=self.initial_error,
                    )
                )
            return

        left, right = self._initial_partition()
        self._establish_verified_pdf(left, right)
        self._refine_pending_chunks()
        self._log_outcome()


def _recover_pdf_ua_math(
    ast: dict[str, Any],
    output_path: Path,
    *,
    lang: str,
    toolbox: ToolboxConfig,
    initial_error: Exception,
    max_bisect_attempts: int | None = None,
    check_cancelled: Callable[[], None] | None = None,
) -> None:
    """Retry PDF/UA rendering by degrading only the formulas the renderer rejects (#258).

    ``ToolboxInvalidInput`` means the request reached a healthy renderer and
    the AST itself is the problem — often a single formula with a macro the
    template does not load (e.g. ``\\chemfig``). Rather than degrading every
    formula in the document:

    1. When the AST has no ``Math`` inline or the retry budget is 0, re-raise
       ``initial_error`` without retrying.
    2. With a single formula (or a retry budget of 1), degrade all math and
       retry once; a second rejection propagates.
    3. With several formulas, isolate the offending ones iteratively
       (largest-chunk-first) within ``budget`` total recovery renders — every
       retry, including the all-degraded fallback, counts against the budget
       and checks ``check_cancelled`` before starting. A focused unconverted
       subset from ``unconverted_math_indices`` (<= half the formulas) is used
       as the first partition so a known-bad formula recovers in one retry.
       Every successful probe writes a render-verified PDF to ``output_path``
       and shrinks the degraded set, so exhausting the budget always leaves the
       smallest verified PDF on disk and logs a distinct budget-exhausted
       warning instead of overstating rejected formulas.
    """
    budget = (
        _MAX_MATH_BISECT_ATTEMPTS
        if max_bisect_attempts is None
        else max(0, max_bisect_attempts)
    )
    total = count_math_nodes(ast)
    if total == 0 or budget == 0:
        raise initial_error

    _PdfUaMathBisector(
        ast,
        output_path,
        lang=lang,
        toolbox=toolbox,
        initial_error=initial_error,
        budget=budget,
        total=total,
        check_cancelled=check_cancelled,
    ).run()


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
    check_cancelled: Callable[[], None] | None = None,
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
            cast(dict[str, Any], ast), output_path, enabled=_export_config(export, format_name).toolbox_docx_enabled,
            toolbox=_toolbox_config(toolbox, format_name), lang=lang,
        ),
        PDF_UA.spec.id: lambda: _render_pdf_ua(
            cast(dict[str, Any], ast),
            output_path,
            enabled=_export_config(export, format_name).toolbox_pdf_ua_enabled,
            toolbox=_toolbox_config(toolbox, format_name),
            lang=lang,
            max_bisect_attempts=_export_config(
                export, format_name
            ).toolbox_pdf_ua_math_bisect_budget,
            check_cancelled=check_cancelled,
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
