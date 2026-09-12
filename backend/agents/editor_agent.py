"""EditorAgent – Text consolidation, deduplication, and accessibility marking."""

from backend.i18n import t
from backend.log_messages import LOG_EDITOR_PAGE_CONSOLIDATED, LOG_EDITOR_PAGE_EMPTY
from backend.tools.region_classifier import region_has_markers
from backend.tools.logger import logger

from backend.agents.types import RegionTask
from backend.tools.text_tools import apply_marker, content_fingerprint


class EditorAgent:
    """Consolidates the other agents' results into accessible text."""

    def consolidate_page(
        self,
        tasks: list[RegionTask],
        results: dict[int, str],
    ) -> str:
        """Build the consolidated text for a page.

        Args:
            tasks: Region tasks detected on the page.
            results: Agent output text keyed by task index.

        Returns:
            The page's consolidated text, or an empty string when nothing survived consolidation.
        """
        text_parts: list[str] = []
        content_fingerprints: set[int] = set()

        for idx, task in enumerate(tasks):
            # Clean-text tasks arrive ready from the ReaderAgent
            if task.agent_target == "editor":
                text = task.text
            else:
                # Results processed by VisionAgent or DataAgent
                text = results.get(idx, "")

            if not text or not text.strip():
                continue

            # Deduplication
            fp = content_fingerprint(text)
            if fp in content_fingerprints:
                continue
            content_fingerprints.add(fp)

            # Apply accessibility markers when needed (vision/data results)
            if task.agent_target != "editor" and region_has_markers(task.classification):
                if task.region is not None:
                    text = apply_marker(text, task.classification, task.region)

            text_parts.append(text)

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
