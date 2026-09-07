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

## BUG-0011: falha de áudio fica invisível no resultado público

Quando a geração de MP3 falhava, o erro ficava só no log. O job terminava como `done`, sem avisar que o áudio não foi gerado, e o ZIP era montado apenas com os arquivos existentes.

A correção registra a falha do MP3 na lista pública de erros da tarefa. O job ainda pode terminar como `done` quando os outros artefatos foram entregues, mas a ausência do áudio fica visível.

## BUG-0012: falha inicial deixa tarefa eternamente na fila

Uma falha logo no início do `process()` podia acontecer antes da criação do estado da tarefa. O worker tentava marcar erro, mas não havia estado para atualizar, então a consulta continuava mostrando o job como `queued`.

A correção faz o worker remover o item de `queued_jobs` e criar o estado da tarefa antes de chamar `process()`. Se qualquer erro inicial acontecer, existe estado para gravar `error`.

## BUG-0013: página web gera links para a porta errada

A página web montava links como `/api/v1/download/...`, mas o app web não atendia essa rota. Em execução com API e web em portas separadas, o clique ia para a porta da web e retornava 404.

A correção adicionou um proxy de download no app web para `/api/v1/download/{token}/{format}`. A página pode continuar usando links relativos, e o frontend busca o arquivo na API por meio do `ApiClient`. O proxy preserva o nome do arquivo e remove a cópia temporária depois do envio ou de uma falha.

## BUG-0014: resultados eram apagados antes do prazo informado

Os links prometem sete dias de validade, mas a limpeza apagava os arquivos de resultado depois de apenas 24 horas.

A correção faz a limpeza usar os mesmos sete dias definidos para a validade dos tokens de download.

## BUG-0015: tokens expirados ainda eram aceitos

A consulta verificava apenas se o token existia e se a pasta do resultado continuava no disco. Por isso, um token com mais de sete dias ainda podia ser usado antes da próxima limpeza.

A correção inclui a validade de sete dias na consulta do token e executa a remoção dos registros expirados durante a limpeza periódica.

## BUG-0016: upload grande era gravado antes da validação

O painel web gravava o arquivo inteiro antes que a API verificasse o limite de tamanho. Isso permitia que um upload grande demais ocupasse espaço no disco do frontend.

A correção grava o upload em blocos e interrompe a cópia assim que o limite configurado é ultrapassado. O arquivo parcial é removido e o painel retorna o erro 413.

## BUG-0017: Compose local construía o estágio de teste

O `docker-compose.yml` usava o `infra/Dockerfile` sem definir o alvo do build. Como o último estágio do Dockerfile é `test`, o Compose local podia subir uma imagem cujo comando padrão roda `pytest` em vez do servidor.

A correção define `target: base` no build local, que é o estágio de runtime usado pela aplicação e pelos workflows de entrega.

## BUG-0018: staging ignorava branch do `.env`

O script de staging só carregava o `.env` quando `GHCR_TOKEN` não estava exportado. Se o token já viesse do ambiente, `TRACK_BRANCH` definido no arquivo era ignorado e o script voltava para `develop`.

A correção carrega o `.env` independentemente do token. Variáveis já exportadas no ambiente continuam tendo prioridade sobre o arquivo.

## BUG-0019: fallback de staging não rodava em falha HTTP

O script prometia fazer `docker pull` direto quando não conseguisse consultar o SHA no GitHub, mas uma falha do `curl` encerrava o script antes desse fallback.

A correção captura a falha da consulta ao GitHub e deixa `LATEST_SHA` vazio. Com isso, o fluxo já existente de fallback é executado.

## BUG-0020: publicação não aguardava o CI

O workflow de Delivery rodava direto em `push`, independente do resultado da suíte completa do CI para o mesmo commit.

A correção faz o Delivery disparar pela conclusão do workflow CI. A publicação só roda quando o CI terminou com sucesso em um evento de `push`, usando o `head_sha` e a branch testados pelo CI.

## BUG-0021: Delivery agrupava execuções pela referência errada

Depois que o Delivery passou a rodar por `workflow_run`, a configuração de concorrência ainda usava `github.ref_name`. Nesse evento, esse valor não representa a branch testada pelo CI.

A correção usa `github.event.workflow_run.head_branch` também na concorrência. Assim o cancelamento e o agrupamento do Delivery seguem a branch real que passou no CI.

## BUG-0022: histórico usava caminho de banco congelado

O serviço de histórico salvava `settings.db_path` em uma variável global durante o import. Quando `settings.data_dir` era alterado depois disso, como acontece nos testes e pode acontecer em inicializações controladas, o serviço continuava usando o banco antigo.

A correção faz `get_connection()` consultar `settings.db_path` na hora de abrir a conexão. Isso mantém o histórico alinhado com a configuração atual.

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
- `tests/test_api.py::test_job_executor_reports_mp3_failure`: simula falha no TTS e confirma que o job registra erro público e não inclui MP3 no ZIP.
- `tests/test_api.py::test_job_executor_records_early_process_failure`: simula falha antes de `process()` criar estado e confirma que o job termina como `error`, sem ficar em `queued`.
- `tests/test_web_panel.py::test_download_proxy_delegates_to_api`: chama o link `/api/v1/download/{token}/{format}` no app web e confirma que ele baixa o arquivo via API.
- `tests/test_web_panel.py::test_download_proxy_removes_partial_file_after_api_failure`: simula uma falha durante o download e confirma que o arquivo parcial é removido.
- `tests/test_cleanup_service.py::test_output_cleanup_keeps_results_younger_than_seven_days`: confirma que um resultado com 25 horas não é apagado.
- `tests/test_cleanup_service.py::test_output_cleanup_removes_results_older_than_seven_days`: confirma que um resultado com mais de sete dias é apagado.
- `tests/test_download_token_service.py::test_expired_download_token_is_rejected`: confirma que um token com oito dias é rejeitado mesmo quando os arquivos ainda existem.
- `tests/test_download_token_service.py::test_recent_download_token_remains_valid`: confirma que um token recente continua disponível.
- `tests/test_web_panel.py::test_upload_rejects_oversized_file_before_api_submission`: confirma que um upload acima do limite é rejeitado, não chega à API e não deixa arquivo parcial.
- `tests/test_cleanup_service.py::test_periodic_cleanup_removes_expired_tokens`: confirma que a limpeza periódica também remove os registros de tokens vencidos.
- `tests/test_compose_config.py::test_local_compose_builds_runtime_stage`: confirma que o Compose local constrói o estágio `base` do Dockerfile.
- `tests/test_staging_update.py::test_staging_update_reads_track_branch_from_dotenv_with_env_token`: confirma que o staging lê `TRACK_BRANCH` do `.env` mesmo com `GHCR_TOKEN` já exportado.
- `tests/test_staging_update.py::test_staging_update_env_track_branch_overrides_dotenv`: confirma que `TRACK_BRANCH` exportado no ambiente tem prioridade sobre o valor do `.env`.
- `tests/test_staging_update.py::test_staging_update_falls_back_when_github_request_fails`: confirma que falha no `curl` aciona o `docker pull` e o `docker compose up` de fallback.
- `tests/test_compose_config.py::test_delivery_runs_only_after_successful_push_ci`: confirma que o Delivery depende do CI aprovado e usa o SHA/branch testados.
- `tests/test_compose_config.py::test_delivery_runs_only_after_successful_push_ci`: também confirma que o Delivery não volta a usar `github.ref_name` no evento `workflow_run`.
