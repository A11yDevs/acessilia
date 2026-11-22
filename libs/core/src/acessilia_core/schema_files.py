"""Write the core's JSON Schema files with one stable formatting policy."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

__all__ = ["write_schema"]


def write_schema(schema: dict[str, Any], destination: Path) -> Path:
    """Write ``schema`` to ``destination`` as UTF-8 JSON, creating its parent."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return destination
