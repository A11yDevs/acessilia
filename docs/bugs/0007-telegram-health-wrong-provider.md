# 🐛 Health do Telegram ignora o provedor configurado

## Identificação

| Campo | Valor |
|---|---|
| **ID** | BUG-0007 |
| **Data** | 2026-09-05 |
| **Reportado por** | Wryel Teodoro |
| **Severidade** | 🟡 Média |
| **Status** | Corrigido localmente · aguardando integração |

## Ambiente

| Item | Valor |
|---|---|
| SO | Linux |
| Python | 3.12.3 (revalidação isolada) |
| Branch / commit | [release/0.1.0](https://github.com/A11yDevs/acessilia/tree/release/0.1.0) @ `7a5e70f4809dd4bae29cfb772042d12784fc48b6` |
| Motor (`PIPELINE_ENGINE`) | Não executado; o comando `/health` consulta o provedor diretamente |
| Estruturador (`STRUCTURER`) | Não utilizado pelo comando `/health` |
| IA (`AI_CLIENT` + modelo) | `AI_CLIENT=openrouter`; o handler consulta Ollama e exibe `ollama_model`. HTTP simulado; nenhuma inferência executada |
| Interface | Telegram /health |

## Resumo

Health do Telegram ignora o provedor configurado. Diagnóstico incorreto de indisponibilidade ou prontidão.

## Entrada usada (qual arquivo/imagem)

- **Entrada:** AI_CLIENT=openrouter; HTTP Ollama interceptado.
- **Observação:** cenário reproduzido com dados sintéticos; não depende de dados de usuários.

## Passos para reproduzir

1. Usar `release/0.1.0` no commit indicado em Ambiente, com as dependências instaladas.
2. Configurar OpenRouter e executar `cmd_health`.

## Resultado esperado

Refletir o provedor/modelo ativo do backend.

## Resultado obtido

Requisição a `/api/tags` do Ollama e mensagem sobre Ollama.

```json
{
  "id": "BUG-0007",
  "configured_provider": "openrouter",
  "checked_provider": "ollama"
}
```

## Causa raiz (se identificada)

[frontend/telegram/handlers/start.py](../../frontend/telegram/handlers/start.py), linhas 182–199, usa sempre `ollama_base_url` e `ollama_model`.

## Correção sugerida (se houver)

Consumir `ApiClient.health()` e apresentar os campos retornados pela API.

## Correção aplicada

O comando `/health` agora consome o endpoint canônico da API e apresenta
`model_client`, `model_name` e `model_reachable`, sem consultar o Ollama
diretamente. A regressão foi coberta para OpenRouter e para erro da API.

## Rastreabilidade

- **Revalidação:** permanece em `release/0.1.0` @ `7a5e70f4809dd4bae29cfb772042d12784fc48b6`, verificado em 2026-09-06.

- **Introdução rastreada:** `c2c4db8` (2026-06-02), quando OpenRouter virou provedor selecionável, mas `/health` continuou consultando e exibindo somente Ollama.
- A reprodução observa que o Telegram não consulta o health canônico da API.

## Evidências

- Handler de health com OpenRouter configurado e transporte HTTP interceptado: a consulta efetuada é ao Ollama.
- Verificação executada em 2026-09-06 sobre o commit da release indicado em Ambiente, com assertions dos resultados.
- Dados desta execução registrados no bloco JSON acima.
