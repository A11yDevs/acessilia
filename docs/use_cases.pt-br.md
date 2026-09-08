# Casos de Uso

Também disponível em **inglês (EUA)**: [English version](use_cases.md)

## Atores
1. Usuário final, via a API REST diretamente ou por meio do bot de Telegram ou do painel web (ambos clientes da API). Os comandos específicos do Telegram abaixo (status, cancel, pause, feedback) se aplicam à interface do bot.
2. Operador/Arquiteto (configuração do ambiente e diagnósticos).
3. Serviço de IA (OpenRouter ou Ollama), usado sob condição.
4. Sistema de arquivos local e banco de dados SQLite.

## Casos de uso principais

## UC-01 Submeter documento e receber saídas acessíveis
- Ator principal: Usuário final.
- Objetivo: converter PDF/imagem/documento em saídas acessíveis.
- Entrada: arquivo suportado.
- Saída: TXT, DOCX, PDF, PDF/UA, HTML e MP3, entregues no chat, como link de download ou por e-mail.
- Implementação:
  - entrada/validação: [frontend/telegram/handlers/document.py](../frontend/telegram/handlers/document.py), [backend/tools/validators.py](../backend/tools/validators.py)
  - processamento: [backend/service.py](../backend/service.py) seleciona o motor (`PIPELINE_ENGINE`): o orquestrador legado [backend/agents/orchestrator.py](../backend/agents/orchestrator.py) ou o orquestrador PDDL [backend/agents/pddl_orchestrator.py](../backend/agents/pddl_orchestrator.py); ambos alimentam o [backend/pipeline/canonical_builder.py](../backend/pipeline/canonical_builder.py)
  - exportação: [backend/export/pandoc_exporter.py](../backend/export/pandoc_exporter.py), [backend/export/exporters](../backend/export/exporters), [backend/export/renderers](../backend/export/renderers)

## UC-02 Selecionar nível de descrição
- Ator principal: Usuário final.
- Objetivo: escolher o nível de descrição — `detalhado`, `medio` (alias `normal`), `baixo` ou `ocr`.
- Implementação:
  - comandos: [frontend/telegram/handlers/start.py](../frontend/telegram/handlers/start.py)
  - prompts por modo: [backend/ai/prompts](../backend/ai/prompts)
  - aplicação no processamento: [backend/agents/vision_agent.py](../backend/agents/vision_agent.py)

## UC-03 Consultar status e cancelar
- Ator principal: Usuário final.
- Objetivo: monitorar o progresso e interromper a tarefa.
- Implementação:
  - comandos /status e /cancelar: [frontend/telegram/handlers/start.py](../frontend/telegram/handlers/start.py)
  - estado/cancelamento: [backend/agents/state_manager.py](../backend/agents/state_manager.py)

## UC-04 Desativar/reativar o bot por chat
- Ator principal: Usuário final.
- Objetivo: pausar o serviço em um chat sem derrubar o processo.
- Implementação:
  - comandos /desativar e /ativar: [frontend/telegram/handlers/start.py](../frontend/telegram/handlers/start.py)
  - controle: [frontend/telegram/middlewares/pause_middleware.py](../frontend/telegram/middlewares/pause_middleware.py)

## UC-05 Verificação operacional de saúde
- Ator principal: Operador.
- Objetivo: verificar a disponibilidade do backend de IA e dos recursos locais.
- Implementação:
  - comando /health: [frontend/telegram/handlers/start.py](../frontend/telegram/handlers/start.py)
  - cliente do backend de IA: [backend/ai/models/ai_client.py](../backend/ai/models/ai_client.py)

## UC-06 Submeter feedback
- Ator principal: Usuário final.
- Objetivo: enviar feedback sobre a qualidade da conversão.
- Implementação:
  - FSM e comando /feedback: [frontend/telegram/handlers/start.py](../frontend/telegram/handlers/start.py)
  - persistência local simplificada: feedback.txt em temp_dir

## UC-07 Persistir histórico de conversões
- Ator principal: Sistema.
- Objetivo: armazenar o rastro de auditoria das conversões e do OCR.
- Implementação:
  - ciclo de vida do histórico: [backend/services/history_service.py](../backend/services/history_service.py)
  - chamadas no fluxo: [backend/service.py](../backend/service.py)

## UC-08 Reutilizar cache para desempenho
- Ator principal: Sistema.
- Objetivo: evitar o processamento repetido de arquivos/páginas.
- Implementação:
  - serviço de cache: [backend/services/cache.py](../backend/services/cache.py)
  - uso no fluxo: [backend/service.py](../backend/service.py) e [backend/agents/orchestrator.py](../backend/agents/orchestrator.py)

## UC-09 Operação segura de instância única
- Ator principal: Operador.
- Objetivo: impedir execução local concorrente não intencional.
- Implementação: [frontend/run.py](../frontend/run.py)

## Resumo do fluxo principal
1. O usuário envia o arquivo.
2. O sistema o valida e faz o download.
3. O sistema cria a tarefa e registra o histórico.
4. O sistema processa página por página com estratégia híbrida:
   - extrai o texto localmente de páginas de PDF baseadas em texto,
   - usa a visão de IA apenas para páginas digitalizadas/sem texto ou arquivos de imagem diretos.
5. O sistema consolida as páginas no documento canônico, o valida, renderiza os formatos e envia os resultados.
6. O sistema finaliza o histórico e o estado da tarefa.

## Fluxos alternativos
1. Extensão inválida ou arquivo grande demais
   - resposta de erro amigável imediata (validadores + handler).
2. Falha no backend de IA
   - fallback de extração simples no [backend/service.py](../backend/service.py), com a exportação canônica ainda disponível.
3. Página de PDF baseada em texto
   - a página é extraída localmente e não requer chamada de IA para o texto principal.
4. Limite de taxa do backend de Telegram/IA (Ollama ou OpenRouter)
   - novas tentativas com espera incremental.
5. Cancelamento da tarefa
   - estado marcado como cancelado e processamento interrompido.

## Requisitos não funcionais cobertos
1. Confiabilidade: novas tentativas, fallback e logs.
2. Desempenho: cache de arquivo/página e compressão de imagem.
3. Operaibilidade: verificações de saúde, trava de processo e limpeza periódica.
4. Facilidade de manutenção: organização dos pacotes, pipeline canônico e separação de responsabilidades.

## Diagrama UML
- [Casos de uso PlantUML](use_cases/use_cases.puml)
