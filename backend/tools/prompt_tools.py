"""Ferramentas de gerenciamento de prompts."""
from pathlib import Path
from backend.tools.logger import logger

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "ai" / "prompts"

MODE_MAP = {
    "detalhado": "detalhado.md",
    "medio": "medio.md",
    "normal": "medio.md",
    "baixo": "baixo.md",
    "ocr": "ocr.md",
}

REGION_PROMPT_MAP = {
    "regiao_imagem": "regiao_imagem.md",
    "regiao_texto_escaneado": "regiao_texto_escaneado.md",
    "regiao_tabela": "regiao_tabela.md",
    "regiao_formula": "regiao_formula.md",
}

def load_system_prompt(mode: str = "medio") -> str:
    filename = MODE_MAP.get(mode, "medio.md")
    prompt_path = PROMPTS_DIR / filename
    if prompt_path.exists():
        return prompt_path.read_text(encoding="utf-8")
    logger.warning(f"Prompt file not found at {prompt_path}, falling back to medio")
    fallback = PROMPTS_DIR / "medio.md"
    if fallback.exists():
        return fallback.read_text(encoding="utf-8")
    return "Você é um sistema de acessibilidade digital..."

def load_region_prompt(region_type: str) -> str:
    filename = REGION_PROMPT_MAP.get(region_type)
    if not filename: return ""
    prompt_path = PROMPTS_DIR / filename
    if prompt_path.exists():
        return prompt_path.read_text(encoding="utf-8")
    return ""

def build_page_prompt(system_prompt: str, total_pages: int, page_num: int, is_pdf: bool) -> str:
    advanced_instructions = (
        "\n\nREGRAS DE FORMATAÇÃO E SEMÂNTICA:\n"
        "1. Se houver imagens, gráficos ou diagramas, forneça a audiodescrição entre colchetes.\n"
        "2. Preserve a ênfase do texto original usando Markdown apenas quando necessário.\n"
        "3. Para MATEMÁTICA: linearize fórmulas simples e use LaTeX para expressões complexas.\n"
        "4. Se um parágrafo termina com hífen ou parece continuar na próxima página, apenas transcreva-o."
    )
    prompt = system_prompt + advanced_instructions
    if is_pdf:
        prompt += f"\n\nEste e o documento de {total_pages} paginas. Voce esta processando a pagina {page_num} de {total_pages}."
    return prompt
