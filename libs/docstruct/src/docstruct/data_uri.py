"""Images carried inline in a document as ``data:`` URIs.

Pure: zero external dependencies, standard library only.

A DOCX or HTML source has no pages to render, so the only pixels of its
pictures are the ones the extraction embedded in them (``metadata["src"]``,
the key the exporters read for ``<img>``). ``decode_data_uri`` reads such a
URI; which media types and how many bytes to accept are the caller's policy.
A remote URL is never fetched.
"""
from __future__ import annotations

import base64
from collections.abc import Collection


def decode_data_uri(src: object, *, media_types: Collection[str], max_bytes: int) -> bytes | None:
    """The bytes of a base64 ``data:`` URI of one of ``media_types``, or ``None``.

    The ``data:`` prefix and the media type are read case-insensitively, and
    whitespace inside the payload is ignored. Anything else is ``None``: not a
    string, not a ``data:`` URI, another media type, a parameter other than
    ``base64``, invalid base64, an empty payload, or more than ``max_bytes``
    bytes (checked on the encoded length first, then on the decoded bytes).
    """
    if not isinstance(src, str):
        return None
    header, separator, payload = src.partition(",")
    if not separator:
        return None
    header = header.strip().lower()
    if not header.startswith("data:"):
        return None
    media_type, _, encoding = header[len("data:"):].partition(";")
    if media_type not in media_types or encoding != "base64":
        return None
    payload = "".join(payload.split())
    if len(payload) > (max_bytes * 4) // 3 + 4:
        return None
    try:
        image = base64.b64decode(payload, validate=True)
    except ValueError:  # binascii.Error
        return None
    # The length check above only bounds the encoded text; several decoded
    # sizes share one encoded length, so the bound is checked again here.
    if len(image) > max_bytes:
        return None
    return image or None


__all__ = ["decode_data_uri"]
