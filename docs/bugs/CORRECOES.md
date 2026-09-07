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

## BUG-0004: nome do ZIP incompatível com a descoberta dos downloads

O worker salvava o pacote como `{nome}_acessivel.zip`, mas a consulta do token procurava `{nome}.zip`. O ZIP existia em disco, mas não aparecia como formato disponível.

A correção ensinou o serviço de download a procurar o sufixo real do pacote: `_acessivel.zip`. O worker continua produzindo o mesmo nome de arquivo.

## BUG-0005: segundo `stem` quebra arquivos com pontos no nome

O worker já salvava no token a base do arquivo, mas a consulta aplicava `Path(...).stem` de novo. Um nome como `relatorio.v2` virava `relatorio`, e os arquivos reais deixavam de ser encontrados.

A correção usa a base salva no token exatamente como ela está. Assim nomes com pontos continuam apontando para `relatorio.v2.txt`, `relatorio.v2_acessivel.zip` e os outros formatos.

## BUG-0006: falso aviso de e-mail enviado e ausência de alternativa

O serviço de e-mail falhava sem devolver esse resultado para quem chamou. No Telegram, quando havia e-mail configurado, a mensagem dizia que o link tinha sido enviado por e-mail e não mostrava o próprio link no chat.

A correção fez o serviço de e-mail retornar `True` ou `False`. O worker registra aviso quando o envio do resultado falha. No Telegram, o link de download sempre aparece quando a tarefa termina, mesmo se houver e-mail configurado.

## BUG-0007: health do Telegram ignora o provedor configurado

O comando `/health` do Telegram consultava o Ollama diretamente. Em ambientes usando outro provedor, como OpenRouter, o diagnóstico podia mostrar o serviço errado.

Este bug já veio corrigido no commit do Wryel. O comando `/health` usa `ApiClient.health()` e mostra os campos retornados pela API: provedor, modelo e disponibilidade.

## BUG-0008: DOCX e HTML não funcionam no caminho legacy anunciado

O validador aceitava DOCX e HTML mesmo quando o motor ativo era `legacy`. Esse motor tratava qualquer não-PDF como imagem, então esses arquivos quebravam depois, na leitura.

A correção bloqueia DOCX e HTML já na validação quando `PIPELINE_ENGINE=legacy`. Em motores fora do legacy, os formatos continuam permitidos.

## BUG-0009: thinking mode é uma opção sem efeito no legacy

O `thinking_mode` era aceito pela interface, mas o prompt com `<|think|>` não era repassado para as chamadas dos agentes no motor legacy.

Este bug já veio corrigido no commit do Wryel. Quando `thinking_mode` está ativo, o prompt despachado para os agentes recebe o marcador `<|think|>`.

## BUG-0010: células vazias eliminadas corrompem alinhamento de tabelas

O pipeline removia células vazias ao montar e ler o `table_ast`. Em tabelas com célula vazia no meio da linha, os valores seguintes mudavam de coluna.

A correção preserva células vazias estruturais no `table_ast`, na conversão de volta para linhas e no renderer HTML. Linhas totalmente vazias continuam sendo descartadas.

## Testes criados

- `tests/test_api.py::test_job_executor_marks_history_error_when_export_fails`: simula sucesso no `process()` e falha na exportação TXT. Confirma que o estado público e o histórico terminam como `error`.
- `tests/test_queue_service.py::test_cancelled_queued_item_is_not_processed`: enfileira uma tarefa, cancela antes do worker executar e confirma que o callback não roda.
- `tests/test_api.py::test_job_executor_stops_exports_after_cancellation`: cancela a tarefa durante a exportação TXT e confirma que o worker não cria ZIP nem token.
- `tests/test_api.py::test_download_full_flow`: passou a criar `doc_acessivel.zip` e confirma que o formato `zip` aparece na consulta do token.
- `tests/test_api.py::test_download_info_keeps_dotted_base_name`: cria artefatos com base `relatorio.v2` e confirma que a consulta encontra os formatos sem cortar o nome.
- `tests/test_email_service.py::test_result_email_reports_missing_smtp`: confirma que envio de resultado sem SMTP configurado retorna `False`.
- `tests/test_telegram_client.py::test_document_passes_email_and_notifies`: passou a confirmar que o Telegram mostra o link mesmo quando existe e-mail configurado.
- `tests/test_telegram_client.py::test_health_uses_provider_reported_by_api`: confirma que `/health` usa o provedor retornado pela API e não menciona Ollama quando a API informa OpenRouter.
- `tests/test_telegram_client.py::test_health_reports_api_error`: confirma que `/health` mostra erro da API quando a consulta falha.
- `tests/test_validators.py::test_validate_file_rejects_docx_and_html_in_legacy`: confirma que DOCX e HTML são recusados no motor legacy.
- `tests/test_validators.py::test_validate_file_allows_docx_and_html_outside_legacy`: confirma que DOCX e HTML continuam aceitos quando o motor não é legacy.
- `tests/test_orchestrator_thinking_mode.py::test_thinking_mode_changes_dispatched_prompt`: confirma que `thinking_mode` altera o prompt enviado aos agentes no legacy.
- `tests/test_table_ast.py::test_table_ast_preserves_empty_structural_cells`: confirma que uma célula vazia no meio da tabela é preservada no AST e na volta para linhas.
- `tests/test_renderers.py::test_render_html_includes_toc_table_and_metadata`: passou a confirmar que o HTML renderiza `<td></td>` para células vazias.
