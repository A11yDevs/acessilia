# 🐛 Testes de `stats`/`history` não são isolados do banco real (falham após usar o app)

## Identificação
| Campo | Valor |
|---|---|
| **ID** | BUG-0002 |
| **Data** | 2026-08-26 |
| **Reportado por** | Pedro Alano |
| **Severidade** | 🟡 Média |
| **Status** | Aberto · a reportar como issue (não corrigido no repo) |
| **Link da issue** | <preencher ao abrir no GitHub> |

## Ambiente
| Item | Valor |
|---|---|
| SO | Windows 11 |
| Python | 3.11 |
| Branch / commit | `main` @ `5c7cf41` (independe do commit; presente desde antes) |
| Motor / estruturador / IA | irrelevante (é sobre estado do banco de histórico) |

## Resumo
`tests/test_api.py::test_stats_empty` e `::test_history_empty` assumem que o banco de histórico está **vazio**. Depois de rodar o app e converter qualquer documento (que grava em `var/data/history.db`), os dois testes **falham**. Passam apenas em cópia limpa / no CI, onde o banco começa vazio.

## Entrada usada
- Não se aplica um arquivo específico — basta existir **≥ 1 conversão registrada** em `var/data/history.db`.
- Reproduzido com 5 conversões reais feitas pelo painel (ex.: `task_id 1b656a43`).

## Passos para reproduzir
1. Em cópia limpa: `poetry run pytest tests/test_api.py -k "stats_empty or history_empty"` → **passa**.
2. Subir o app e converter **≥ 1 documento** (grava em `var/data/history.db`).
3. Rodar os mesmos testes de novo → **falham**.
4. Prova complementar: rodar com um banco vazio temporário volta ao verde:
   ```powershell
   $env:DATA_DIR="$env:TEMP\acessilia-test-data"; poetry run pytest -m "not docling"
   ```
   → **133 passed** (confirma que a única causa é o banco populado).

## Resultado esperado
Os testes são **herméticos**: independem do estado do banco real (usam sempre um banco isolado/temporário).

## Resultado obtido
Leem o banco real `var/data/history.db`:

```
FAILED tests/test_api.py::test_stats_empty
  assert {'total': 5, 'sucesso': 5, 'erros': 0, 'tempo_medio_segundos': 45.1} == {'total': 0, ...}
FAILED tests/test_api.py::test_history_empty
  assert [{'task_id': '1b656a43', ...}, ...(5 itens)] == []
```

## Causa raiz (identificada)
`backend/services/history_service.py`:
- **Linha 6:** `DB_PATH = settings.db_path` — o caminho é fixado **no import** (constante de módulo).
- `get_connection()` (linha ~71) usa essa global `DB_PATH`, **não** `settings.db_path` dinâmico.
- O fixture `_isolate_paths` em `tests/test_api.py` faz `monkeypatch.setattr(settings, "data_dir", <temp>)` e `hs._connection = None`, mas como `DB_PATH` **já foi capturado no import**, o monkeypatch **não redireciona** o histórico → os testes leem o banco real.
- `backend/services/download_token_service.py` provavelmente tem o **mesmo padrão latente** (mesmo `_connection` resetado pelo fixture).

## Correção sugerida
1. **Produção (preferível):** `get_connection()` resolver o caminho **dinamicamente** a cada abertura, lendo `settings.db_path` em vez da global `DB_PATH` fixada no import. (Idem `download_token_service`.)
2. **Alternativa lado-teste:** o fixture `_isolate_paths` também sobrescrever `history_service.DB_PATH` (e o equivalente do download_token_service).

## Impacto em testes / regressão
- **Coberto por teste automatizado?** Não — são os próprios testes que estão frágeis (falta isolamento).
- O CI passa porque sempre roda com banco vazio → **mascara** o problema.
- **Sugestões para o CI/CD:**
  - Fixture que garanta banco **temporário para toda a suíte** de API.
  - Teste que rode `stats`/`history` com o banco **populado** (no temp), validando a **lógica de contagem** — hoje só o caso vazio é coberto.

## Evidências
- Falha reproduzida em `main @ 5c7cf41` após 5 conversões reais.
- Verde (133) restaurado ao apontar `DATA_DIR` para pasta vazia — prova da causa.
