from __future__ import annotations

from pathlib import Path
import re
from typing import Any
from xml.sax.saxutils import escape, quoteattr

from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    ListFlowable,
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
)

from backend.export.pandoc_exporter import MSG_DEFAULT_ACCESSIBLE_TITLE
from backend.i18n import t
from backend.pipeline.table_ast import linearize_table_for_text
from backend.pipeline.verbosity_manager import filter_blocks_for_profile
from backend.tools.code_tools import normalize_code_text

#: Canonical English msgid for the PDF table-of-contents heading.
MSG_PDF_TABLE_OF_CONTENTS: str = "Contents"
#: Canonical English msgid for the PDF note-block prefix label.
MSG_PDF_NOTE_LABEL: str = "Note"
#: Canonical English msgid for the PDF warning-block prefix label.
MSG_PDF_WARNING_LABEL: str = "Warning"


def _escape_text(value: Any) -> str:
    return escape(str(value))


class _DocTemplate(SimpleDocTemplate):
    """SimpleDocTemplate subclass that records heading bookmarks to emit a PDF outline on page end."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._outline = []
        self._last_outline_level = -1

    def afterFlowable(self, flowable):
        """After each flowable is drawn, capture heading paragraphs as outline bookmark candidates.

        Args:
            flowable (Any): The platypus flowable that was just rendered.
        """
        if isinstance(flowable, Paragraph) and getattr(flowable, "_heading_id", None):
            self.canv.bookmarkPage(flowable._heading_id)
            self._outline.append(
                (
                    flowable._heading_level - 1,
                    flowable.getPlainText(),
                    flowable._heading_id,
                )
            )
        super().afterFlowable(flowable)

    def handle_pageEnd(self):
        """Flush the queued outline entries to the canvas at the end of each page."""
        if self._outline:
            for level, text, key in self._outline:
                safe_level = self._normalize_outline_level(level)
                self.canv.addOutlineEntry(
                    text,
                    key,
                    level=safe_level,
                    closed=False,
                )
                self._last_outline_level = safe_level
            self._outline.clear()
        super().handle_pageEnd()

    def _normalize_outline_level(self, raw_level: int) -> int:
        """Clamp an outline level so entries never skip more than one level deeper than the previous entry.

        Args:
            raw_level (int): 0-based outline level requested for the entry.

        Returns:
            int: The clamped, ReportLab-safe level.
        """
        target = max(int(raw_level), 0)
        if self._last_outline_level < 0:
            # ReportLab requires the first outline entry to start at level 0.
            return 0
        if target > self._last_outline_level + 1:
            return self._last_outline_level + 1
        return target


def render_pdf(
    document: dict[str, Any],
    output_path: Path,
    profile_name: str = "pdf",
    title: str | None = None,
) -> Path:
    """Renders the canonical document into a marked A4 PDF with bookmarks for headings.

    Args:
        document (dict): Canonical document mapping (title, sections) to render.
        output_path (Path): Destination file path; the parent directory is created when missing.
        profile_name (str): Export verbosity profile applied to block filtering (default "pdf").
        title (str | None): Optional title override; falls back to the document title, then the localized default (default None).

    Returns:
        Path: The output_path where the PDF was written.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            "A11yTitle", parent=styles["Title"], alignment=TA_CENTER, spaceAfter=12
        )
    )
    styles.add(
        ParagraphStyle(
            "A11yHeading1", parent=styles["Heading1"], spaceBefore=10, spaceAfter=6
        )
    )
    styles.add(
        ParagraphStyle(
            "A11yHeading2", parent=styles["Heading2"], spaceBefore=8, spaceAfter=4
        )
    )
    styles.add(
        ParagraphStyle("A11yBody", parent=styles["BodyText"], leading=14, spaceAfter=6)
    )
    styles.add(
        ParagraphStyle(
            "A11yCode",
            parent=styles["Code"],
            fontName="Courier",
            fontSize=9,
            leading=11,
            leftIndent=10,
            spaceBefore=3,
            spaceAfter=6,
        )
    )
    doc = _DocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=title or document.get("title") or t(MSG_DEFAULT_ACCESSIBLE_TITLE),
        author="a11y-devs-describer",
    )
    story = [
        Paragraph(
            _escape_text(title or document.get("title", t(MSG_DEFAULT_ACCESSIBLE_TITLE))),
            styles["A11yTitle"],
        ),
        Spacer(1, 6 * mm),
    ]
    toc = _build_toc(document)
    if toc:
        story.append(Paragraph(t(MSG_PDF_TABLE_OF_CONTENTS), styles["A11yHeading1"]))
        for level, heading_title, heading_id in toc:
            indent = "&nbsp;" * (level - 1) * 4
            story.append(
                Paragraph(
                    f"{indent}<link href={quoteattr(f'#{heading_id}')}>"
                    f"{_escape_text(heading_title)}</link>",
                    styles["A11yBody"],
                )
            )
        story.append(PageBreak())
    for section in document.get("sections", []):
        _render_section(story, section, styles, profile_name)
    doc.build(story)
    return output_path


def _build_toc(document: dict[str, Any]) -> list[tuple[int, str, str]]:
    """Collects every titled section (including nested children) into table-of-contents entries.

    Args:
        document (dict): Canonical document mapping with a top-level "sections" list.

    Returns:
        list[tuple[int, str, str]]: (level, title, id) tuples in document order.
    """
    toc: list[tuple[int, str, str]] = []
    for section in document.get("sections", []):
        toc.extend(_section_toc(section))
    return toc


def _section_toc(section: dict[str, Any]) -> list[tuple[int, str, str]]:
    """Gathers the toc entry for one section and recurses into its nested children.

    Args:
        section (dict): Canonical section mapping with optional "title", "level", "id" and "children".

    Returns:
        list[tuple[int, str, str]]: Titled (level, title, id) entries for this section and its children.
    """
    entries = []
    if section.get("title"):
        entries.append(
            (section.get("level", 1), section["title"], section.get("id", ""))
        )
    for child in section.get("children", []):
        entries.extend(_section_toc(child))
    return entries


def _render_section(story, section: dict[str, Any], styles, profile_name: str) -> None:
    """Appends the section title heading and its profile-filtered blocks (and nested children) to the story.

    Args:
        story (list): The platypus story flowable list being built (mutated in place).
        section (dict): Canonical section mapping with optional "title", "id", "level", "blocks", "children".
        styles (dict): The ParagraphStyle mapping for this document.
        profile_name (str): Export verbosity profile applied to the section's block filtering.
    """
    if section.get("title"):
        style_name = {1: "A11yHeading1", 2: "Heading2"}.get(
            section.get("level", 1), "A11yHeading2"
        )
        paragraph = Paragraph(
            f'<a name={quoteattr(str(section.get("id", "")))}/>'
            f'{_escape_text(section["title"])}',
            styles[style_name],
        )
        paragraph._heading_id = section.get("id", "")
        paragraph._heading_level = section.get("level", 1)
        story.append(paragraph)
    for block in filter_blocks_for_profile(section.get("blocks", []), profile_name):
        _render_block(story, block, styles)
    for child in section.get("children", []):
        _render_section(story, child, styles, profile_name)


def _render_block(story, block: dict[str, Any], styles) -> None:
    """Appends the PDF flowables for a single canonical block, choosing markup by block type.

    Args:
        story (list): The platypus story flowable list being built (mutated in place).
        block (dict): Canonical block mapping with at least "type" and the type-specific payload.
        styles (dict): The ParagraphStyle mapping for this document.
    """
    block_type = block.get("type")
    if block_type == "heading":
        paragraph = Paragraph(
            f'<a name={quoteattr(str(block.get("id", "")))}/>'
            f'{_escape_text(block.get("title", block.get("text", "")))}',
            styles["A11yHeading2"],
        )
        paragraph._heading_id = block.get("id", "")
        paragraph._heading_level = block.get("level", 1)
        story.append(paragraph)
    elif block_type == "paragraph":
        story.append(Paragraph(_escape_text(block.get("text", "")), styles["A11yBody"]))
    elif block_type == "code":
        code_text = normalize_code_text(block.get("text", ""))
        story.append(
            Preformatted(_escape_text(code_text), styles["A11yCode"], dedent=False)
        )
    elif block_type == "list":
        items = [
            Paragraph(_escape_text(item), styles["A11yBody"])
            for item in block.get("items", [])
        ]
        story.append(
            ListFlowable(items, bulletType="1" if block.get("ordered") else "bullet")
        )
    elif block_type == "table":
        for line in linearize_table_for_text(block):
            story.append(Paragraph(_escape_text(line), styles["A11yBody"]))
    elif block_type in {"details", "note", "warning", "quote", "image", "math"}:
        text = (
            block.get("long_description")
            or block.get("alt_text")
            or block.get("text", "")
        )
        if block_type in {"note", "warning"}:
            label = t(MSG_PDF_WARNING_LABEL) if block_type == "warning" else t(MSG_PDF_NOTE_LABEL)
            if text:
                story.append(
                    Paragraph(
                        f"<b>{label}:</b> {_escape_text(text)}",
                        styles["A11yBody"],
                    )
                )
            else:
                story.append(Paragraph(f"<b>{label}</b>", styles["A11yBody"]))
        else:
            story.append(Paragraph(_escape_text(text), styles["A11yBody"]))
    else:
        text = block.get("text", "")
        if _looks_like_code_text(text):
            story.append(
                Preformatted(
                    _escape_text(normalize_code_text(text)),
                    styles["A11yCode"],
                    dedent=False,
                )
            )
        else:
            story.append(Paragraph(_escape_text(text), styles["A11yBody"]))


def _looks_like_code_text(text: str) -> bool:
    """Heuristically decides whether a string of text is likely source code rather than prose.

    Args:
        text (str): The block text to inspect.

    Returns:
        bool: True when the text is long enough (or multi-line with 90+ chars) and scores >= 2
        Java-like tokens together with at least one code punctuation mark; False otherwise.
    """
    if not isinstance(text, str) or not text.strip():
        return False
    if "\n" not in text and len(text) < 90:
        return False
    java_tokens = (
        "class ",
        "public ",
        "private ",
        "protected ",
        "return ",
        "if (",
        "else",
    )
    score = sum(1 for token in java_tokens if token in text)
    has_code_marks = bool(re.search(r"[{};()]", text))
    return score >= 2 and has_code_marks
