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
| `docstruct.fusion.verse` | `record_like`, `verse_lines`, `chunk_verse`, `split_box_rows`, `verse_blocks` |
| `docstruct.fusion.line_numbers` | `line_number_chain`, `extract_line_numbers` |
| `docstruct.fusion.flood` | `flood_guard` |
| `docstruct.fusion.tailjoin` | `is_page_number`, `join_tail`, `page_number_position`, `tailjoin3` |
| `docstruct.fusion.repetition` | `collapse`, `guard_page`, `is_blank_page`, `strip_comment` |
| `docstruct.fusion.page_select` | `fuse`, `select_by_agreement`, `swap_low_agreement_pages`, `ratio` |
| `docstruct.fusion.judge` | `debias`, `decide_pair`, `p2_from_logprobs`, `should_judge` |
| `docstruct.fusion.adjudication` | `decide_v0`, `decide_v1`, `decide`, `filter_decision` |
| `docstruct.fusion.oracle` | `oracle_page`, `best_score`, `summarize` |
| `docstruct.fusion.hf_end` | `move_hf_to_end`, `move_body_hf_to_tail` |
| `docstruct.fusion.table_specialist` | `extract_table`, `norm_table`, `select_table`, `select_greedy` |
| `docstruct.text.latex` | `strip_latex_delimiters`, `normalize_latex`, `wrap_latex` — normalização canônica e padronização de fórmulas LaTeX |
| `docstruct.text.normalize` | `norm` — limpezas determinísticas de texto |
| `docstruct.text.norm_fix` | `norm_fix` — reparos pós-normalização |
| `docstruct.adapters.mineru` | `clean_mineru_text`, `format_mineru_block_text`, `extract_mineru_blocks` — parsing de `middle_json` do MinerU, espaçamento, de-hifenização e formatação de fórmulas/tabelas |
| `docstruct.tables.ast` | `table_ast_from_docling_grid`, `analyze_table_complexity`, `TableAST`, `TableComplexityMetrics`, `TableASTError` |
| `docstruct.text` | `sanitize_text`, `merge_broken_paragraphs`, `normalize_code_text`, `classify_text_block` |
| `docstruct.imaging.policy` | `upscale_factor`, `decide_orientation` (sem PIL/cv2) |
| `docstruct.evaluation.holdout` | `partition`, `score`, `evaluate_candidate` |
| `docstruct.profiles` | `OUTPUT_PROFILES`, `filter_blocks_for_profile`, `normalize_profile` |
| `docstruct.validation` | `validate_canonical_document`, `validate_output_text`, `Finding` |

Módulos planejados (fases 2–3): `blocks/`, `regions/`, `tables/`, `math/`, `render/`, `validation.py`.

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

- `merge_blocks(D, M, policy)` — fusão block-level de dois providers com
  alinhamento Húngaro texto+bbox; o provider B (MinerU) fornece o esqueleto
  de ordem de leitura; blocos unilaterais de A são inseridos junto ao
  vizinho geometricamente mais próximo.
- `_hungarian.py` — implementação pura Kuhn-Munkres O(n³) (substitui scipy;
  zero dependências).
- `noise.py` — decor-tail, running heads, junk filter, supressão de regiões,
  re-fusão de parágrafos, fusão de colunas de linhas.
- `FusionPolicy` — frozen dataclass. Os defaults são a política de **produção**:
  as capacidades determinísticas com evidência de ganho (ou que corrigem um
  defeito) ficam ligadas, e o que consome modelo fica desligado. Os presets de
  benchmark (`drbench_v12`, `drbench_v13`, `drbench_v14`, `drbench_v15`,
  `drbench_best_method`) são classmethods nomeados, nunca defaults (foram
  sobreajustados ao split dev).
- `fusion/verse.py`, `fusion/line_numbers.py`, `fusion/flood.py`,
  `fusion/tailjoin.py`, `fusion/repetition.py`, `fusion/page_select.py`,
  `fusion/judge.py`, `fusion/adjudication.py`, `fusion/oracle.py`,
  `fusion/hf_end.py`, `fusion/table_specialist.py` — as políticas
  determinísticas da PR #125 do Dr.DocBench, portadas como funções puras.
- `text/normalize.py`, `text/norm_fix.py` — primitivas de normalização de texto.
- `imaging/policy.py` — decisões puras de upscale/orientação (sem PIL/cv2).

### Defaults de produção

| Capacidade | Default | Por quê |
|---|---|---|
| `verse_chunk` 300, `verse_kind` records | ligado | determinístico; preserva verso real inteiro |
| `line_numbers`, `table_eq`, `norm_text`, `hf_end` | ligado | determinístico, baixo risco |
| `tailjoin` end / 50 / 3 / `hdr` | ligado | a regra `tj3`: Δtune +1.47, Δhold +0.79 |
| `rep_guard`, `blank_pages` | ligado | corrige loops de geração degenerada |
| `upscale`, `orientation` | ligado | maior ganho isolado da linha Tele (Δtune +1.59, Δhold +2.91) |
| `page_judge` | **desligado** | consome modelo; ligue quando a Toolbox expuser `document.adjudicate.page` |

Os experimentos rejeitados (word_vote, dedup_blocks, medoide, juiz por bloco,
mover cabeçalho, tabelas do dots, árbitro DeepSeek, seletor logístico, ensemble
de prompts, reajuste de limiares) **não** entram nos defaults: mostraram
Δtune ≤ 0 e Δhold ≤ 0.

### Presets do Dr.DocBench

| Preset | Composição | Status |
|---|---|---|
| `drbench_v12` | differ-v12 (calibrado no dev) | nomeado, nunca default |
| `drbench_v13` | v12 + pic-need-text + formula-text | nomeado, nunca default |
| `drbench_v14` | v13 + line-numbers + table-eq + verse-chunk 300 | nomeado, nunca default |
| `drbench_v15` | v14 + juiz de página + tailjoin `end/50/3/hdr` + rep-guard + hf-end + upscale + orientation | **melhor confirmado no leaderboard** (EvalAI 70.37) |
| `drbench_best_method` | v15 + limiares do judge2 + page swap + páginas brancas + norm-text | melhor de dev (87.33), **nunca confirmado** — gap dev→test ≈ 8 pts |

`drbench_best_method` existe para tornar o melhor método do loop reproduzível
para trabalho futuro de performance. Ele nunca deve virar default: o ganho de
TEDS não transferiu (dev +5.9 → test +0.2), e o ganho real no test veio da ordem
de leitura com a fonte MinerU hybrid-VLM.

## Desenvolvimento

```bash
pip install -e "libs/docstruct[dev]"
pytest libs/docstruct/tests
```

`tests/test_purity.py` importa todos os módulos num interpretador que recusa `backend`, `acessilia_toolbox` e `acessilia_sdk`, então uma mudança que os importe falha mesmo quando eles estão instalados (como no CI do core).

## Releases

A Toolbox e os demais repositórios consomem um artefato publicado, não este
diretório. O `.github/workflows/docstruct-release.yml` publica uma wheel e um
sdist num GitHub Release quando é enviada uma tag igual à versão:

1. Atualizar `version` em `libs/docstruct/pyproject.toml` (versionamento
   semântico: mudar o comportamento ou a assinatura de uma função pública é
   major enquanto a versão for menor que 1.0, e minor depois).
2. Fazer o merge e criar a tag no commit mergeado:
   `git tag docstruct-v0.2.0 && git push origin docstruct-v0.2.0`.

O workflow recusa uma tag diferente da versão do pacote, roda esta suíte só com
a docstruct instalada, gera os arquivos de forma reprodutível a partir do commit
(`SOURCE_DATE_EPOCH`), importa todos os módulos a partir da wheel instalada e
anexa os arquivos com o SHA-256. As notas do release trazem a linha para copiar:

```
acessilia-docstruct @ https://github.com/A11yDevs/acessilia/releases/download/docstruct-v<versão>/acessilia_docstruct-<versão>-py3-none-any.whl#sha256=<hash>
```

O pip confere o fragmento `#sha256=` no download, inclusive quando o
consumidor instala sem arquivo de lock.
