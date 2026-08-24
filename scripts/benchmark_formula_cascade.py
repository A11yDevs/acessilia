"""Benchmark da cascata local de fórmulas: OCR (filtro) + CodeFormula (extração).

Testa imagens variadas — fórmulas (limpas e degradadas) e não-fórmulas (foto,
logo, texto corrido, diagrama, gráfico) — medindo onde a cascata acerta o
roteamento e a qualidade do LaTeX, sem nenhuma chamada de LLM.

Uso: python scripts/benchmark_formula_cascade.py
"""

from __future__ import annotations

import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import numpy as np

from backend.tools import formula_tools

WORKDIR = Path("var/temp/benchmark_formulas/cascade")
WORKDIR.mkdir(parents=True, exist_ok=True)

CODECOGS_URL = "https://latex.codecogs.com/png.image"

FORMULAS = [
    ("formula_simples", r"E=mc^2"),
    ("formula_bhaskara", r"x=\frac{-b\pm\sqrt{b^2-4ac}}{2a}"),
    ("formula_integral", r"\int_0^\infty e^{-x^2}\,dx=\frac{\sqrt{\pi}}{2}"),
    ("formula_somatorio", r"\sum_{n=1}^{\infty}\frac{1}{n^2}=\frac{\pi^2}{6}"),
    ("formula_matriz", r"A=\begin{pmatrix}a&b\\c&d\end{pmatrix}"),
]

REMOTE_IMAGES = [
    # (nome, url, é fórmula?)
    (
        "foto_gato",
        "https://upload.wikimedia.org/wikipedia/commons/thumb/3/3a/Cat03.jpg/500px-Cat03.jpg",
        False,
    ),
    (
        "logo_python",
        "https://upload.wikimedia.org/wikipedia/commons/thumb/c/c3/Python-logo-notext.svg/250px-Python-logo-notext.svg.png",
        False,
    ),
    (
        "circuito_eletronico",
        "https://commons.wikimedia.org/wiki/Special:FilePath/Circuit_diagram_6.jpg",
        False,
    ),
    (
        "partitura_musical",
        "https://commons.wikimedia.org/wiki/Special:FilePath/Alcina_-_Beginn_der_Arie_%22Verdi_prati%22.png",
        False,
    ),
]


@dataclass
class Case:
    name: str
    is_formula: bool
    expected_latex: str
    path: Path
    routed_to: str = ""
    latex: str = ""
    ocr_text: str = ""
    seconds: float = 0.0


def _download(url: str, dest: Path) -> None:
    if dest.exists():
        return
    req = urllib.request.Request(url, headers={"User-Agent": "acessilia-benchmark"})
    dest.write_bytes(urllib.request.urlopen(req, timeout=30).read())


def _download_formula(latex: str, dest: Path) -> None:
    if dest.exists():
        return
    query = urllib.parse.quote(r"\dpi{150}" + latex)
    _download(f"{CODECOGS_URL}?{query}", dest)


def _flatten_alpha(img: np.ndarray) -> np.ndarray:
    if img.ndim == 3 and img.shape[-1] == 4:
        alpha = img[:, :, 3:] / 255.0
        img = (img[:, :, :3] * alpha + 255 * (1 - alpha)).astype(np.uint8)
    return img


def _degrade(src: Path, dest: Path) -> None:
    img = _flatten_alpha(cv2.imread(str(src), cv2.IMREAD_UNCHANGED))
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), 2.5, 1.0)
    img = cv2.warpAffine(img, m, (w, h), borderValue=(255, 255, 255))
    img = cv2.resize(img, (int(w * 0.55), int(h * 0.55)))
    img = cv2.GaussianBlur(img, (3, 3), 0)
    noise = np.random.default_rng(42).normal(0, 12, img.shape).astype(np.int16)
    img = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    cv2.imwrite(str(dest), img, [cv2.IMWRITE_JPEG_QUALITY, 55])


def _make_text_paragraph(dest: Path) -> None:
    img = np.full((200, 640, 3), 255, np.uint8)
    lines = [
        "A acessibilidade digital garante que pessoas",
        "com deficiencia possam perceber, compreender,",
        "navegar e interagir com conteudos na web,",
        "conforme as diretrizes WCAG em vigor.",
    ]
    for i, line in enumerate(lines):
        cv2.putText(img, line, (20, 45 + i * 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (20, 20, 20), 2)
    cv2.imwrite(str(dest), img)


def _make_diagram(dest: Path) -> None:
    img = np.full((240, 640, 3), 255, np.uint8)
    for i, label in enumerate(["Entrada", "Processo", "Saida"]):
        x = 30 + i * 220
        cv2.rectangle(img, (x, 80), (x + 160, 160), (60, 60, 200), 2)
        cv2.putText(img, label, (x + 20, 128), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)
        if i < 2:
            cv2.arrowedLine(img, (x + 160, 120), (x + 220, 120), (0, 0, 0), 2)
    cv2.imwrite(str(dest), img)


def _make_bar_chart(dest: Path) -> None:
    img = np.full((300, 480, 3), 255, np.uint8)
    cv2.line(img, (50, 260), (450, 260), (0, 0, 0), 2)
    cv2.line(img, (50, 260), (50, 30), (0, 0, 0), 2)
    for i, (label, value) in enumerate([("2021", 120), ("2022", 170), ("2023", 90)]):
        x = 90 + i * 120
        cv2.rectangle(img, (x, 260 - value), (x + 70, 260), (180, 120, 40), -1)
        cv2.putText(img, label, (x + 5, 285), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1)
    cv2.imwrite(str(dest), img)


def _make_photo_like(dest: Path) -> None:
    """Substituto local quando o download remoto falha."""
    rng = np.random.default_rng(7)
    img = rng.integers(40, 220, (300, 400, 3), dtype=np.uint8)
    img = cv2.GaussianBlur(img, (31, 31), 0)
    cv2.circle(img, (200, 150), 80, (30, 90, 160), -1)
    cv2.imwrite(str(dest), img)


def build_cases() -> list[Case]:
    cases: list[Case] = []
    for name, latex in FORMULAS:
        clean = WORKDIR / f"{name}.png"
        _download_formula(latex, clean)
        cases.append(Case(name, True, latex, clean))

        degraded = WORKDIR / f"{name}_degradada.jpg"
        _degrade(clean, degraded)
        cases.append(Case(f"{name}_degradada", True, latex, degraded))

    for name, url, is_formula in REMOTE_IMAGES:
        path = WORKDIR / f"{name}{Path(url).suffix or '.png'}"
        try:
            _download(url, path)
        except Exception as error:
            print(f"  (download de {name} falhou: {error}; usando substituto local)")
            path = WORKDIR / f"{name}_local.png"
            _make_photo_like(path)
        cases.append(Case(name, is_formula, "", path))

    for name, maker in [
        ("texto_paragrafo", _make_text_paragraph),
        ("diagrama_fluxo", _make_diagram),
        ("grafico_barras", _make_bar_chart),
    ]:
        path = WORKDIR / f"{name}.png"
        maker(path)
        cases.append(Case(name, False, "", path))

    return cases


def main() -> None:
    cases = build_cases()
    print(f"{len(cases)} casos preparados. Rodando cascata...\n")

    for case in cases:
        image_bytes = case.path.read_bytes()
        start = time.time()
        case.ocr_text = formula_tools.ocr_image_text(image_bytes)
        is_math = bool(case.ocr_text) and formula_tools.is_formula_image(image_bytes)
        if is_math:
            case.latex = formula_tools.extract_latex_from_image(image_bytes)
            case.routed_to = "formula (local)" if case.latex else "LLM formula (fallback)"
        else:
            case.routed_to = "LLM visao (descricao)"
        case.seconds = time.time() - start
        print(f"  -> {case.name}: {case.routed_to} ({case.seconds:.1f}s)", flush=True)

    correct = 0
    print("\n## Resultados da cascata\n")
    print("| Caso | É fórmula? | Roteamento | Correto? | LaTeX extraído | Tempo (s) |")
    print("|---|---|---|---|---|---|")
    for case in cases:
        went_formula_path = case.routed_to.startswith(("formula", "LLM formula"))
        ok = went_formula_path == case.is_formula
        correct += ok
        latex = (case.latex or "—").replace("|", "\\|")
        if len(latex) > 60:
            latex = latex[:57] + "..."
        print(
            f"| {case.name} | {'sim' if case.is_formula else 'nao'} "
            f"| {case.routed_to} | {'✅' if ok else '❌'} | `{latex}` | {case.seconds:.1f} |"
        )

    total = len(cases)
    local_hits = sum(1 for c in cases if c.routed_to == "formula (local)")
    print(f"\nRoteamento correto: {correct}/{total}")
    print(f"Fórmulas resolvidas 100% local (zero LLM): {local_hits}/{sum(1 for c in cases if c.is_formula)}")
    print("\n### OCR capturado (debug)\n")
    for case in cases:
        print(f"- {case.name}: {case.ocr_text[:100] or '(vazio)'}")


if __name__ == "__main__":
    main()
