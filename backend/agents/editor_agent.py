"""EditorAgent – Text consolidation, deduplication, and accessibility marking."""

from agno.workflow.step import Step, StepInput, StepOutput

from backend.i18n import t
from backend.log_messages import LOG_EDITOR_PAGE_CONSOLIDATED, LOG_EDITOR_PAGE_EMPTY
from backend.tools.region_classifier import region_has_markers
from backend.tools.logger import logger

from backend.agents.types import RegionTask
from backend.tools.formula_tools import ensure_math_delimiters
from backend.tools.text_tools import FORMULA_SENTINEL, apply_marker, content_fingerprint


class EditorAgent:
    """Consolidates the other agents' results into accessible text."""

    def __init__(self):
        self.__name__ = self.__class__.__name__

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
            text = task.text if task.agent_target == "editor" else results.get(idx, "")
            if not text or not text.strip():
                continue

            fp = content_fingerprint(text)
            if fp in content_fingerprints:
                continue
            content_fingerprints.add(fp)

            formatted = self._format_task_text(task, text)
            if formatted:
                text_parts.append(formatted)

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

    @staticmethod
    def _format_task_text(task: RegionTask, text: str) -> str:
        if task.agent_target != "editor" and text.startswith(FORMULA_SENTINEL):
            return ensure_math_delimiters(text[len(FORMULA_SENTINEL):].strip())
        if task.agent_target == "data" and task.classification == "formula":
            return ensure_math_delimiters(text)
        if task.agent_target != "editor" and region_has_markers(task.classification) and task.region is not None:
            return apply_marker(text, task.classification, task.region)
        return text

    def execute_step(self, step_input: StepInput) -> StepOutput:
        """Executes editor step for an Agno workflow."""
        tasks: list[RegionTask] | None = None
        results: dict[int, str] = {}

        candidates = [step_input.input, step_input.previous_step_content, step_input.get_step_content("ReaderAgent")]
        for src in candidates:
            if isinstance(src, dict) and "tasks" in src:
                tasks = src["tasks"]
                results = src.get("results", {}) or results
                break
            if isinstance(src, list):
                tasks = src
                break

        if tasks is None:
            return StepOutput(content="", success=False, error="EditorAgent step received no tasks to consolidate")

        try:
            return StepOutput(content=self.consolidate_page(tasks=tasks, results=results), success=True)
        except Exception as exc:
            logger.error(f"EditorAgent step execution failed: {exc}")
            return StepOutput(content="", success=False, error=str(exc))

    def __call__(self, step_input: StepInput) -> StepOutput:
        """Allows EditorAgent instance to be passed directly as an Agno workflow step."""
        return self.execute_step(step_input)

    def as_step(
        self,
        name: str = "EditorAgent",
        description: str = "Consolidates and sanitizes text into accessible output",
    ) -> Step:
        """Wraps EditorAgent as an explicit Agno Step instance."""
        return Step(name=name, description=description, executor=self.execute_step)


def editor_step(step_input: StepInput) -> StepOutput:
    """Module-level step function for EditorAgent in Agno workflows."""
    return EditorAgent().execute_step(step_input)


