"""Format identity records; consumers own delivery and execution policy."""

from dataclasses import dataclass
from typing import Literal

Execution = Literal["local_pure", "remote", "local"]


@dataclass(frozen=True)
class FormatSpec:
    """Identity of an existing format, without rendering or I/O.

    ``local`` describes consumer-owned I/O such as packaging or legacy audio;
    it does not authorize an executor in docstruct. ``None`` means download-only
    identity with no current production route. Version is the binding revision,
    not a claim about a binary file specification's version.
    """

    id: str
    version: str
    media_type: str
    extension: str
    execution: Execution | None


__all__ = ["Execution", "FormatSpec"]
