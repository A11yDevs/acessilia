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

- **A representação é `$…$` na prosa.** Math inline em parágrafo, item de lista, callout ou tabela é escrito no texto como `$…$` (ou `\(…\)`). A prosa de uma tabela é a sua legenda mais o texto de cada célula (#260). A regra de separação é `docstruct.text.math_spans`: o `tex_math_dollars` do Pandoc, mais a exigência de que o `$` de abertura não venha depois de um caractere de palavra (letra, dígito ou `_`), de uma barra invertida ou de outro `$`, para que `R$ 10,00` continue texto. Em texto puro, uma linha com um span `$…$` no meio da prosa é um parágrafo, não um bloco math (`docstruct.blocks.parser`).
- **O enriquecimento canônico converte cada span uma vez.** Ele chama `math.convert` e `math.verbalize`, com cache por documento, e guarda o resultado em `block.metadata["inline_math"]` como `{source, latex, mathml?, speech?}`, indexado pelo LaTeX de origem. Numa tabela as entradas ficam no bloco, não nas células, porque o sanitizador da exportação reconstrói cada dict de célula. A fala inline não leva o rótulo "Fórmula:" (`MathEnricher.verbalize_inline`).
- **Os exportadores devem renderizar o span como math, nunca com os delimitadores literais:**
  - **AST Pandoc** (PDF/UA, DOCX): `InlineMath`, envolto no span de alt de fórmula quando há fala.
  - **HTML:** o MathML sanitizado recebe seu próprio `aria-label` com a fala; só o fallback em LaTeX usa um span rotulado com `role="math"`.
  - **TXT/MP3:** a fala. Sem fala, o LaTeX sem delimitadores.
- **A detecção lê as fontes matemáticas do PDF** (opção 3). Ler fontes é operacional, então pelo [ADR-0003](0003-remote-only-operational-capabilities.pt-br.md) é uma capability da Toolbox (`document.text.spans`). Montar o LaTeX a partir dos spans é um algoritmo puro da docstruct. O core casa cada corrida com o texto do elemento e insere o `$…$`. Uma corrida que ele não consegue casar deixa o texto como está. `INLINE_MATH_DETECTION` (`fonts`, o padrão, ou `off`) liga o passo e faz parte da chave do cache de processamento. Uma barra de negação que uma corrida compõe (`h \neq 0`) fica registrada no seu elemento de barra solta, para que a reanexação das barras soltas no reparo Unicode não componha outro `=` do parágrafo.
- **As células de tabela são detectadas pelos mesmos spans** (#260). O passo roda depois do enriquecimento de tabelas, porque uma tabela relida a partir da imagem ganha células novas. As células não têm caixa, então cada corrida das linhas da tabela vai para a célula cujo texto a contém (`assign_runs_to_cells`). Uma célula que é exatamente a corrida tem preferência, e uma corrida que células de textos diferentes contêm fica de fora. Duas linhas que são cada uma uma corrida inteira, menores que o texto ao redor e empilhadas sobre o mesmo centro, viram uma corrida `\frac`: uma fração numa célula de cabeçalho não tem traço na camada de texto. Uma vírgula decimal em fonte de math pode ter o espaço do TeX antes dos seus dígitos (`$-0,0833$`); ela continua `,` simples, porque o `math.convert` lê `0{,}0833` como `0,083` e `3`. Os passos de prosa e de tabela leem os spans por um só leitor, então cada página é buscada uma vez.
- **O passo da prosa é uma ação planejada** (#640, M4b), a obrigação do documento `mark-inline-math` com o método `inline-math-marker`, e o passo das tabelas faz parte do enriquecimento de tabelas (M2). Até a 0.3.19 o passo da prosa rodava antes do planejamento, e os dois passos rodavam de novo numa passagem transitória depois da execução (#599), porque o `rescue-omitted` insere blocos do provedor primário enquanto o plano roda e o build canônico só converte os spans que o manifesto executado carrega. O passo planejado substitui as duas:
  - **Alvos.** Num PDF, os elementos de prosa com caixas que nenhuma detecção marcou ainda, os elementos de prosa sem caixas que já trazem `$…$` (evidência que a detecção não lê) e as tabelas marcadas `inline_math_stale` (adotadas do provedor secundário depois das suas marcas). Um elemento que carrega `metadata["inline_math_detection"]` não volta a ser alvo, enquanto um que nunca recebeu marca continua candidato.
  - **Blocos acrescentados.** Um bloco que o plano acrescenta recebe o passo num replanejamento, pela reconciliação dos passos do documento: uma execução concluída com esse trabalho replaneja por ele como descoberta, dentro de `max_discovery_replans`. Uma tabela adotada de novo depois de as suas marcas ficarem obsoletas entra numa obrigação nova, porque uma satisfeita não a cobre mais.
  - **As conversões de fórmula esperam por ele** (`waiting_kinds`), porque marcam produtos implícitos com as variáveis que as suas marcas dão. Quando o passo encontra evidência de variáveis depois de uma conversão já ter rodado (uma marca sua, ou um span `$…$` que um alvo traz), as conversões (`metadata["mathml"]`, `metadata["verbalization"]`) são descartadas, para que o build canônico as refaça com o manifesto final. Antes de qualquer conversão rodar, nada é descartado.
  - **Degradação.** O passo é não crítico: um bloco que fica sem as suas marcas mantém o texto do extrator, e um passo esgotado não segura as conversões. O passo lê os spans pelo leitor da execução (`RunPorts.services`), compartilhado com o passo das tabelas, então uma página já buscada nessa execução não é pedida de novo; uma retomada reconstrói esse cache em memória. Um leitor que falha registra `inline_math_detection = "unavailable"` e o job não falha. Com `INLINE_MATH_DETECTION=off` o passo não marca nada e informa `detection: off`, mas ainda pesa a evidência que os seus alvos trazem.

## Consequências

- Qualquer produtor que escreva `$…$` (OCR de página, MinerU, o detector de fontes) passa a ter saída em math sem trabalho extra, desde que o documento passe pelo build canônico com um enricher de math.
- A conversão só acontece no build canônico. Um documento canônico que o pulou (por exemplo, um passado aos exportadores como dict) não tem `inline_math`. Seus spans ainda viram math no AST Pandoc, mas o HTML marca o fallback em LaTeX com `role="math"` sem MathML nem fala, e o TXT lê o LaTeX sem delimitadores. A exportação não chama a Toolbox de novo.
- Um span que o `math.convert` rejeita ainda vira math no AST Pandoc. O degrade-and-retry do PDF/UA (`degrade_math_to_text`) cobre uma falha de compilação, como já faz para blocos math.
- O build canônico transforma um parágrafo cujo texto inteiro é um único span inline (`$s(t) = t^3$`) num bloco `math` de exibição, reaproveitando a conversão do span quando o bloco já a traz. Qualquer texto em volta do span, mesmo um ponto final, o mantém inline. `build_canonical_document(inline_math_promote=False)` desliga a promoção; o padrão segue `FusionPolicy.inline_math_promote` (#296).
- O roteador da fusão conta um span com um único `$` como fórmula na página (`decide_v0`/`decide_v1`, #297). O classificador de blocos e o oráculo de texto só tomam um bloco como fórmula quando ele é um único span; prosa que contém um span continua texto, então os critérios de comprimento e qualidade seguem escolhendo entre os providers. Entre parágrafos de comprimento comparável, vence o que manteve as fórmulas como `$…$`. Moeda como `R$ 10,00` nunca é span.
- A detecção só cobre PDFs com fonte matemática na camada de texto (TeX e a maior parte da math tipografada). Páginas escaneadas passam pelo modelo de OCR de página, que já emite `$…$`.
- Conformidade: `tests/test_inline_math.py` cobre a regra de separação e cada exportador, e `tests/test_table_inline_math.py` cobre células e legendas de tabela; `tests/test_table_inline_math_marking.py` e `libs/docstruct/tests/test_table_inline_math_detection.py` cobrem a detecção nas células. A detecção é medida pelo scorecard de referência de math; a meta é "Inline expressions as math" ≥ 90% no caso 036.
