from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from backend.export.filters.pandoc_filters import strip_internal_audit_blocks
from backend.pipeline.canonical_builder import build_canonical_document
from backend.pipeline.canonical_builder import sanitize_canonical_document
from backend.pipeline.pandoc_ast_builder import build_pandoc_ast
from backend.pipeline.validators import audit_canonical_document
from backend.pipeline.validators import validate_export_profile


def _pandoc_bin() -> str | None:
    """Retorna o caminho do binário pandoc, ou None se não disponível."""
    return shutil.which("pandoc")


def _xelatex_bin() -> str | None:
    """Retorna o caminho do binário xelatex, ou None se não disponível."""
    return shutil.which("xelatex")


def _lualatex_bin() -> str | None:
    """Retorna o caminho do binário lualatex, ou None se não disponível."""
    return shutil.which("lualatex")


def _pdf_ua_engine() -> str | None:
    """Seleciona engine LaTeX para PDF/UA (prefere XeLaTeX)."""
    if _xelatex_bin() is not None:
        return "xelatex"
    if _lualatex_bin() is not None:
        return "lualatex"
    return None


def _pdf_ua_template_path() -> Path:
    return Path(__file__).resolve().parent / "templates" / "pdf_ua.tex"


def _render_with_pandoc(
    ast: dict[str, Any],
    output_path: Path,
    to_format: str,
    extra_args: list[str] | None = None,
) -> Path:
    """Converte o documento canônico para o formato via pandoc JSON AST."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ast_json = json.dumps(ast).encode()
    pandoc = _pandoc_bin()
    if pandoc is None:
        raise RuntimeError("pandoc não encontrado no PATH")
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
        raise RuntimeError(f"pandoc falhou ({to_format}): {result.stderr.decode()}")
    return output_path


def _render_pdf_ua_with_pandoc(ast: dict[str, Any], output_path: Path) -> Path:
    pandoc = _pandoc_bin()
    if pandoc is None:
        raise RuntimeError(
            "pandoc não encontrado no PATH. O formato pdf_ua exige pandoc + engine LaTeX."
        )
    engine = _pdf_ua_engine()
    if engine is None:
        raise RuntimeError(
            "Nenhuma engine LaTeX encontrada no PATH. O formato pdf_ua exige lualatex ou xelatex."
        )

    template_path = _pdf_ua_template_path()
    if not template_path.exists():
        raise RuntimeError(f"Template PDF/UA não encontrado: {template_path}")

    return _render_with_pandoc(
        ast,
        output_path,
        "pdf",
        extra_args=[
            "--standalone",
            "--no-highlight",
            f"--pdf-engine={engine}",
            f"--template={template_path}",
            "-V",
            "lang=pt-BR",
        ],
    )


def export_accessible_document(
    source_text_or_document: str | dict[str, Any],
    output_path: Path,
    *,
    format_name: str,
    title: str = "Documento acessível",
    profile_name: str | None = None,
    filename: str = "",
) -> Path:
    document = _ensure_document(source_text_or_document, title=title)

    # Nova auditoria determinística
    audit_report = audit_canonical_document(document)
    if audit_report["BLOCKER"]:
        raise ValueError(f"Auditoria falhou: {'; '.join(audit_report['BLOCKER'])}")

    profile = profile_name or format_name
    filtered = strip_internal_audit_blocks(document, profile)
    profile_errors = validate_export_profile(profile, filtered)
    if profile_errors:
        raise ValueError("; ".join(profile_errors))
    ast = build_pandoc_ast(filtered)
    pandoc = _pandoc_bin()
    if format_name == "html":
        if pandoc:
            return _render_with_pandoc(
                ast, output_path, "html5", extra_args=["--toc", "--standalone"]
            )
        from backend.export.renderers.html_renderer import render_html

        return render_html(filtered, output_path, profile_name=profile)
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
            title=title,
        )
    if format_name == "pdf_ua":
        return _render_pdf_ua_with_pandoc(ast, output_path)
    if format_name == "txt":
        from backend.export.renderers.txt_renderer import render_txt

        return render_txt(filtered, output_path, profile_name=profile)
    raise ValueError(f"Formato de exportacao nao suportado: {format_name}")


def _ensure_document(
    source_text_or_document: str | dict[str, Any],
    *,
    title: str,
) -> dict[str, Any]:
    if isinstance(source_text_or_document, dict):
        return sanitize_canonical_document(source_text_or_document)
    return build_canonical_document(source_text_or_document, title=title)
