# Registro de bugs e testes — Acessilia

Registro de bugs e resultados de teste levantados durante a homologação, por **Pedro Alano**.
Para reportar um bug novo, copie o [`BUG_TEMPLATE.md`](BUG_TEMPLATE.md) para `NNNN-slug.md`.

## Findings

| ID | Título | Severidade | Status |
|---|---|---|---|
| [0001](0001-html-export-crash.md) | Conversão web/API quebra na exportação HTML (`_run_in_executor` não aceita kwargs) | 🔴 Crítica | Corrigido localmente · a reportar |
| [0002](0002-test-isolation-history-db.md) | Testes de `stats`/`history` não isolados do banco real | 🟡 Média | Aberto |
| [0003](0003-vision-no-description-dark-image.md) | Modelo de visão recusa imagens válidas de forma inconsistente, sem validação no pipeline | 🟠 Alta | Confirmado (questão de modelo) |
| [0004](0004-api-blocks-during-inference.md) | API sem responder durante a inferência (bloqueio do event loop) | 🟡 Média | Aberto |

> **Tema comum (0001 e 0002):** o CI passa verde, mas os defeitos existem — o 0001 tem o trecho *mockado* e o 0002 só falha com banco populado. Reforça a necessidade de testes E2E além do CI.

## Sessão de testes E2E — 2026-09-01

### Metodologia
Aplicação rodando **localmente** (Windows) com `AI_CLIENT=ollama`, `OLLAMA_MODEL=llava:7b`, motor `legacy`, estruturador `docling`. Testes disparados por um **script automatizado** via API REST (`e2e_cache_test.py`): faz upload, mede tempo, baixa o TXT e compara resultados. Reutilizável para os testes E2E na VPS.

### Entradas e resultados
| Entrada | Tempo | Resultado |
|---|---|---|
| 🐧 pinguins (1ª vez) | 39 s | descrição gerada (698 chars) |
| 🐧 pinguins (2ª vez) | 3 s | **idêntico** → cache hit |
| 🧘 yoga (silhueta escura) | ~9 s | ❌ "Não há imagem anexada para descrever" → **[0003](0003-vision-no-description-dark-image.md)** |
| 📄 PDF 001 (Java OO, 3 pág.) | 57 s | texto extraído (5.059 chars) + figura da pág. 3 descrita ✅ |

### Cache — verificado OK (sem bug)
A chave do cache é o **hash do conteúdo** do arquivo. Reenviar a **mesma** imagem → cache hit (rápido e idêntico); imagens diferentes **não se misturam**. O log confirma `Cache hit para ...`.

> ⚠️ **Sobre o "bug de cache" atribuído em reunião:** **não reproduzido** no cenário de mesma imagem. Candidato remanescente: a chave **não inclui o modelo** (`_cache_version` = `{ai_client}-{engine}-v1`; cache por página = `page_{n}_{mode}`) — trocar apenas o **modelo** e reenviar a mesma imagem tende a devolver resultado antigo (stale). Ainda **não testado** (requer 2 modelos). *Confirmar com a equipe o que foi originalmente observado.*

### Qualidade das descrições (com `llava:7b`)
- **Pinguins:** descreveu, mas com erros do modelo (ex.: "três **pingos**" em vez de "pinguins"). Limite do modelo gratuito.
- **PDF:** boa extração de texto e descrição da figura embutida. (Cosmético: texto sai com tabs `\t`.)
- **Yoga:** o `llava:7b` recusou (ver 0003). Modelos melhores descreveram bem — ver **[Comparativo de modelos de visão](comparativo-modelos-visao.md)**.

### Comparativo de modelos de visão
Teste das mesmas imagens em vários modelos confirmou que a falha do 0003 é **questão de modelo**: `llava:7b` recusa de forma inconsistente, enquanto `minimax-m3` e `dots-3-note-preview` (gratuitos, via OpenRouter) descreveram tudo bem. Detalhes e ressalvas em **[comparativo-modelos-visao.md](comparativo-modelos-visao.md)**.

### Ambiente de dependências (observações)
- **PDF/UA** não é gerado localmente: exige **Pandoc + engine LaTeX** (não instalados). É tratado por `try/except`, não derruba o job — mas o formato fica ausente.
