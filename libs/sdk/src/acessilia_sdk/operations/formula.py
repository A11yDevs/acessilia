"""The formula chain: crop a region, recognize its LaTeX, convert and verbalize it.

ADR-0017's first operation. Each step is a function of its own, so a caller can
stop after any of them, and each reports a :class:`Step` with the capability,
the provider and the effective parameters:

1. :func:`crop_formula_region` renders the region of a page that holds a
   formula (``pdf.render@2``). The clip comes from the formula's box through
   ``docstruct.geometry.boxes.best_effort_clip``; a box that cannot be used is
   no crop, never the whole page, since a recognizer would invent a formula
   from a page of prose;
2. :func:`recognize_formula` sends the crop to ``math.recognize`` and ranks the
   LaTeX candidates with ``docstruct.text.latex.ranked_latex_candidates``;
3. :func:`speak_formula` turns LaTeX into MathML (``math.convert``) and into
   spoken text (``math.verbalize``).

:func:`formula_chain` runs the three in order for one formula, speaking the
candidate the caller chooses (the first by default).

The steps raise the SDK's typed errors unchanged (``ToolboxInvalidInput`` for
an input the Toolbox refused, ``ToolboxUnavailable`` and the like for an
outage): an operation does not decide that a failure is "no formula". Which
formulas to read, whether a saved crop is reused, how a recognition is judged
against the text layer, falling back to a vision model and skipping a
capability after an outage are the caller's decisions (the core's, for its
formula enrichment).
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from docstruct.geometry.boxes import PageBox, best_effort_clip
from docstruct.text.latex import ranked_latex_candidates

from acessilia_sdk.toolbox.clients.math import (
    CONVERT_CAPABILITY,
    RECOGNIZE_CAPABILITY,
    VERBALIZE_CAPABILITY,
    ToolboxMathClient,
    recognized_formulas,
)
from acessilia_sdk.toolbox.clients.pdf import RENDER_CAPABILITY, ToolboxPdfClient

#: Resolution of a formula crop: chips read small subscripts better at 200 dpi.
FORMULA_CROP_DPI = 200
#: Smallest side, in the units of the clip the Toolbox applied, of a usable
#: crop; a thinner one is a rule or a dot, not a formula.
FORMULA_CROP_MIN_SIDE = 4.0


@dataclass(frozen=True)
class Step:
    """What one step did: its capability, the provider asked and its parameters."""

    capability: str
    provider: str | None
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FormulaCrop:
    """A formula's crop, or why there is none (``reason``).

    ``clip`` is the region the Toolbox applied, in its units. ``step`` is
    ``None`` when nothing was rendered.
    """

    image: bytes | None
    page_number: int
    clip: tuple[float, float, float, float] | None = None
    reason: str | None = None
    step: Step | None = None


@dataclass(frozen=True)
class FormulaCandidates:
    """``math.recognize``'s LaTeX candidates for a crop, best first.

    Each is a dict with a non-empty ``latex`` (delimiters stripped) and a
    ``confidence`` that is a finite number or ``None``, plus what the provider
    reported (``page``, ``bbox``).
    """

    candidates: list[dict[str, Any]]
    step: Step


@dataclass(frozen=True)
class FormulaSpeech:
    """A formula as MathML and as spoken text.

    An empty string is a formula the Toolbox could not convert or verbalize
    (``ToolboxInvalidInput`` is raised instead when it refused the input).
    """

    mathml: str
    verbalization: str
    steps: tuple[Step, ...]


@dataclass(frozen=True)
class FormulaChain:
    """Every step of :func:`formula_chain` for one formula.

    ``latex`` is the chosen candidate, ``""`` when there was no crop or no
    candidate of that rank; ``speech`` is ``None`` then.
    """

    crop: FormulaCrop
    candidates: FormulaCandidates | None
    latex: str
    speech: FormulaSpeech | None

    @property
    def steps(self) -> tuple[Step, ...]:
        """The steps that ran, in order."""
        steps: list[Step] = []
        if self.crop.step is not None:
            steps.append(self.crop.step)
        if self.candidates is not None:
            steps.append(self.candidates.step)
        if self.speech is not None:
            steps.extend(self.speech.steps)
        return tuple(steps)


async def crop_formula_region(
    pdf: ToolboxPdfClient,
    source: Path | None,
    *,
    page_number: int,
    box: PageBox | None,
    artifact_id: str | None = None,
    dpi: int = FORMULA_CROP_DPI,
    min_side: float = FORMULA_CROP_MIN_SIDE,
    use_remote_cache: bool | None = None,
) -> FormulaCrop:
    """Render the region of ``page_number`` that ``box`` delimits.

    No crop, without a request, for a page below 1 or a box that cannot be
    used (absent, or with a non-finite coordinate). No crop either when the
    Toolbox applied a region thinner than ``min_side``. Errors of the render
    are raised as they are. With ``artifact_id``, whether a source the Toolbox
    no longer stores is sent again is the client's setting
    (``resend_file_on_missing_artifact``), not the operation's.
    """
    if page_number < 1:
        return FormulaCrop(None, page_number, reason="no page")
    clip, origin = best_effort_clip(box)
    if clip is None:
        return FormulaCrop(None, page_number, reason="no usable box")
    parameters = {"page_number": page_number, "dpi": dpi, "clip": clip, "clip_origin": origin}
    page = await pdf.render(
        source,
        artifact_id,
        page_number=page_number,
        dpi=dpi,
        clip=clip,
        clip_origin=origin,
        use_remote_cache=use_remote_cache,
    )
    step = Step(RENDER_CAPABILITY, pdf.provider, parameters)
    left, top, right, bottom = page.clip
    if right - left < min_side or bottom - top < min_side:
        return FormulaCrop(None, page_number, page.clip, reason="crop too small", step=step)
    return FormulaCrop(page.image, page_number, page.clip, step=step)


async def recognize_formula(
    math: ToolboxMathClient,
    image: bytes,
    *,
    language: str = "pt-BR",
    use_remote_cache: bool | None = None,
) -> FormulaCandidates:
    """``math.recognize`` on ``image``, with its LaTeX candidates ranked.

    An answer without LaTeX is an empty list; an image the Toolbox refused
    raises ``ToolboxInvalidInput``.
    """
    with tempfile.TemporaryDirectory(prefix="acessilia-formula-") as directory:
        path = Path(directory) / "formula.png"
        path.write_bytes(image)
        envelope = await math.recognize(
            file_path=path, language=language, use_remote_cache=use_remote_cache
        )
    candidates = ranked_latex_candidates(recognized_formulas(envelope.get("document")))
    return FormulaCandidates(
        candidates, Step(RECOGNIZE_CAPABILITY, math.provider, {"language": language})
    )


async def speak_formula(
    math: ToolboxMathClient,
    latex: str,
    *,
    language: str = "pt-BR",
    use_remote_cache: bool | None = None,
) -> FormulaSpeech:
    """``latex`` as MathML (``math.convert``) and as spoken text (``math.verbalize``)."""
    converted = await math.convert(
        latex, direction="latex-to-mathml", use_remote_cache=use_remote_cache
    )
    spoken = await math.verbalize(latex, language=language, use_remote_cache=use_remote_cache)
    return FormulaSpeech(
        mathml=str((converted.get("document") or {}).get("mathml") or ""),
        verbalization=str((spoken.get("document") or {}).get("verbalized") or ""),
        steps=(
            Step(CONVERT_CAPABILITY, math.transform_provider, {"direction": "latex-to-mathml"}),
            Step(VERBALIZE_CAPABILITY, math.transform_provider, {"language": language}),
        ),
    )


async def formula_chain(
    pdf: ToolboxPdfClient,
    math: ToolboxMathClient,
    source: Path | None,
    *,
    page_number: int,
    box: PageBox | None,
    artifact_id: str | None = None,
    candidate: int = 1,
    dpi: int = FORMULA_CROP_DPI,
    min_side: float = FORMULA_CROP_MIN_SIDE,
    language: str = "pt-BR",
    use_remote_cache: bool | None = None,
) -> FormulaChain:
    """Crop, recognize, then convert and verbalize the ``candidate``-th candidate (1-based).

    Stops after the crop when there is none, and after recognition when there
    is no candidate of that rank. Errors are raised as the steps raise them.
    """
    if candidate < 1:
        raise ValueError("candidate is 1-based")
    crop = await crop_formula_region(
        pdf,
        source,
        page_number=page_number,
        box=box,
        artifact_id=artifact_id,
        dpi=dpi,
        min_side=min_side,
        use_remote_cache=use_remote_cache,
    )
    if crop.image is None:
        return FormulaChain(crop, None, "", None)
    found = await recognize_formula(
        math, crop.image, language=language, use_remote_cache=use_remote_cache
    )
    if len(found.candidates) < candidate:
        return FormulaChain(crop, found, "", None)
    latex = found.candidates[candidate - 1]["latex"]
    speech = await speak_formula(
        math, latex, language=language, use_remote_cache=use_remote_cache
    )
    return FormulaChain(crop, found, latex, speech)


__all__ = [
    "FORMULA_CROP_DPI",
    "FORMULA_CROP_MIN_SIDE",
    "FormulaCandidates",
    "FormulaChain",
    "FormulaCrop",
    "FormulaSpeech",
    "Step",
    "crop_formula_region",
    "formula_chain",
    "recognize_formula",
    "speak_formula",
]
