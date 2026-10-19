"""LaTeX formula enrichment: normalization, MathML conversion and pt-BR verbalization.

Formula recognition from images runs on the Toolbox (``math.recognize``,
see backend/tools/toolbox_math_tools.py); this module only works on LaTeX.
"""

from __future__ import annotations

import re

from backend.tools.logger import logger


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
    """Strip outer math delimiters and collapse whitespace without rewriting math."""
    text = latex.strip()
    if text.startswith("$$") and text.endswith("$$") and len(text) > 4:
        text = text[2:-2]
    elif text.startswith("$") and text.endswith("$") and len(text) > 2:
        text = text[1:-1]
    elif text.startswith("\\[") and text.endswith("\\]"):
        text = text[2:-2]
    elif text.startswith("\\(") and text.endswith("\\)"):
        text = text[2:-2]
    if not text.strip("$ "):
        return ""
    return " ".join(text.split())


def wrap_latex(latex: str, display: bool = False) -> str:
    """Wrap normalized LaTeX in display ($$) or inline ($) delimiters."""
    norm = normalize_latex(latex)
    if not norm:
        return ""
    return f"$${norm}$$" if display else f"${norm}$"


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


# Tabela pt-BR de símbolos e comandos terminais (fallback determinístico, sem LLM).
# Comandos estruturais (\frac, \sqrt, ^, _, \begin/\end) são tratados pelo parser.
_VERBAL_REPLACEMENTS: dict[str, str] = {
    "\\begin{pmatrix}": "matriz:",
    "\\begin{bmatrix}": "matriz:",
    "\\end{pmatrix}": "fim da matriz",
    "\\end{bmatrix}": "fim da matriz",
    "\\sum": "somatório",
    "\\prod": "produtório",
    "\\int": "integral",
    "\\lim": "limite",
    "\\infty": "infinito",
    "\\pm": "mais ou menos",
    "\\times": "vezes",
    "\\cdot": "vezes",
    "\\div": "dividido por",
    "\\leq": "menor ou igual a",
    "\\geq": "maior ou igual a",
    "\\neq": "diferente de",
    "\\approx": "aproximadamente",
    "\\alpha": "alfa",
    "\\beta": "beta",
    "\\pi": "pi",
    "\\theta": "teta",
    "\\lambda": "lambda",
    "\\mu": "mi",
    "\\sigma": "sigma",
    "\\omega": "ômega",
    "\\Delta": "delta",
    "\\partial": "derivada parcial",
    "\\nabla": "nabla",
    "\\,": "",
    "\\\\": ";",
    "&": ",",
    "=": "igual a",
    "+": "mais",
    "-": "menos",
    "^": "elevado a",
    "_": "índice",
}

_LATEX_TOKEN = re.compile(r"\\[a-zA-Z]+|\\.|\d+(?:\.\d+)?|\s+|.", re.DOTALL)


class _LatexVerbalizer:
    """Descida recursiva sobre tokens LaTeX que produz palavras faladas (melhor esforço)."""

    def __init__(self, latex: str) -> None:
        self.tokens = [t for t in _LATEX_TOKEN.findall(latex) if not t.isspace() and t != "\\"]
        self.pos = 0

    def run(self) -> list[str]:
        return self._sequence(stop=None)

    def _sequence(self, stop: str | None) -> list[str]:
        words: list[str] = []
        while self.pos < len(self.tokens):
            token = self.tokens[self.pos]
            if token == stop:
                self.pos += 1
                return words
            if token == "}":
                self.pos += 1  # fechamento sem abertura correspondente
                continue
            words.extend(self._atom())
        return words

    def _atom(self) -> list[str]:
        token = self.tokens[self.pos]
        self.pos += 1
        if token == "{":
            return self._sequence(stop="}")
        if token == "\\frac":
            return self._fraction(self._argument(), self._argument())
        if token == "\\sqrt":
            return self._root()
        if token in ("\\begin", "\\end"):
            environment = "".join(self._argument())
            return _VERBAL_REPLACEMENTS.get(f"{token}{{{environment}}}", "").split()
        if token in ("^", "_"):
            return _VERBAL_REPLACEMENTS[token].split() + self._argument()
        if token in _VERBAL_REPLACEMENTS:
            return _VERBAL_REPLACEMENTS[token].split()
        if token.startswith("\\"):
            return []  # comando desconhecido: descartado, argumentos seguem falados
        return [token]

    def _argument(self) -> list[str]:
        if self.pos >= len(self.tokens) or self.tokens[self.pos] == "}":
            return []
        return self._atom()

    @staticmethod
    def _fraction(numerator: list[str], denominator: list[str]) -> list[str]:
        if not numerator or not denominator:
            return numerator + denominator
        if len(numerator) == 1 and len(denominator) == 1:
            return [*numerator, "sobre", *denominator]
        return [*numerator[:-1], numerator[-1] + ",", "dividido", "por", *denominator]

    def _root(self) -> list[str]:
        index: list[str] = []
        if self.pos < len(self.tokens) and self.tokens[self.pos] == "[":
            self.pos += 1
            index = self._sequence(stop="]")
        radicand = self._argument()
        if not index:
            prefix = ["raiz", "quadrada", "de"]
        elif index == ["3"]:
            prefix = ["raiz", "cúbica", "de"]
        else:
            prefix = ["raiz", "de", "índice", *index, "de"]
        return prefix + radicand


def _join_spoken_words(words: list[str]) -> str:
    joined: list[str] = []
    for word in words:
        if word in (",", ";") and joined:
            joined[-1] += word
        else:
            joined.append(word)
    return " ".join(joined)


def verbalize_latex_fallback(latex: str) -> str:
    """Verbalização pt-BR estrutural e determinística de LaTeX (melhor esforço, não validada)."""
    text = normalize_latex(latex)
    if not text:
        return ""
    try:
        words = _LatexVerbalizer(text).run()
    except Exception:
        logger.debug("Verbalização estrutural falhou; usando achatamento literal")
        words = re.sub(r"\\[a-zA-Z]+|[\\{}]", " ", text).split()
    spoken = _join_spoken_words(words)
    return f"Fórmula: {spoken}" if spoken else ""
