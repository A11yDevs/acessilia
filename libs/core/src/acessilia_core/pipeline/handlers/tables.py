"""The document's table enrichment as a planned method (#640, M2).

Until 0.3.11 the orchestrator read the tables and marked their inline math
before planning. ``table-enrichment`` runs the same two steps as the method of
the document's ``enrich-tables`` obligation, so the plan chooses, orders and
accounts them (``docs/architecture/workflow-actions.md``):

- ``_enrich_table_structures`` reads, with the ``DataAgent``, the tables
  without a usable structure and the garbled ones, with its single retry pass;
- ``_mark_table_inline_math`` then marks the inline math of every table's
  cells from the text layer.

The breaker and the text-span reader are the run's (``RunPorts.services``),
the ones the enrichment before planning used, so a provider outage and a
fetched page count for the whole document. A table that cannot be read is
recorded on it (``table_read_failure``) and left to ``linearize-table``, as
before; the method fails only when a step raises.
"""

from __future__ import annotations

from pathlib import Path

from acessilia_core.config import CoreConfig
from acessilia_core.execution.models import MethodResult
from acessilia_core.i18n import n
from acessilia_core.manifest.models import ProcessingManifest
from acessilia_core.pipeline.enrichment.common import run_breaker
from acessilia_core.pipeline.enrichment.inline_math import (
    _mark_table_inline_math,
    run_text_spans,
)
from acessilia_core.pipeline.enrichment.tables import _enrich_table_structures
from acessilia_core.pipeline.handlers.common import (
    _missing_obligation,
    _target_elements,
)
from acessilia_core.pipeline.handlers.messages import MSG_TABLES_ENRICHED
from acessilia_core.ports import RunPorts
from acessilia_sdk.runtime import run_sync


async def _enrich_tables(
    manifest: ProcessingManifest, source: Path, config: CoreConfig, ports: RunPorts
) -> tuple[int, int]:
    """Read, then mark: the order of the steps before planning, kept (step 6
    runs after step 5, which can replace a table's cells)."""
    read = await _enrich_table_structures(
        manifest,
        source,
        vision=config.vision,
        toolbox=config.toolbox,
        models=config.models,
        breaker=run_breaker(ports, config.vision),
    )
    marks = await _mark_table_inline_math(
        manifest,
        source,
        config.document,
        run_text_spans(ports, manifest, source, config.toolbox),
    )
    return read, marks["marked"]


def _handle_table_enrichment_method(
    manifest: ProcessingManifest, obligation_id: str, *, config: CoreConfig, ports: RunPorts
) -> MethodResult:
    """Run the document's table enrichment; satisfied once both steps ran."""
    tables = [element for element in _target_elements(manifest, obligation_id) if element.type == "table"]
    if not tables:
        return _missing_obligation(obligation_id)
    read, marked = run_sync(_enrich_tables(manifest, Path(manifest.source.path), config, ports))
    return MethodResult(
        success=True,
        validated=True,
        message=n(*MSG_TABLES_ENRICHED, len(tables)).format(
            count=len(tables), read=read, marked=marked
        ),
    )


__all__ = ["_handle_table_enrichment_method"]
