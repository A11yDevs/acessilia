"""Explicit selections for the two published layout variants, never a union compiler."""

import json
from pathlib import Path


def render_layout(factory, directory: Path) -> str:
    schema = json.loads((directory / "layout-analysis@1.json").read_text())
    if (
        schema["type"] != "object"
        or schema["anyOf"]
        != [{"$ref": "#/$defs/LayoutPages"}, {"$ref": "#/$defs/MineruLayoutResult"}]
        or set(schema)
        - {
            "$schema",
            "$id",
            "$comment",
            "title",
            "description",
            "type",
            "anyOf",
            "$defs",
        }
    ):
        raise ValueError("unsupported layout root; review the complete published union")
    expected = {
        "allOf": [
            {"$ref": "#/$defs/ProcessingManifest"},
            {
                "properties": {
                    "extractor": {
                        "required": ["configuration"],
                        "properties": {
                            "configuration": {
                                "$ref": "#/$defs/MineruLayoutConfiguration"
                            }
                        },
                    }
                }
            },
        ]
    }
    if schema["$defs"]["MineruLayoutResult"] != expected:
        raise ValueError(
            "unsupported MinerU branch; containing constraints must be reviewed"
        )
    structured = json.loads((directory / "structured-document@1.json").read_text())
    if {
        k: v
        for k, v in structured.items()
        if k not in ("$schema", "$id", "$defs", "description")
    } != schema["$defs"]["ProcessingManifest"]:
        raise ValueError("layout manifest and published structured document disagree")
    if any(schema["$defs"][key] != value for key, value in structured["$defs"].items()):
        raise ValueError("layout and structure manifest definitions disagree")
    operational = factory(plain_definitions=("LayoutClassificationBox",))
    for definition in ("LayoutPages", "MineruLayoutConfiguration"):
        operational.compile(schema, definition, definition=definition)
    # Compile validation data, not competing canonical SDK classes. The adapter
    # below constructs docstruct's existing document and geometry types.
    wire = factory(emit_models=False, nullable_branches=True)
    rule = wire.compile(structured, "ProcessingManifest")
    assert not wire.classes
    return (
        operational.render("layout-analysis@1.json; scripts/generate_sdk_bindings.py")
        + "\nMANIFEST_RULE = "
        + repr(rule)
        + "\n"
    )
