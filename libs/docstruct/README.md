# acessilia-docstruct

Pure document-structure processing core for Acessilia.

> Also available in **Brazilian Portuguese**: [Portuguese version](README.pt-br.md)

## Principles

- **Pure**: no function touches network, files, subprocess, settings, logger, or dynamic i18n.
- **Single dependency direction**: `backend → docstruct`. The lib never imports from `backend/`.
- **i18n = msgids**: functions that produce messages return `(msgid, args)`; the consumer translates.
- **Deterministic or injected IDs**: no `uuid4` inside the lib.

## Public API (v0.1)

| Module | Symbols |
|---|---|
| `docstruct.types` | `BBox`, `CanonicalBlock`, `CanonicalDocument`, `Region`, `BlockPairing`, `OrientationResult` |
| `docstruct.geometry` | `content_fingerprint`, `overlaps_clean`, `merge_bboxes`, `union` |
| `docstruct.policy` | `FusionPolicy` (+ presets) |
| `docstruct.fusion` | `merge_blocks`, `block_to_diff`, `DiffBlock`, `ProviderBlocks`, `quality`, `is_junk` |
| `docstruct.fusion.xycut` | `xycut_order`, `count_columns`, `column_balance`, `reorder` — optional XY-cut reading order (`FusionPolicy.order_xycut`) |

Planned modules (phases 2–3): `text/`, `blocks/`, `regions/`, `tables/`, `math/`, `render/`, `validation.py`.

## Fusion (`docstruct.fusion`)

Port of the Tree Differ v2 from PR #98 (Dr.DocBench) as a pure library:

- `merge_blocks(D, M, policy)` — block-level merge of two providers with
  Hungarian text+bbox alignment; provider B (MinerU) provides the reading
  order skeleton; unmatched A blocks are inserted next to their geometric
  nearest neighbor.
- `_hungarian.py` — pure Kuhn-Munkres O(n³) implementation (replaces scipy;
  zero dependencies).
- `noise.py` — decor-tail, running heads, junk filter, region suppression,
  paragraph re-fusion, line-run fusing.
- `FusionPolicy` — frozen dataclass with conservative defaults; benchmark
  presets (`drbench_v12`, `drbench_v13`, `drbench_v14`, `drbench_v15`,
  `drbench_best_method`) are named classmethods, never defaults (they were
  overfitted to the dev split).
- `fusion/verse.py`, `fusion/line_numbers.py`, `fusion/flood.py`,
  `fusion/tailjoin.py`, `fusion/repetition.py`, `fusion/page_select.py`,
  `fusion/judge.py`, `fusion/adjudication.py`, `fusion/oracle.py`,
  `fusion/hf_end.py`, `fusion/table_specialist.py` — the deterministic
  Dr.DocBench PR #125 policies, ported as pure functions.
- `text/normalize.py`, `text/norm_fix.py`, `text/latex.py` — text
  normalization primitives.
- `imaging/policy.py` — pure upscale/orientation decisions (no PIL/cv2).

### Dr.DocBench presets

| Preset | Composition | Status |
|---|---|---|
| `drbench_v12` | differ-v12 (calibrated on dev) | named, never default |
| `drbench_v13` | v12 + pic-need-text + formula-text | named, never default |
| `drbench_v14` | v13 + line-numbers + table-eq + verse-chunk 300 | named, never default |
| `drbench_v15` | v14 + page judge + tailjoin `end/50/3/hdr` + rep-guard + hf-end + upscale + orientation | **confirmed leaderboard best** (EvalAI 70.37) |
| `drbench_best_method` | v15 + judge2 thresholds + page swap + blank pages + norm-text | dev best (87.33), **never confirmed** — dev→test gap ≈ 8 pts |

`drbench_best_method` exists to make the loop's best method reproducible for
future performance work. It must never become a default: the TEDS gain did not
transfer (dev +5.9 → test +0.2), and the real test gain came from reading order
with the MinerU hybrid-VLM source.

## Development

```bash
pip install -e "libs/docstruct[dev]"
pytest libs/docstruct/tests
```

CI runs `pytest libs/docstruct/tests` without the backend installed — if a
change needs to import `backend/`, it is violating the decoupling.
