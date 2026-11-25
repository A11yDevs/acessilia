"""The document's table enrichment as a planned method (#640, M2).

Until 0.3.11 the orchestrator read the tables and marked their inline math
before planning. ``table-enrichment`` runs the same two steps as the method of
the document's ``enrich-tables`` obligation, so the plan chooses, orders and
accounts them (``docs/architecture/workflow-actions.md``):

- ``_enrich_table_structures`` reads, with the ``DataAgent``, the tables
  without a usable structure and the garbled ones, with its single retry pass;
- ``_mark_table_inline_math`` then marks the inline math of every table's
  cells from the text layer.

The breaker, the text-span reader and the progress reporter are the run's
(``RunPorts.services``), the ones the enrichment before planning used, so a
provider outage, a fetched page and a progress message count for the whole
document.

**What the result means.** ``success`` and ``validated`` say that the
collective attempt ran: both steps completed for every table. They do not say
that every table now has a structure. That stays per table, as before: a
table that could not be read keeps its reason (``table_read_failure``:
``model_failed``, ``admission_rejected``, ``crop_unavailable``), and its
``linearize-table`` obligation validates it. Failing the whole obligation for
one table would block the tables that are usable. The message reports what
happened to each table, so the execution report never reads as if every table
were enriched. The method fails only when a step raises.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from acessilia_core.config import CoreConfig
from acessilia_core.execution.models import MethodResult
from acessilia_core.i18n import n, t
from acessilia_core.i18n.stage_messages import STAGE_ENRICHING_TABLES_OCR
from acessilia_core.manifest.models import ManifestElement, ProcessingManifest
from acessilia_core.pipeline.elements import _table_element_has_structured_content
from acessilia_core.pipeline.enrichment.common import run_breaker
from acessilia_core.pipeline.enrichment.inline_math import (
    _mark_table_inline_math,
    inline_math_detection_status,
    run_text_spans,
)
from acessilia_core.pipeline.enrichment.tables import (
    _enrich_table_structures,
    _tables_to_read,
)
from acessilia_core.pipeline.handlers.common import run_status, step_checkpoint
from acessilia_core.pipeline.handlers.messages import (
    MSG_TABLE_NO_TABLE,
    MSG_TABLES_ENRICHED,
)
from acessilia_core.ports import RunPorts
from acessilia_sdk.runtime import run_sync


async def _enrich_tables(
    manifest: ProcessingManifest,
    source: Path,
    config: CoreConfig,
    ports: RunPorts,
    targets: frozenset[str],
    obligation_id: str,
) -> int:
    """Read, then mark: the order of the steps before planning, kept (step 6
    runs after step 5, which can replace a table's cells). Returns the runs of
    inline math marked.

    Both steps keep to ``targets``, the obligation's tables: a second
    enrichment (``obligation-enrich-tables-2``, #832) reads and marks only its
    new tables, never the ones an earlier enrichment owns. The breaker, the
    span reader and the progress stay the run's."""
    status = run_status(ports)
    if status is not None:
        await status(t(STAGE_ENRICHING_TABLES_OCR))
    await _enrich_table_structures(
        manifest,
        source,
        vision=config.vision,
        toolbox=config.toolbox,
        models=config.models,
        status_callback=status,
        breaker=run_breaker(ports, config.vision),
        targets=targets,
        # Each table read is saved into the execution checkpoint (#836).
        on_progress=step_checkpoint(ports, manifest, obligation_id),
    )
    marks = await _mark_table_inline_math(
        manifest,
        source,
        config.document,
        run_text_spans(ports, manifest, source, config.toolbox),
        targets=targets,
    )
    return marks["marked"]


def _outcome(element: ManifestElement) -> str:
    """What the reading left on a table that needed one."""
    failure = element.metadata.get("table_read_failure")
    if failure:
        return str(failure)
    review = element.metadata.get("table_review")
    if isinstance(review, dict) and review.get("outcome") == "kept":
        return "kept"
    if not _table_element_has_structured_content(element):
        return "unread"
    hint = element.metadata.get("table_linearization_hint")
    return "from_text" if hint == "text-heuristic" else "read"


def _handle_table_enrichment_method(
    manifest: ProcessingManifest, obligation_id: str, *, config: CoreConfig, ports: RunPorts
) -> MethodResult:
    """Run the document's table enrichment; satisfied once both steps ran."""
    obligation = next((item for item in manifest.obligations if item.id == obligation_id), None)
    targets = frozenset(obligation.target_ids) if obligation is not None else frozenset()
    tables = [
        element for element in manifest.elements
        if element.id in targets and element.type == "table"
    ]
    if not tables:
        return MethodResult(success=False, validated=False, message=t(MSG_TABLE_NO_TABLE))
    needing, _ = _tables_to_read(
        manifest, visual_review=config.vision.table_visual_review, targets=targets
    )
    needing_ids = [element.id for element in needing]
    marked = run_sync(_enrich_tables(manifest, Path(manifest.source.path), config, ports, targets, obligation_id))
    by_id = {element.id: element for element in manifest.elements}
    outcomes = Counter(_outcome(by_id[element_id]) for element_id in needing_ids)
    structured = outcomes.pop("read", 0) + outcomes.pop("from_text", 0)
    return MethodResult(
        success=True,
        validated=True,
        message=n(*MSG_TABLES_ENRICHED, len(tables)).format(
            count=len(tables),
            needing=len(needing_ids),
            structured=structured,
            left=", ".join(f"{reason}: {count}" for reason, count in sorted(outcomes.items())) or "-",
            inline=inline_math_detection_status(manifest, config.document),
            marked=marked,
        ),
    )


__all__ = ["_handle_table_enrichment_method"]
