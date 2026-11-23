## Mutation experiment (#644)

Module: `libs/docstruct/src/docstruct/fusion/flood.py`

Tests: `tests/test_flood.py`

| Total | Killed | Survived | Timeout | Uncovered | Invalid | Mutation score |
|---:|---:|---:|---:|---:|---:|---:|
| 17 | 17 | 0 | 0 | 0 | 0 | 100.0% |

Equivalent mutants are not identified automatically: a surviving mutant still needs a manual judgement.

### Mutants

| Id | Line | Mutation | Status | Killed by |
|---|---:|---|---|---|
| M001 | 48 | In -> NotIn | killed | `tests/test_flood.py::TestFloodGuard::test_blocos_longos_sao_preservados`, `tests/test_flood.py::TestFloodGuard::test_blocos_nao_textuais_sao_preservados`, `tests/test_flood.py::TestFloodGuard::test_descarta_blocos_curtos_sem_palavra_do_lexico`, `tests/test_flood.py::TestFloodGuard::test_lexico_vazio_descarta_todos_os_curtos`, `tests/test_flood.py::TestFloodGuard::test_o_comprimento_curto_e_inclusivo`, `tests/test_flood.py::TestFloodGuard::test_o_minimo_de_blocos_e_inclusivo`, `tests/test_flood.py::TestFloodGuard::test_ratio_e_respeitado`, `tests/test_flood.py::TestFloodGuard::test_tag_entra_nas_stats` |
| M002 | 49 | In -> NotIn | killed | `tests/test_flood.py::TestFloodGuard::test_nao_age_quando_a_nao_inunda_b`, `tests/test_flood.py::TestFloodGuard::test_ratio_e_respeitado` |
| M003 | 50 | negate condition | killed | `tests/test_flood.py::TestFloodGuard::test_blocos_longos_sao_preservados`, `tests/test_flood.py::TestFloodGuard::test_blocos_nao_textuais_sao_preservados`, `tests/test_flood.py::TestFloodGuard::test_descarta_blocos_curtos_sem_palavra_do_lexico`, `tests/test_flood.py::TestFloodGuard::test_lexico_vazio_descarta_todos_os_curtos`, `tests/test_flood.py::TestFloodGuard::test_nao_age_abaixo_do_minimo_de_blocos`, `tests/test_flood.py::TestFloodGuard::test_nao_age_quando_a_nao_inunda_b`, `tests/test_flood.py::TestFloodGuard::test_o_comprimento_curto_e_inclusivo`, `tests/test_flood.py::TestFloodGuard::test_o_minimo_de_blocos_e_inclusivo`, `tests/test_flood.py::TestFloodGuard::test_ratio_e_respeitado`, `tests/test_flood.py::TestFloodGuard::test_tag_entra_nas_stats` |
| M004 | 50 | Or -> And | killed | `tests/test_flood.py::TestFloodGuard::test_nao_age_abaixo_do_minimo_de_blocos`, `tests/test_flood.py::TestFloodGuard::test_nao_age_quando_a_nao_inunda_b`, `tests/test_flood.py::TestFloodGuard::test_ratio_e_respeitado` |
| M005 | 50 | Lt -> LtE | killed | `tests/test_flood.py::TestFloodGuard::test_o_minimo_de_blocos_e_inclusivo` |
| M006 | 50 | Lt -> LtE | killed | `tests/test_flood.py::TestFloodGuard::test_ratio_e_respeitado` |
| M007 | 52 | Or -> And | killed | `tests/test_flood.py::TestFloodGuard::test_descarta_blocos_curtos_sem_palavra_do_lexico`, `tests/test_flood.py::TestFloodGuard::test_o_comprimento_curto_e_inclusivo` |
| M008 | 55 | negate condition | killed | `tests/test_flood.py::TestFloodGuard::test_blocos_longos_sao_preservados`, `tests/test_flood.py::TestFloodGuard::test_blocos_nao_textuais_sao_preservados`, `tests/test_flood.py::TestFloodGuard::test_descarta_blocos_curtos_sem_palavra_do_lexico`, `tests/test_flood.py::TestFloodGuard::test_disparar_sem_descartar_nao_conta_pagina`, `tests/test_flood.py::TestFloodGuard::test_lexico_vazio_descarta_todos_os_curtos`, `tests/test_flood.py::TestFloodGuard::test_o_comprimento_curto_e_inclusivo`, `tests/test_flood.py::TestFloodGuard::test_o_minimo_de_blocos_e_inclusivo`, `tests/test_flood.py::TestFloodGuard::test_ratio_e_respeitado`, `tests/test_flood.py::TestFloodGuard::test_tag_entra_nas_stats` |
| M009 | 56 | And -> Or | killed | `tests/test_flood.py::TestFloodGuard::test_blocos_longos_sao_preservados`, `tests/test_flood.py::TestFloodGuard::test_blocos_nao_textuais_sao_preservados`, `tests/test_flood.py::TestFloodGuard::test_descarta_blocos_curtos_sem_palavra_do_lexico`, `tests/test_flood.py::TestFloodGuard::test_disparar_sem_descartar_nao_conta_pagina` |
| M010 | 56 | Eq -> NotEq | killed | `tests/test_flood.py::TestFloodGuard::test_blocos_longos_sao_preservados`, `tests/test_flood.py::TestFloodGuard::test_blocos_nao_textuais_sao_preservados`, `tests/test_flood.py::TestFloodGuard::test_descarta_blocos_curtos_sem_palavra_do_lexico`, `tests/test_flood.py::TestFloodGuard::test_lexico_vazio_descarta_todos_os_curtos`, `tests/test_flood.py::TestFloodGuard::test_o_comprimento_curto_e_inclusivo`, `tests/test_flood.py::TestFloodGuard::test_o_minimo_de_blocos_e_inclusivo`, `tests/test_flood.py::TestFloodGuard::test_ratio_e_respeitado`, `tests/test_flood.py::TestFloodGuard::test_tag_entra_nas_stats` |
| M011 | 57 | LtE -> Lt | killed | `tests/test_flood.py::TestFloodGuard::test_o_comprimento_curto_e_inclusivo` |
| M012 | 58 | remove not | killed | `tests/test_flood.py::TestFloodGuard::test_blocos_longos_sao_preservados`, `tests/test_flood.py::TestFloodGuard::test_blocos_nao_textuais_sao_preservados`, `tests/test_flood.py::TestFloodGuard::test_descarta_blocos_curtos_sem_palavra_do_lexico`, `tests/test_flood.py::TestFloodGuard::test_lexico_vazio_descarta_todos_os_curtos`, `tests/test_flood.py::TestFloodGuard::test_o_comprimento_curto_e_inclusivo`, `tests/test_flood.py::TestFloodGuard::test_o_minimo_de_blocos_e_inclusivo`, `tests/test_flood.py::TestFloodGuard::test_ratio_e_respeitado`, `tests/test_flood.py::TestFloodGuard::test_tag_entra_nas_stats` |
| M013 | 58 | In -> NotIn | killed | `tests/test_flood.py::TestFloodGuard::test_descarta_blocos_curtos_sem_palavra_do_lexico`, `tests/test_flood.py::TestFloodGuard::test_o_comprimento_curto_e_inclusivo` |
| M014 | 60 | Add -> Sub | killed | `tests/test_flood.py::TestFloodGuard::test_descarta_blocos_curtos_sem_palavra_do_lexico`, `tests/test_flood.py::TestFloodGuard::test_lexico_vazio_descarta_todos_os_curtos`, `tests/test_flood.py::TestFloodGuard::test_o_comprimento_curto_e_inclusivo`, `tests/test_flood.py::TestFloodGuard::test_tag_entra_nas_stats` |
| M015 | 63 | negate condition | killed | `tests/test_flood.py::TestFloodGuard::test_descarta_blocos_curtos_sem_palavra_do_lexico`, `tests/test_flood.py::TestFloodGuard::test_disparar_sem_descartar_nao_conta_pagina`, `tests/test_flood.py::TestFloodGuard::test_o_minimo_de_blocos_e_inclusivo` |
| M016 | 63 | Lt -> LtE | killed | `tests/test_flood.py::TestFloodGuard::test_disparar_sem_descartar_nao_conta_pagina` |
| M017 | 64 | Add -> Sub | killed | `tests/test_flood.py::TestFloodGuard::test_descarta_blocos_curtos_sem_palavra_do_lexico`, `tests/test_flood.py::TestFloodGuard::test_o_minimo_de_blocos_e_inclusivo` |

### Test subsumption

A subsumes B when every mutant B kills, A also kills. High coverage similarity does not imply this relation.

| Subsumer | Subsumed | Mutants | Equal sets | Coverage Jaccard |
|---|---|---:|---|---:|
| `tests/test_flood.py::TestFloodGuard::test_descarta_blocos_curtos_sem_palavra_do_lexico` | `tests/test_flood.py::TestFloodGuard::test_blocos_longos_sao_preservados` | 6 | no | — |
| `tests/test_flood.py::TestFloodGuard::test_descarta_blocos_curtos_sem_palavra_do_lexico` | `tests/test_flood.py::TestFloodGuard::test_blocos_nao_textuais_sao_preservados` | 6 | no | — |
| `tests/test_flood.py::TestFloodGuard::test_descarta_blocos_curtos_sem_palavra_do_lexico` | `tests/test_flood.py::TestFloodGuard::test_lexico_vazio_descarta_todos_os_curtos` | 6 | no | — |
| `tests/test_flood.py::TestFloodGuard::test_descarta_blocos_curtos_sem_palavra_do_lexico` | `tests/test_flood.py::TestFloodGuard::test_tag_entra_nas_stats` | 6 | no | — |
| `tests/test_flood.py::TestFloodGuard::test_o_comprimento_curto_e_inclusivo` | `tests/test_flood.py::TestFloodGuard::test_lexico_vazio_descarta_todos_os_curtos` | 6 | no | — |
| `tests/test_flood.py::TestFloodGuard::test_o_comprimento_curto_e_inclusivo` | `tests/test_flood.py::TestFloodGuard::test_tag_entra_nas_stats` | 6 | no | — |
| `tests/test_flood.py::TestFloodGuard::test_ratio_e_respeitado` | `tests/test_flood.py::TestFloodGuard::test_nao_age_quando_a_nao_inunda_b` | 3 | no | — |
| `tests/test_flood.py::TestFloodGuard::test_nao_age_quando_a_nao_inunda_b` | `tests/test_flood.py::TestFloodGuard::test_nao_age_abaixo_do_minimo_de_blocos` | 2 | no | — |
| `tests/test_flood.py::TestFloodGuard::test_ratio_e_respeitado` | `tests/test_flood.py::TestFloodGuard::test_nao_age_abaixo_do_minimo_de_blocos` | 2 | no | — |
| `tests/test_flood.py::TestFloodGuard::test_blocos_longos_sao_preservados` | `tests/test_flood.py::TestFloodGuard::test_blocos_nao_textuais_sao_preservados` | 6 | yes | — |
| `tests/test_flood.py::TestFloodGuard::test_lexico_vazio_descarta_todos_os_curtos` | `tests/test_flood.py::TestFloodGuard::test_tag_entra_nas_stats` | 6 | yes | — |

### Mutants detected by exactly one test

| Test | Mutants |
|---|---|
| `tests/test_flood.py::TestFloodGuard::test_disparar_sem_descartar_nao_conta_pagina` | M016 |
| `tests/test_flood.py::TestFloodGuard::test_o_comprimento_curto_e_inclusivo` | M011 |
| `tests/test_flood.py::TestFloodGuard::test_o_minimo_de_blocos_e_inclusivo` | M005 |
| `tests/test_flood.py::TestFloodGuard::test_ratio_e_respeitado` | M006 |
