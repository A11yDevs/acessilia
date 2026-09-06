# 🐛 Sucesso antes dos artefatos e histórico divergente

## Identificação

| Campo | Valor |
|---|---|
| **ID** | BUG-0001 |
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
| Motor (`PIPELINE_ENGINE`) | `legacy` configurado; retorno do orquestrador simulado no serviço real |
| Estruturador (`STRUCTURER`) | `pymupdf` configurado; extração não executada |
| IA (`AI_CLIENT` + modelo) | `ollama` configurado; resposta válida simulada, sem chamada a modelo |
| Interface | API / histórico / polling |

## Resumo

Sucesso antes dos artefatos e histórico divergente. Polling pode encerrar antes de existir link; estatísticas contam conversão não entregue como sucesso.

## Entrada usada (qual arquivo/imagem)

- **Entrada:** Job sintético com falha na exportação TXT.
- **Observação:** cenário reproduzido com dados sintéticos; não depende de dados de usuários.

## Passos para reproduzir

1. Usar `release/0.1.0` no commit indicado em Ambiente, com as dependências instaladas.
2. Observar o estado durante `set_cache`; em seguida, simular erro de disco na exportação TXT.

## Resultado esperado

`processing` até completar os artefatos obrigatórios, e histórico consistente com o resultado final.

## Resultado obtido

`done` é observável antes de qualquer exportação; estado final `error`, mas histórico permanece `done`.

```json
{
  "id": "BUG-0001",
  "during_cache": [
    "done"
  ],
  "final_job": "error",
  "history": "done"
}
```

## Causa raiz (se identificada)

A prova usa falha de disco simulada e também observa o estado antes da exportação. A inconsistência existe com resposta válida e não depende de uma falha já registrada na referência.

[service.py](../../backend/service.py), linhas 186–202, chama `state_manager.finalizar` antes de `await set_cache` e registra histórico `done` antes de devolver ao worker. A reversão para `processing` em [worker.py](../../backend/api/worker.py), linhas 119–123, só acontece depois que `process` retorna. Erros de exportação não atualizam o histórico.

## Correção sugerida (se houver)

Deixar o worker controlar a conclusão da conversão API e atualizar o histórico na mesma transição terminal.

## Rastreabilidade

- **Revalidação:** permanece em `release/0.1.0` @ `7a5e70f4809dd4bae29cfb772042d12784fc48b6`, verificado em 2026-09-06.

- **Introdução rastreada:** `c511727` (2026-05-15) introduziu o histórico concluído antes das exportações; o estado prematuro já existia desde `ad1efa9`, e `a728607` (2026-07-31) tornou a janela observável pela API.
- A reprodução observa que o status deixa de ser `processing` antes da entrega ao estágio de artefatos.

## Evidências

- Worker e serviço reais, com resposta válida simulada e erro de disco injetado na exportação TXT; histórico consultado após a falha.
- Verificação executada em 2026-09-06 sobre o commit da release indicado em Ambiente, com assertions dos resultados.
- Dados desta execução registrados no bloco JSON acima.
