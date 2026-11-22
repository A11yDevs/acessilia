# Baseline de qualidade arquitetural, novembro de 2026

> [quality-baseline.md](quality-baseline.md). A versão em inglês é a fonte.

Esta é a instrumentação e o baseline da [issue #656](https://github.com/A11yDevs/acessilia/issues/656), PR 1. Ela mede a revisão atual e registra os números que os próximos PRs usarão para duplicação (PR 2), acoplamento e coesão (PR 3), fronteiras e migrações (PR 4) e guardas de CI (PR 5). Nenhum código de produção muda.

- **Snapshot:** `develop` em `b00636fc` (2026-11-21), Python 3.12.13.
- **Ferramenta:** [`scripts/architecture_quality.py`](../../scripts/architecture_quality.py), somente biblioteca padrão.
- **Baseline legível por máquina:** [`quality-baseline.json`](quality-baseline.json).
- **Escopo:** código Python do core, SDK, docstruct, backend e frontend. Testes ficam fora do baseline; a duplicação deles é acompanhada pela [#644](https://github.com/A11yDevs/acessilia/issues/644).

## Método

O script lê cada arquivo `.py` rastreado pelo `git` na revisão pedida, então um baseline pode ser reproduzido sem fazer checkout do commit. Ele usa [`scripts/architecture_metrics.py`](../../scripts/architecture_metrics.py) para os nomes de arquivos e para a aproximação de complexidade de McCabe: 1 por função mais 1 por branch, laço, `except`, `with`, expressão condicional, compreensão, `assert`, `match` e operando extra de `and`/`or`; escopos aninhados são medidos separadamente.

| Medida | Definição |
|---|---|
| Tamanho | Arquivos, linhas não vazias, funções e mediana de linhas por função, por componente |
| Complexidade | Funções acima de 15 e acima de 100 linhas, por componente |
| Aresta de dependência | Um arquivo do componente A importa um módulo first-party do componente B (`acessilia_core`, `acessilia_sdk`, `docstruct`, `backend`, `frontend`); cada arquivo conta uma vez por destino, e imports relativos contam como o componente atual |
| Fan-in / fan-out | Componentes que importam A / componentes que A importa |
| Ciclo | Um ciclo simples no grafo de componentes |
| Duplicata estrutural | Funções com pelo menos 20 nós AST e dois comandos cujos corpos normalizados têm o mesmo digest SHA-256; nomes, constantes, atributos e nomes de keyword são normalizados |
| Hotspot | As funções mais complexas e os maiores módulos |

Uma duplicata estrutural é uma **candidata**, não um clone semântico. Duas funções podem compartilhar o fluxo de controle e ainda diferir em tipos, efeitos colaterais ou tratamento de erro. O PR 2 decide quais grupos valem consolidar. Coesão (LCOM), fan-in em nível de módulo e duplicação semântica ficam deliberadamente para o PR 3; este baseline expõe as entradas para essas análises.

## Baseline

### Tamanho e complexidade

| Componente | Arquivos | Linhas não vazias | Funções | > 100 linhas | Complexidade > 15 |
|---|---:|---:|---:|---:|---:|
| Core (`libs/core/src/acessilia_core`) | 112 | 21.367 | 799 | 0 | 0 |
| SDK (`libs/sdk/src/acessilia_sdk`) | 45 | 5.783 | 221 | 1 | 3 |
| docstruct (`libs/docstruct/src/docstruct`) | 89 | 13.883 | 680 | 6 | 40 |
| Backend (`backend`) | 46 | 5.100 | 238 | 3 | 5 |
| Frontend (`frontend`) | 24 | 2.294 | 89 | 1 | 1 |

O core carrega o resultado da #612: nenhuma função passa de 100 linhas ou de complexidade 15. A complexidade residual concentra-se na docstruct (40 funções acima de 15), seguida pelo backend (5), SDK (3) e frontend (1).

### Dependências entre componentes

| De | Para | Arquivos |
|---|---|---:|
| Backend | Core | 27 |
| Backend | docstruct | 1 |
| Backend | SDK | 3 |
| Core | docstruct | 47 |
| Core | SDK | 19 |
| Frontend | Backend | 9 |
| Frontend | Core | 13 |
| SDK | docstruct | 4 |

Nenhum ciclo entre componentes foi encontrado. Fan-in: Core 2, SDK 2, docstruct 3, backend 1, frontend 0. Fan-out: Core 2, SDK 1, docstruct 0, backend 3, frontend 2.

### Duplicatas estruturais

O baseline contém **50 grupos**, **133 funções** e **1.529 linhas** em grupos duplicados. O JSON guarda os 40 maiores grupos; os totais cobrem todos. Os cinco maiores grupos são:

| Grupo | Linhas | Exemplos |
|---:|---:|---|
| 9 funções | 99 | wrappers de operações do `FusionAgent` (`move_header_footer_to_end`, `normalize_formula`, `normalize_text`, `refine_reading_order`, …) |
| 7 funções | 87 | wrappers de `AdjudicationAgent` e `OrderAdjudicationAgent` (`decide_from_transcription`, `complete_order`, `kendall_tau`, `parse_order`, …) |
| 7 funções | 33 | `FusionAgent.process_*` e `OrderAdjudicationAgent.process_refine_reading_order` |
| 6 funções | 22 | `OrderAdjudicationAgent.process_*` e `PageLevelAgent.process_decide_orientation` |
| 5 funções | 15 | leitores de dataset do SDK (`read_dataset_list`, `read_dataset_sample`, `read_dataset_splits`, …) |

Os primeiros grupos são dominados por métodos de processo/wrapper em volta dos agentes Agno. Eles podem ser adaptadores legítimos ou esconder uma operação reutilizável; o PR 2 avalia cada grupo antes de tocar no código. O detector não encontrou grupo entre componentes grande o suficiente para mudar o mapa de responsabilidades sozinho.

### Hotspots

| Função | Componente | Complexidade | Linhas |
|---|---|---:|---:|
| `merge_blocks` (`fusion/differ.py`) | docstruct | 89 | 198 |
| `table_ast_from_docling_grid` (`tables/ast.py`) | docstruct | 63 | 147 |
| `decode` (`toolbox/results/_model.py`) | SDK | 56 | 109 |
| `recover_empty_lettered_list_items` (`blocks/lists.py`) | docstruct | 53 | 131 |
| `JobExecutor.run` (`api/worker.py`) | backend | 43 | 325 |

Os maiores módulos são o orquestrador do core (808 linhas), o payload do core (801), o vision agent do core (793), o worker do backend (788) e o extrator da Toolbox do core (751). Todos estão abaixo do limite atual de 900 linhas por módulo, mas são os primeiros candidatos à revisão de acoplamento do PR 3.

## Reprodução

```bash
# JSON completo do baseline na revisão atual (stdout)
python scripts/architecture_quality.py --rev HEAD

# Reescrever o snapshot versionado
python scripts/architecture_quality.py --rev HEAD \
  --output docs/architecture/quality-baseline.json

# Forma do baseline e detector de duplicatas
python -m pytest tests/test_architecture_quality.py
```

O JSON versionado registra o commit medido em `rev`. O script é apenas diagnóstico: ele sai com 0 mesmo quando os números crescem. O PR 5 decide quais medidas viram ratchet, com o fluxo de allowlist e atualização dos baselines existentes da #652 e do Ruff.

## O que este PR não decide

- Não remove duplicata, move módulo nem muda fronteira de componente.
- Não afirma que uma duplicata estrutural é segura para unir.
- Ainda não mede coesão nem duplicação semântica.
- Não adiciona falha de CI; um baseline que quebra o build antes do PR 2 congelaria trabalho não relacionado.

A sequência continua sendo PR 1 (este baseline), PR 2 (duplicação e consolidação), PR 3 (acoplamento e coesão), PR 4 (fronteiras e migrações) e PR 5 (guardas), com PRs menores quando a mudança for substancial.
