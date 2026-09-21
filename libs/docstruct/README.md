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
  presets (`drbench_v12`, `drbench_v13`) are named classmethods, never
  defaults (they were overfitted to the dev split).

## Development

```bash
pip install -e "libs/docstruct[dev]"
pytest libs/docstruct/tests
```

CI runs `pytest libs/docstruct/tests` without the backend installed — if a
change needs to import `backend/`, it is violating the decoupling.
