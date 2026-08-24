"""EditorAgent – Consolidação de textos, deduplicação e marcação de acessibilidade."""

from backend.tools.region_classifier import region_has_markers
from backend.tools.logger import logger

from backend.agents.types import RegionTask
from backend.tools.formula_tools import ensure_math_delimiters
from backend.tools.text_tools import FORMULA_SENTINEL, apply_marker, content_fingerprint


class EditorAgent:
    """Consolida os resultados dos demais agentes em texto acessível."""

    def consolidate_page(
        self,
        tasks: list[RegionTask],
        results: dict[int, str],
    ) -> str:
        """Monta o texto consolidado da página."""
        text_parts: list[str] = []
        content_fingerprints: set[int] = set()

        for idx, task in enumerate(tasks):
            # Tarefas de texto limpo já vêm prontas do ReaderAgent
            if task.agent_target == "editor":
                text = task.text
            else:
                # Resultado processado pelo VisionAgent ou DataAgent
                text = results.get(idx, "")

            if not text or not text.strip():
                continue

            # Deduplicação
            fp = content_fingerprint(text)
            if fp in content_fingerprints:
                continue
            content_fingerprints.add(fp)

            # Imagem identificada pela visao como formula → mantem so o LaTeX
            if task.agent_target != "editor" and text.startswith(FORMULA_SENTINEL):
                text = ensure_math_delimiters(text[len(FORMULA_SENTINEL):].strip())
                if not text:
                    continue
            # Resultado de fórmula do DataAgent → delimita p/ virar bloco math
            elif task.agent_target == "data" and task.classification == "formula":
                text = ensure_math_delimiters(text)
            # Aplica marcadores se necessário (para resultados de visão/dados)
            elif task.agent_target != "editor" and region_has_markers(task.classification):
                if task.region is not None:
                    text = apply_marker(text, task.classification, task.region)

            text_parts.append(text)

        if not text_parts:
            logger.warning(
                "[pag {}] EditorAgent: nenhum texto consolidado",
                tasks[0].page_num if tasks else 0,
            )
            return ""

        logger.info(
            "[pag {}] EditorAgent: {} partes consolidadas",
            tasks[0].page_num if tasks else 0,
            len(text_parts),
        )

        return "\n\n".join(text_parts)
