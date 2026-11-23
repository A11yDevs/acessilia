## Coverage overlap (#644)

9 tests, 15 executed lines, 18 pairs at Jaccard >= 0.5 with at least 2 shared lines.
0 parametrized families with identical line coverage; 9 tests without an exclusive production line.

No test is removed by this report: high overlap is a review candidate.

| Test A | Test B | Jaccard | Shared | Only A | Only B | Param. |
|---|---|---:|---:|---:|---:|---|
| `tests/test_flood.py::TestFloodGuard::test_blocos_longos_sao_preservados` | `tests/test_flood.py::TestFloodGuard::test_blocos_nao_textuais_sao_preservados` | 1.000 | 14 | 0 | 0 |  |
| `tests/test_flood.py::TestFloodGuard::test_blocos_longos_sao_preservados` | `tests/test_flood.py::TestFloodGuard::test_descarta_blocos_curtos_sem_palavra_do_lexico` | 1.000 | 14 | 0 | 0 |  |
| `tests/test_flood.py::TestFloodGuard::test_blocos_nao_textuais_sao_preservados` | `tests/test_flood.py::TestFloodGuard::test_descarta_blocos_curtos_sem_palavra_do_lexico` | 1.000 | 14 | 0 | 0 |  |
| `tests/test_flood.py::TestFloodGuard::test_lexico_vazio_descarta_todos_os_curtos` | `tests/test_flood.py::TestFloodGuard::test_tag_entra_nas_stats` | 1.000 | 13 | 0 | 0 |  |
| `tests/test_flood.py::TestFloodGuard::test_lista_vazia_nao_quebra` | `tests/test_flood.py::TestFloodGuard::test_nao_age_abaixo_do_minimo_de_blocos` | 1.000 | 4 | 0 | 0 |  |
| `tests/test_flood.py::TestFloodGuard::test_lista_vazia_nao_quebra` | `tests/test_flood.py::TestFloodGuard::test_nao_age_quando_a_nao_inunda_b` | 1.000 | 4 | 0 | 0 |  |
| `tests/test_flood.py::TestFloodGuard::test_nao_age_abaixo_do_minimo_de_blocos` | `tests/test_flood.py::TestFloodGuard::test_nao_age_quando_a_nao_inunda_b` | 1.000 | 4 | 0 | 0 |  |
| `tests/test_flood.py::TestFloodGuard::test_blocos_longos_sao_preservados` | `tests/test_flood.py::TestFloodGuard::test_lexico_vazio_descarta_todos_os_curtos` | 0.929 | 13 | 1 | 0 |  |
| `tests/test_flood.py::TestFloodGuard::test_blocos_longos_sao_preservados` | `tests/test_flood.py::TestFloodGuard::test_tag_entra_nas_stats` | 0.929 | 13 | 1 | 0 |  |
| `tests/test_flood.py::TestFloodGuard::test_blocos_nao_textuais_sao_preservados` | `tests/test_flood.py::TestFloodGuard::test_lexico_vazio_descarta_todos_os_curtos` | 0.929 | 13 | 1 | 0 |  |
| `tests/test_flood.py::TestFloodGuard::test_blocos_nao_textuais_sao_preservados` | `tests/test_flood.py::TestFloodGuard::test_tag_entra_nas_stats` | 0.929 | 13 | 1 | 0 |  |
| `tests/test_flood.py::TestFloodGuard::test_descarta_blocos_curtos_sem_palavra_do_lexico` | `tests/test_flood.py::TestFloodGuard::test_lexico_vazio_descarta_todos_os_curtos` | 0.929 | 13 | 1 | 0 |  |
| `tests/test_flood.py::TestFloodGuard::test_descarta_blocos_curtos_sem_palavra_do_lexico` | `tests/test_flood.py::TestFloodGuard::test_tag_entra_nas_stats` | 0.929 | 13 | 1 | 0 |  |
| `tests/test_flood.py::TestFloodGuard::test_lexico_vazio_descarta_todos_os_curtos` | `tests/test_flood.py::TestFloodGuard::test_ratio_e_respeitado` | 0.929 | 13 | 0 | 1 |  |
| `tests/test_flood.py::TestFloodGuard::test_ratio_e_respeitado` | `tests/test_flood.py::TestFloodGuard::test_tag_entra_nas_stats` | 0.929 | 13 | 1 | 0 |  |
| `tests/test_flood.py::TestFloodGuard::test_blocos_longos_sao_preservados` | `tests/test_flood.py::TestFloodGuard::test_ratio_e_respeitado` | 0.867 | 13 | 1 | 1 |  |
| `tests/test_flood.py::TestFloodGuard::test_blocos_nao_textuais_sao_preservados` | `tests/test_flood.py::TestFloodGuard::test_ratio_e_respeitado` | 0.867 | 13 | 1 | 1 |  |
| `tests/test_flood.py::TestFloodGuard::test_descarta_blocos_curtos_sem_palavra_do_lexico` | `tests/test_flood.py::TestFloodGuard::test_ratio_e_respeitado` | 0.867 | 13 | 1 | 1 |  |

### Parametrized families with identical coverage

| Family | Variants | Lines |
|---|---:|---:|
| — | — | — |

### Tests with no exclusive line

These tests cover no line that another test in the same report does not also cover. They are the strongest overlap candidates, not a verdict: they can still be the only one checking a contract or an error message.

| Test | Lines |
|---|---:|
| `tests/test_flood.py::TestFloodGuard::test_blocos_longos_sao_preservados` | 14 |
| `tests/test_flood.py::TestFloodGuard::test_blocos_nao_textuais_sao_preservados` | 14 |
| `tests/test_flood.py::TestFloodGuard::test_descarta_blocos_curtos_sem_palavra_do_lexico` | 14 |
| `tests/test_flood.py::TestFloodGuard::test_ratio_e_respeitado` | 14 |
| `tests/test_flood.py::TestFloodGuard::test_lexico_vazio_descarta_todos_os_curtos` | 13 |
| `tests/test_flood.py::TestFloodGuard::test_tag_entra_nas_stats` | 13 |
| `tests/test_flood.py::TestFloodGuard::test_lista_vazia_nao_quebra` | 4 |
| `tests/test_flood.py::TestFloodGuard::test_nao_age_abaixo_do_minimo_de_blocos` | 4 |
| `tests/test_flood.py::TestFloodGuard::test_nao_age_quando_a_nao_inunda_b` | 4 |
