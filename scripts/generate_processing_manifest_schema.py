#!/usr/bin/env python3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.core.manifest.schema import write_processing_manifest_schema


if __name__ == "__main__":
    path = write_processing_manifest_schema(
        ROOT / "schemas" / "processing_manifest.schema.json"
    )
    print(path)
