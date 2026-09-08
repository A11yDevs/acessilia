"""Structural validation for canonical documents, export profiles and final output text.

Every user-visible finding returned by the public validator functions is resolved through the active locale strings
files via :func:`backend.i18n.t`, with the canonical English msgid constants below acting as the single source of
truth consumed by scripts/gen_locale_catalogs for catalog generation.
"""

from __future__ import annotations

import re
from typing import Any

from backend.i18n import t
from backend.pipeline.sanitizer import contains_markdown_artifacts
from backend.pipeline.sanitizer import contains_prompt_leak
from backend.pipeline.verbosity_manager import OUTPUT_PROFILES

#: Canonical English msgid for a canonical document that is not a JSON object mapping.
MSG_CANONICAL_DOC_NOT_OBJECT: str = "Canonical document must be a JSON object."
#: Canonical English msgid template for a missing required canonical-document field; {field} is substituted by callers after lookup.
MSG_FIELD_MISSING: str = "Required field missing: {field}"
#: Canonical English msgid for a sections field that is not a list.
MSG_SECTIONS_NOT_LIST: str = "The sections field must be a list."
#: Canonical English msgid template for a duplicated internal block/section id; {block_id} is substituted by callers after lookup.
MSG_DUPLICATE_ID: str = "Duplicate internal id: {block_id}"
#: Canonical English msgid template for a suspected prompt leak inside a paragraph block; {block_id} is substituted by callers after lookup.
MSG_PROMPT_LEAK_IN_BLOCK: str = "Possible prompt leak in {block_id}"
#: Canonical English msgid template for markdown artifacts found inside a paragraph block; {block_id} is substituted by callers after lookup.
MSG_MARKDOWN_IN_BLOCK: str = "Improper markdown in {block_id}"
#: Canonical English msgid template for lost code indentation inside a code block; {block_id} is substituted by callers after lookup.
MSG_INCONSISTENT_CODE_INDENT: str = "Inconsistent code indentation in {block_id}"
#: Canonical English msgid for a document containing more than one top-level H1 heading.
MSG_MULTIPLE_H1: str = "The document must have only one main H1 heading."
#: Canonical English msgid for a document whose first heading is not an H1.
MSG_MISSING_FIRST_H1: str = "The document must start with a main H1 heading."
#: Canonical English msgid for a heading hierarchy that skips levels (e.g., H1 to H3).
MSG_HEADING_LEVELS_SKIPPED: str = "Heading hierarchy skips levels improperly."
#: Canonical English msgid template for an internal link pointing at a nonexistent id; {link} is substituted by callers after lookup.
MSG_INTERNAL_LINK_BROKEN: str = "Internal link points to a nonexistent id: {link}"
#: Canonical English msgid template for an export profile the runtime does not recognize; {profile_name} is substituted by callers after lookup.
MSG_UNKNOWN_EXPORT_PROFILE: str = "Unknown export profile: {profile_name}"
#: Canonical English msgid template for a block whose verbosity is not allowed by the active export profile; {block_id}/{profile_name} are substituted by callers after lookup.
MSG_BLOCK_NOT_ALLOWED_IN_PROFILE: str = "Block {block_id} not allowed in profile {profile_name}"
#: Canonical English msgid for a prompt leak detected in the final exported output text.
MSG_PROMPT_LEAK_IN_OUTPUT: str = "Possible prompt leak in the final output."
#: Canonical English msgid for markdown artifacts detected in a non-HTML final output.
MSG_MARKDOWN_IN_OUTPUT: str = "Improper markdown in the final output."
#: Canonical English msgid for technical audiodescription metadata leaking into a TXT export.
MSG_TECHNICAL_METADATA_IN_TXT: str = "Technical metadata must not appear in TXT."
#: Canonical English msgid template for an image block lacking alt text; {block_id} is substituted by callers after lookup.
MSG_IMAGE_MISSING_ALT: str = "Image {block_id} has no alt-text."
#: Canonical English msgid template for a multi-row table lacking an explicit header; {table_id} is substituted by callers after lookup.
MSG_TABLE_MISSING_HEADER: str = "Table {table_id} has no explicit header; review header inference."
#: Canonical English msgid template for a table lacking a table_ast and falling back to legacy row handling; {table_id} is substituted by callers after lookup.
MSG_TABLE_LEGACY_FALLBACK: str = "Table {table_id} has no table_ast; using legacy row fallback."
#: Canonical English msgid for a document that has no sections at all.
MSG_DOCUMENT_NO_SECTIONS: str = "Document has no sections."
#: Placeholder id label used in validator messages when a block has no id of its own.
MSG_NO_ID_PLACEHOLDER: str = "(no-id)"
#: Canonical English msgid template for a table block carrying neither rows nor a table_ast; {block_id} is substituted by callers after lookup.
MSG_TABLE_EMPTY: str = "Empty table in {block_id}"
#: Canonical English msgid template for a table whose rows field is not a non-empty list; {block_id} is substituted by callers after lookup.
MSG_TABLE_ROWS_INVALID: str = "Table with invalid rows in {block_id}"
#: Canonical English msgid template for a table row that is not a non-empty list; {block_id}/{row_index} are substituted by callers after lookup.
MSG_TABLE_ROW_INVALID: str = "Table with invalid row in {block_id} (row {row_index})"
#: Canonical English msgid template for a table row whose column count differs from the first row; {block_id}/{row_index} are substituted by callers after lookup.
MSG_TABLE_COLUMNS_INCONSISTENT: str = "Table with inconsistent columns in {block_id} (row {row_index})"
#: Canonical English msgid template for a table cell that is not a text string; {block_id}/{row_index}/{col_index} are substituted by callers after lookup.
MSG_TABLE_CELL_NOT_TEXT: str = "Table with non-textual cell in {block_id} (row {row_index}, col {col_index})"
#: Canonical English msgid template for a table cell that is blank; {block_id}/{row_index}/{col_index} are substituted by callers after lookup.
MSG_TABLE_CELL_EMPTY: str = "Table with empty cell in {block_id} (row {row_index}, col {col_index})"
#: Canonical English msgid template for a table_ast value that is not a mapping; {block_id} is substituted by callers after lookup.
MSG_TABLE_AST_INVALID: str = "Invalid table_ast in {block_id}"
#: Canonical English msgid template for a table_ast lacking a non-empty body list; {block_id} is substituted by callers after lookup.
MSG_TABLE_AST_NO_BODY: str = "table_ast without body in {block_id}"
#: Canonical English msgid template for a table_ast section that is not a list; {section_name}/{block_id} are substituted by callers after lookup.
MSG_TABLE_AST_SECTION_INVALID: str = "table_ast.{section_name} invalid in {block_id}"
#: Canonical English msgid template for a table_ast section row that is not a mapping; {section_name}/{row_index}/{block_id} are substituted by callers after lookup.
MSG_TABLE_AST_ROW_INVALID: str = "table_ast.{section_name}[{row_index}] invalid in {block_id}"
#: Canonical English msgid template for a table_ast row lacking a non-empty cells list; {section_name}/{row_index}/{block_id} are substituted by callers after lookup.
MSG_TABLE_AST_ROW_NO_CELLS: str = "table_ast.{section_name}[{row_index}] without cells in {block_id}"
#: Canonical English msgid template for a table_ast cell that is not a mapping; {section_name}/{block_id}/row:col coordinates are substituted by callers after lookup.
MSG_TABLE_AST_CELL_INVALID: str = "table_ast invalid cell in {block_id} ({section_name} {row_index}:{col_index})"
#: Canonical English msgid template for a table_ast cell with missing or blank text; {section_name}/{block_id}/row:col coordinates are substituted by callers after lookup.
MSG_TABLE_AST_CELL_NO_TEXT: str = "table_ast cell without text in {block_id} ({section_name} {row_index}:{col_index})"
#: Canonical English msgid template for a table_ast section whose row widths differ; {section_name}/{block_id}/{row_index} are substituted by callers after lookup.
MSG_TABLE_AST_WIDTH_INCONSISTENT: str = "table_ast.{section_name} with inconsistent width in {block_id} (row {row_index})"


def validate_canonical_document(document: dict[str, Any]) -> list[str]:
    """Validate a canonical document structure and collect localized error messages.

    Args:
        document (dict): Canonical document mapping expected to carry the schema_version, id, title, language and sections keys.

    Returns:
        list[str]: Localized error strings describing every structural problem found; empty when the document is well-formed.
    """
    errors: list[str] = []
    if not isinstance(document, dict):
        return [t(MSG_CANONICAL_DOC_NOT_OBJECT)]
    for field in ["schema_version", "id", "title", "language", "sections"]:
        if field not in document:
            errors.append(t(MSG_FIELD_MISSING).format(field=field))
    if not isinstance(document.get("sections"), list):
        errors.append(t(MSG_SECTIONS_NOT_LIST))
        return errors

    ids: set[str] = set()
    headings: list[int] = []
    internal_links: list[str] = []

    def walk_blocks(blocks: list[dict[str, Any]]) -> None:
        for block in blocks:
            block_id = block.get("id")
            if block_id:
                if block_id in ids:
                    errors.append(t(MSG_DUPLICATE_ID).format(block_id=block_id))
                ids.add(block_id)
            if block.get("type") == "heading":
                headings.append(int(block.get("level", 1)))
            if block.get("type") == "paragraph":
                text = block.get("text", "")
                if contains_prompt_leak(text):
                    errors.append(
                        t(MSG_PROMPT_LEAK_IN_BLOCK).format(block_id=block_id)
                    )
                if contains_markdown_artifacts(text):
                    errors.append(
                        t(MSG_MARKDOWN_IN_BLOCK).format(block_id=block_id)
                    )
            if block.get("type") == "code":
                code_text = block.get("text", "")
                if _indentation_lost(code_text):
                    errors.append(
                        t(MSG_INCONSISTENT_CODE_INDENT).format(block_id=block_id)
                    )
            if block.get("type") == "table":
                errors.extend(_validate_table_block(block))
            internal_links.extend(_extract_internal_links(block))

    for section in document.get("sections", []):
        walk_blocks(section.get("blocks", []))
        _walk_sections(section.get("children", []), walk_blocks)

    if headings.count(1) > 1:
        errors.append(t(MSG_MULTIPLE_H1))
    if headings and headings[0] != 1:
        errors.append(t(MSG_MISSING_FIRST_H1))
    if _heading_skips_levels(headings):
        errors.append(t(MSG_HEADING_LEVELS_SKIPPED))
    for link in internal_links:
        if link not in ids:
            errors.append(t(MSG_INTERNAL_LINK_BROKEN).format(link=link))
    return errors


def validate_export_profile(
    profile_name: str,
    document: dict[str, Any],
) -> list[str]:
    """Check that every block's verbosity is allowed by the named export profile.

    Args:
        profile_name (str): Export profile key looked up in OUTPUT_PROFILES (e.g., "txt", "html", "pdf").
        document (dict): Canonical document mapping whose section blocks are walked for verbosity compliance.

    Returns:
        list[str]: Localized error strings for blocks whose verbosity the profile forbids; empty when all blocks comply.
    """
    profile = OUTPUT_PROFILES.get(profile_name)
    if not profile:
        return [t(MSG_UNKNOWN_EXPORT_PROFILE).format(profile_name=profile_name)]
    allowed = set(profile["verbosity"])
    errors: list[str] = []

    def walk(blocks: list[dict[str, Any]]) -> None:
        for block in blocks:
            if block.get("verbosity", "basic") not in allowed:
                errors.append(
                    t(MSG_BLOCK_NOT_ALLOWED_IN_PROFILE).format(
                        block_id=block.get("id"),
                        profile_name=profile_name,
                    )
                )
            for child in block.get("children", []) or []:
                if isinstance(child, dict):
                    walk([child])

    for section in document.get("sections", []):
        walk(section.get("blocks", []))
        _walk_sections(section.get("children", []), walk)
    return errors


def validate_output_text(text: str, profile_name: str) -> list[str]:
    """Scan the final exported text for prompt leaks, stray markdown and technical metadata.

    Args:
        text (str): Exported output text to scan.
        profile_name (str): Export profile the text was produced for; only non-html profiles are scanned for markdown and only "txt" is scanned for audiodescription metadata leaks.

    Returns:
        list[str]: Localized error strings for each forbidden artifact found; empty when the text is clean.
    """
    errors: list[str] = []
    if contains_prompt_leak(text):
        errors.append(t(MSG_PROMPT_LEAK_IN_OUTPUT))
    if profile_name != "html" and contains_markdown_artifacts(text):
        errors.append(t(MSG_MARKDOWN_IN_OUTPUT))
    if profile_name == "txt" and re.search(
        r"\[\s*IN[IÍ]CIO DA AUDIODESCRI[CÇ][AÃ]O\s*\]",
        text,
        re.I,
    ):
        errors.append(t(MSG_TECHNICAL_METADATA_IN_TXT))
    return errors


def audit_canonical_document(document: dict[str, Any]) -> dict[str, list[str]]:
    """Perform a detailed structural audit separating findings into severity levels.

    Args:
        document (dict): Canonical document mapping to audit; must be a dict for base validation and section walking.

    Returns:
        dict[str, list[str]]: Report with "BLOCKER" (structural failures from base validation plus missing sections) and "WARNING" (accessibility findings such as images without alt text and tables without explicit AST headers) keys.
    """
    report = {"BLOCKER": [], "WARNING": []}

    # Base validation (original logic kept as BLOCKER severity).
    base_errors = validate_canonical_document(document)
    if base_errors:
        report["BLOCKER"].extend(base_errors)

    # Accessibility audit (additional WARNING-severity findings).
    sections = document.get("sections", [])
    if not sections:
        report["BLOCKER"].append(t(MSG_DOCUMENT_NO_SECTIONS))

    # Check whether images carry alt text (when the schema supports it).
    def check_accessibility(blocks: list[dict[str, Any]]) -> None:
        for block in blocks:
            if block.get("type") == "image" and not block.get("metadata", {}).get(
                "alt"
            ):
                report["WARNING"].append(
                    t(MSG_IMAGE_MISSING_ALT).format(block_id=block.get("id"))
                )
            if block.get("type") == "table":
                table_id = block.get("id") or t(MSG_NO_ID_PLACEHOLDER)
                table_ast = block.get("table_ast")
                if isinstance(table_ast, dict):
                    header = table_ast.get("header")
                    body = table_ast.get("body")
                    if (not isinstance(header, list) or not header) and isinstance(body, list) and len(body) > 1:
                        report["WARNING"].append(
                            t(MSG_TABLE_MISSING_HEADER).format(table_id=table_id)
                        )
                elif block.get("rows"):
                    rows = block.get("rows")
                    if isinstance(rows, list) and len(rows) > 1:
                        report["WARNING"].append(
                            t(MSG_TABLE_LEGACY_FALLBACK).format(table_id=table_id)
                        )

    for section in sections:
        check_accessibility(section.get("blocks", []))
        _walk_sections(section.get("children", []), check_accessibility)

    return report


def _walk_sections(sections: list[dict[str, Any]], callback) -> None:
    """Recursively run a callback over every section's blocks, descending into nested child sections.

    Args:
        sections (list): List of section mappings each carrying a "blocks" list and optional "children" section list.
        callback (callable): Function invoked with each section's block list so the caller can inspect or count blocks.
    """
    for section in sections:
        callback(section.get("blocks", []))
        _walk_sections(section.get("children", []), callback)


def _extract_internal_links(block: dict[str, Any]) -> list[str]:
    """Collect internal fragment links ("#id") referenced from a block's metadata.

    Args:
        block (dict): Block mapping whose optional "metadata" mapping may hold fragment link strings directly or inside nested lists.

    Returns:
        list[str]: Target ids (leading '#' stripped) referenced by metadata fragment links; empty when the block holds none.
    """
    links: list[str] = []
    metadata = block.get("metadata", {})
    if isinstance(metadata, dict):
        for value in metadata.values():
            if isinstance(value, str) and value.startswith("#"):
                links.append(value[1:])
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, str) and item.startswith("#"):
                        links.append(item[1:])
    return links


def _heading_skips_levels(levels: list[int]) -> bool:
    """Report whether a heading level sequence jumps more than one level at a time.

    Args:
        levels (list[int]): Ordered heading levels as found while walking the document (e.g. [1, 3] skips level 2).

    Returns:
        bool: True when any heading level is more than one greater than the previous level, False otherwise.
    """
    previous = 0
    for level in levels:
        if level > previous + 1:
            return True
        previous = level
    return False


def _indentation_lost(text: str) -> bool:
    """Detect code text whose interior lines lost their original indentation entirely.

    Args:
        text (str): Code block text whose non-blank lines are inspected for leading space or tab indentation.

    Returns:
        bool: True when more than one non-blank line exists but none of the interior content lines is indented; signature-only or single-line blocks are exempt.
    """
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) <= 1:
        return False

    # Do not require indentation when the block has only a signature and a
    # closing line, e.g. "public interface X {" + "}".
    candidate_lines: list[str] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if index == 0:
            continue
        if stripped in {"}", "};", "{"}:
            continue
        candidate_lines.append(line)

    if not candidate_lines:
        return False

    return not any(line.startswith((" ", "\t")) for line in candidate_lines)


def _validate_table_block(block: dict[str, Any]) -> list[str]:
    """Validate the rows or table_ast payload of a single table block.

    Args:
        block (dict): Table block mapping whose optional rows list and/or table_ast mapping are checked for structure, type and width consistency.

    Returns:
        list[str]: Localized error strings for every table structure problem found; empty when the table is well-formed.
    """
    errors: list[str] = []
    block_id = block.get("id") or t(MSG_NO_ID_PLACEHOLDER)

    rows = block.get("rows")
    table_ast = block.get("table_ast")

    if not rows and not table_ast:
        return [t(MSG_TABLE_EMPTY).format(block_id=block_id)]

    if rows is not None:
        if not isinstance(rows, list) or not rows:
            errors.append(t(MSG_TABLE_ROWS_INVALID).format(block_id=block_id))
        else:
            expected_columns: int | None = None
            for row_index, row in enumerate(rows):
                if not isinstance(row, list) or not row:
                    errors.append(
                        t(MSG_TABLE_ROW_INVALID).format(
                            block_id=block_id, row_index=row_index
                        )
                    )
                    continue
                if expected_columns is None:
                    expected_columns = len(row)
                elif len(row) != expected_columns:
                    errors.append(
                        t(MSG_TABLE_COLUMNS_INCONSISTENT).format(
                            block_id=block_id, row_index=row_index
                        )
                    )
                for col_index, cell in enumerate(row):
                    if not isinstance(cell, str):
                        errors.append(
                            t(MSG_TABLE_CELL_NOT_TEXT).format(
                                block_id=block_id,
                                row_index=row_index,
                                col_index=col_index,
                            )
                        )
                        continue
                    if not cell.strip():
                        errors.append(
                            t(MSG_TABLE_CELL_EMPTY).format(
                                block_id=block_id,
                                row_index=row_index,
                                col_index=col_index,
                            )
                        )

    if table_ast is not None:
        if not isinstance(table_ast, dict):
            errors.append(t(MSG_TABLE_AST_INVALID).format(block_id=block_id))
            return errors

        if not isinstance(table_ast.get("body"), list) or not table_ast.get("body"):
            errors.append(t(MSG_TABLE_AST_NO_BODY).format(block_id=block_id))

        for section_name in ("header", "body", "footer"):
            section = table_ast.get(section_name)
            if section is None:
                continue
            if not isinstance(section, list):
                errors.append(
                    t(MSG_TABLE_AST_SECTION_INVALID).format(
                        section_name=section_name, block_id=block_id
                    )
                )
                continue
            expected_width: int | None = None
            for row_index, row in enumerate(section):
                if not isinstance(row, dict):
                    errors.append(
                        t(MSG_TABLE_AST_ROW_INVALID).format(
                            section_name=section_name,
                            row_index=row_index,
                            block_id=block_id,
                        )
                    )
                    continue
                cells = row.get("cells")
                if not isinstance(cells, list) or not cells:
                    errors.append(
                        t(MSG_TABLE_AST_ROW_NO_CELLS).format(
                            section_name=section_name,
                            row_index=row_index,
                            block_id=block_id,
                        )
                    )
                    continue
                row_effective_width = 0
                for col_index, cell in enumerate(cells):
                    if not isinstance(cell, dict):
                        errors.append(
                            t(MSG_TABLE_AST_CELL_INVALID).format(
                                block_id=block_id,
                                section_name=section_name,
                                row_index=row_index,
                                col_index=col_index,
                            )
                        )
                        continue
                    text = cell.get("text")
                    if not isinstance(text, str) or not text.strip():
                        errors.append(
                            t(MSG_TABLE_AST_CELL_NO_TEXT).format(
                                block_id=block_id,
                                section_name=section_name,
                                row_index=row_index,
                                col_index=col_index,
                            )
                        )
                    colspan = cell.get("colspan")
                    if isinstance(colspan, int) and colspan >= 1:
                        row_effective_width += colspan
                    else:
                        row_effective_width += 1

                if expected_width is None:
                    expected_width = row_effective_width
                elif row_effective_width != expected_width:
                    errors.append(
                        t(MSG_TABLE_AST_WIDTH_INCONSISTENT).format(
                            section_name=section_name,
                            block_id=block_id,
                            row_index=row_index,
                        )
                    )

    return errors
