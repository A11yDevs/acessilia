"""docstruct — núcleo puro de processamento estrutural de documentos.

API pública estável. Tudo que não está aqui (``_internal``) pode mudar
sem aviso. A lib não depende do backend Acessilia nem de I/O externo.
"""

__version__ = "0.5.3"

from docstruct.geometry import content_fingerprint, merge_bboxes, overlaps_clean, union
from docstruct.policy import FusionPolicy
from docstruct.types import (
    BBox,
    BlockPairing,
    CanonicalBlock,
    OrientationResult,
    Region,
)

# Deprecated since 0.5.3; compatibility reexports retain their original classes.
# New code uses canonical.build_canonical_document and schemas.accessible_document_schema.
from docstruct.types import CanonicalDocument, CanonicalSection

__all__ = [
    "BBox",
    "BlockPairing",
    "CanonicalBlock",
    "CanonicalDocument",
    "CanonicalSection",
    "FusionPolicy",
    "OrientationResult",
    "Region",
    "content_fingerprint",
    "merge_bboxes",
    "overlaps_clean",
    "union",
    "__version__",
]
