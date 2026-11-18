"""A ``PageJudgement`` from a ``document.adjudicate.page`` document, for fakes.

Tests that replace the core's ``_judge_page`` return what it returns, the
SDK's ``PageJudgement``. ``judged`` builds one by running the SDK's own
``judge_page`` against a client that answers ``document``, so the answer is
read exactly as a run reads it.
"""

from __future__ import annotations

from typing import Any

from acessilia_sdk.operations.page_judge import PageJudgement, judge_page
from acessilia_sdk.runtime import run_sync


class _Answering:
    provider = "fake"

    def __init__(self, document: Any) -> None:
        self.document = document

    async def judge_page(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"document": self.document}


def judged(document: Any) -> PageJudgement:
    """What ``_judge_page`` returns when the Toolbox answers ``document``."""
    return run_sync(judge_page(_Answering(document), b"\x89PNG", "a", "b"))
