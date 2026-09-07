# Correções dos bugs

Este arquivo resume, de forma curta, como cada bug foi corrigido nesta branch.

## BUG-0001: sucesso antes dos artefatos e histórico divergente

O `process()` marcava a tarefa como `done` antes de o worker gerar os arquivos finais, ZIP, token e link de download. Isso fazia o histórico registrar sucesso mesmo quando uma exportação falhava depois.

A correção deixou a conclusão da tarefa da API sob responsabilidade do worker. Quando `process()` recebe um `task_id` externo, ele monta o documento canônico e atualiza o cache, mas não grava `done` no estado nem no histórico. O worker só grava `done` depois que os artefatos e o token ficam prontos. Se uma exportação falhar, o worker grava `error` também no histórico.

## Testes criados

- `tests/test_api.py::test_job_executor_marks_history_error_when_export_fails`: simula sucesso no `process()` e falha na exportação TXT. Confirma que o estado público e o histórico terminam como `error`.
