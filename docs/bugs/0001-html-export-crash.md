# 🐛 Conversão web/API quebra na exportação HTML (`_run_in_executor` não aceita kwargs)

## Identificação
| Campo | Valor |
|---|---|
| **ID** | BUG-0001 |
| **Data** | 2026-08-26 |
| **Reportado por** | Pedro Alano |
| **Severidade** | 🔴 Crítica |
| **Status** | Corrigido localmente (patch não commitado) · a reportar como issue |
| **Link da issue** | <preencher ao abrir no GitHub> |

## Ambiente
| Item | Valor |
|---|---|
| SO | Windows 11 |
| Python | 3.11 |
| Branch / commit | presente em `main` **e** `develop`; introduzido no commit `aa53214` |
| Motor (`PIPELINE_ENGINE`) | legacy (independe do motor) |
| Estruturador (`STRUCTURER`) | docling |
| IA (`AI_CLIENT` + modelo) | reproduz com qualquer backend (ollama `llava:7b` e openrouter) |
| Interface | web / api |

## Resumo
Toda conversão via painel web/API aborta na etapa de exportar o **HTML**, com `TypeError`, antes de gerar MP3, ZIP, token e link de download.

## Entrada usada (qual arquivo/imagem)
- **Arquivo:** qualquer imagem ou PDF (ex.: `input/005.jpeg` do dataset, ou um print `.png`).
- **Observação:** o bug **não** depende do arquivo nem do conteúdo — ocorre em 100% das conversões.

## Passos para reproduzir
1. `.env` com `ENABLED_INTERFACES=api,web` (qualquer backend de IA).
2. `poetry run python -m frontend.run`
3. Abrir `http://localhost:8001` e enviar qualquer imagem/PDF.
4. Observar o worker falhar no log logo após a IA concluir.

## Resultado esperado
Job conclui e disponibiliza o pacote completo: **TXT, DOCX, PDF, (PDF/UA), HTML, MP3, ZIP** + link de download.

## Resultado obtido
Job aborta. Apenas `TXT`, `DOCX` e `PDF` são gravados (etapas anteriores ao crash); sem HTML, MP3, ZIP, token ou e-mail de resultado.

```
2026-... | WARNING | backend.api.worker:run:134 - Falha ao gerar PDF/UA: pandoc não encontrado no PATH.
2026-... | ERROR   | backend.api.worker:run:192 - Erro no JobExecutor para <task_id>
Traceback (most recent call last):
  ...
  File ".../backend/api/worker.py", line 139, in run
    await self._run_in_executor(
TypeError: JobExecutor._run_in_executor() got an unexpected keyword argument 'format_name'
```

## Causa raiz (identificada)
`backend/api/worker.py`:
- `_run_in_executor(self, fn, *args)` (linha ~81) só aceita argumentos **posicionais**.
- A exportação do HTML (linha ~139) chama passando **kwargs**: `format_name="html"`, `title=base`, `profile_name="html"`.
- `loop.run_in_executor` também não repassa kwargs → `TypeError`.

As exportações anteriores (TXT/DOCX/PDF) usam só posicionais, por isso funcionam; o crash começa exatamente no HTML.

## Correção sugerida (validada localmente)
```python
import functools  # topo do arquivo

def _run_in_executor(self, fn, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return loop.run_in_executor(
        self._executor, functools.partial(fn, *args, **kwargs)
    )
```
Retrocompatível: as chamadas posicionais continuam funcionando. **Confirmado:** com o patch, o job gera o pacote completo (HTML + MP3 + ZIP).

## Impacto em testes / regressão
- **Coberto por teste automatizado?** **Não** de forma efetiva.
- `tests/test_api.py::test_download_full_flow` passa (verde) porque **mocka** o caminho de exportação e nunca executa a chamada real com kwargs → **lacuna de cobertura**.
- **Teste sugerido para o CI/CD:** exercitar `JobExecutor.run` de ponta a ponta com um _fake_ de `export_accessible_document` que **preserve a assinatura** (aceite `format_name`/`title`/`profile_name`), garantindo que o helper repassa os kwargs.

## Evidências
- **Antes do fix:** `var/temp/output/<task_id>/` contém só `.txt`, `.docx`, `.pdf`.
- **Depois do fix:** a mesma pasta contém também `.html`, `.mp3` e `_acessivel.zip` (pacote completo).
- Nota: o aviso `pandoc não encontrado` (PDF/UA) é **outro assunto** (dependência de sistema ausente), tratado por `try/except` e não relacionado a este bug.
