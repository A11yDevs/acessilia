"""The page judge: render a page, then ask which of two transcriptions it holds.

ADR-0017's second operation, after the formula chain. Two steps, each a
function of its own that reports a :class:`~acessilia_sdk.operations.formula.Step`:

1. :func:`render_judge_page` renders a whole page for the judge
   (``pdf.render@2``), at :data:`JUDGE_PAGE_DPI` with its longest side bounded
   by :data:`JUDGE_PAGE_MAX_SIDE`, so the image and two candidates fit one
   slot of the vision model;
2. :func:`judge_page` sends the image and the two candidates to
   ``document.adjudicate.page`` and reads its answer: ``pB``, the
   position-debiased probability that candidate B is the more faithful
   transcription, read by ``page_judgement_probability``, and what else the
   answer reports.

:func:`page_judgement` runs both for one page.

The steps raise the SDK's typed errors unchanged, and an answer without a
valid ``pB`` is a judgement whose ``p_b`` is ``None``: the operation does not
decide what that means. Which pages to judge and with which candidates, the
threshold that turns ``pB`` into a choice, and what a failure does to the run
are the caller's decisions (the core's, for its ``vlm-pairwise-judge``
method).
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from acessilia_sdk.operations.formula import Step
from acessilia_sdk.toolbox.clients.adjudicate import (
    PAGE_CAPABILITY,
    ToolboxAdjudicateClient,
    page_judgement_probability,
)
from acessilia_sdk.toolbox.clients.pdf import RENDER_CAPABILITY, ToolboxPdfClient

#: Resolution of the page image sent to the judge.
JUDGE_PAGE_DPI = 144
#: Longest side, in pixels, of that image: two candidates plus the image must
#: fit one 8192-token slot of the production vision model.
JUDGE_PAGE_MAX_SIDE = 1600


@dataclass(frozen=True)
class JudgePage:
    """A page rendered for the judge."""

    image: bytes
    page_number: int
    step: Step


@dataclass(frozen=True)
class PageJudgement:
    """What ``document.adjudicate.page`` answered for one page.

    ``p_b`` is what ``page_judgement_probability`` reads from ``pB``: whatever
    ``float()`` reads (a number, a numeric string, a boolean) when it falls in
    [0, 1], else ``None`` (review of #605). ``p_b_ab``, ``p_a_ba`` and
    ``model`` are what the answer reports, as it reports them. ``document`` is
    the answer's document when it is an object, and ``{}`` when it is absent or
    not an object, as with no ``pB``.
    """

    p_b: float | None
    p_b_ab: Any
    p_a_ba: Any
    model: Any
    document: dict[str, Any]
    step: Step


@dataclass(frozen=True)
class PageJudgementChain:
    """Both steps of :func:`page_judgement` for one page."""

    page: JudgePage
    judgement: PageJudgement

    @property
    def steps(self) -> tuple[Step, ...]:
        """The steps that ran, in order."""
        return (self.page.step, self.judgement.step)


async def render_judge_page(
    pdf: ToolboxPdfClient,
    source: Path | None,
    *,
    page_number: int,
    artifact_id: str | None = None,
    dpi: int = JUDGE_PAGE_DPI,
    max_side: int = JUDGE_PAGE_MAX_SIDE,
    use_remote_cache: bool | None = None,
) -> JudgePage:
    """Render the whole of ``page_number`` (1-based) for the judge.

    Errors of the render are raised as they are. With ``artifact_id``, whether
    a source the Toolbox no longer stores is sent again is the client's
    setting (``resend_file_on_missing_artifact``), not the operation's.
    """
    page = await pdf.render(
        source,
        artifact_id,
        page_number=page_number,
        dpi=dpi,
        max_side=max_side,
        use_remote_cache=use_remote_cache,
    )
    parameters = {"page_number": page_number, "dpi": dpi, "max_side": max_side}
    return JudgePage(page.image, page_number, Step(RENDER_CAPABILITY, pdf.provider, parameters))


async def judge_page(
    adjudicate: ToolboxAdjudicateClient,
    image: bytes,
    candidate_a: str,
    candidate_b: str,
    *,
    prompt: str = "base",
    use_remote_cache: bool | None = None,
) -> PageJudgement:
    """``document.adjudicate.page`` on ``image`` with two candidates.

    Candidate A is the transcription the caller holds, B the other one. An
    answer whose document is not an object counts as one without ``pB``.
    """
    with tempfile.TemporaryDirectory(prefix="acessilia-judge-") as directory:
        path = Path(directory) / "page.png"
        path.write_bytes(image)
        envelope = await adjudicate.judge_page(
            candidate_a,
            candidate_b,
            file_path=path,
            prompt=prompt,
            use_remote_cache=use_remote_cache,
        )
    document = envelope.get("document")
    if not isinstance(document, dict):
        document = {}
    return PageJudgement(
        p_b=page_judgement_probability(document),
        p_b_ab=document.get("pB_ab"),
        p_a_ba=document.get("pA_ba"),
        model=document.get("model"),
        document=document,
        step=Step(PAGE_CAPABILITY, adjudicate.provider, {"prompt": prompt}),
    )


async def page_judgement(
    pdf: ToolboxPdfClient,
    adjudicate: ToolboxAdjudicateClient,
    source: Path | None,
    *,
    page_number: int,
    candidate_a: str,
    candidate_b: str,
    artifact_id: str | None = None,
    prompt: str = "base",
    dpi: int = JUDGE_PAGE_DPI,
    max_side: int = JUDGE_PAGE_MAX_SIDE,
    use_remote_cache: bool | None = None,
) -> PageJudgementChain:
    """Render ``page_number`` and judge its two candidates.

    ``dpi`` and ``max_side`` go to the render, ``prompt`` to the judge, and
    ``use_remote_cache`` to both, as when the steps are called one by one.
    """
    page = await render_judge_page(
        pdf, source, page_number=page_number, artifact_id=artifact_id,
        dpi=dpi, max_side=max_side, use_remote_cache=use_remote_cache,
    )
    judgement = await judge_page(
        adjudicate, page.image, candidate_a, candidate_b,
        prompt=prompt, use_remote_cache=use_remote_cache,
    )
    return PageJudgementChain(page, judgement)


__all__ = [
    "JUDGE_PAGE_DPI",
    "JUDGE_PAGE_MAX_SIDE",
    "JudgePage",
    "PageJudgement",
    "PageJudgementChain",
    "judge_page",
    "page_judgement",
    "render_judge_page",
]
