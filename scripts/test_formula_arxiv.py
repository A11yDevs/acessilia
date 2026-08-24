"""Teste rápido: extração de fórmulas em PDFs reais do arXiv (nativo, não sintético).

Baixa alguns papers de áreas diferentes (transformers, VAEs, GANs) para variar o
estilo de notação matemática, seleciona automaticamente a página com maior
densidade de símbolos matemáticos em cada um e roda o DoclingStructurer nela.

Uso: python scripts/test_formula_arxiv.py
"""

import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fitz

from backend.tools.structurer import DoclingStructurer

WORKDIR = Path("var/temp/benchmark_formulas")
WORKDIR.mkdir(parents=True, exist_ok=True)

# (nome, arxiv id, descricao)
PAPERS = [
    ("attention", "1706.03762", "Attention Is All You Need (transformers)"),
    ("vae", "1312.6114", "Auto-Encoding Variational Bayes (ELBO/KL)"),
    ("wgan", "1701.07875", "Wasserstein GAN (distancia/Lipschitz)"),
    ("gan", "1406.2661", "Generative Adversarial Networks (minimax)"),
]

_MATH_CHARS = set("√∫∑∏±×÷≤≥≠≈²³πθλμσωΔ∂∞∇")


def _download(arxiv_id: str, dest: Path) -> None:
    if dest.exists():
        return
    req = urllib.request.Request(
        f"https://arxiv.org/pdf/{arxiv_id}", headers={"User-Agent": "acessilia-benchmark"}
    )
    dest.write_bytes(urllib.request.urlopen(req, timeout=60).read())


def _best_math_page(doc: fitz.Document) -> int:
    """Escolhe a página com maior densidade de símbolos/expressões matemáticas."""
    best_index, best_score = 0, -1.0
    for i in range(len(doc)):
        text = doc[i].get_text()
        score = sum(text.count(c) for c in _MATH_CHARS) + text.count("=") * 0.3
        if score > best_score:
            best_index, best_score = i, score
    return best_index


structurer = DoclingStructurer()
total_formulas = 0
total_regions = 0

for name, arxiv_id, description in PAPERS:
    pdf_path = WORKDIR / f"{name}.pdf"
    print(f"\n=== {name} ({arxiv_id}): {description} ===")
    _download(arxiv_id, pdf_path)

    src = fitz.open(str(pdf_path))
    page_index = _best_math_page(src)
    page_pdf = WORKDIR / f"{name}_p{page_index + 1}.pdf"
    single = fitz.open()
    single.insert_pdf(src, from_page=page_index, to_page=page_index)
    single.save(str(page_pdf))
    single.close()
    src.close()

    doc = fitz.open(str(page_pdf))
    start = time.time()
    regions = structurer.extract_page_regions(doc[0])
    elapsed = time.time() - start
    doc.close()

    formulas = [r for r in regions if r.type == "formula"]
    total_regions += len(regions)
    total_formulas += len(formulas)
    print(f"pagina {page_index + 1}: {len(regions)} regioes em {elapsed:.1f}s, "
          f"{len(formulas)} formula(s) detectada(s)")
    for i, r in enumerate(formulas, 1):
        print(f"  --- formula {i} (enriched={r.metadata.get('formula_enriched')}) ---")
        print(f"  {r.text or '(sem texto)'}")

print(f"\n### Resumo: {total_formulas} formula(s) em {total_regions} regioes, "
      f"{len(PAPERS)} papers reais testados")
