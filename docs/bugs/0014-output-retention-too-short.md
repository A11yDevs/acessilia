# 🐛 Retenção real é de 24 horas, promessa é de sete dias

## Identificação

| Campo | Valor |
|---|---|
| **ID** | BUG-0014 |
| **Data** | 2026-09-06 |
| **Reportado por** | Wryel Teodoro |
| **Severidade** | 🟠 Alta |
| **Status** | Aberto · reproduzido em ambiente isolado |

## Ambiente

| Item | Valor |
|---|---|
| SO | Linux |
| Python | 3.12.3 |
| Branch / commit | [release/0.1.0](https://github.com/A11yDevs/acessilia/tree/release/0.1.0) @ `7a5e70f4809dd4bae29cfb772042d12784fc48b6` |
| Motor (`PIPELINE_ENGINE`) | Não executado; limpeza de arquivos de saída |
| Estruturador (`STRUCTURER`) | Não utilizado; arquivos de saída criados diretamente para verificar retenção |
| IA (`AI_CLIENT` + modelo) | Não utilizada; a remoção depende da idade dos arquivos |
| Interface | API / links de download |

## Resumo

A limpeza periódica remove resultados ainda dentro dos sete dias de validade anunciados ao usuário.

## Entrada usada (qual arquivo/imagem)

- **Entrada:** Diretório temporário com TXT e token reais; `mtime` dos arquivos e do diretório ajustado para 25 horas atrás.
- **Observação:** reprodução isolada com dados sintéticos, sem acesso a dados de usuários ou serviços externos reais.

## Passos para reproduzir

1. Criar um diretório de saída com arquivo e registrar um token por `criar_token`.
2. Ajustar o `mtime` do diretório e de todos os arquivos para 25 horas atrás.
3. Executar `_clean_output_directory` e consultar novamente o token.

## Resultado esperado

Manter os artefatos enquanto o link anunciado por sete dias continuar válido.

## Resultado obtido

O diretório é apagado e `obter_info_token` deixa de retornar informações, apesar do token recém-criado.

```json
{
  "id": "BUG-0014",
  "age_hours": 25,
  "output_exists": false,
  "promised_days": 7
}
```

## Causa raiz (se identificada)

[cleanup_service.py](../../backend/services/cleanup_service.py), linhas 64–75, usa `FILE_MAX_AGE * 12`, ou 86.400 segundos. [email_service.py](../../backend/services/email_service.py) e [document.py](../../frontend/telegram/handlers/document.py) anunciam sete dias. A decisão de limpeza considera o `mtime`, não a validade do token.

## Correção sugerida (se houver)

Vincular a retenção à validade dos tokens e preservar diretórios referenciados por links válidos.

## Rastreabilidade

- **Revalidação:** permanece em `release/0.1.0` @ `7a5e70f4809dd4bae29cfb772042d12784fc48b6`, verificado em 2026-09-06.

- **Origem rastreada:** A remoção de `data_dir/output` com limite de 24 horas foi introduzida em `81c95f8` (2026-08-31), conforme `git blame` de `_clean_output_directory`.
- **Auditoria anterior:** `AUD-09`; restaurado com o ID `BUG-0014` na sequência dos registros atuais.

## Evidências

- SQLite e limpeza reais em diretório temporário: saída envelhecida para 25 horas é removida apesar da promessa de sete dias.
- Verificação executada em 2026-09-06 sobre o commit da release indicado em Ambiente, com assertions dos resultados.
- Dados desta execução registrados no bloco JSON acima.
