"""Valida a cascata de fórmulas num material real pt-BR já presente no repo.

Roda o DoclingStructurer em todas as páginas de
tests/fixtures/presentations/grandezas-e-medidas-42pgs.pdf (slide de física/
química, com fórmulas provavelmente coladas como imagem) e reporta a
distribuição de tipos de região e onde a cascata local capturou fórmulas.

Uso: python scripts/benchmark_formula_grandezas_medidas.py
"""

from __future__ import annotations

import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fitz

from backend.tools.structurer import DoclingStructurer

PDF = Path("tests/fixtures/presentations/grandezas-e-medidas-42pgs.pdf")

structurer = DoclingStructurer()
doc = fitz.open(str(PDF))

type_counts: Counter[str] = Counter()
formula_pages: list[tuple[int, str]] = []
total_start = time.time()
page_count = len(doc)

for i in range(page_count):
    page = doc[i]
    start = time.time()
    regions = structurer.extract_page_regions(page)
    elapsed = time.time() - start
    for region in regions:
        type_counts[region.type] += 1
        if region.type == "formula":
            formula_pages.append((i + 1, region.text.strip() or "(sem texto)"))
    print(f"pagina {i + 1}/{page_count}: {len(regions)} regioes em {elapsed:.1f}s "
          f"({Counter(r.type for r in regions)})")

total_elapsed = time.time() - total_start
doc.close()

print(f"\n### Resumo: {page_count} paginas em {total_elapsed:.1f}s\n")
print("Distribuicao de tipos de regiao:")
for region_type, count in type_counts.most_common():
    print(f"  {region_type}: {count}")

print(f"\nFormulas detectadas: {len(formula_pages)}")
for page_num, text in formula_pages:
    print(f"  pagina {page_num}: {text[:120]}")
