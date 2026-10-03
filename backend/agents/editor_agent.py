"""EditorAgent – Text consolidation, deduplication, and accessibility marking."""

from typing import Any

from backend.i18n import t
from backend.log_messages import LOG_EDITOR_PAGE_CONSOLIDATED, LOG_EDITOR_PAGE_EMPTY
from backend.tools.region_classifier import region_has_markers
from backend.tools.logger import logger

from backend.agents.types import RegionTask
from backend.agents.output_schemas import DataOutput, StructuredOutput, VisionOutput
from backend.pipeline.structure_parser import parse_text_to_blocks
from backend.tools.formula_tools import ensure_math_delimiters
from backend.tools.text_tools import FORMULA_SENTINEL, apply_marker, content_fingerprint


class EditorAgent:
    """Consolidates the other agents' results into accessible text."""

    def consolidate_page(
        self,
        tasks: list[RegionTask],
        results: dict[int, str | StructuredOutput | None],
    ) -> str:
        """Build the consolidated text for a page.

        Args:
            tasks: Region tasks detected on the page.
            results: Validated agent outputs (or trusted fallback text) keyed by task index.

        Returns:
            The page's consolidated text, or an empty string when nothing survived consolidation.
        """
        text_parts = [text for _, text, _ in self._consolidated_entries(tasks, results)]

        if not text_parts:
            logger.warning(
                t(LOG_EDITOR_PAGE_EMPTY).format(
                    page_num=tasks[0].page_num if tasks else 0,
                )
            )
            return ""

        logger.info(
            t(LOG_EDITOR_PAGE_CONSOLIDATED).format(
                page_num=tasks[0].page_num if tasks else 0,
                count=len(text_parts),
            )
        )

        return "\n\n".join(text_parts)

    def build_page_blocks(
        self,
        tasks: list[RegionTask],
        results: dict[int, str | StructuredOutput | None],
    ) -> list[dict[str, Any]]:
        """Build canonical-ready blocks, preserving typed table structure."""
        blocks: list[dict[str, Any]] = []
        for _task, text, output in self._consolidated_entries(tasks, results):
            if isinstance(output, DataOutput) and output.kind == "table":
                metadata: dict[str, Any] = {
                    "source": "data-agent",
                    "language": output.language,
                    "confidence": output.confidence,
                }
                if output.warnings:
                    metadata["warnings"] = list(output.warnings)
                blocks.append(
                    {
                        "type": "table",
                        "rows": output.table_rows(),
                        "table_ast": output.table_ast(),
                        "metadata": metadata,
                    }
                )
                continue

            parsed = parse_text_to_blocks(text)
            for block in parsed:
                # The canonical builder assigns document-wide ids later.
                block.pop("id", None)
                if isinstance(output, (VisionOutput, DataOutput)):
                    metadata = block.setdefault("metadata", {})
                    metadata.update(
                        {
                            "source": (
                                "vision-agent"
                                if isinstance(output, VisionOutput)
                                else "data-agent"
                            ),
                            "language": output.language,
                            "confidence": output.confidence,
                        }
                    )
                    if output.warnings:
                        metadata["warnings"] = list(output.warnings)
                blocks.append(block)
        return blocks

    def _consolidated_entries(
        self,
        tasks: list[RegionTask],
        results: dict[int, str | StructuredOutput | None],
    ) -> list[tuple[RegionTask, str, StructuredOutput | None]]:
        entries: list[tuple[RegionTask, str, StructuredOutput | None]] = []
        content_fingerprints: set[int] = set()

        for idx, task in enumerate(tasks):
            raw_output = results.get(idx)
            structured = raw_output if isinstance(raw_output, (VisionOutput, DataOutput)) else None

            if task.agent_target == "editor":
                text = task.text
            elif isinstance(raw_output, VisionOutput):
                text = (
                    f"{FORMULA_SENTINEL} {raw_output.formula_latex}"
                    if raw_output.kind == "formula"
                    else raw_output.description
                )
            elif isinstance(raw_output, DataOutput):
                if raw_output.kind == "formula":
                    text = raw_output.latex or ""
                else:
                    table_lines = [
                        "| " + " | ".join(row) + " |"
                        for row in raw_output.table_rows()
                    ]
                    if raw_output.caption:
                        table_lines.insert(0, raw_output.caption)
                    table_lines.extend(note for note in raw_output.notes if note)
                    text = "\n".join(table_lines)
            else:
                text = raw_output if isinstance(raw_output, str) else ""

            if not text or not text.strip():
                continue

            fingerprint = content_fingerprint(text)
            if fingerprint in content_fingerprints:
                continue
            content_fingerprints.add(fingerprint)

            if task.agent_target != "editor" and text.startswith(FORMULA_SENTINEL):
                text = ensure_math_delimiters(text[len(FORMULA_SENTINEL):].strip())
                if not text:
                    continue
            elif task.agent_target == "data" and task.classification == "formula":
                text = ensure_math_delimiters(text)
            elif task.agent_target != "editor" and region_has_markers(task.classification):
                if task.region is not None:
                    text = apply_marker(text, task.classification, task.region)

            entries.append((task, text, structured))

        return entries
