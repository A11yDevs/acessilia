from __future__ import annotations

from pathlib import Path
from typing import Any

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

from pipeline.verbosity_manager import filter_blocks_for_profile


class _DocTemplate(SimpleDocTemplate):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._outline = []
        self._last_outline_level = -1

    def afterFlowable(self, flowable):
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
        target = max(int(raw_level), 0)
        if self._last_outline_level < 0:
            # ReportLab exige que a primeira entrada comece no nível 0.
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
    doc = _DocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=title or document.get("title", "Documento acessível"),
        author="a11y-devs-describer",
    )
    story = [
        Paragraph(
            title or document.get("title", "Documento acessível"), styles["A11yTitle"]
        ),
        Spacer(1, 6 * mm),
    ]
    toc = _build_toc(document)
    if toc:
        story.append(Paragraph("Sumario", styles["A11yHeading1"]))
        for level, heading_title, heading_id in toc:
            indent = "&nbsp;" * (level - 1) * 4
            story.append(
                Paragraph(
                    f'{indent}<link href="#{heading_id}">{heading_title}</link>',
                    styles["A11yBody"],
                )
            )
        story.append(PageBreak())
    for section in document.get("sections", []):
        _render_section(story, section, styles, profile_name)
    doc.build(story)
    return output_path


def _build_toc(document: dict[str, Any]) -> list[tuple[int, str, str]]:
    toc: list[tuple[int, str, str]] = []
    for section in document.get("sections", []):
        toc.extend(_section_toc(section))
    return toc


def _section_toc(section: dict[str, Any]) -> list[tuple[int, str, str]]:
    entries = []
    if section.get("title"):
        entries.append(
            (section.get("level", 1), section["title"], section.get("id", ""))
        )
    for child in section.get("children", []):
        entries.extend(_section_toc(child))
    return entries


def _render_section(story, section: dict[str, Any], styles, profile_name: str) -> None:
    if section.get("title"):
        style_name = {1: "A11yHeading1", 2: "Heading2"}.get(
            section.get("level", 1), "A11yHeading2"
        )
        paragraph = Paragraph(
            f'<a name="{section.get("id", "")}"/>{section["title"]}', styles[style_name]
        )
        paragraph._heading_id = section.get("id", "")
        paragraph._heading_level = section.get("level", 1)
        story.append(paragraph)
    for block in filter_blocks_for_profile(section.get("blocks", []), profile_name):
        _render_block(story, block, styles)
    for child in section.get("children", []):
        _render_section(story, child, styles, profile_name)


def _render_block(story, block: dict[str, Any], styles) -> None:
    block_type = block.get("type")
    if block_type == "heading":
        paragraph = Paragraph(
            f'<a name="{block.get("id", "")}"/>{block.get("title", block.get("text", ""))}',
            styles["A11yHeading2"],
        )
        paragraph._heading_id = block.get("id", "")
        paragraph._heading_level = block.get("level", 1)
        story.append(paragraph)
    elif block_type == "paragraph":
        story.append(Paragraph(block.get("text", ""), styles["A11yBody"]))
    elif block_type == "code":
        story.append(
            Preformatted(block.get("text", ""), styles["A11yBody"], dedent=False)
        )
    elif block_type == "list":
        items = [
            Paragraph(str(item), styles["A11yBody"]) for item in block.get("items", [])
        ]
        story.append(
            ListFlowable(items, bulletType="1" if block.get("ordered") else "bullet")
        )
    elif block_type == "table":
        for row in block.get("rows", []):
            story.append(
                Paragraph(" | ".join(str(cell) for cell in row), styles["A11yBody"])
            )
    elif block_type in {"details", "note", "warning", "quote", "image", "math"}:
        text = (
            block.get("long_description")
            or block.get("alt_text")
            or block.get("text", "")
        )
        story.append(Paragraph(text, styles["A11yBody"]))
    else:
        story.append(Paragraph(block.get("text", ""), styles["A11yBody"]))
