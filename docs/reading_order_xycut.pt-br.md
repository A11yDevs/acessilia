# Ordem de leitura por XY-cut em páginas multicoluna

> English version: [reading_order_xycut.md](reading_order_xycut.md)

Etapa opcional da fusão multi-provider (`docstruct.fusion`) que corrige a ordem
de leitura de **páginas com mais de uma coluna**. Vem **desligada por padrão**:
nada muda enquanto uma política não ligar.

## O problema

A fusão herda a ordem de leitura de um provider (MinerU, o "esqueleto"). Em
páginas com duas ou mais colunas de texto, o esqueleto às vezes lê **linha a
linha, atravessando as colunas**, em vez de terminar uma coluna antes de
começar a outra:

```
  como a página é                  ordem do esqueleto (errada)   ordem esperada

  +---------+  +---------+          1 -> 2                      1    3
  |    A    |  |    C    |          |  /                        |    |
  +---------+  +---------+          v /                         v    v
  +---------+  +---------+          3 -> 4                      2    4
  |    B    |  |    D    |
  +---------+  +---------+          A, C, B, D                  A, B, C, D
```

No plano do Dr.DocBench isto é o item **S6.3 / alavanca D** ("ordem geométrica
para páginas `three_column` / `1andmore`").

## A ideia

O **XY-cut** é um método geométrico clássico: olha as caixas dos blocos,
encontra os espaços verticais em branco ("calhas") que dividem a página em
colunas, lê as colunas da esquerda para a direita e, dentro de cada coluna, de
cima para baixo. Blocos que ocupam a largura toda (um título, uma tabela larga)
funcionam como quebra de seção. Usa só as caixas que os providers já entregam —
sem modelo, sem OCR, sem LLM, cerca de 0,1 ms por página.

É o método que teve o melhor resultado no estudo de ordem de leitura em diários
oficiais multicoluna que motivou esta contribuição (tau de Kendall 0,837).

## Quando age (e quando não age)

Aplicar o XY-cut em todas as páginas piora o resultado: em páginas de coluna
única a ordem esperada frequentemente foge de uma leitura puramente de cima para
baixo (figuras, legendas, boxes laterais). Por isso a etapa tem dois portões:

| Portão | Campo da política | Significado |
|---|---|---|
| multicoluna | `xycut_min_columns` (padrão `2`) | só páginas cujas caixas formam pelo menos esse número de colunas |
| colunas equilibradas | `xycut_min_balance` (padrão `0.0` = desligado; `0.7` recomendado) | a coluna mais estreita precisa ter pelo menos essa fração da mais larga |

O segundo portão separa colunas de texto de verdade de uma **coluna principal ao
lado de uma barra lateral estreita** — o caso em que o XY-cut erra.

Os dois portões deixam de lado os blocos de largura total antes de procurar
colunas: um título ou uma tabela larga que atravessa duas colunas "tampa" a
calha e faria a página parecer de coluna única. Pelo mesmo motivo, uma coluna de
texto dominante (60% ou mais da mancha) ao lado de uma coluna de margem estreita
é tratada como página de coluna única.

A etapa só muda a *sequência* dos blocos que sobreviveram às etapas anteriores
da fusão: nada é acrescentado, removido ou reescrito. Blocos sem caixa
utilizável acompanham o bloco anterior. Cabeçalho, rodapé e número de página
continuam na cauda de decorativos.

## Como ligar

Python:

```python
from dataclasses import replace
from docstruct.policy import FusionPolicy

policy = replace(FusionPolicy.drbench_v13(), order_xycut="multicol", xycut_min_balance=0.7)
```

Script de experimento do Dr.DocBench:

```bash
python -m scripts.drbench.experiments.differ.lib_fuse \
  --docling runs/docling/predictions --mineru runs/mineru/predictions \
  --out runs/fusion-xycut/predictions --policy v13 \
  --xycut multicol --xycut-min-balance 0.7
```

Slurm:

```bash
sbatch --export=ALL,SPLIT=dev,POLICY=v13,XYCUT=multicol,XYCUT_MIN_BALANCE=0.7,RUN_NAME=lib-fuse-v13-xycut-bal07 \
  scripts/drbench/experiments/slurm/lib_fuse.sbatch
```

`order_xycut` aceita `off` (padrão), `multicol` e `always` (todas as páginas;
mantido só para comparação). As decisões são contadas no `decisions.csv`:
`xycut-applied`, `xycut-moved`, `xycut-columns:<n>`,
`xycut-skipped:single-column`, `xycut-skipped:unbalanced-columns`,
`xycut-skipped:few-boxes`.

## Experimento (lote pequeno)

**Montagem.** Réplica local do protocolo de aceite: o subconjunto fixo
**dev-120** (`docs/drbench/experiments/dev120-subset.json`), avaliador oficial
DrDocBench (`multipage_md2md_dataset`, janela de 1 página, sem CDM; o gabarito
avaliado contra ele mesmo dá 100), Docling pela Toolbox, MinerU 2.7.6 backend
`pipeline` em CPU convertido pelo adaptador da Toolbox, fusão com
`lib_fuse.py --policy v13`. São 119 páginas avaliáveis (113 com nota de ordem
de leitura). A comparação é **pareada por página** contra a mesma fusão sem
XY-cut.

| Variante (sobre a fusão v13) | Δ RO | IC 95% | páginas ↑ / ↓ | sign test p | Δ Overall |
|---|---|---|---|---|---|
| XY-cut em todas as páginas (`always`) | −0,29 | [−3,0, +2,5] | 12 / 13 | 1,00 | −0,14 |
| `multicol` | +1,12 | [−1,2, +3,6] | 12 / 8 | 0,50 | +0,53 |
| `multicol` + balance 0,5 | +1,91 | [+0,15, +3,98] | 10 / 2 | 0,039 | +0,91 |
| **`multicol` + balance 0,7** | **+2,14** | **[+0,75, +3,97]** | **9 / 0** | **0,004** | **+1,02** |

A distância de edição do texto não muda em nenhuma variante (o avaliador casa os
blocos independentemente da ordem). A política v12 dá o mesmo +2,14.

Por layout da página:

| Layout (páginas) | Δ RO, `multicol` | Δ RO, `multicol` + balance 0,7 |
|---|---|---|
| double_column (26) | +7,1 (6 sobem, 0 caem) | +6,0 (5 sobem, 0 caem) |
| three_column (9) | +5,6 (2 sobem, 0 caem) | +1,0 (1 sobe, 0 caem) |
| 1andmore_column (22) | −2,1 (3 sobem, 5 caem) | +3,4 (3 sobem, 0 caem) |
| other_layout (8) | −7,0 (0 sobem, 2 caem) | 0,0 (não é tocado) |
| single_column (48) | −0,1 | 0,0 (não é tocado) |

Números por página: [`drbench/experiments/xycut-dev120-local_per_page.csv`](drbench/experiments/xycut-dev120-local_per_page.csv).

### O quanto o +2,14 é robusto?

O resultado passou por uma revisão adversarial; estas são as verificações mais
duras, todas para `multicol` + balance 0,7:

| Verificação | Resultado |
|---|---|
| Metade par das páginas (ids ordenados, posições pares) | +3,06 (6 sobem, 0 caem) |
| Metade ímpar | +1,13 (3 sobem, 0 caem) |
| IC 95% reamostrando **documentos** inteiros (48 livros) em vez de páginas | [+0,39, +4,38] |
| Documentos que melhoram / pioram | 5 / 0 |
| Sem o documento mais forte | +1,51 |
| Sem os dois documentos mais fortes | +0,90 |

Ou seja: a direção se mantém nas duas metades e nenhuma página ou documento
piora, mas o tamanho depende de poucos livros — o ganho vem de **5 dos 48
documentos** (culinária, jardinagem, ciências sociais, transporte, casa).

Teto do método: o XY-cut aplicado às caixas do *gabarito* reproduz a ordem do
gabarito com RO 87,1 nas páginas multicoluna, 84,6 em coluna única e 61,8 em
`other_layout` — por isso os portões existem.

## Limitações — leia antes de usar os números

- **Réplica local, não o cluster.** O Docling rodou sem `force_ocr` e sem a
  correção de rotação, o MinerU em CPU, e as tabelas não saíram renderizadas nos
  blocos locais (TEDS n=0). Por isso os valores absolutos são menores que os do
  cluster (RO da fusão 69,8 aqui contra 79,3 no dev-986) e **não são
  comparáveis**; só a diferença pareada entre variantes tem significado.
- **O limiar 0,7 foi escolhido no dev-120** (foram testados 0,5 e 0,7). Passar
  de "sem portão de equilíbrio" para 0,7 responde por cerca de metade do ganho,
  ao deixar de fora as páginas que perdiam. Precisa ser confirmado no
  **dev-986 com o avaliador do cluster** antes de qualquer envio ao EvalAI
  (regra de aceite: pelo menos +0,3 em `evalai_style`, nenhum componente caindo
  mais de 0,3).
- O ganho é **pequeno e concentrado** (cerca de +2 de RO na média, vindo de 9
  páginas em 5 livros). Sozinho, não fecha a diferença de ordem de leitura para
  os líderes do leaderboard.
- Os portões de coluna são geométricos. Um layout assimétrico legítimo (por
  exemplo, coluna de texto com 65% e coluna de notas contínuas com 35%) fica
  intocado, por construção; a constante da calha (4 pt numa página A4) vem do
  estudo com diários oficiais e não foi recalibrada para livros.
- É independente da opção `order_relations` (posicionamento conservador dos
  blocos que só o Docling viu): aquela corrige inserções, esta corrige a ordem
  do esqueleto em páginas multicoluna. Aplicar `order_relations` primeiro e o
  XY-cut depois passou nas duas suítes de teste numa mesclagem local.

## Código

- `libs/docstruct/src/docstruct/fusion/xycut.py` — `xycut_order`, `count_columns`, `column_balance`, `reorder`
- `libs/docstruct/src/docstruct/policy.py` — `order_xycut`, `xycut_min_columns`, `xycut_min_balance`
- `libs/docstruct/src/docstruct/fusion/differ.py` — gancho no fim do `merge_blocks`
- `libs/docstruct/tests/test_xycut.py` — 29 testes

## Livros adicionais de validação (03/10/2026)

A implementação corrigida, com `multicol` e balance `0.7` congelados, foi
avaliada em outras 60 páginas do DrDocBench, de 16 livros ausentes do dev-120.
Semente `3102026`; revisão do dataset `7a2bc3882dff68e883fb55d10d4df22865ce2b07`.
O [CSV por página](drbench/experiments/xycut-new60-local_per_page.csv) identifica
toda a amostra, incluindo uma página sem conteúdo avaliável.

São 59 comparações pareadas, avaliador oficial md2md, janela 1, sem CDM.
Este baseline preserva HTML recuperado de tabelas; o lote, porém, não tem GT de
tabelas/fórmulas. Os resultados absolutos não devem ser agrupados com o dev-120.

Overall: 73.1276 → 73.3544 (+0.2269);
RO: 72.9665 → 73.4202 (+0.4537). Texto inalterado.
Há 4 melhorias, 1 piora e 54 empates
(tolerância 0,05 ponto). IC 95% de Overall por reamostragem de livros:
[0.0000, 0.6249].

O ganho menor e a regressão observada justificam manter a opção desligada por
padrão. Outros 120 exemplos do DrDocBench e 120 do OmniDocBench estão em
processamento; seus resultados não são apresentados como concluídos.

## Mais 120 páginas de validação (03/10/2026)

Selecionadas antes de avaliar, semente `3102027`, sem repetir as 180 páginas
anteriores; 66 livros, mas com sobreposição de livros com os experimentos
anteriores. Portanto é validação em páginas novas, **não em livros novos**.
[CSV e IDs da amostra](drbench/experiments/xycut-new120-local_per_page.csv).

Avaliador oficial md2md, janela 1, sem CDM; balance 0,7 congelado e baseline
com recuperação de HTML. Todas as 120 predições presentes. Cobertura: 115
páginas com Overall, 111 com RO, 5 com TEDS e 4 com distância de edição de fórmulas.

Média por página de Overall: 76.7906 → 77.9596
(+1.1691); IC 95% por livros
[0.3136, 2.2990].
RO: 73.1632 → 75.5673 (+2.4041).
Overall: 9 melhorias, 0 pioras, 106 empates.
A média dos componentes sem CDM foi 67.7168 →
68.5241; difere da média por página por causa da cobertura
diferente dos componentes. Nenhuma é nota de uma submissão ao EvalAI.

O multiconjunto de conteúdo dos parágrafos foi preservado nas 120 saídas,
após desconsiderar espaços nas bordas. TEDS e fórmulas não mudam. O avaliador
altera a nota de texto em uma página (+0.0177 na média) com
conteúdo idêntico; não é melhora de OCR. A reavaliação independente repetiu
exatamente as métricas por página de ambas as variantes.

A evidência favorece a opção de ordem em páginas adicionais, mas o resultado
menor nos livros novos acima ainda limita a generalização. Resta confirmar no
dev-986 do cluster; OmniDocBench e TeleOCR ainda estão em processamento.
