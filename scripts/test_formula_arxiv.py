"""Teste rápido: extração de fórmulas em PDF real do arXiv (nativo, não sintético)."""

import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fitz

from backend.tools.structurer import DoclingStructurer

WORKDIR = Path("var/temp/benchmark_formulas")
WORKDIR.mkdir(parents=True, exist_ok=True)
PDF = WORKDIR / "attention.pdf"

if not PDF.exists():
    print("Baixando arXiv 1706.03762 (Attention is All You Need)...")
    req = urllib.request.Request(
        "https://arxiv.org/pdf/1706.03762", headers={"User-Agent": "acessilia-benchmark"}
    )
    PDF.write_bytes(urllib.request.urlopen(req, timeout=60).read())

# Página 4 (índice 3): fórmula da atenção softmax(QK^T/sqrt(d_k))V
src = fitz.open(str(PDF))
page_pdf = WORKDIR / "attention_p4.pdf"
single = fitz.open()
single.insert_pdf(src, from_page=3, to_page=3)
single.save(str(page_pdf))
single.close()
src.close()

structurer = DoclingStructurer()
doc = fitz.open(str(page_pdf))
start = time.time()
regions = structurer.extract_page_regions(doc[0])
elapsed = time.time() - start
doc.close()

print(f"\n{len(regions)} regioes em {elapsed:.1f}s")
formulas = [r for r in regions if r.type == "formula"]
print(f"{len(formulas)} formulas detectadas:\n")
for i, r in enumerate(formulas, 1):
    print(f"--- formula {i} (enriched={r.metadata.get('formula_enriched')}) ---")
    print(r.text or "(sem texto)")
    print()
