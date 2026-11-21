"""The table enrichment stage: read each table's structure with the data agent.

Runs before planning. It chooses the tables to read (no structure, or a
structure that looks misread), backfills a structure from the text when it
can, asks the data agent for the rest one table at a time, keeps a new
reading only when it shares enough words with the old one, records why a table
was left unread, and retries the failures a second try may fix. Moved verbatim
from the PDDL orchestrator (#402, phase 3, step 6).

The agents it asks (the vision or the data agent) live in the core, in
``acessilia_core.agents`` (ADR-0016, step 2).
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Coroutine
from pathlib import Path
from typing import Any, Literal

from docstruct.tables.ast import (
    raw_rows_from_table_ast as _rows_from_table_ast,
)
from docstruct.tables.ast import (
    table_ast_column_count,
    table_ast_from_rows,
)
from docstruct.tables.garble import table_garble_reason
from docstruct.tables.text_rows import rows_from_visual_table_text

from acessilia_core.agents.data_agent import DataAgent
from acessilia_core.agents.output_schemas import DataOutput
from acessilia_core.agents.provider_breaker import ProviderBreaker
from acessilia_core.config import ModelConfig, ToolboxConfig, VisionConfig
from acessilia_core.manifest.models import (
    ManifestElement,
    ProcessingManifest,
)
from acessilia_core.pipeline.elements import (
    _table_element_has_structured_content,
)
from acessilia_core.pipeline.enrichment.common import (
    _extract_picture_bytes,
    _retry_failed,
)
from acessilia_core.pipeline.obligations import (
    _pages_label,
)
from acessilia_core.pipeline.toolbox import (
    _source_artifact_id,
)
from acessilia_core.i18n import t
from acessilia_core.i18n.log_messages import (
    LOG_PDDL_TABLE_REREAD_ACCEPTED,
    LOG_PDDL_TABLE_REREAD_REJECTED,
    LOG_PDDL_TABLES_ENRICHED,
)
from acessilia_core.blocking import run_blocking
from acessilia_core.i18n.stage_messages import (
    STAGE_RECOGNIZING_TABLE,
)
from acessilia_core.logger import logger


class _TableReader:
    """The state ``_enrich_table_structures`` shares across one document's tables."""

    def __init__(
        self,
        *,
        manifest: ProcessingManifest,
        source_file: Path,
        toolbox: ToolboxConfig,
        data_agent: DataAgent,
        breaker: ProviderBreaker,
        garbled: dict[str, str],
        total: int,
        status_callback: Callable[[str], Coroutine[Any, Any, None]] | None,
        on_progress: Callable[[], Awaitable[None]] | None,
    ) -> None:
        self.manifest = manifest
        self.source_file = source_file
        self.toolbox = toolbox
        self.data_agent = data_agent
        self.breaker = breaker
        self.garbled = garbled
        self.total = total
        self.status_callback = status_callback
        self.on_progress = on_progress

    async def read_and_notify(self, position: int, element: ManifestElement) -> bool:
        """Read one table, then let the caller persist its outcome (#407)."""
        try:
            return await self._read_one(position, element)
        finally:
            if self.on_progress is not None:
                await self.on_progress()

    async def _report_progress(self, position: int, page_number: int | None) -> None:
        if self.status_callback:
            await self.status_callback(
                t(STAGE_RECOGNIZING_TABLE).format(
                    current=position,
                    total=self.total,
                    pages=_pages_label([page_number], len(self.manifest.pages)),
                )
            )

    async def _read_one(self, position: int, element: ManifestElement) -> bool:
        """Read one table from its image, or keep it as it is; True when enriched."""
        reason = self.garbled.get(element.id)
        if reason is None and _backfill_table_from_existing_text(element):
            return True

        fallback_page_number = element.page_number
        if fallback_page_number is None and len(self.manifest.pages) == 1:
            fallback_page_number = self.manifest.pages[0].page_number

        await self._report_progress(position, fallback_page_number)
        # The breaker is consulted before the crop: a provider the pictures
        # declared down must not cost one Toolbox render per remaining table.
        # The second pass calls this anyway for its probe, because the probe
        # is let through before any `_read_one` sees the breaker.
        if self.breaker.open:
            if reason is not None:
                _keep_misread_table(
                    element,
                    fallback_page_number or 0,
                    reason,
                    self.breaker.skip_detail(),
                    _table_review_attempts(element, 0),
                )
            _record_table_read_failure(element, "model_failed")
            return False
        image_bytes, page_number = await run_blocking(
            _extract_picture_bytes,
            self.source_file,
            element,
            fallback_page_number,
            _source_artifact_id(self.manifest),
            self.manifest.source.media_type,
            toolbox=self.toolbox,
        )
        if not image_bytes:
            _record_table_read_failure(element, "crop_unavailable")
            if reason is not None:
                _keep_misread_table(
                    element, page_number, reason, "no image of the table",
                    _table_review_attempts(element, 0),
                )
            return False

        table_output, answered, why, attempt = await _read_table(
            self.data_agent, self.breaker, element, image_bytes, page_number, reason
        )
        if table_output is None:
            _record_unread_table(element, page_number, reason, answered, why, attempt)
            return False
        _fold_table_reading(element, table_output, page_number, reason, attempt)
        return True


async def _enrich_table_structures(
    manifest: ProcessingManifest,
    source_file: Path,
    *,
    vision: VisionConfig,
    toolbox: ToolboxConfig,
    models: ModelConfig,
    status_callback: Callable[[str], Coroutine[Any, Any, None]] | None = None,
    breaker: ProviderBreaker | None = None,
    on_progress: Callable[[], Awaitable[None]] | None = None,
) -> None:
    table_elements, garbled = _tables_to_read(
        manifest, visual_review=vision.table_visual_review
    )
    if not table_elements:
        return

    breaker = breaker or ProviderBreaker(vision.breaker_threshold)
    reader = _TableReader(
        manifest=manifest,
        source_file=source_file,
        toolbox=toolbox,
        data_agent=DataAgent(models=models, toolbox=toolbox),
        breaker=breaker,
        garbled=garbled,
        total=len(table_elements),
        status_callback=status_callback,
        on_progress=on_progress,
    )

    enriched = 0
    for position, element in enumerate(table_elements, start=1):
        enriched += await reader.read_and_notify(position, element)
    enriched += await _retry_failed(
        [
            (position, element)
            for position, element in enumerate(table_elements, start=1)
            if element.metadata.get("table_read_failure") == "model_failed"
        ],
        reader.read_and_notify,
        kind="tables",
        breaker=breaker,
        delay_seconds=vision.retry_pass_delay_seconds,
    )

    if enriched:
        logger.info(t(LOG_PDDL_TABLES_ENRICHED).format(count=enriched))


def _tables_to_read(
    manifest: ProcessingManifest, *, visual_review: bool
) -> tuple[list[ManifestElement], dict[str, str]]:
    """The tables to read from their image, and why each misread one is read again.

    A table without a usable structure is read. With ``visual_review``
    (``VisionConfig.table_visual_review``), so is a table read in the wrong shape (rows
    collapsed into one, cells doubled): it has structure but not the right
    one, and ``garbled`` maps its id to the reason (``table_garble_reason``).
    """
    garbled: dict[str, str] = {}
    if visual_review:
        for element in manifest.elements:
            if element.type == "table" and _table_element_has_structured_content(element):
                reason = table_garble_reason(
                    _rows_from_table_ast(element.metadata["table_ast"])
                )
                if reason:
                    garbled[element.id] = reason
    table_elements = [
        element
        for element in manifest.elements
        if element.type == "table"
        and (element.id in garbled or not _table_element_has_structured_content(element))
    ]
    return table_elements, garbled


async def _read_table(
    data_agent: DataAgent,
    breaker: ProviderBreaker,
    element: ManifestElement,
    image_bytes: bytes,
    page_number: int,
    reason: str | None,
) -> tuple[DataOutput | None, bool, str, int]:
    """Ask the data agent for a table: ``(reading, answered, why, attempts)``.

    A misread table (``reason``) gets a few readings: the model may drop
    columns or rows on one try and read the table whole on the next, and a
    reading that is not the same table read better is refused
    (``_table_reread_disqualified``). ``reading`` is ``None`` when none was
    kept; ``answered`` says whether the model answered at all, ``why`` why
    nothing was kept, and ``attempts`` how many readings were made.
    """
    attempts = _TABLE_REREAD_ATTEMPTS if reason is not None else 1
    table_output = None
    answered = False
    why = "no table was read"
    attempt = 0
    for attempt in range(1, attempts + 1):
        if breaker.open:
            why = breaker.skip_detail()
            attempt -= 1  # this try was not made
            break
        candidate = await data_agent.process_region(
            image_bytes=image_bytes,
            classification="table",
            page_num=page_number,
            fallback_text=element.text or "",
        )
        # The data agent returns None for any failure, an unusable answer
        # included, so the breaker may count one of those too.
        breaker.record(candidate is not None)
        answered = answered or isinstance(candidate, DataOutput)
        if not isinstance(candidate, DataOutput) or candidate.kind != "table":
            continue
        if reason is not None:
            why = _table_reread_disqualified(
                element.metadata["table_ast"], candidate.table_rows()
            )
            if why:
                continue
        table_output = candidate
        break
    return table_output, answered, why, attempt


def _record_unread_table(
    element: ManifestElement,
    page_number: int,
    reason: str | None,
    answered: bool,
    why: str,
    attempt: int,
) -> None:
    """Record that no reading of a table was kept.

    A reading refused as worse than the table, or an answer that it is not a
    table, is the model's answer; only no answer at all is a failure a rerun
    may not repeat. A misread table stays as it was, with why.
    """
    if answered:
        # The provider is up and answered; a failure an earlier pass
        # recorded on this element is no longer true.
        element.metadata.pop("table_read_failure", None)
    else:
        _record_table_read_failure(element, "model_failed")
    if reason is not None:
        _keep_misread_table(
            element, page_number, reason, why, _table_review_attempts(element, attempt)
        )


def _fold_table_reading(
    element: ManifestElement,
    table_output: DataOutput,
    page_number: int,
    reason: str | None,
    attempt: int,
) -> None:
    """Write a kept table reading into ``element``, keeping a replaced misread AST."""
    element.metadata.pop("table_read_failure", None)
    rows = table_output.table_rows()
    table_ast = table_output.table_ast()
    if reason is not None:
        element.metadata["table_ast_replaced"] = element.metadata["table_ast"]
        element.metadata["table_review"] = {
            "reason": reason, "outcome": "replaced",
            "attempts": _table_review_attempts(element, attempt),
        }
        logger.info(
            t(LOG_PDDL_TABLE_REREAD_ACCEPTED).format(
                element_id=element.id, page=page_number, reason=reason,
            )
        )

    element.metadata["table_ast"] = table_ast
    element.metadata["table_linearization_hint"] = "data-agent-structured"
    element.metadata["table_row_count"] = len(rows)
    element.metadata["table_column_count"] = table_ast_column_count(table_ast)
    element.metadata["table_has_header"] = any(
        cell.header or cell.scope != "none"
        for row in table_output.rows
        for cell in row.cells
    )
    element.metadata["data_language"] = table_output.language
    element.metadata["data_confidence"] = table_output.confidence
    # Always overwrite the previous reading's warnings (#682): a replacement
    # reading with none must clear the list, not keep the replaced AST's.
    element.metadata["data_warnings"] = list(table_output.warnings)
    element.text = ""
    if element.page_number is None and page_number >= 1:
        element.page_number = page_number


#: Why a table was left unread, recorded in metadata["table_read_failure"]: the
#: crop could not be rendered, or the data agent returned no answer at all.
TableReadFailure = Literal["crop_unavailable", "model_failed"]


def _record_table_read_failure(element: ManifestElement, reason: TableReadFailure) -> None:
    """Mark ``element`` as a table no reading came back for, and say why."""
    element.metadata["table_read_failure"] = reason


def _table_review_attempts(element: ManifestElement, attempts: int) -> int:
    """How many readings a table has had, with ``attempts`` more.

    Every pass that reads a table again stores the count it made, so the
    metadata says how many readings the table got in total (3 on one pass, 1
    more on the next), not only the last pass's.
    """
    review = element.metadata.get("table_review")
    previous = review.get("attempts", 0) if isinstance(review, dict) else 0
    return previous + attempts


def _keep_misread_table(
    element: ManifestElement, page_number: int, reason: str, why: str, attempts: int
) -> None:
    """Record that a misread table stays as it was read, and why."""
    element.metadata["table_review"] = {
        "reason": reason, "outcome": "kept", "why": why, "attempts": attempts,
    }
    logger.warning(
        t(LOG_PDDL_TABLE_REREAD_REJECTED).format(
            element_id=element.id, page=page_number, reason=reason, why=why,
        )
    )


#: Share of the words two readings of a table must share, each way, for the
#: new one to replace the misread one: it is the same table read better, so
#: most of its words were there, misplaced (a crop of the wrong region, or an
#: invented table, shares few), and it must keep most of the misread one's
#: words (on 006.pdf the model once returned only the header row).
_TABLE_REREAD_MIN_SHARED = 0.5


#: Readings asked for a misread table before it is kept as it is.
_TABLE_REREAD_ATTEMPTS = 3


_TABLE_WORD = re.compile(r"\w{2,}")


def _table_reread_disqualified(
    misread_ast: dict[str, Any], rows: list[list[str]]
) -> str | None:
    """Why a new reading of a misread table must not replace it, or None."""
    reason = table_garble_reason(rows)
    if reason:
        return f"the new reading is misread too: {reason}"
    misread_rows = _rows_from_table_ast(misread_ast)
    width = max((len(row) for row in rows), default=0)
    misread_width = max((len(row) for row in misread_rows), default=0)
    if width < misread_width:
        return f"the new reading has {width} column(s), the table {misread_width}"
    words = {word for row in rows for cell in row for word in _TABLE_WORD.findall(cell.casefold())}
    if not words:
        return "the new reading has no text"
    misread = {
        word for row in misread_rows for cell in row for word in _TABLE_WORD.findall(cell.casefold())
    }
    shared = len(words & misread) / len(words)
    if shared < _TABLE_REREAD_MIN_SHARED:
        return f"only {shared:.0%} of its words are in the table it would replace"
    kept = len(words & misread) / len(misread) if misread else 1.0
    if kept < _TABLE_REREAD_MIN_SHARED:
        return f"it keeps only {kept:.0%} of the words of the table it would replace"
    return None


def _backfill_table_from_existing_text(element: ManifestElement) -> bool:
    text = (element.text or "").strip()
    if not text:
        return False

    rows = rows_from_visual_table_text(text)
    if not rows:
        return False

    table_ast = table_ast_from_rows(rows)
    if table_ast is None:
        return False

    element.metadata["table_ast"] = table_ast
    element.metadata["table_linearization_hint"] = "text-heuristic"
    element.metadata["table_row_count"] = len(rows)
    element.metadata["table_column_count"] = max((len(row) for row in rows), default=0)
    element.metadata["table_has_header"] = bool(rows and len(rows[0]) >= 2)
    element.text = ""
    return True
