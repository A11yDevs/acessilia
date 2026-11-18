"""Regenerate or check the root copy of docstruct's accessible-document schema.

Run with the repository's locked environment. The package resource is normative;
schemas/accessible_document.schema.json remains a byte-identical compatibility
copy for tools that read the historical path.
"""

from __future__ import annotations

import argparse
from importlib.resources import files
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if the root copy differs; do not write.")
    args = parser.parse_args()
    source = files("docstruct.schemas").joinpath("accessible_document.schema.json").read_bytes()
    target = Path(__file__).resolve().parents[1] / "schemas/accessible_document.schema.json"
    if args.check:
        if not target.is_file() or target.read_bytes() != source:
            parser.exit(1, "Root schema differs; run uv run python scripts/sync_accessible_document_schema.py\n")
    else:
        target.write_bytes(source)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
