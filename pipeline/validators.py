from __future__ import annotations

import re
from typing import Any

from pipeline.sanitizer import contains_markdown_artifacts
from pipeline.sanitizer import contains_prompt_leak
from pipeline.verbosity_manager import OUTPUT_PROFILES


def validate_canonical_document(document: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(document, dict):
        return ["Documento canônico deve ser um objeto JSON."]
    for field in ["schema_version", "id", "title", "language", "sections"]:
        if field not in document:
            errors.append(f"Campo obrigatório ausente: {field}")
    if not isinstance(document.get("sections"), list):
        errors.append("Campo sections deve ser uma lista.")
        return errors

    ids: set[str] = set()
    headings: list[int] = []
    internal_links: list[str] = []

    def walk_blocks(blocks: list[dict[str, Any]]) -> None:
        for block in blocks:
            block_id = block.get("id")
            if block_id:
                if block_id in ids:
                    errors.append(f"ID interno duplicado: {block_id}")
                ids.add(block_id)
            if block.get("type") == "heading":
                headings.append(int(block.get("level", 1)))
            if block.get("type") == "paragraph":
                text = block.get("text", "")
                if contains_prompt_leak(text):
                    errors.append(
                        f"Possivel vazamento de prompt em {block_id}"
                    )
                if contains_markdown_artifacts(text):
                    errors.append(f"Markdown indevido em {block_id}")
            if block.get("type") == "code":
                code_text = block.get("text", "")
                if _indentation_lost(code_text):
                    errors.append(
                        f"Indentacao de codigo inconsistente em {block_id}"
                    )
            if block.get("type") == "table" and not block.get("rows"):
                errors.append(f"Tabela vazia em {block_id}")
            internal_links.extend(_extract_internal_links(block))

    for section in document.get("sections", []):
        walk_blocks(section.get("blocks", []))
        _walk_sections(section.get("children", []), walk_blocks)

    if headings.count(1) > 1:
        errors.append("O documento deve ter apenas um H1 principal.")
    if headings and headings[0] != 1:
        errors.append("O documento deve começar com um H1 principal.")
    if _heading_skips_levels(headings):
        errors.append("Hierarquia de headings salta niveis indevidamente.")
    for link in internal_links:
        if link not in ids:
            errors.append(f"Link interno aponta para ID inexistente: {link}")
    return errors


def validate_export_profile(
    profile_name: str,
    document: dict[str, Any],
) -> list[str]:
    profile = OUTPUT_PROFILES.get(profile_name)
    if not profile:
        return [f"Perfil de exportacao desconhecido: {profile_name}"]
    allowed = set(profile["verbosity"])
    errors: list[str] = []

    def walk(blocks: list[dict[str, Any]]) -> None:
        for block in blocks:
            if block.get("verbosity", "basic") not in allowed:
                errors.append(
                    f"Bloco {block.get('id')} nao permitido no perfil "
                    f"{profile_name}"
                )
            for child in block.get("children", []) or []:
                if isinstance(child, dict):
                    walk([child])

    for section in document.get("sections", []):
        walk(section.get("blocks", []))
        _walk_sections(section.get("children", []), walk)
    return errors


def validate_output_text(text: str, profile_name: str) -> list[str]:
    errors: list[str] = []
    if contains_prompt_leak(text):
        errors.append("Possivel vazamento de prompt na saida final.")
    if profile_name != "html" and contains_markdown_artifacts(text):
        errors.append("Markdown indevido na saida final.")
    if profile_name == "txt" and re.search(
        r"\[\s*IN[IÍ]CIO DA AUDIODESCRI[CÇ][AÃ]O\s*\]",
        text,
        re.I,
    ):
        errors.append("Metadados tecnicos nao devem aparecer no TXT.")
    return errors


def _walk_sections(sections: list[dict[str, Any]], callback) -> None:
    for section in sections:
        callback(section.get("blocks", []))
        _walk_sections(section.get("children", []), callback)


def _extract_internal_links(block: dict[str, Any]) -> list[str]:
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
    previous = 0
    for level in levels:
        if level > previous + 1:
            return True
        previous = level
    return False


def _indentation_lost(text: str) -> bool:
    lines = text.splitlines()
    if len(lines) <= 1:
        return False
    return not any(line.startswith((" ", "\t")) for line in lines)
