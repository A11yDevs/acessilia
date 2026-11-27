"""Public transport for document.text.normalize@1; no local normalization."""

from __future__ import annotations

from acessilia_sdk.toolbox.client import ToolboxCapabilityClient
from acessilia_sdk.toolbox.text_normalization import (
    NormalizationBatch,
    NormalizedBatch,
    read_normalization,
)

CAPABILITY = "document.text.normalize"


class ToolboxTextNormalizeClient(ToolboxCapabilityClient):
    provider_key = "toolbox_text_normalize_provider"

    async def normalize(
        self, batch: NormalizationBatch, *, use_remote_cache: bool = True
    ) -> NormalizedBatch:
        """Send one immutable bounded batch through the versioned public executor."""
        envelope = await self._execute(
            CAPABILITY,
            upload=("normalization.json", batch.payload, "application/json"),
            no_cache=not use_remote_cache,
        )
        assert self.provider is not None
        return read_normalization(envelope, batch, provider=self.provider)


__all__ = ["ToolboxTextNormalizeClient"]
