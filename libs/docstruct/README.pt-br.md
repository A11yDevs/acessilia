# acessilia-docstruct

Núcleo puro de processamento estrutural de documentos do Acessilia.

> Também disponível em **inglês (EUA)**: [English version](README.md) — versão autoritativa.

## Princípios

- **Pura**: nenhuma função toca rede, arquivos, subprocess, settings, logger ou i18n dinâmico. Zero dependências pesadas de ML (`dependencies = []`).
- **Direção única de dependência**: `backend → docstruct` ou `acessilia-toolbox → docstruct`. A lib nunca importa de `backend/` ou `acessilia_toolbox/`.
- **i18n = msgids**: funções que produzem mensagens retornam `(msgid, args)`; o consumidor traduz.
- **IDs determinísticos ou injetados**: nada de `uuid4` dentro da lib.

## API pública

| Módulo | Símbolos |
|---|---|
| `docstruct.types` | `BBox`, `CanonicalBlock`, `CanonicalDocument`, `Region`, `BlockPairing`, `OrientationResult` |
| `docstruct.geometry` | `content_fingerprint`, `overlaps_clean`, `merge_bboxes`, `union`, `intersection_area` |
| `docstruct.geometry.reading_order` | `refine_reading_order` — refinamento de ordem de leitura sensível a colunas com isolamento de marginais e particionamento em 2/3 colunas |
| `docstruct.policy` | `FusionPolicy` (+ presets: `drbench_v12`, `drbench_v13`) |
| `docstruct.fusion` | `merge_blocks`, `block_to_diff`, `DiffBlock`, `ProviderBlocks`, `quality`, `is_junk` |
| `docstruct.fusion.xycut` | `xycut_order`, `count_columns`, `column_balance`, `reorder` — ordem de leitura XY-cut opcional (`FusionPolicy.order_xycut`) |
| `docstruct.text.latex` | `strip_latex_delimiters`, `normalize_latex`, `wrap_latex` — normalização canônica e padronização de fórmulas LaTeX |
| `docstruct.adapters.mineru` | `clean_mineru_text`, `format_mineru_block_text`, `extract_mineru_blocks` — parsing de `middle_json` do MinerU, espaçamento, de-hifenização e formatação de fórmulas/tabelas |
| `docstruct.tables.ast` | `table_ast_from_docling_grid`, `analyze_table_complexity`, `TableAST`, `TableComplexityMetrics`, `TableASTError` |
| `docstruct.text` | `sanitize_text`, `merge_broken_paragraphs`, `normalize_code_text`, `classify_text_block` |
| `docstruct.profiles` | `OUTPUT_PROFILES`, `filter_blocks_for_profile`, `normalize_profile` |
| `docstruct.validation` | `validate_canonical_document`, `validate_output_text`, `Finding` |

## Módulos

### Normalização de LaTeX (`docstruct.text.latex`)

Rotinas canônicas para padronização e higienização de fórmulas matemáticas:
- `strip_latex_delimiters(text)`: Remove delimitadores inline (`$...$`, `\(...\)`) e display (`$$...$$`, `\[...\]`).
- `normalize_latex(text)`: Converte caracteres Unicode em seus equivalentes ASCII (e.g., letras gregas, expoentes, operadores), padroniza macros comuns (e.g., `\bm` para `\mathbf`, `\bold` para `\mathbf`) e colapsa espaços redundantes.
- `wrap_latex(text, display=False)`: Envolve expressões LaTeX brutas nos delimitadores padrão (`$...$` ou `$$...$$`).

### Adaptador MinerU (`docstruct.adapters.mineru`)

Parser leve para saída `middle_json` do MinerU:
- `clean_mineru_text(lines_or_pieces)`: Preserva quebras de linha com espaços únicos e reconstrói palavras hifenizadas no final de linhas (e.g., `["impor-", "tant"]` -> `"important"`).
- `format_mineru_block_text(block)`: Formata blocos de fórmulas e tabelas para texto canônico (fórmulas display envolvidas em `$$...$$`, inline em `$...$`, tabelas em markdown/HTML).
- `extract_mineru_blocks(middle_json)`: Extrai lista linearizada de blocos com geometria e conteúdo normalizados.

### AST de Tabelas e Complexidade (`docstruct.tables.ast`)

Análise pura de grades e conversão em AST:
- `table_ast_from_docling_grid(grid_or_cells, caption=None)`: Constrói uma `TableAST` canônica a partir de células do Docling (`start_row_offset_idx`, `start_col_offset_idx`, spans de linhas e colunas).
- `analyze_table_complexity(table_ast_or_cells)`: Avalia métricas de complexidade retornando `TableComplexityMetrics` (`has_spans`, `max_rowspan`, `max_colspan`, `spanned_cell_count`, `is_complex`).

### Refinamento da Ordem de Leitura (`docstruct.geometry.reading_order`)

Otimização topológica da ordem de leitura:
- `refine_reading_order(blocks)`: Agrupa blocos por página, isola cabeçalhos e rodapés nas margens superior e inferior, e reconstrói o fluxo de leitura em páginas multicolunares (calhas de 2 e 3 colunas separadas por banners de largura total).

### Fusão (`docstruct.fusion`)

Porta do Tree Differ v2 da PR #98 (Dr.DocBench) como biblioteca pura:

- `merge_blocks(D, M, policy)` — fusão block-level de dois providers com alinhamento Húngaro texto+bbox; o provider B (MinerU) fornece o esqueleto de ordem de leitura; blocos unilaterais de A são inseridos junto ao vizinho geometricamente mais próximo.
- `_hungarian.py` — implementação pura Kuhn-Munkres O(n³) (substitui scipy; zero dependências).
- `noise.py` — decor-tail, running heads, junk filter, supressão de regiões, re-fusão de parágrafos, fusão de colunas de linhas.
- `FusionPolicy` — frozen dataclass com defaults conservadores; presets de benchmark (`drbench_v12`, `drbench_v13`) são classmethods nomeados, nunca defaults.

## Desenvolvimento

```bash
pip install -e "libs/docstruct[dev]"
pytest libs/docstruct/tests
```

O CI roda `pytest libs/docstruct/tests` sem o backend instalado — se precisar importar `backend/`, a mudança está violando o desacoplamento.
