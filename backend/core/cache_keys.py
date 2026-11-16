"""Cache variants built from the options an answer depends on.

The core names what a cached answer depends on (a region description's
prompt, model and budget); the service names what a processed document
depends on. Both build the variant here, so the two keys share one format
(ADR-0016, step 4).
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def options_cache_key(prefix: str, **options: Any) -> str:
    """Build a filesystem-safe cache variant from output-affecting options."""
    serialized = json.dumps(
        options,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


__all__ = ["options_cache_key"]
