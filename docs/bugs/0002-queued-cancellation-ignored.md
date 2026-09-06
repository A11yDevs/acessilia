# 🐛 Job cancelado na fila é executado

## Identificação

| Campo | Valor |
|---|---|
| **ID** | BUG-0002 |
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
| Motor (`PIPELINE_ENGINE`) | Não executado; falha no cancelamento da fila, antes do motor |
| Estruturador (`STRUCTURER`) | Não utilizado; o callback da fila é suficiente para reproduzir |
| IA (`AI_CLIENT` + modelo) | Não utilizada; não é necessário consumir um modelo para verificar o cancelamento |
| Interface | API / fila |

## Resumo

Job cancelado na fila é executado. Consumo de IA e produção de arquivos após cancelamento explícito.

## Entrada usada (qual arquivo/imagem)

- **Entrada:** Item na fila cancelado antes do worker.
- **Observação:** cenário reproduzido com dados sintéticos; não depende de dados de usuários.

## Passos para reproduzir

1. Usar `release/0.1.0` no commit indicado em Ambiente, com as dependências instaladas.
2. Enfileirar, cancelar antes da retirada da fila e iniciar o worker.

## Resultado esperado

Callback de processamento não executado e estado `cancelled` preservado.

## Resultado obtido

Callback executado e estado substituído por `processing`.

```json
{
  "id": "BUG-0002",
  "cancelled_queue_callback_executed": true,
  "status": "processing"
}
```

## Causa raiz (se identificada)

[worker.py](../../backend/api/worker.py), `cancel_job_status`, altera somente o dicionário da fila. [queue_service.py](../../backend/services/queue_service.py), `_worker`, não verifica esse estado e executa o callback. `process` cria um novo estado `processing` e um novo evento de cancelamento.

## Correção sugerida (se houver)

Remover o item ou consultar uma fonte única de cancelamento antes de iniciar; não recriar tarefa apagando o cancelamento.

## Rastreabilidade

- **Revalidação:** permanece em `release/0.1.0` @ `7a5e70f4809dd4bae29cfb772042d12784fc48b6`, verificado em 2026-09-06.

- **Introdução rastreada:** `a728607` (2026-07-31), criação da API standalone e do registro `queued_jobs` sem remoção ou consulta equivalente na fila real.
- A reprodução demonstra que o callback de um job cancelado ainda na fila é executado.

## Evidências

- Fila real: cancelamento antes de iniciar o consumidor, seguido da observação do callback e do estado recriado.
- Verificação executada em 2026-09-06 sobre o commit da release indicado em Ambiente, com assertions dos resultados.
- Dados desta execução registrados no bloco JSON acima.
