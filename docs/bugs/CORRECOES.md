# Correções dos bugs

Este arquivo resume, de forma curta, como cada bug foi corrigido nesta branch.

## BUG-0001: sucesso antes dos artefatos e histórico divergente

O `process()` marcava a tarefa como `done` antes de o worker gerar os arquivos finais, ZIP, token e link de download. Isso fazia o histórico registrar sucesso mesmo quando uma exportação falhava depois.

A correção deixou a conclusão da tarefa da API sob responsabilidade do worker. Quando `process()` recebe um `task_id` externo, ele monta o documento canônico e atualiza o cache, mas não grava `done` no estado nem no histórico. O worker só grava `done` depois que os artefatos e o token ficam prontos. Se uma exportação falhar, o worker grava `error` também no histórico.

## BUG-0002: job cancelado na fila é executado

O cancelamento de uma tarefa ainda na fila só mudava o status em `queued_jobs`. O item continuava dentro da fila real e o worker executava o callback mesmo depois do cancelamento.

A correção adicionou cancelamento direto na fila. Quando uma tarefa enfileirada é cancelada, o item pendente é removido da `UnifiedQueue` e o status `cancelled` continua disponível para consulta.

## BUG-0003: cancelamento durante exportação permite publicação do resultado

O worker verificava cancelamento depois do `process()`, mas não verificava de novo entre as exportações. Com isso, uma tarefa cancelada durante a geração dos arquivos ainda podia criar ZIP, token e link.

A correção adicionou checagens de cancelamento entre as etapas finais do worker. Se a tarefa for cancelada durante uma exportação, o fluxo para antes de gerar os próximos artefatos, o ZIP, o token e a URL pública.

## Testes criados

- `tests/test_api.py::test_job_executor_marks_history_error_when_export_fails`: simula sucesso no `process()` e falha na exportação TXT. Confirma que o estado público e o histórico terminam como `error`.
- `tests/test_queue_service.py::test_cancelled_queued_item_is_not_processed`: enfileira uma tarefa, cancela antes do worker executar e confirma que o callback não roda.
- `tests/test_api.py::test_job_executor_stops_exports_after_cancellation`: cancela a tarefa durante a exportação TXT e confirma que o worker não cria ZIP nem token.
