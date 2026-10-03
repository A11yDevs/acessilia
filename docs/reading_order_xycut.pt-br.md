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
`lib_fuse.py --policy v13`. São 119 páginas avaliáveis. A comparação é
**pareada por página** contra a mesma fusão sem XY-cut.

| Variante (sobre a fusão v13) | Δ RO | IC 95% | páginas ↑ / ↓ | sign test p | Δ Overall |
|---|---|---|---|---|---|
| XY-cut em todas as páginas (`always`) | −0,29 | [−3,0, +2,5] | 12 / 13 | 1,00 | −0,14 |
| `multicol` | +0,84 | [−1,1, +3,0] | 8 / 5 | 0,58 | +0,40 |
| `multicol` + balance 0,5 | +1,17 | [−0,4, +3,0] | 7 / 2 | 0,18 | +0,56 |
| **`multicol` + balance 0,7** | **+1,65** | **[+0,45, +3,30]** | **7 / 0** | **0,016** | **+0,79** |

A distância de edição do texto não muda em nenhuma variante (o avaliador casa os
blocos independentemente da ordem). A política v12 mostra o mesmo padrão.

Por layout da página, `multicol` → `multicol` + balance 0,7:

| Layout (páginas) | Δ RO sem balance | Δ RO com balance 0,7 |
|---|---|---|
| double_column (26) | +6,0 | +4,5 (4 sobem, 0 caem) |
| three_column (9) | +1,0 | +1,0 |
| 1andmore_column (22) | −0,7 | +2,8 (2 sobem, 0 caem) |
| other_layout (8) | −7,0 | 0,0 (não é tocado) |
| single_column (48) | 0,0 | 0,0 (não é tocado) |

Números por página: [`drbench/experiments/xycut-dev120-local_per_page.csv`](drbench/experiments/xycut-dev120-local_per_page.csv).

Teto do método: o XY-cut aplicado às caixas do *gabarito* reproduz a ordem do
gabarito com RO 87,1 nas páginas que o portão multicoluna seleciona (84,6 em
coluna única e 61,8 em `other_layout` — por isso o portão existe).

## Limitações — leia antes de usar os números

- **Réplica local, não o cluster.** O Docling rodou sem `force_ocr` e sem a
  correção de rotação, o MinerU em CPU, e as tabelas não saíram renderizadas nos
  blocos locais (TEDS n=0). Por isso os valores absolutos são menores que os do
  cluster (RO da fusão 69,8 aqui contra 79,3 no dev-986) e **não são
  comparáveis**; só a diferença pareada entre variantes tem significado.
- **O limiar 0,7 foi escolhido no dev-120** (só 0,5 e 0,7 foram testados).
  Precisa ser confirmado no **dev-986 com o avaliador do cluster** antes de
  qualquer envio ao EvalAI (regra de aceite: pelo menos +0,3 em `evalai_style`,
  nenhum componente caindo mais de 0,3).
- O ganho é **pequeno e localizado** (cerca de +1,6 de RO na média, concentrado
  em ~25 páginas multicoluna). Sozinho, não fecha a diferença de ordem de leitura
  para os líderes do leaderboard.
- É independente da opção `order_relations` (posicionamento conservador dos
  blocos que só o Docling viu): aquela corrige inserções, esta corrige a ordem
  do esqueleto em páginas multicoluna. Aplicar `order_relations` primeiro e o
  XY-cut depois passou nas duas suítes de teste numa mesclagem local.

## Código

- `libs/docstruct/src/docstruct/fusion/xycut.py` — `xycut_order`, `count_columns`, `column_balance`, `reorder`
- `libs/docstruct/src/docstruct/policy.py` — `order_xycut`, `xycut_min_columns`, `xycut_min_balance`
- `libs/docstruct/src/docstruct/fusion/differ.py` — gancho no fim do `merge_blocks`
- `libs/docstruct/tests/test_xycut.py` — 25 testes
