from __future__ import annotations

from copy import deepcopy

OUTPUT_PROFILES = {
    "html": {
        "verbosity": ["basic", "detailed", "technical"],
        "interactive": True,
        "collapsible": True,
        "include_audit": False,
    },
    "pdf": {
        "verbosity": ["basic", "detailed"],
        "interactive": False,
        "collapsible": False,
        "include_audit": False,
    },
    "docx": {
        "verbosity": ["basic", "detailed"],
        "interactive": False,
        "collapsible": False,
        "include_audit": False,
    },
    "txt": {
        "verbosity": ["basic"],
        "interactive": False,
        "collapsible": False,
        "include_audit": False,
    },
}

MODE_TO_VERBOSITY = {
    "normal": "detailed",
    "medio": "detailed",
    "detalhado": "technical",
    "baixo": "basic",
    "ocr": "detailed",
}


def normalize_profile(profile_name: str) -> dict:
    return deepcopy(OUTPUT_PROFILES.get(profile_name, OUTPUT_PROFILES["txt"]))


def verbosity_for_mode(mode: str) -> str:
    return MODE_TO_VERBOSITY.get(mode, "detailed")


def filter_blocks_for_profile(
    blocks: list[dict],
    profile_name: str,
) -> list[dict]:
    allowed = set(normalize_profile(profile_name)["verbosity"])
    return [block for block in blocks if block.get("verbosity", "basic") in allowed]
