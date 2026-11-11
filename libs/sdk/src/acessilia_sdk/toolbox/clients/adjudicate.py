"""Client for ``document.adjudicate.page`` and ``document.adjudicate.region``.

- ``document.adjudicate.page``: a VLM pairwise judge. It sees the page image
  and two candidate transcriptions and says which is more faithful; both
  orders are asked, to remove position bias.
- ``document.adjudicate.region``: an exact transcription of a region crop,
  used to derive the differ's decision (select, replace or drop).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from acessilia_sdk.toolbox.client import ToolboxCapabilityClient

PAGE_CAPABILITY = "document.adjudicate.page"
REGION_CAPABILITY = "document.adjudicate.region"


def page_judgement_probability(document: Any) -> float | None:
    """``pB`` of a ``document.adjudicate.page`` answer, or ``None`` when absent or outside [0, 1].

    ``pB`` is the position-debiased probability that candidate B is the more
    faithful transcription. Whatever ``float`` reads is taken (a numeric
    string, a boolean); NaN and infinities are outside [0, 1]. What to do
    with ``None`` is the caller's decision.
    """
    try:
        p_b = float(document["pB"])
    except (KeyError, TypeError, ValueError):
        return None
    return p_b if 0.0 <= p_b <= 1.0 else None


class ToolboxAdjudicateClient(ToolboxCapabilityClient):
    """VLM adjudication of pages and regions."""

    provider_key = "toolbox_adjudicate_provider"

    async def judge_page(
        self,
        candidate_a: str,
        candidate_b: str,
        file_path: Path | None = None,
        artifact_id: str | None = None,
        *,
        prompt: str = "base",
        use_remote_cache: bool | None = None,
    ) -> dict[str, Any]:
        """``POST /v1/capabilities/document.adjudicate.page:execute``.

        ``prompt`` is the prompt variant (``base``, ``para`` or ``err``).
        Returns the response envelope; its ``document`` holds ``pB_ab``,
        ``pA_ba`` and ``pB`` (probability that B is better, debiased), which
        ``page_judgement_probability`` reads.
        """
        return await self._execute(
            PAGE_CAPABILITY,
            file_path=file_path,
            artifact_id=artifact_id,
            parameters={
                "candidate_a": candidate_a,
                "candidate_b": candidate_b,
                "prompt": prompt,
            },
            no_cache=use_remote_cache is False,
        )

    async def transcribe_region(
        self,
        candidates: list[str],
        file_path: Path | None = None,
        artifact_id: str | None = None,
        *,
        use_remote_cache: bool | None = None,
    ) -> dict[str, Any]:
        """``POST /v1/capabilities/document.adjudicate.region:execute``.

        ``candidates`` are OCR hypotheses for the region, given as hints.
        Returns the response envelope; its ``document`` holds ``text``, empty
        when the region has no legible text.
        """
        return await self._execute(
            REGION_CAPABILITY,
            file_path=file_path,
            artifact_id=artifact_id,
            parameters={"candidates": candidates},
            no_cache=use_remote_cache is False,
        )


__all__ = [
    "PAGE_CAPABILITY",
    "REGION_CAPABILITY",
    "ToolboxAdjudicateClient",
    "page_judgement_probability",
]
