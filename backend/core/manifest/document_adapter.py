"""Convert between the core's manifest and docstruct's document model.

docstruct owns the document part of a manifest (``docstruct.manifest``); the
core's ``ProcessingManifest`` is the wire model that also carries the envelope
(``$schema``, version, ids, timestamps, summary), the origin (source,
extractor) and the process state (observations, obligations, artifacts).
These adapters go through the wire payload, so aliases, timestamps, enums
and defaults are handled exactly as the schema defines them.
"""

from __future__ import annotations

from backend.core.manifest.models import ProcessingManifest
from docstruct.manifest import (
    StructuredDocument,
    structured_document_from_payload,
    structured_document_to_payload,
)


def to_structured_document(manifest: ProcessingManifest) -> StructuredDocument:
    """The document part of ``manifest`` as docstruct types."""
    return structured_document_from_payload(manifest.model_dump(mode="json", by_alias=True))


def with_structured_document(
    manifest: ProcessingManifest, document: StructuredDocument
) -> ProcessingManifest:
    """A new manifest: ``manifest``'s envelope, origin and process with ``document``.

    The result is validated as a whole, so a document whose pages or elements
    no longer match the summary counts or the obligations' targets is refused.
    """
    payload = manifest.model_dump(mode="json", by_alias=True)
    payload.update(structured_document_to_payload(document))
    return ProcessingManifest.model_validate(payload)
