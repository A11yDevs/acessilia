"""Per-capability Toolbox clients.

Each client shapes the parameters and results of one capability family around
:class:`~acessilia_sdk.toolbox.client.ToolboxCapabilityClient`. They read no
settings and log nothing: the caller passes the configuration and records what
it needs.
"""

import inspect

from acessilia_sdk.toolbox.client import ToolboxCapabilityClient
from acessilia_sdk.toolbox.clients.adjudicate import ToolboxAdjudicateClient
from acessilia_sdk.toolbox.clients.artifact import ToolboxArtifactClient
from acessilia_sdk.toolbox.clients.dataset import ToolboxDatasetClient
from acessilia_sdk.toolbox.clients.docx import ToolboxDocxClient
from acessilia_sdk.toolbox.clients.layout import ToolboxLayoutClient
from acessilia_sdk.toolbox.clients.math import ToolboxMathClient
from acessilia_sdk.toolbox.clients.media_inspect import ToolboxMediaInspectClient
from acessilia_sdk.toolbox.clients.ocr import ToolboxOcrClient
from acessilia_sdk.toolbox.clients.operation import ToolboxOperationClient
from acessilia_sdk.toolbox.clients.orientation import ToolboxOrientationClient
from acessilia_sdk.toolbox.clients.page_ocr import ToolboxPageOcrClient
from acessilia_sdk.toolbox.clients.pdf import ToolboxPdfClient
from acessilia_sdk.toolbox.clients.pdf_ua import ToolboxPdfUaClient
from acessilia_sdk.toolbox.clients.pdf_validate import ToolboxPdfValidateClient
from acessilia_sdk.toolbox.clients.structure import ToolboxStructureClient
from acessilia_sdk.toolbox.clients.table import ToolboxTableClient
from acessilia_sdk.toolbox.clients.text_normalization import ToolboxTextNormalizeClient

__all__ = [
    "ToolboxAdjudicateClient",
    "ToolboxArtifactClient",
    "ToolboxDatasetClient",
    "ToolboxDocxClient",
    "ToolboxLayoutClient",
    "ToolboxMathClient",
    "ToolboxMediaInspectClient",
    "ToolboxOcrClient",
    "ToolboxOperationClient",
    "ToolboxOrientationClient",
    "ToolboxPageOcrClient",
    "ToolboxPdfClient",
    "ToolboxPdfUaClient",
    "ToolboxPdfValidateClient",
    "ToolboxStructureClient",
    "ToolboxTableClient",
    "ToolboxTextNormalizeClient",
    "client_timeout_keys",
]


def client_timeout_keys() -> frozenset[str]:
    """The ``timeout_key`` of each exported client that has its own timeout.

    Callers that build a :class:`~acessilia_sdk.toolbox.ToolboxClientConfig`
    from their own settings use this to know which settings map to the
    ``timeouts`` field; clients without a ``timeout_key`` use the shared
    timeout.
    """
    keys: set[str] = set()
    for name in __all__:
        value = globals()[name]
        if (
            inspect.isclass(value)
            and issubclass(value, ToolboxCapabilityClient)
            and value.timeout_key
        ):
            keys.add(value.timeout_key)
    return frozenset(keys)
