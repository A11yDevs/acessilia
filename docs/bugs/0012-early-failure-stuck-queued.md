# 🐛 Falha inicial deixa tarefa eternamente na fila

## Identificação

| Campo | Valor |
|---|---|
| **ID** | BUG-0012 |
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
| Motor (`PIPELINE_ENGINE`) | `legacy` configurado; falha de acesso ao cache antes de executar o motor |
| Estruturador (`STRUCTURER`) | `pymupdf` configurado; falha ocorre antes da extração |
| IA (`AI_CLIENT` + modelo) | Não utilizada; o acesso inicial ao cache falha antes de chamar qualquer modelo |
| Interface | API / fila |

## Resumo

Uma falha técnica antes da criação do estado deixa o job como `queued`, embora o worker já tenha terminado e apagado o upload.

## Entrada usada (qual arquivo/imagem)

- **Entrada:** Upload sintético e `PermissionError` no acesso inicial ao cache; nenhum modelo de IA é chamado.
- **Observação:** reprodução isolada com dados sintéticos, sem acesso a dados de usuários ou serviços externos reais.

## Passos para reproduzir

1. Registrar o upload na fila com `register_queued_job`.
2. Fazer `backend.service.get_cached` levantar `PermissionError("cache inacessivel")` e executar `JobExecutor.run`.
3. Consultar `get_job_status` depois que o worker retornar e verificar a existência do upload.

## Resultado esperado

Estado terminal `error` com a causa consultável.

## Resultado obtido

O job continua `queued`, e o arquivo de entrada já foi removido.

```json
{
  "id": "BUG-0012",
  "after_exception": "queued",
  "input_exists": false
}
```

## Causa raiz (se identificada)

[service.py](../../backend/service.py), linhas 102–117, acessa o cache antes de criar a tarefa. O tratamento de exceção em [worker.py](../../backend/api/worker.py), linhas 208–218, chama `state_manager.atualizar`, que não cria estados ausentes, e apaga o upload. A entrada em `queued_jobs` permanece. O defeito é a falta de estado terminal após erro de acesso a arquivo; não depende da chave do cache nem da qualidade de IA.

## Correção sugerida (se houver)

Criar o estado antes das operações sujeitas a falha e retirar a entrada de fila quando o worker assumir a tarefa.

## Rastreabilidade

- **Revalidação:** permanece em `release/0.1.0` @ `7a5e70f4809dd4bae29cfb772042d12784fc48b6`, verificado em 2026-09-06.

- **Origem rastreada:** O caminho API que expõe o problema foi introduzido em `a728607` (2026-07-31): criação da tarefa por `process`, consulta da fila e tratamento de erro do worker. A ordem atual de acesso ao cache foi conferida por `git blame`.
- **Auditoria anterior:** `AUD-03`; restaurado com o ID `BUG-0012` na sequência dos registros atuais.

## Evidências

- Worker real com PermissionError injetado no acesso inicial ao cache; consulta do estado e existência do upload após o retorno.
- Verificação executada em 2026-09-06 sobre o commit da release indicado em Ambiente, com assertions dos resultados.
- Dados desta execução registrados no bloco JSON acima.
