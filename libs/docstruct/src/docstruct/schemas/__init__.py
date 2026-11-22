"""Bundled canonical schemas, owned by docstruct (ADR-0004)."""

import json
from importlib.resources import files
from typing import Any

__all__ = ["accessible_document_schema"]


def accessible_document_schema() -> dict[str, Any]:
    """Return a fresh copy of the bundled accessible-document JSON Schema.

    Only the installed package resource is read; no checkout path, caller file
    or remote schema is consulted. Mutating the result cannot change later calls.
    """
    resource = files(__package__).joinpath("accessible_document.schema.json")
    return json.loads(resource.read_text(encoding="utf-8"))
