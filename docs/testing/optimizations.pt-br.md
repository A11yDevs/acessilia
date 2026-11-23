# Resultados da otimização de testes: field specs em cache e testes de fronteira

> [optimizations.md](optimizations.md). A versão em inglês é a fonte.

Este é o PR 4 da [issue #644](https://github.com/A11yDevs/acessilia/issues/644):
as otimizações medidas, escolhidas a partir do baseline e do experimento de
mutação. Ele não remove testes, não muda limiares de cobertura e não adiciona
um novo gate de CI.

- **Snapshot:** `develop` em `7c9311f` (2026-11-23), Python 3.12.13.
- **Baseline:** o método do PR 1, uma execução silenciosa na mesma máquina de
  referência.
- **Baseline posterior legível por máquina:** [`baseline-after.json`](baseline-after.json).
- **Depois dos testes de fronteira:** [`mutation-flood-after.json`](mutation-flood-after.json).

## 1. Cache das especificações de campo usadas na validação de documentos

### Problema

O baseline mediu a docstruct em 96,48 segundos de tempo de parede, com
`test_long_parent_chains_are_acyclic` sozinho levando 23,59 segundos. O perfil
desse teste mostrou onde o tempo ia:

| Função | Tempo cumulativo | Chamadas |
|---|---:|---:|
| `typing.get_type_hints` (via `field_specs`) | 3,53s de 4,9s sob o profiler | 6.007 |
| `field_specs` | 2,76s | 4.004 |
| `structured_document_from_payload` | 1,52s | 1 |

`field_specs()` resolvia os mesmos type hints para cada elemento e depois
reconstruía os mesmos dicionários de restrições. Um documento de 2.000
elementos pagava pela mesma introspecção 2.000 vezes. Isso é trabalho de
produção, não de fixture: o mesmo caminho valida manifestos reais.

### Mudança

`libs/docstruct/src/docstruct/manifest.py` agora constrói as specs uma vez por
classe com `functools.cache` e devolve `copy.deepcopy` do resultado cacheado. A
cópia mantém a função pública segura: um chamador que altera suas specs não
muda a próxima chamada. Comportamento, achados, ordenação e mensagens de erro
não mudam; apenas a introspecção repetida é removida.

A docstring pública declara o contrato de cache somente leitura. Um teste de
regressão altera o primeiro resultado e verifica que a segunda chamada não é
afetada.

### Efeito medido

A mesma máquina, as mesmas opções de cobertura e os mesmos comandos de suíte do
baseline:

| Suíte | Parede antes (s) | Parede depois (s) | Mudança |
|---|---:|---:|---:|
| Aplicação | 157,23 | 90,91 | −42,2% |
| docstruct | 96,48 | 14,48 | −85,0% |
| SDK | 31,20 | 16,83 | −46,1% |
| core | 41,25 | 44,65 | +8,2% (ruído; fora do caminho alterado) |
| **Total** | **326,17** | **166,87** | **−48,8%** |

O total JUnit passou de 310,32s para 158,75s (−48,8%). O teste mais lento da
docstruct foi de **23,59s para 2,10s** (11,2×). As suítes da aplicação, da
docstruct e do SDK exercitam o adaptador de manifesto; a mudança do core está
dentro da variação entre execuções e não é atribuída a este PR.

As contagens de testes diferem pelo trabalho entregue, não por remoção: os
testes de instrumentação do PR 1 (10) não estão neste branch, e este PR adiciona
quatro testes à docstruct (três de fronteira e um de regressão do cache). A
cobertura permaneceu em 87,9% (aplicação), 87,0% (docstruct), 97,3% (SDK) e
82,7% (core).

## 2. Fechar os três mutantes de fronteira sobreviventes do `flood_guard`

### Problema

O experimento de mutação do PR 3 deu ao `docstruct.fusion.flood` 14/17 (82,3%).
Os três sobreviventes eram lacunas reais de fronteira, não mutantes
equivalentes:

| Mutante | Fronteira |
|---|---|
| M005 | exatamente `DEFAULT_MIN_BLOCKS` blocos |
| M011 | texto com exatamente `DEFAULT_SHORT` caracteres |
| M016 | guarda disparado sem descartar nenhum bloco |

### Mudança

Três testes em `libs/docstruct/tests/test_flood.py`:

- `test_o_minimo_de_blocos_e_inclusivo`
- `test_o_comprimento_curto_e_inclusivo`
- `test_disparar_sem_descartar_nao_conta_pagina`

São testes unitários rápidos comuns; a suíte inteira da docstruct ainda
conclui em cerca de 14,5 segundos.

### Efeito medido

O mesmo harness de mutação e os mesmos 17 mutantes:

| Medida | Antes | Depois |
|---|---:|---:|
| Mortos | 14 | 17 |
| Sobreviventes | 3 | 0 |
| Mutation score | 82,3% | **100%** |
| Tempo de parede do experimento | ~15s | ~17s |
| Mutantes detectados por exatamente um teste | M006, M007, M013, M015, M017 | M005, M006, M011, M013, M015, M016, M017 |

Cada novo teste é o único detector de um mutante que antes sobrevivia: M005,
M011 e M016. O relatório do experimento é
[`mutation-flood-after.json`](mutation-flood-after.json).

## O que este PR deliberadamente não faz

- **Nenhuma remoção de teste.** O relatório de sobreposição encontrou alta
  similaridade, mas nenhum subconjunto par-a-par; a matriz de mutação mostrou
  contratos e diagnósticos que a cobertura não vê. Remover um teste trocaria um
  ganho medido por um risco não medido.
- **Nenhuma mudança de comportamento de produção.** O cache muda apenas o
  desempenho; os achados de validação são idênticos.
- **Nenhuma mudança de limiar ou gate.** Os pisos de cobertura e os checks
  obrigatórios permanecem.
- **Nenhuma mudança de paralelismo.** Quatro workers continuam sendo o limite
  suportado para a suíte da aplicação; as suítes das bibliotecas ficam seriais
  porque agora levam de 14 a 45 segundos cada.

## Reprodução

Com a ferramenta do PR 1 integrada:

```bash
# O baseline posterior completo (grava var/timings/baseline.json)
make test-baseline

# A comparação antes/depois
make test-baseline-compare BASELINE=var/timings/baseline.json

# A suíte da docstruct sozinha
(cd libs/docstruct && uv run --extra dev pytest --durations=25)
```

Sem a ferramenta do PR 1, o comando equivalente é:

```bash
uv run pytest -m "not e2e" -n 4 --dist worksteal --durations=25
(cd libs/docstruct && uv run --extra dev pytest --durations=25)
```

As mutações são reproduzidas com o harness do PR 3:

```bash
uv run python scripts/tests/mutation_report.py \
  --module libs/docstruct/src/docstruct/fusion/flood.py \
  --tests tests/test_flood.py --suite libs/docstruct \
  --source-root libs/docstruct/src \
  --coverage-file var/timings/coverage/docstruct/.coverage \
  --output var/mutation/flood-after.json
```

## Limitações

- **Uma execução por medição.** Os segundos absolutos variam com a carga da
  máquina; a direção e a magnitude da docstruct são grandes o suficiente para
  sobreviver a essa variação, o +8% do core não é.
- **O cache assume que os hints das classes não mudam em tempo de execução.** Os
  tipos do documento são fixos na importação; uma classe redefinida
  dinamicamente está fora do contrato.
- **O conjunto de operadores de mutação ainda é limitado.** 17/17 significa que
  as três lacunas de fronteira foram fechadas, não que o módulo detecta todo
  defeito possível.
- **A suíte da aplicação ainda tem uma cauda longa.** O teste mais lento
  continua sendo o caso do juiz VLM; este PR não o altera.
