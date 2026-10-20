from __future__ import annotations

import hashlib
import json
from typing import Any


def json_sha256(payload: dict[str, Any]) -> str:
    """SHA-256 of ``payload`` in the core's canonical JSON serialization.

    The serialization is: keys sorted, no whitespace (``","`` and ``":"``
    separators), non-ASCII characters written as UTF-8 rather than escaped.
    The planner records this hash of the manifest it planned from, and the
    executor checks it before running the plan.

    It stays in the core (#203, D2): the core is its only consumer. If another
    component ever needs the same hash, this policy is documented first and
    then shared, so both sides hash the same bytes.
    """
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
