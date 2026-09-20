# Relatório de Validação do Core — Acessilia

| Campo | Valor |
|---|---|
| **Alvo** | Acessilia Core (Python) — branch `develop` @ `315cead` |
| **Testador** | Pedro Alano (testes E2E / homologação) |
| **Data** | 2026-09-20 |
| **Método** | Validação **offline**: suíte pytest completa, testes exploratórios, verificação de montagem da app e leitura de código. (O Gestor/navegador ficou de fora porque o **ambiente de dev está instável**.) |

## Contexto — a arquitetura mudou

Desde a v0.1.0 o core foi bastante refatorado:
- **Poetry → pip** (`pip install ".[dev]"`, PEP 621).
- **Docling/RapidOCR saíram do core** → viraram serviço **Toolbox**.
- **Pipeline agora é só PDDL + Toolbox** (`PIPELINE_ENGINE=pddl`); os motores **legacy** e **PDDL+local** foram **desativados** (o código levanta `RuntimeError` se `PIPELINE_ENGINE=legacy`).

> ⚙️ **Nota de ambiente:** um `.env` antigo com `PIPELINE_ENGINE=legacy` **quebra** a app/os testes agora. Usar `PIPELINE_ENGINE=pddl`.

---

## 1. Validação da suíte (offline)

`pytest -m "not e2e"` na máquina do testador (Windows, Python 3.11):

| Métrica | Valor |
|---|---|
| ✅ Passaram | **493** |
| ⚠️ Falharam | 33 |
| ⏭️ Deselecionados | 39 (`e2e`, exigem Toolbox) |
| ❔ xpassed | 1 |

**As 33 falhas são exclusivas de Windows, não são bug do app** (o CI no Linux está verde):
- `tests/test_formula_timeout.py` (28) — usa `os.killpg` e protocolo de file-descriptor POSIX (não existe no Windows).
- `tests/test_staging_update.py` (5) — executa scripts `.sh` (`WinError 193` no Windows).

**Achado menor:** 1 teste **xpassed** — um teste marcado como `xfail` (`test_worker_pipeline_failure`) que **agora passa**. O marcador `xfail` provavelmente está **obsoleto** e pode ser removido para o teste voltar a proteger de regressão.

## 2. Bug #99 — teste de regressão (cruzamento de dados entre usuários)

O fix (PR #100) está **mergeado e passando**. Porém os testes que vieram com ele são **rasos**: checam só o *formato da chave* e se o *owner é armazenado*, **sem provar o isolamento**.

➡️ **Criado `tests/test_issue_99_cross_user.py`** (3 testes) que reproduz o cenário:
1. cache não cruza dados entre dois documentos diferentes;
2. a chave usa **SHA-256 completo (64)** + tamanho do arquivo;
3. dois jobs de **donos diferentes** geram tokens isolados (cada token só devolve o próprio arquivo).

**Prova de que é regressão de verdade:** rodado contra o código **antes** do PR #100 → **2 dos 3 falham** (hash truncado em 16 chars; `criar_token` sem `task_id`/`owner`); contra o **corrigido** → **os 3 passam**.

> ⚠️ **Limite:** o cruzamento real em **entrega concorrente no Telegram** não é reproduzível em teste unitário — precisa do app rodando. Como o dev está instável, esse cenário fica pendente (idealmente validar em produção, com cuidado).

## 3. Validação de entrada (upload) — testes exploratórios

➡️ **Criado `tests/test_validators_edge_cases.py`** (21 testes, **todos passam**) cobrindo `backend/tools/validators.py`:
- rejeita extensões perigosas (`.exe/.bat/.sh/.js/.php/.bin/.cmd`) e arquivo **sem extensão**;
- aceita as permitidas de forma **case-insensitive** (`.JPG`, `.Jpeg`…);
- **dupla extensão** perigosa no final (`malware.pdf.exe`) é barrada;
- limite de tamanho: **exatamente no limite** aceita, **1 byte acima** barra.

**Achados menores (baixo risco):**
- **Quirk documentado:** só a **última** extensão conta, então `payload.exe.pdf` **é aceito**. O conteúdo não é executado (vira artefato), mas fica registrado.
- **Inconsistência:** `.gif` está na whitelist, mas a **mensagem de erro** de formato não menciona GIF (lista "PDF, DOCX, HTML, PNG, JPG, TIFF, BMP ou WEBP").
- **Código morto:** `validate_file` tem uma regra para `PIPELINE_ENGINE=legacy` (rejeitar DOCX/HTML) que **nunca executa**, pois o motor legacy foi desativado antes.

## 4. Montagem da aplicação (smoke)

Importação/montagem offline OK:
- `backend.api.app.create_app()` monta a API com **12 rotas** (jobs, download, history, stats, health, docs…).
- `backend.service` importa e normaliza o engine como `pddl`; backend PDDL usa `ToolboxManifestExtractor`.
- `frontend.web.app` importa sem erro.

## 5. Achados anteriores que **seguem presentes** no `develop` (revalidados)

Da revisão de segurança anterior do core — ainda no código:
- **`backend/api/routes/history.py`** — `/history` e `/stats` **sem autenticação**, e `/history` devolve `extra = {toda coluna do banco fora da lista}` (vaza colunas novas). *Média (Alta em produção com dados reais).*
- **`frontend/web/messages.py:11`** — `WEB_ERROR_INTERNAL = "Internal server error: {error}"` → o handler global da web mostra `str(exc)` na tela do usuário. A **API** faz certo (mensagem genérica); a web deveria copiar. *Média.*

---

## Resumo / veredito

- **Core valida bem offline:** 493 testes passam; as 33 falhas são portabilidade Windows (CI Linux verde).
- **Fix do #99 confirmado** e agora coberto por um **teste de regressão real** (`tests/test_issue_99_cross_user.py`).
- **Validação de entrada robusta**, com 2 quirks e 1 trecho de código morto de baixo risco.
- **2 achados anteriores** (history sem auth / erro web vazando `str(exc)`) **seguem em aberto**.

## Próximos passos sugeridos
1. Levar os 2 novos arquivos de teste para a `develop` via PR (estão prontos e verdes).
2. Remover o `xfail` obsoleto de `test_worker_pipeline_failure`.
3. Time decidir sobre os achados da Seção 5 (auth no `/history`+`/stats`; mensagem genérica na web).
4. Quando o dev estabilizar, reproduzir o cruzamento concorrente do #99 no app rodando.

> **Papel:** relatório de teste/homologação. Os testes novos são **sugestão** para o time levar à `develop`; nenhum código de produção foi alterado pelo testador.
