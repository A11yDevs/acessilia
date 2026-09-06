"""Benchmark de extração de fórmulas: Docling/CodeFormula vs LLM de visão.

Baixa imagens de fórmulas renderizadas (CodeCogs), gera variantes degradadas
(simulando scans ruins), embute cada uma em um PDF de página única e roda o
DoclingStructurer com formula enrichment. Com --llm, compara com o DataAgent.

Uso:
    python scripts/benchmark_formula_extraction.py [--llm] [--keep]
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cv2
import fitz
import numpy as np

from backend.tools.structurer import DoclingStructurer

CODECOGS_URL = "https://latex.codecogs.com/png.image"

# (nome, LaTeX de referência)
FORMULAS = [
    ("simples", r"E=mc^2"),
    ("bhaskara", r"x=\frac{-b\pm\sqrt{b^2-4ac}}{2a}"),
    ("integral", r"\int_0^\infty e^{-x^2}\,dx=\frac{\sqrt{\pi}}{2}"),
    ("somatorio", r"\sum_{n=1}^{\infty}\frac{1}{n^2}=\frac{\pi^2}{6}"),
    ("matriz", r"A=\begin{pmatrix}a&b\\c&d\end{pmatrix}"),
    ("maxwell", r"\nabla\times\vec{B}=\mu_0\vec{J}+\mu_0\varepsilon_0\frac{\partial\vec{E}}{\partial t}"),
]


@dataclass
class Case:
    name: str
    variant: str  # "limpa" | "degradada"
    expected: str
    image_path: Path
    pdf_path: Path | None = None
    detected_as_formula: bool = False
    docling_latex: str = ""
    docling_seconds: float = 0.0
    llm_latex: str = ""
    all_region_types: list[str] = field(default_factory=list)


def download_formula(latex: str, dest: Path) -> None:
    query = urllib.parse.quote(r"\dpi{150}" + latex)
    url = f"{CODECOGS_URL}?{query}"
    req = urllib.request.Request(url, headers={"User-Agent": "acessilia-benchmark"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        dest.write_bytes(resp.read())


def degrade(src: Path, dest: Path) -> None:
    """Simula scan ruim: fundo, rotação leve, blur, ruído e recompressão JPEG."""
    img = cv2.imread(str(src), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise RuntimeError(f"Falha ao ler {src}")
    if img.shape[-1] == 4:  # alpha -> fundo branco
        alpha = img[:, :, 3:] / 255.0
        img = (img[:, :, :3] * alpha + 255 * (1 - alpha)).astype(np.uint8)

    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), 2.5, 1.0)
    img = cv2.warpAffine(img, m, (w, h), borderValue=(255, 255, 255))
    img = cv2.resize(img, (int(w * 0.55), int(h * 0.55)))
    img = cv2.GaussianBlur(img, (3, 3), 0)
    noise = np.random.default_rng(42).normal(0, 12, img.shape).astype(np.int16)
    img = np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)
    cv2.imwrite(str(dest), img, [cv2.IMWRITE_JPEG_QUALITY, 55])


def build_pdf(image_path: Path, dest: Path) -> None:
    """Página A4 com um parágrafo e a fórmula centralizada, como num documento real."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text(
        (72, 100),
        "Considere a seguinte expressao matematica apresentada abaixo:",
        fontsize=11,
    )
    pix = fitz.Pixmap(str(image_path))
    scale = min(300 / pix.width, 1.5)
    w, h = pix.width * scale, pix.height * scale
    x0 = (595 - w) / 2
    page.insert_image(fitz.Rect(x0, 160, x0 + w, 160 + h), filename=str(image_path))
    page.insert_text(
        (72, 200 + h),
        "A equacao acima e amplamente utilizada na literatura.",
        fontsize=11,
    )
    doc.save(str(dest))
    doc.close()


def run_docling(case: Case, structurer: DoclingStructurer) -> None:
    doc = fitz.open(str(case.pdf_path))
    try:
        start = time.time()
        regions = structurer.extract_page_regions(doc[0])
        case.docling_seconds = time.time() - start
    finally:
        doc.close()

    case.all_region_types = [r.type for r in regions]
    for region in regions:
        if region.type == "formula":
            case.detected_as_formula = True
            if region.text.strip():
                case.docling_latex = region.text.strip()
            break


async def run_llm(case: Case) -> None:
    from backend.agents.data_agent import DataAgent

    image_bytes = case.image_path.read_bytes()
    result = await DataAgent().process_region(image_bytes, "formula", page_num=1)
    case.llm_latex = result.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--llm", action="store_true", help="compara com DataAgent (requer API)")
    parser.add_argument("--keep", action="store_true", help="mantem artefatos em var/temp")
    args = parser.parse_args()

    if args.keep:
        workdir = Path("var/temp/benchmark_formulas")
        workdir.mkdir(parents=True, exist_ok=True)
    else:
        tmp = tempfile.TemporaryDirectory()
        workdir = Path(tmp.name)

    cases: list[Case] = []
    print("Baixando formulas do CodeCogs...")
    for name, latex in FORMULAS:
        clean = workdir / f"{name}_limpa.png"
        download_formula(latex, clean)
        cases.append(Case(name, "limpa", latex, clean))

        degraded = workdir / f"{name}_degradada.jpg"
        degrade(clean, degraded)
        cases.append(Case(name, "degradada", latex, degraded))

    print(f"{len(cases)} casos preparados. Gerando PDFs e rodando Docling...")
    structurer = DoclingStructurer()
    for case in cases:
        case.pdf_path = workdir / f"{case.name}_{case.variant}.pdf"
        build_pdf(case.image_path, case.pdf_path)
        print(f"  -> {case.name} ({case.variant})...", flush=True)
        run_docling(case, structurer)

    if args.llm:
        print("Rodando LLM de visao (DataAgent)...")
        for case in cases:
            print(f"  -> {case.name} ({case.variant})...", flush=True)
            asyncio.run(run_llm(case))

    print("\n## Resultados\n")
    header = "| Caso | Variante | Detectou formula? | LaTeX Docling | Tempo (s) |"
    sep = "|---|---|---|---|---|"
    if args.llm:
        header += " LaTeX LLM |"
        sep += "---|"
    print(header)
    print(sep)
    for case in cases:
        detected = "sim" if case.detected_as_formula else f"NAO ({','.join(set(case.all_region_types))})"
        latex = case.docling_latex.replace("|", "\\|") or "(vazio)"
        row = (
            f"| {case.name} | {case.variant} | {detected} "
            f"| `{latex}` | {case.docling_seconds:.1f} |"
        )
        if args.llm:
            row += f" `{case.llm_latex.replace('|', chr(92) + '|') or '(vazio)'}` |"
        print(row)

    print("\n### Referencia (ground truth)\n")
    for name, latex in FORMULAS:
        print(f"- {name}: `{latex}`")


if __name__ == "__main__":
    main()
