"""Client for ``table.recognize``: table candidates from a VLM."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from acessilia_sdk.toolbox.client import ToolboxCapabilityClient

CAPABILITY = "table.recognize"


class ToolboxTableClient(ToolboxCapabilityClient):
    """Table recognition by VLM."""

    provider_key = "toolbox_table_provider"

    async def recognize(
        self,
        file_path: Path | None = None,
        artifact_id: str | None = None,
        *,
        hints: list[str] | None = None,
        use_hints: bool = True,
        header_cells: str = "th",
        samples: int = 3,
        temperature: float = 0.7,
        top_p: float = 0.95,
        seed: int = 0,
        use_remote_cache: bool | None = None,
    ) -> dict[str, Any]:
        """``POST /v1/capabilities/table.recognize:execute``.

        ``hints`` are the providers' tables in HTML, shown to the model unless
        ``use_hints`` is False. ``header_cells`` is the tag asked for the
        header (``th`` or ``td``). ``samples`` is the number of samples on top
        of the greedy generation, drawn with ``temperature``, ``top_p`` and
        ``seed``. Returns the response envelope; its ``document`` follows
        ``table-candidates@1`` (``greedy`` and ``samples`` with ``text`` and
        ``finish``).
        """
        return await self._execute(
            CAPABILITY,
            file_path=file_path,
            artifact_id=artifact_id,
            parameters={
                "hints": list(hints or []),
                "use_hints": use_hints,
                "header_cells": header_cells,
                "samples": samples,
                "temperature": temperature,
                "top_p": top_p,
                "seed": seed,
            },
            no_cache=use_remote_cache is False,
        )


__all__ = ["CAPABILITY", "ToolboxTableClient"]
