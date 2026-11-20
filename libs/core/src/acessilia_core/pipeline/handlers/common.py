"""Helpers every deterministic method handler shares.

A handler takes the manifest and an obligation id and returns a
``MethodResult``. Moved verbatim from the PDDL orchestrator (#402, phase 3,
step 6).
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from acessilia_core.agents.fusion_agent import FusionAgent
from acessilia_core.execution.models import MethodResult
from acessilia_core.manifest.models import (
    Artifact,
    ManifestElement,
    ProcessingManifest,
)
from acessilia_core.pipeline.handlers.messages import MSG_HANDLER_OBLIGATION_NOT_FOUND
from acessilia_core.i18n import t


def _fusion_agent() -> FusionAgent:
    """Fusion agent used to reach the deterministic fusion primitives.

    The `docstruct` functions take classified blocks, counters and tuning
    parameters; `FusionAgent.process_*` is the in-repo entry point that supplies
    them, so handlers call that instead of a primitive whose signature they would
    otherwise have to guess.
    """
    return FusionAgent()


def _target_elements(
    manifest: ProcessingManifest, obligation_id: str
) -> list[ManifestElement]:
    """Elements an obligation points at, in reading order."""
    obligation = next(
        (o for o in manifest.obligations if o.id == obligation_id), None
    )
    if obligation is None:
        return []
    targets = set(obligation.target_ids)
    return sorted(
        (el for el in manifest.elements if el.id in targets),
        key=lambda el: el.reading_order,
    )


def _missing_obligation(obligation_id: str) -> MethodResult:
    return MethodResult(
        success=False,
        validated=False,
        message=t(MSG_HANDLER_OBLIGATION_NOT_FOUND).format(
            obligation_id=obligation_id
        ),
    )


def write_atomic_artifact(
    content: bytes,
    *,
    category: str,
    scope: str,
    kind: str,
    suffix: str,
    media_type: str,
    data_dir: Path,
    id_prefix: str | None = None,
) -> Artifact:
    """Write ``content`` atomically under ``data_dir/artifacts/<category>/<scope>/``."""
    digest = hashlib.sha256(content).hexdigest()
    output_path = data_dir / "artifacts" / category / scope / f"{digest}.{suffix}"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=output_path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        os.replace(temporary, output_path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    prefix = id_prefix if id_prefix is not None else kind
    return Artifact(
        id=f"artifact-{prefix}-{scope[:16]}-{digest[:16]}",
        kind=kind,
        path=str(output_path),
        media_type=media_type,
        sha256=digest,
    )
