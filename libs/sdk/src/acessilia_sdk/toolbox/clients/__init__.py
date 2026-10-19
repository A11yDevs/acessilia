"""Per-capability Toolbox clients.

Each client shapes the parameters and results of one capability family around
:class:`~acessilia_sdk.toolbox.client.ToolboxCapabilityClient`. They read no
settings and log nothing: the caller passes the configuration and records what
it needs.
"""

from acessilia_sdk.toolbox.clients.adjudicate import ToolboxAdjudicateClient
from acessilia_sdk.toolbox.clients.layout import ToolboxLayoutClient
from acessilia_sdk.toolbox.clients.math import ToolboxMathClient
from acessilia_sdk.toolbox.clients.media_inspect import ToolboxMediaInspectClient
from acessilia_sdk.toolbox.clients.ocr import ToolboxOcrClient
from acessilia_sdk.toolbox.clients.orientation import ToolboxOrientationClient
from acessilia_sdk.toolbox.clients.page_ocr import ToolboxPageOcrClient
from acessilia_sdk.toolbox.clients.pdf import ToolboxPdfClient
from acessilia_sdk.toolbox.clients.pdf_ua import ToolboxPdfUaClient
from acessilia_sdk.toolbox.clients.table import ToolboxTableClient

__all__ = [
    "ToolboxAdjudicateClient",
    "ToolboxLayoutClient",
    "ToolboxMathClient",
    "ToolboxMediaInspectClient",
    "ToolboxOcrClient",
    "ToolboxOrientationClient",
    "ToolboxPageOcrClient",
    "ToolboxPdfClient",
    "ToolboxPdfUaClient",
    "ToolboxTableClient",
]
