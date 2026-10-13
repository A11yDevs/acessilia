# acessilia-docstruct

Núcleo puro de processamento estrutural de documentos do Acessilia.

> Também disponível em **inglês (EUA)**: [English version](README.md) — versão autoritativa.

## Princípios

- **Pura**: nenhuma função toca rede, arquivos, subprocess, settings, logger ou i18n dinâmico.
- **Direção única de dependência**: `backend → docstruct`. A lib nunca importa de `backend/`.
- **i18n = msgids**: funções que produzem mensagens retornam `(msgid, args)`; o consumidor traduz.
- **IDs determinísticos ou injetados**: nada de `uuid4` dentro da lib.

## API pública (v0.1)

| Módulo | Símbolos |
|---|---|
| `docstruct.types` | `BBox`, `CanonicalBlock`, `CanonicalDocument`, `Region`, `BlockPairing`, `OrientationResult` |
| `docstruct.geometry` | `content_fingerprint`, `overlaps_clean`, `merge_bboxes`, `union` |
| `docstruct.policy` | `FusionPolicy` (+ presets) |
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
| `docstruct.text` | `normalize.norm`, `norm_fix.norm_fix`, `latex.normalize_latex` |
| `docstruct.imaging.policy` | `upscale_factor`, `decide_orientation` (sem PIL/cv2) |
| `docstruct.evaluation.holdout` | `partition`, `score`, `evaluate_candidate` |

Módulos planejados (fases 2–3): `blocks/`, `regions/`, `tables/`, `math/`, `render/`, `validation.py`.

## Fusão (`docstruct.fusion`)

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
- `text/normalize.py`, `text/norm_fix.py`, `text/latex.py` — primitivas de
  normalização de texto.
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

O CI roda `pytest libs/docstruct/tests` sem o backend instalado — se precisar
importar `backend/`, a mudança está violando o desacoplamento.