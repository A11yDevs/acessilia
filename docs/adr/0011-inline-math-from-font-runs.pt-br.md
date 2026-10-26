# 0011. Math inline viaja como `$…$` na prosa e é detectado pelas fontes matemáticas do PDF

Você também pode ler esta documentação em **inglês**: [English](0011-inline-math-from-font-runs.md)

- **Status:** Aceito
- **Data:** 2026-10-26
- **Componentes:** docstruct, core, SDK, Toolbox
- **Issues:** #265

## Contexto

No caso de referência `036` (`velocidade-instantanea.pdf`), as fórmulas dentro das frases chegam a todas as saídas como texto espaçado. "s ( t ) = t 3" é lido "t 3", e `s0 ∈ R` perde o índice e o ℝ. O scorecard de `python -m scripts.bench.math_case` dá 0% em "Inline expressions as math". Duas lacunas distintas causam isso.

**Saída.** Nada renderiza uma fórmula dentro da prosa:

- o AST Pandoc quebra o texto em `Str` (`docstruct.export.pandoc_ast._meta_inlines`);
- o HTML escapa o texto;
- o TXT o imprime como está.

Nenhum código de produção emite `InlineMath`. O modelo de OCR de página já escreve math inline como `$…$`. Esse caminho está ativo hoje, e os `$` chegam literais ao leitor.

**Detecção.** O Docling não devolve região de fórmula inline para esse PDF: não há grupo `inline`, e o texto do parágrafo vem achatado. O próprio PDF traz o sinal. As variáveis estão em `CMMI12`, `∈` em `CMSY10`, `ℝ` em `MSBM10`, e índices e expoentes estão em `CMR8`, fora da linha de base. Nada lê fontes hoje.

Opções consideradas para a detecção:

1. **Rotear páginas com muita math para o MinerU (fusão).** O provider MinerU da Toolbox junta o conteúdo dos spans sem delimitadores, então o math inline dele também vem achatado. O roteador de páginas (`docstruct.fusion.adjudication.decide_v1`) também não conta um `$` simples.
2. **Ligar o enriquecimento de fórmulas do Docling.** Ele reconhece as regiões de fórmula que o modelo de layout encontra, e esse modelo não encontra nenhuma inline aqui.
3. **Ler os spans de texto com fonte e geometria** e montar o LaTeX a partir deles. Funciona para os PDFs TeX, que são a maior parte do material de matemática, e não custa chamada de modelo.

## Decisão

- **A representação é `$…$` na prosa.** Math inline em parágrafo, item de lista ou callout é escrito no texto como `$…$` (ou `\(…\)`). A regra de separação é `docstruct.text.math_spans`: o `tex_math_dollars` do Pandoc, mais a exigência de que o `$` de abertura não venha depois de um caractere de palavra (letra, dígito ou `_`), de uma barra invertida ou de outro `$`, para que `R$ 10,00` continue texto. Em texto puro, uma linha com um span `$…$` no meio da prosa é um parágrafo, não um bloco math (`docstruct.blocks.parser`).
- **O enriquecimento canônico converte cada span uma vez.** Ele chama `math.convert` e `math.verbalize`, com cache por documento, e guarda o resultado em `block.metadata["inline_math"]` como `{source, latex, mathml?, speech?}`, indexado pelo LaTeX de origem. A fala inline não leva o rótulo "Fórmula:" (`MathEnricher.verbalize_inline`).
- **Os exportadores devem renderizar o span como math, nunca com os delimitadores literais:**
  - **AST Pandoc** (PDF/UA, DOCX): `InlineMath`, envolto no span de alt de fórmula quando há fala.
  - **HTML:** um span `role="math"` rotulado com a fala, como num bloco math. Ele contém o MathML sanitizado, ou o LaTeX quando não há MathML.
  - **TXT/MP3:** a fala. Sem fala, o LaTeX sem delimitadores.
- **A detecção lê as fontes matemáticas do PDF** (opção 3). Ler fontes é operacional, então pelo [ADR-0003](0003-remote-only-operational-capabilities.pt-br.md) é uma capability da Toolbox (`document.text.spans`). Montar o LaTeX a partir dos spans é um algoritmo puro da docstruct. O core casa cada corrida com o texto do elemento e insere o `$…$`. Uma corrida que ele não consegue casar deixa o texto como está. `INLINE_MATH_DETECTION` (`fonts`, o padrão, ou `off`) liga o passo e faz parte da chave do cache de processamento. Uma barra de negação que uma corrida compõe (`h \neq 0`) fica registrada no seu elemento de barra solta, para que a reanexação das barras soltas no reparo Unicode não componha outro `=` do parágrafo.

## Consequências

- Qualquer produtor que escreva `$…$` (OCR de página, MinerU, o detector de fontes) passa a ter saída em math sem trabalho extra, desde que o documento passe pelo build canônico com um enricher de math.
- A conversão só acontece no build canônico. Um documento canônico que o pulou (por exemplo, um passado aos exportadores como dict) não tem `inline_math`. Seus spans ainda viram math no AST Pandoc, mas o HTML marca o LaTeX com `role="math"` sem MathML nem fala, e o TXT lê o LaTeX sem delimitadores. A exportação não chama a Toolbox de novo.
- Um span que o `math.convert` rejeita ainda vira math no AST Pandoc. O degrade-and-retry do PDF/UA (`degrade_math_to_text`) cobre uma falha de compilação, como já faz para blocos math.
- A detecção só cobre PDFs com fonte matemática na camada de texto (TeX e a maior parte da math tipografada). Páginas escaneadas passam pelo modelo de OCR de página, que já emite `$…$`.
- Fora do escopo:
  - `inline_math_promote` (um parágrafo só de math vira display) continua sem uso.
  - O `FORMULA_RE` do roteador de fusão continua ignorando um `$` simples.
  - Células e legendas de tabela mantêm o `$…$` como texto (a #260 cuida de math em tabelas).
- Conformidade: `tests/test_inline_math.py` cobre a regra de separação e cada exportador. A detecção é medida pelo scorecard de referência de math; a meta é "Inline expressions as math" ≥ 90% no caso 036.
