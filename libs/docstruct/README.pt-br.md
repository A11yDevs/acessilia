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

Módulos planejados (fases 2–3): `text/`, `blocks/`, `regions/`, `tables/`, `math/`, `render/`, `validation.py`.

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
- `FusionPolicy` — frozen dataclass com defaults conservadores; presets de
  benchmark (`drbench_v12`, `drbench_v13`) são classmethods nomeados, nunca
  defaults (foram sobreajustados ao split dev).

## Desenvolvimento

```bash
pip install -e "libs/docstruct[dev]"
pytest libs/docstruct/tests
```

O CI roda `pytest libs/docstruct/tests` sem o backend instalado — se precisar
importar `backend/`, a mudança está violando o desacoplamento.