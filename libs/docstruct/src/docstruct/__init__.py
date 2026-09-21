"""docstruct — núcleo puro de processamento estrutural de documentos.

API pública estável. Tudo que não está aqui (``_internal``) pode mudar
sem aviso. A lib não depende do backend Acessilia nem de I/O externo.
"""

__version__ = "0.1.0"

from docstruct.geometry import content_fingerprint, merge_bboxes, overlaps_clean, union
from docstruct.policy import FusionPolicy
from docstruct.types import (
    BBox,
    BlockPairing,
    CanonicalBlock,
    CanonicalDocument,
    CanonicalSection,
    OrientationResult,
    Region,
)

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
