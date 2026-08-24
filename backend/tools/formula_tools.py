"""Detecção e extração local de fórmulas em imagens (sem LLM).

Cascata: OCR local (RapidOCR) filtra imagens com aparência matemática;
CodeFormula (Docling) extrai o LaTeX do recorte. LLM fica como último recurso.
"""

from __future__ import annotations

import io
from typing import Any

from backend.tools.image_enhancer import is_math_likely
from backend.tools.logger import logger

_ocr_engine: Any = None
_ocr_failed = False
_codeformula_model: Any = None
_codeformula_failed = False


def _get_ocr() -> Any:
    global _ocr_engine, _ocr_failed
    if _ocr_engine is None and not _ocr_failed:
        try:
            from rapidocr import EngineType, RapidOCR

            # backend torch: mesmo usado pelo Docling no repo (onnxruntime ausente)
            _ocr_engine = RapidOCR(
                params={
                    "Det.engine_type": EngineType.TORCH,
                    "Cls.engine_type": EngineType.TORCH,
                    "Rec.engine_type": EngineType.TORCH,
                }
            )
        except Exception as error:
            _ocr_failed = True
            logger.warning("RapidOCR indisponível para cascata de fórmulas: {}", error)
    return _ocr_engine


def _get_codeformula() -> Any:
    global _codeformula_model, _codeformula_failed
    if _codeformula_model is None and not _codeformula_failed:
        try:
            from docling.datamodel.accelerator_options import AcceleratorOptions
            from docling.datamodel.pipeline_options import PdfPipelineOptions
            from docling.models.stages.code_formula.code_formula_vlm_model import (
                CodeFormulaVlmModel,
            )

            options = PdfPipelineOptions().code_formula_options.model_copy(
                update={"extract_code": False, "extract_formulas": True}
            )
            _codeformula_model = CodeFormulaVlmModel(
                enabled=True,
                enable_remote_services=False,
                artifacts_path=None,
                options=options,
                accelerator_options=AcceleratorOptions(),
            )
        except Exception as error:
            _codeformula_failed = True
            logger.warning("CodeFormula indisponível para cascata: {}", error)
    return _codeformula_model


def ocr_image_text(image_bytes: bytes) -> str:
    """Extrai texto bruto do recorte via OCR local; '' em falha."""
    engine = _get_ocr()
    if engine is None:
        return ""
    try:
        import numpy as np
        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        result = engine(np.array(img))
        texts = getattr(result, "txts", None) or []
        return " ".join(str(t) for t in texts)
    except Exception as error:
        logger.debug("OCR da cascata falhou: {}", error)
        return ""


def is_formula_image(image_bytes: bytes) -> bool:
    """Heurística barata: OCR do recorte contém símbolos matemáticos?"""
    return _looks_math(ocr_image_text(image_bytes))


_STRONG_MATH_CHARS = "√∫∑∏±×÷≤≥≠≈²³πθλμσωΔ∂∞"
_WEAK_MATH_CHARS = "=+^_/"


def _looks_math(text: str) -> bool:
    """Classifica texto de OCR como matemático; mais sensível que is_math_likely."""
    text = text.strip()
    if not text:
        return False

    strong = sum(text.count(ch) for ch in _STRONG_MATH_CHARS)
    if strong >= 1:
        return True

    weak = sum(text.count(ch) for ch in _WEAK_MATH_CHARS)
    if weak >= 2 and len(text) <= 120:
        return True

    # Matrizes/expressões simbólicas: muitos tokens de um só caractere
    tokens = text.split()
    if len(tokens) >= 4:
        single = sum(1 for tok in tokens if len(tok) == 1)
        if single / len(tokens) >= 0.6:
            return True

    return is_math_likely(text)


def looks_like_latex(text: str) -> bool:
    """Validação leve da saída do CodeFormula."""
    text = text.strip()
    if not text or len(text) > 2000:
        return False
    math_hints = ("\\", "=", "^", "_", "+", "-", "/")
    return any(hint in text for hint in math_hints)


def extract_latex_from_image(image_bytes: bytes) -> str:
    """Roda o CodeFormula diretamente no recorte; '' quando falha/inválido."""
    model = _get_codeformula()
    if model is None or model.engine is None:
        return ""
    try:
        from PIL import Image

        from docling.models.inference_engines.vlm import VlmEngineInput

        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        engine_input = VlmEngineInput(
            image=img,
            prompt="<formula>",
            temperature=0.0,
            # 512 é folgado p/ fórmulas e evita geração degenerada de minutos em CPU
            max_new_tokens=512,
            extra_generation_config={"skip_special_tokens": False},
        )
        outputs = model.engine.predict_batch([engine_input])
        latex = model._post_process([outputs[0].text])[0].strip()
        return latex if looks_like_latex(latex) else ""
    except Exception as error:
        logger.warning("CodeFormula falhou no recorte: {}", error)
        return ""


def try_extract_formula_locally(image_bytes: bytes) -> str:
    """Cascata completa: filtro OCR + CodeFormula. '' quando não é fórmula ou falhou."""
    if not image_bytes or not is_formula_image(image_bytes):
        return ""
    return extract_latex_from_image(image_bytes)


# ── Enriquecimento: LaTeX → MathML + verbalização pt-BR ──


def ensure_math_delimiters(latex: str) -> str:
    """Garante $...$ para que o parser estrutural reconheça o bloco como math."""
    text = latex.strip()
    if not text:
        return text
    if (text.startswith("$") and text.endswith("$")) or (
        text.startswith("\\[") and text.endswith("\\]")
    ):
        return text
    return f"${text}$"


def normalize_latex(latex: str) -> str:
    """Remove delimitadores ($, $$, \\[ \\]) e espaços redundantes."""
    text = latex.strip()
    if text.startswith("$$") and text.endswith("$$") and len(text) > 4:
        text = text[2:-2]
    elif text.startswith("$") and text.endswith("$") and len(text) > 2:
        text = text[1:-1]
    elif text.startswith("\\[") and text.endswith("\\]"):
        text = text[2:-2]
    if not text.strip("$ "):
        return ""
    return " ".join(text.split())


def latex_to_mathml(latex: str) -> str:
    """Converte LaTeX em MathML (latex2mathml); '' quando inválido."""
    latex = normalize_latex(latex)
    if not latex:
        return ""
    try:
        import latex2mathml.converter

        return latex2mathml.converter.convert(latex)
    except Exception as error:
        logger.warning("Conversão LaTeX→MathML falhou ({}): {}", latex[:60], error)
        return ""


# Traduções pt-BR para verbalização determinística (fallback sem LLM)
_VERBAL_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("\\begin{pmatrix}", " matriz: "),
    ("\\begin{bmatrix}", " matriz: "),
    ("\\end{pmatrix}", " fim da matriz "),
    ("\\end{bmatrix}", " fim da matriz "),
    ("\\frac", " fração "),
    ("\\sqrt", " raiz quadrada de "),
    ("\\sum", " somatório "),
    ("\\prod", " produtório "),
    ("\\int", " integral "),
    ("\\lim", " limite "),
    ("\\infty", " infinito "),
    ("\\pm", " mais ou menos "),
    ("\\times", " vezes "),
    ("\\cdot", " vezes "),
    ("\\div", " dividido por "),
    ("\\leq", " menor ou igual a "),
    ("\\geq", " maior ou igual a "),
    ("\\neq", " diferente de "),
    ("\\approx", " aproximadamente "),
    ("\\alpha", " alfa "),
    ("\\beta", " beta "),
    ("\\pi", " pi "),
    ("\\theta", " teta "),
    ("\\lambda", " lambda "),
    ("\\mu", " mi "),
    ("\\sigma", " sigma "),
    ("\\omega", " ômega "),
    ("\\Delta", " delta "),
    ("\\partial", " derivada parcial "),
    ("\\nabla", " nabla "),
    ("\\,", " "),
    ("\\\\", "; "),
    ("&", ", "),
    ("=", " igual a "),
    ("+", " mais "),
    ("^", " elevado a "),
    ("_", " índice "),
)


def verbalize_latex_fallback(latex: str) -> str:
    """Verbalização pt-BR determinística de LaTeX (sem LLM); melhor esforço."""
    import re

    text = normalize_latex(latex)
    if not text:
        return ""
    for token, spoken in _VERBAL_REPLACEMENTS:
        text = text.replace(token, spoken)
    text = re.sub(r"\\[a-zA-Z]+", " ", text)  # comandos não mapeados
    text = text.replace("{", " ").replace("}", " ")
    text = " ".join(text.split())
    return f"Fórmula: {text}" if text else ""
