# 🐛 Cancelamento durante exportação permite publicação do resultado

## Identificação

| Campo | Valor |
|---|---|
| **ID** | BUG-0003 |
| **Data** | 2026-09-05 |
| **Reportado por** | Wryel Teodoro |
| **Severidade** | 🟠 Alta |
| **Status** | Aberto · reproduzido em ambiente isolado |

## Ambiente

| Item | Valor |
|---|---|
| SO | Linux |
| Python | 3.12.3 (revalidação isolada) |
| Branch / commit | [release/0.1.0](https://github.com/A11yDevs/acessilia/tree/release/0.1.0) @ `7a5e70f4809dd4bae29cfb772042d12784fc48b6` |
| Motor (`PIPELINE_ENGINE`) | `legacy` configurado; retorno do orquestrador simulado antes da exportação |
| Estruturador (`STRUCTURER`) | `pymupdf` configurado; extração não executada |
| IA (`AI_CLIENT` + modelo) | `ollama` configurado; resposta válida simulada, cancelamento ocorre na exportação |
| Interface | API / cancelamento |

## Resumo

Cancelamento durante exportação permite publicação do resultado. Cancelamento parece funcionar, mas não interrompe efeitos posteriores.

## Entrada usada (qual arquivo/imagem)

- **Entrada:** Job cancelado durante exportação TXT.
- **Observação:** cenário reproduzido com dados sintéticos; não depende de dados de usuários.

## Passos para reproduzir

1. Usar `release/0.1.0` no commit indicado em Ambiente, com as dependências instaladas.
2. Cancelar durante `export_txt` e permitir que os demais exporters terminem.

## Resultado esperado

Respeitar o cancelamento antes de disponibilizar resultado ou enviar notificações.

## Resultado obtido

Tarefa `cancelled` com ZIP e token criados; o fluxo chega ao log de conclusão.

```json
{
  "id": "BUG-0003",
  "status": "cancelled",
  "token_created": true,
  "zip_exists": true
}
```

## Causa raiz (se identificada)

[worker.py](../../backend/api/worker.py) verifica cancelamento somente depois de `process`, antes das exportações. Não há nova verificação antes do ZIP, token ou e-mail. `registrar_download_url` permite adicionar URL até em tarefa cancelada.

## Correção sugerida (se houver)

Verificar cancelamento entre etapas e antes de emitir token/notificação, com política explícita de descarte dos arquivos parciais.

## Rastreabilidade

- **Revalidação:** permanece em `release/0.1.0` @ `7a5e70f4809dd4bae29cfb772042d12784fc48b6`, verificado em 2026-09-06.

- **Introdução rastreada:** `a728607` (2026-07-31), primeiro worker da API com uma única verificação de cancelamento antes de toda a sequência de exportação.
- A reprodução cancela durante o TXT e observa a publicação posterior do token e da URL de download.

## Evidências

- Worker real, cancelamento injetado durante a exportação TXT, com verificação do token e do ZIP produzidos.
- Verificação executada em 2026-09-06 sobre o commit da release indicado em Ambiente, com assertions dos resultados.
- Dados desta execução registrados no bloco JSON acima.
