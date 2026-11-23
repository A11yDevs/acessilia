"""Shared bodies for the agents' Agno tool envelopes."""

from __future__ import annotations

from typing import Any, Protocol


class _SelectPageProcess(Protocol):
    def __call__(
        self,
        a_text: str,
        vlm_text: str,
        docling_text: str,
        mineru_text: str,
        finish: str | None,
        dm: float,
        ab: float,
    ) -> tuple[str, bool]: ...


class _SwapLowAgreementProcess(Protocol):
    def __call__(
        self,
        base_text: str,
        alt_text: str | None,
        docling_text: str,
        mineru_text: str,
        agree_thr: float,
        min_alt_frac: float,
    ) -> tuple[str, bool]: ...


class _JoinTail(Protocol):
    def __call__(
        self, blocks: list[str], mode: str, max_len: int, k: int
    ) -> list[str]: ...


class _TailJoin3(Protocol):
    def __call__(
        self,
        blocks: list[str],
        position: str | None,
        max_len: int,
        k: int,
        bot: str,
    ) -> list[str]: ...


def select_page_tool(
    process: _SelectPageProcess,
    a_text: str,
    vlm_text: str,
    docling_text: str,
    mineru_text: str,
    finish: str | None,
    dm: float,
    ab: float,
) -> dict[str, Any]:
    """Run a page-selection process function and wrap its result for Agno."""
    text, swapped = process(
        a_text, vlm_text, docling_text, mineru_text, finish, dm, ab
    )
    return {"text": text, "swapped": swapped}


def swap_low_agreement_tool(
    process: _SwapLowAgreementProcess,
    base_text: str,
    alt_text: str | None,
    docling_text: str,
    mineru_text: str,
    agree_thr: float,
    min_alt_frac: float,
) -> dict[str, Any]:
    """Run a low-agreement swap process function and wrap its result for Agno."""
    text, swapped = process(
        base_text, alt_text, docling_text, mineru_text, agree_thr, min_alt_frac
    )
    return {"text": text, "swapped": swapped}


def join_tail_tool(
    join_tail: _JoinTail,
    tailjoin3: _TailJoin3,
    blocks: list[str],
    mode: str,
    max_len: int,
    k: int,
    position: str | None,
    bot: str,
) -> list[str]:
    """Apply the plain tail-join or the position-conditioned ``tj3`` rule."""
    if position is not None:
        return tailjoin3(blocks, position, max_len, k, bot)
    return join_tail(blocks, mode, max_len, k)
