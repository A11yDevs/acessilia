"""Bound output names while keeping the original upload name for display."""

import hashlib
from pathlib import Path


# Leaves room for export suffixes, including .pdf_ua.verapdf.json, within
# the common 255-byte filesystem component limit. Count bytes for Unicode.
MAX_OUTPUT_STEM_BYTES = 160


def output_stem(filename: str) -> str:
    """Return a stable, bounded stem for a document's output files.

    Args:
        filename (str): Original document filename, including its extension.

    Returns:
        str: The original stem if short enough, otherwise a UTF-8 byte-limited
            prefix and digest. An empty shortened prefix becomes "document".
    """
    stem = Path(filename).stem
    encoded = stem.encode("utf-8")
    if len(encoded) <= MAX_OUTPUT_STEM_BYTES:
        return stem
    digest = hashlib.sha256(encoded).hexdigest()[:16]
    prefix = encoded[:MAX_OUTPUT_STEM_BYTES - len(digest) - 1]
    # A byte boundary may fall inside a Unicode character.
    shortened = prefix.decode("utf-8", errors="ignore").rstrip(" .")
    shortened = shortened or "document"
    return f"{shortened}-{digest}"
