# Taxonomia de erros — v3a-clean (dev-986 md2md)

## A. Texto — blocos casados (pred != '' e gt != '')
blocos=10914 massa de erro total=3775 (texto por página ≈ 1 − média do edit por bloco)

| categoria | blocos | massa de erro | % da massa | exemplo (gt → pred) |
|---|---|---|---|---|
| GT sem par (pred vazio) | 2014 | 2014 | 53% | adf0ea9c `21` → `` |
| bloco errado/OCR lixo (edit > 0.5) | 1002 | 936 | 25% | adf0ea9c `Introduction` → `Figurel.7a` |
| pred truncado (subconjunto do GT) | 603 | 306 | 8% | adf0ea9c `*Figure 1.8b*⏎**Le Corbusier's Villa Church at Ville d'Avray, living r` → `Figure 1.8b Le Corbusier's Villa Church at Ville d'Avray, living room.` |
| erros médios de OCR (0.1 < edit ≤ 0.5) | 548 | 155 | 4% | adf0ea9c `The term space is used in the most literal way. Not like a space, or a` → `The term space is used in the most literal way. Not like a space, or a` |
| pred extra (sem GT) | 107 | 107 | 3% | 38a7285c `` → `Elo EdtVew Favorites Iools HelpBackStopNoool Noo00oo! NooFigure 5.4209` |
| GT fundido (vários blocos GT → 1 pred) | 311 | 97 | 3% | adf0ea9c `*Figure 1.8a*⏎**Le Corbusier's Ozenfant studio.**18` → `Figure 1.8a Le Corbusier's Ozenfant studio.` |
| pred com conteúdo extra (superconjunto) | 165 | 77 | 2% | adf0ea9c `A view of *A View of the World...* or *A View of the World...* as proj` → `Figure 1.2a A view of A View of the World... or A View of the World...` |
| erros leves de OCR (edit ≤ 0.1) | 903 | 29 | 1% | adf0ea9c `It should be clear that there is no psychoanalytic architecture, only ` → `It should be clear that there is no psychoanalytic architecture, only ` |
| só dígitos diferem | 145 | 26 | 1% | adf0ea9c `This cartoon is funny because it turns out that the fear New Yorkers h` → `This cartoon is funny because it turns out that the fear New Yorkers h` |
| GT com \textbf/\textit (artefato de normalização) | 70 | 25 | 1% | adf0ea9c `*Figure 1.7a*⏎\textbf{A still from Alain Renais' *Last Year in Marienb` → `Figure 1.7a A still from Alain Renais' Last Year in Marienbad (1961), ` |
| só caixa (maiúsc/minúsc) | 29 | 3 | 0% | 16345dc6 `**FIGURE 1-19** Insurance company: conceptual and physical data models` → `FIGuRE 1-19Insurance company: conceptual and physical data models.` |
| perfeito | 5017 | 0 | 0% |  `` → `` |

### A2. Recursos de formatação no GT (quantos blocos GT contêm) vs nas predições
| recurso | GT blocos | pred blocos |
|---|---|---|
| **negrito** | 746 | 0 |
| *itálico* | 875 | 13 |
| # heading | 1530 | 1371 |
| \textbf/\textit | 81 | 0 |
| inline math \(..\) | 15 | 0 |
| inline math $..$ | 1045 | 15 |
| <br> | 17 | 0 |
| lista - / • | 17 | 13 |
| lista 1. | 43 | 19 |
| quebra de linha interna (\n) | 1405 | 0 |
| hífen fim de linha | 43 | 0 |
| aspas curvas ‘’“” | 540 | 22 |
| reticências … | 9 | 10 |
| travessão — | 603 | 313 |
| <span class=math> | 17 | 0 |
| sup/sub ^ _ | 360 | 29 |
| footnote marker [n] | 7 | 7 |

### A3. Massa de erro de texto por assunto (top 12) e por causa dominante
| assunto | blocos | massa total | sem par | extra | casado c/ erro |
|---|---|---|---|---|---|
| SPORTS&RECREATION | 1590 | 1219 | 1025 | 4 | 190 |
| POETRY | 343 | 198 | 148 | 0 | 50 |
| GAMES&ACTIVITIES | 473 | 191 | 29 | 13 | 149 |
| STUDYAIDS | 814 | 166 | 66 | 1 | 99 |
| EDUCATION | 608 | 142 | 79 | 0 | 63 |
| GARDENING | 580 | 122 | 43 | 3 | 76 |
| COMICS&GRAPHICNOVELS | 193 | 121 | 0 | 1 | 120 |
| PSYCHOLOGY | 233 | 120 | 1 | 0 | 119 |
| SOCIALSCIENCE | 526 | 110 | 56 | 0 | 54 |
| HOUSE&HOME | 648 | 100 | 45 | 5 | 50 |
| YOUNGADULTFICTION | 370 | 82 | 13 | 8 | 61 |
| POLITICALSCIENCE | 164 | 79 | 62 | 2 | 15 |

## B. Ordem de leitura
Quadrantes (página):  {'texto ok / RO ok': 392, 'texto ok / RO ruim': 193, 'texto ruim / RO ruim': 197, 'texto ruim / RO ok': 143}
Páginas com texto ≥80 mas RO <40 (problema puro de ordem): 74
  por layout: {'single_column': 41, 'other_layout': 14, '1andmore_column': 11, 'double_column': 6, 'three_column': 2}
  por assunto: {'DESIGN': 8, 'SPORTS&RECREATION': 7, 'ARCHITECTURE': 6, 'LANGUAGEARTS&DISCIPLINES': 5, 'EDUCATION': 4, 'SOCIALSCIENCE': 4, 'POLITICALSCIENCE': 4, 'ART': 3, 'POETRY': 3, 'TRANSPORTATION': 3}
  padrão da permutação: {'pred com menos blocos casados': 38, 'último bloco do GT (decorativo?) veio primeiro': 15, 'permutação geral (colunas/blocos trocados)': 21}
RO médio por nº de blocos GT casados: {'1-2': (72.4, 96), '11-20': (55.0, 232), '3-5': (59.5, 195), '6-10': (62.3, 308), '>20': (55.6, 94)}
Exemplos texto≥80/RO<40:
  a38f2d0b p85 BIOGRAPHY&AUTOBIOGRAPHY single_column RO=0 text=81 gt=[327, 329] pred=[]
  bf710e01 p33 DESIGN other_layout RO=0 text=89 gt=[50, 434] pred=[434, 50]
  75d1e9a2 p35 SPORTS&RECREATION other_layout RO=0 text=93 gt=[32] pred=[]
  4df2a4de p60 SOCIALSCIENCE single_column RO=0 text=96 gt=[3751] pred=[]
  75d1e9a2 p38 SPORTS&RECREATION other_layout RO=0 text=97 gt=[78] pred=[]
  38a7285c p218 ART single_column RO=0 text=97 gt=[73, 234, 1335, 1338] pred=[1335, 1338, 73, 234]
  75d1e9a2 p40 SPORTS&RECREATION other_layout RO=0 text=98 gt=[109] pred=[]
  15efdcba p190 FICTION single_column RO=0 text=98 gt=[22, 48] pred=[48, 22]

## C. Tabelas
Casamento: {'linhas diferentes': 50, 'estrutura igual (linhas×colunas)': 108, 'colunas diferentes': 36, 'tabela GT sem par (pred não tem tabela)': 4} | n tabelas GT=198
TEDS médio=65.3  structure_only=71.7  (gap conteúdo≈6.4)
  dims iguais: n=108 TEDS=80.1 | dims diferentes: n=86 TEDS=46.8
  10 piores: TEDS | struct | GT r×c | pred r×c | página | assunto
    -12 | 25 | 2×4 | 2×5 | c18d05a4 p138 | TRANSPORTATION
    2 | 6 | 59×7 | 6×6 | 591d786d p8 | JUVENILENONFICTION
    2 | 4 | 110×5 | 5×5 | 591d786d p9 | JUVENILENONFICTION
    2 | 3 | 134×5 | 4×5 | 591d786d p16 | JUVENILENONFICTION
    3 | 5 | 19×2 | 1×2 | 11fb213b p79 | SELF-HELP
    5 | 6 | 43×5 | 2×7 | 591d786d p17 | JUVENILENONFICTION
    6 | 18 | 5×6 | 4×6 | c18d05a4 p136 | TRANSPORTATION
    6 | 8 | 57×5 | 2×6 | 591d786d p18 | JUVENILENONFICTION
    8 | 15 | 12×8 | 2×7 | ea572e13 p86 | COMPUTERS
    9 | 13 | 21×4 | 2×4 | 11fb213b p81 | SELF-HELP
GT tabelas com <br>: 12/198 (pred 0) | GT com <th>: 55 (pred 1) | GT com <strong>: 74 | GT com math inline: 83 | GT com span>1: 102 (pred 134)
tabelas em que a pred colou linhas de célula sem espaço (ex. 'Jack builtAt the zoo'): 5

## D. Fórmulas display no GT md2md (componente 'formula' local; no test só CDM)
{'texto em negrito/itálico embrulhado em $..$ (balões de quadrinhos etc.)': 14, 'matemática real': 113} | casadas=52 de 127
  assuntos com fórmulas GT: {'TECHNOLOGY&ENGINEERING': 37, 'PHILOSOPHY': 28, 'STUDYAIDS': 17, 'SELF-HELP': 10, 'TRANSPORTATION': 6, 'HOUSE&HOME': 4, 'POETRY': 4, 'COOKING': 3}

## E. Anomalias por página
predições vazias: 0 | páginas com parágrafo duplicado na pred: 15 | páginas com heading '#' na pred: 556 vs GT: 541
razão nº blocos pred/GT: mediana=1.00; páginas com pred < 0.5×GT (sub-segmentação/perda): 48; pred > 2×GT (sobre-segmentação): 0
