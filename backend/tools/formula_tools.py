"""Detecção e extração local de fórmulas em imagens (sem LLM).

Cascata: OCR local (RapidOCR) filtra imagens com aparência matemática;
CodeFormula (Docling) extrai o LaTeX do recorte. LLM fica como último recurso.
"""

from __future__ import annotations

import io
import json
import math
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
import unicodedata
from typing import Any

from backend.tools.logger import logger

_ocr_engine: Any = None
_ocr_failed = False

CODEFORMULA_TIMEOUT_SECONDS = 120.0
_MAX_WORKER_RESULT_BYTES = 8192


def _codeformula_timeout() -> float:
    """Lê segundos positivos finitos por chamada; configuração inválida usa 120s."""
    try:
        timeout = float(os.environ.get("FORMULA_CODEFORMULA_TIMEOUT", "120"))
        if math.isfinite(timeout) and timeout > 0:
            return timeout
    except ValueError:
        pass
    logger.warning("FORMULA_CODEFORMULA_TIMEOUT inválido; usando 120s")
    return CODEFORMULA_TIMEOUT_SECONDS


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


_LETTERLIKE_MATH_CHARS = frozenset("ℂℍℕℙℚℝℤℓℏℎℑℜ℘")
_ASCII_MATH_FUNCTIONS = frozenset(("sin", "cos", "tan", "log", "ln", "exp", "sqrt"))
_MATH_TOKEN = re.compile(r"[^\W\d]\w*|\d+(?:\.\d+)?|[=+*/^<>|~()\[\]{},;\-]", re.UNICODE)


def _is_strong_math_char(ch: str) -> bool:
    """True if ch is a mathematical symbol or clearly mathematical letter/number."""
    category = unicodedata.category(ch)
    if category == "Sm":
        return ch not in "+-=<>|~"
    if ch in _LETTERLIKE_MATH_CHARS:
        return True
    if category in ("Ll", "Lu"):
        cp = ord(ch)
        if 0x0391 <= cp <= 0x03A9 or 0x03B1 <= cp <= 0x03C9:
            return True
        if 0x1D400 <= cp <= 0x1D7FF:
            return True
    if category == "No":
        cp = ord(ch)
        if 0x2070 <= cp <= 0x2089 or cp in (0xB9, 0xB2, 0xB3):
            return True
    return False


def _looks_math(text: str) -> bool:
    """Heurística de símbolos fortes ou estrutura de expressão, não validação."""
    text = text.strip()
    if not text:
        return False
    if any(unicodedata.category(ch) == "Sc" for ch in text):
        return False
    if re.search(r"(?:\w+://|www\.)", text, re.IGNORECASE):
        return False

    if any(_is_strong_math_char(ch) for ch in text):
        return True

    if len(text) > 120:
        return False
    tokens = _MATH_TOKEN.findall(text)
    if "".join(tokens) != re.sub(r"\s+", "", text):
        return False
    words = text.split()
    if len(words) >= 4 and all(len(word) == 1 and word.isalnum() for word in words):
        return True
    atoms = [token for token in tokens if token[0].isalnum() or token[0] == "_"]
    if not atoms:
        return False
    for previous, current in zip(tokens, tokens[1:]):
        if previous in atoms and current in atoms and previous not in _ASCII_MATH_FUNCTIONS:
            if not ("[" in tokens and "]" in tokens and previous.isdecimal() and current.isdecimal()):
                return False
    return any(token in _ASCII_MATH_FUNCTIONS for token in tokens) or any(
        token in "=+*/^<>|-" or token == "[" for token in tokens
    )


def looks_like_latex(text: str) -> bool:
    """Validação leve da saída do CodeFormula."""
    text = text.strip()
    if not text or len(text) > 2000:
        return False
    math_hints = ("\\", "=", "^", "_", "+", "-", "/")
    return any(hint in text for hint in math_hints)


def _codeformula_command(result_fd: int) -> list[str]:
    return [sys.executable, "-m", "backend.tools.formula_worker", str(result_fd)]


def extract_latex_from_image(image_bytes: bytes) -> str:
    """Extrai em processo descartável; orçamento inclui startup, carga e inferência."""
    if not image_bytes:
        return ""
    if not hasattr(os, "killpg"):
        logger.warning("CodeFormula isolado requer POSIX; usando fallback")
        return ""
    timeout = _codeformula_timeout()
    deadline = time.monotonic() + timeout
    try:
        with tempfile.TemporaryFile() as image, tempfile.TemporaryFile() as result:
            image.write(image_bytes)
            image.seek(0)
            process = subprocess.Popen(
                _codeformula_command(result.fileno()),
                stdin=image,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                pass_fds=(result.fileno(),),
                close_fds=True,
                shell=False,
                start_new_session=True,
            )
            try:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(process.args, timeout)
                returncode = process.wait(timeout=remaining)
            finally:
                # Não aguarda EOF de pipes herdados; encerra também descendentes do grupo.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                finally:
                    process.wait()
            if returncode != 0:
                logger.warning("CodeFormula falhou no recorte (status {})", returncode)
                return ""
            result.seek(0)
            payload = result.read(_MAX_WORKER_RESULT_BYTES + 1)
            if len(payload) > _MAX_WORKER_RESULT_BYTES:
                raise ValueError("oversized worker result")
            decoded = json.loads(payload)
            if not isinstance(decoded, dict) or set(decoded) != {"latex"}:
                raise ValueError("invalid worker result")
            latex = decoded["latex"]
            if not isinstance(latex, str):
                raise ValueError("invalid latex type")
            return latex.strip() if looks_like_latex(latex) else ""
    except subprocess.TimeoutExpired:
        logger.warning("CodeFormula excedeu orçamento de {}s; retornando vazio", timeout)
    except Exception:
        logger.warning("CodeFormula falhou no recorte ou retornou resultado inválido")
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
    except ImportError:
        logger.warning("latex2mathml indisponível; conversão LaTeX→MathML omitida")
        return ""
    except Exception:
        logger.warning("Conversão LaTeX→MathML falhou; usando fallback")
        return ""
    try:
        return latex2mathml.converter.convert(latex)
    except Exception:
        logger.warning("Conversão LaTeX→MathML falhou; usando fallback")
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
