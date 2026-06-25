from __future__ import annotations

from copy import deepcopy

from pipeline.verbosity_manager import filter_blocks_for_profile


def strip_internal_audit_blocks(document: dict, profile_name: str) -> dict:
    filtered = deepcopy(document)
    filtered["sections"] = _filter_sections(filtered.get("sections", []), profile_name)
    return filtered


def apply_output_profile_filter(blocks: list[dict], profile_name: str) -> list[dict]:
    return filter_blocks_for_profile(blocks, profile_name)


def _filter_sections(sections: list[dict], profile_name: str) -> list[dict]:
    result: list[dict] = []
    for section in sections:
        new_section = deepcopy(section)
        new_section["blocks"] = filter_blocks_for_profile(
            section.get("blocks", []), profile_name
        )
        new_section["children"] = _filter_sections(
            section.get("children", []), profile_name
        )
        result.append(new_section)
    return result
