"""Stress test fim-a-fim do enriquecimento de fórmulas (fases 2-3).

Passa entradas reais (incluindo saídas defeituosas do CodeFormula capturadas
no benchmark) e casos extremos pelo pipeline: texto → bloco math → MathML →
verbalização → HTML/TXT. Reporta onde a arquitetura quebra.

Uso: python scripts/benchmark_formula_enrichment.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.pipeline.canonical_builder import build_canonical_document
from backend.pipeline.validators import validate_canonical_document
from backend.export.renderers.html_renderer import _render_block as render_html
from backend.export.renderers.txt_renderer import _render_block as render_txt

# (nome, LaTeX como sai do pipeline, esperado detectar como math?)
CASES = [
    # Saídas reais do CodeFormula (benchmark anterior)
    ("codeformula_simples", r"E = m c ^ { 2 }", True),
    ("codeformula_bhaskara", r"x = \frac { - b \pm \sqrt { b ^ { 2 } - 4 a c } } { 2 a }", True),
    ("codeformula_bhaskara_ruim", r"x = \frac { - b \pm \sqrt { b } - 1 a c } { 2 }", True),
    ("codeformula_integral", r"\int _ { 0 } ^ { \infty } e ^ { - x ^ { 2 } } \, d x = \frac { \sqrt { \pi } } { 2 }", True),
    ("codeformula_somatorio_lixo", r"\sum \lim i t s _ { n = 1 } ^ { 1 } \frac { 1 } { n ^ { 2 } }", True),
    ("codeformula_matriz", r"A = \begin{pmatrix} a & b \\ c & d \end{pmatrix}", True),
    # Saídas do DataAgent/LLM (com delimitadores, conforme prompt)
    ("llm_com_dollar", r"$E=mc^2$", True),
    ("llm_display", r"$$\frac{a+b}{c+d}$$", True),
    ("llm_ilegivel", r"$x = [ilegivel] + 2$", True),
    # Casos extremos
    ("latex_malformado", r"\frac{a}{", True),
    ("latex_gigante", "$" + " + ".join(f"x_{{{i}}}" for i in range(200)) + "$", True),
    ("comando_desconhecido", r"\foobar{x} + \bazqux{y} = \sum z", True),
    ("unicode_direto", "α² + β² = γ²", False),  # sem comandos LaTeX nem $
    # Falsos positivos potenciais
    ("preco_em_texto", "O produto custa $10 e o frete custa $5 no total.", False),
    ("texto_normal", "A acessibilidade digital é um direito de todos.", False),
]


def main() -> None:
    print("| Caso | Virou math? | Esperado | MathML? | Verbalização | HTML ok? | TXT | ms |")
    print("|---|---|---|---|---|---|---|---|")

    problems: list[str] = []
    for name, text, expect_math in CASES:
        start = time.time()
        doc = build_canonical_document(f"# Doc\n\n{text}\n", title="Doc")
        errors = validate_canonical_document(doc)
        blocks = [
            b
            for s in doc["sections"]
            for b in s.get("blocks", [])
        ]
        math_blocks = [b for b in blocks if b.get("type") == "math"]
        is_math = bool(math_blocks)
        elapsed_ms = (time.time() - start) * 1000

        mathml_ok = verbal = html_ok = txt_out = "—"
        if math_blocks:
            block = math_blocks[0]
            mathml_ok = "sim" if block.get("metadata", {}).get("mathml") else "NAO"
            verbal = (block.get("alt_text") or "(vazio)")[:45]
            try:
                html = render_html(block, {})
                html_ok = "sim" if 'role="math"' in html else "parcial"
            except Exception as e:
                html_ok = f"ERRO: {e}"
            txt_out = (render_txt(block) or ["(vazio)"])[0][:35]

        routing_ok = is_math == expect_math
        if not routing_ok:
            problems.append(f"{name}: detecção math={is_math}, esperado={expect_math}")
        if errors:
            problems.append(f"{name}: schema inválido: {errors[:2]}")
        if is_math and mathml_ok == "NAO":
            problems.append(f"{name}: MathML não gerado")

        flag = "" if routing_ok else " ❌"
        print(
            f"| {name}{flag} | {'sim' if is_math else 'nao'} | {'sim' if expect_math else 'nao'} "
            f"| {mathml_ok} | {verbal} | {html_ok} | {txt_out} | {elapsed_ms:.0f} |"
        )

    print(f"\n### Gargalos encontrados ({len(problems)})\n")
    for p in problems or ["nenhum"]:
        print(f"- {p}")


if __name__ == "__main__":
    main()
