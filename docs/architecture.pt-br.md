# Arquitetura

Também disponível em **inglês (EUA)**: [English version](architecture.md)

## Visão geral
O sistema converte documentos em formatos acessíveis por meio de um pipeline de extração multiagente (extração estrutural local-first com PyMuPDF/Docling, mais agentes de visão e de dados de IA multimodal conduzidos por Agno), um pipeline de documento canônico, validação determinística e renderizadores específicos de formato. A arquitetura é modular: **backend/** guarda a lógica de domínio e a API REST que a expõe, **frontend/** guarda os clientes de interface (Telegram, Web, CLI) que conversam com essa API, e **infra/** guarda o Dockerfile (o arquivo Compose fica na raiz do repositório).

O sistema combina **planejamento determinístico com execução guiada por IA**: as funções determinísticas (extração, geração do problema PDDL, validação de contrato) são a fonte da verdade, e os LLMs fornecem interpretação e descrição. Dois motores de pipeline coexistem, selecionados pela configuração `PIPELINE_ENGINE`:

- **`legacy`** (motor workflow Agno): o pipeline orquestrado direto — `AccessibilityWorkflow` executa Reader → Vision/Data → Editor.
- **`pddl`**: o pipeline baseado em planejamento — um manifesto de processamento é extraído, um plano PDDL é gerado e validado, e um executor Agno Workflow o aplica. Veja [pmv_agno_pddl.md](pmv_agno_pddl.md).

Ambos os motores convergem para o mesmo documento canônico e os mesmos renderizadores.

---

## Camadas

### 0. Backend (`backend/`) — lógica de negócio agnóstica de interface e pipeline de IA

#### 0.1. Pipeline Multiagente e Orquestração (`backend/agents/`)
- [backend/agents/workflow.py](../backend/agents/workflow.py): `AccessibilityWorkflow` coordena o pipeline de execução Agno Workflow multiagente, a consulta de cache, o estado das tarefas, o histórico e os callbacks de status.
- [backend/agents/reader_agent.py](../backend/agents/reader_agent.py): `ReaderAgent` realiza o parsing estrutural local-first de PDF/imagens (via PyMuPDF ou Docling), divide as páginas e classifica as regiões de conteúdo (imagem, tabela, fórmula, texto).
- [backend/agents/vision_agent.py](../backend/agents/vision_agent.py): `VisionAgent` utiliza o Agno (`agno.agent.Agent`) e as capacidades multimodais do LLM (`agno.media.Image`) para produzir alt-text detalhado e descrições em áudio para elementos visuais e páginas escaneadas.
- [backend/agents/data_agent.py](../backend/agents/data_agent.py): `DataAgent` utiliza o Agno (`agno.agent.Agent`) e as capacidades do LLM para converter tabelas complexas e fórmulas matemáticas em representações Markdown e LaTeX estruturadas.
- [backend/agents/editor_agent.py](../backend/agents/editor_agent.py): `EditorAgent` higieniza o conteúdo e remove duplicatas de trechos repetidos por meio de impressões digitais de conteúdo (`content_fingerprint` em [backend/tools/text_tools.py](../backend/tools/text_tools.py), que normaliza o texto antes do hashing). A implementação atual usa `hash()` embutido do Python e deve ser trocada por um hashing estável mais tarde; o `ReaderAgent` usa as mesmas impressões digitais para descartar regiões repetidas entre páginas.
- [backend/agents/state_manager.py](../backend/agents/state_manager.py): máquina de estados em memória para tarefas com suporte a cancelamento cooperativo.
- [backend/agents/types.py](../backend/agents/types.py): contratos de dados compartilhados e tipos de tarefa (`RegionTask`).

#### 0.2. Integração do Cliente de IA (`backend/ai/`)
- [backend/ai/models/ai_client.py](../backend/ai/models/ai_client.py): inicializador central `get_agno_model()` que instancia envelopes de Model do Agno para Ollama ou OpenRouter com base nas configurações de ambiente.

#### 0.3. Serviços de Infraestrutura (`backend/services/`)
- [backend/services/cache.py](../backend/services/cache.py): cache de texto por hash de arquivo em `var/temp/cache`.
- [backend/services/history_service.py](../backend/services/history_service.py): persistência SQLite (modo WAL) para conversões e logs de auditoria, em `var/data/history.db`.
- [backend/services/queue_service.py](../backend/services/queue_service.py): fila de processamento assíncrona unificada com limites de concorrência.
- [backend/services/cleanup_service.py](../backend/services/cleanup_service.py): limpeza periódica de arquivos temporários.
- [backend/services/email_service.py](../backend/services/email_service.py): envio de e-mail SMTP assíncrono (confirmação + resultado com anexos ZIP).
- [backend/services/download_token_service.py](../backend/services/download_token_service.py): geração de token para links de download seguro na Web.

#### 0.4. Ferramentas e Utilitários de Domínio (`backend/tools/`)
- [backend/tools/logger.py](../backend/tools/logger.py): configuração centralizada do logger loguru.
- [backend/tools/validators.py](../backend/tools/validators.py): validação de extensão e tamanho de arquivo.
- [backend/tools/pdf_splitter.py](../backend/tools/pdf_splitter.py): divisor de PDF em páginas únicas.
- [backend/tools/image_converter.py](../backend/tools/image_converter.py): conversão de página de PDF em PNG.
- [backend/tools/image_enhancer.py](../backend/tools/image_enhancer.py): remoção de inclinação (deskew), contraste CLAHE e redução de ruído via OpenCV para páginas escaneadas.
- [backend/tools/text_processor.py](../backend/tools/text_processor.py): normalização de texto e parsing de Markdown.
- [backend/tools/image_tools.py](../backend/tools/image_tools.py): recorte de imagem e extração de regiões.
- [backend/tools/prompt_tools.py](../backend/tools/prompt_tools.py): carregador de prompt e resolutor de templates.

#### 0.5. Camada de Planejamento (`backend/core/`) — motor PDDL

Usado quando `PIPELINE_ENGINE=pddl`. Ele transforma a estrutura do documento em um plano explícito antes de qualquer IA rodar, de modo que a ordem e as dependências das tarefas sejam determinísticas e auditáveis.

- `backend/core/manifest/`: o agente Informacional-Estrutural extrai um `processing-manifest.json` do documento (regiões, tipos e obrigações de processamento) via extratores Docling ou PyMuPDF.
- `backend/core/planning/`: o `PlannerAgent` compila o manifesto mais um domínio PDDL em um problema, gera um `nominal-plan.json` (planejador interno ou backend Fast Downward) e o valida. A geração do problema PDDL é determinística — nenhum LLM escreve PDDL.
- `backend/core/execution/`: o Executor aplica o plano validado como um Agno Workflow, invocando os agentes Vision/Data onde o plano os exige, e produz um `execution-report.json`.
- `backend/agents/pddl_orchestrator.py`: coordena as fases manifesto → plano → execução, com fallback para extração determinística caso o planejamento falhe.

O domínio PDDL vive em `backend/core/planning/domains/`. Os esquemas JSON (manifesto, plano, comparação, relatório de execução) ficam em `schemas/` na raiz do repositório e são gerados por `scripts/generate_pmv_schemas.py`.

---

### 1. Frontend (`frontend/`) — clientes de interface e runtimes

#### Bot Telegram (`frontend/telegram/`)
- [frontend/telegram/bot.py](../frontend/telegram/bot.py): inicializa o Bot/Dispatcher do aiogram, registra roteadores, middlewares e hooks de ciclo de vida.
- [frontend/telegram/handlers/start.py](../frontend/telegram/handlers/start.py): comandos de controle (/start, /help, /status, /health, /feedback, modos, /cancelar).
- [frontend/telegram/handlers/document.py](../frontend/telegram/handlers/document.py): recebe arquivos/fotos, valida, dispara o processamento e envia as saídas.
- [frontend/telegram/handlers/errors.py](../frontend/telegram/handlers/errors.py): tratamento global de exceções.
- [frontend/telegram/adapters/status_tracker.py](../frontend/telegram/adapters/status_tracker.py): barra de progresso específica do Telegram.
- [frontend/telegram/adapters/file_service.py](../frontend/telegram/adapters/file_service.py): auxiliares de download/upload de arquivo no Telegram.

#### Painel Web (`frontend/web/`)
- [frontend/web/app.py](../frontend/web/app.py): painel HTML renderizado no servidor. É um cliente fino da API REST — upload, status e download são delegados a `backend/api` via `frontend/clients/api_client.py`.

#### Interface de Linha de Comando (`frontend/cli/`)
- [frontend/cli/run.py](../frontend/cli/run.py): ponto de entrada da CLI para processamento em lote e execução autônoma.

#### API REST (`backend/api/`)
- A API JSON autônoma que todas as interfaces consomem: envio e status de jobs, download, histórico e saúde. Ela possui a fila de processamento e o pipeline. O bot Telegram e o painel Web são clientes dela. Referência completa de endpoints em [endpoints.md](endpoints.md).

#### Runtime AgentOS (`frontend/agent_os.py`)
- Um runtime Agno opcional que expõe os agentes Vision e Data para inspeção (chat, sessões, memória, métricas, traces) via painel AgentOS ou agent-ui. Ele não executa o pipeline; veja [endpoints.md](endpoints.md).

---

### 2. Pipeline de Documento Canônico e Exportação (`backend/pipeline/`, `backend/export/`)

- [backend/pipeline/canonical_builder.py](../backend/pipeline/canonical_builder.py): constrói o documento canônico e a árvore de seções.
- [backend/pipeline/sanitizer.py](../backend/pipeline/sanitizer.py): limpa o texto bruto, remove vazamentos de prompt e artefatos de Markdown.
- [backend/pipeline/structure_parser.py](../backend/pipeline/structure_parser.py): parser compartilhado texto-para-blocos.
- [backend/pipeline/validators.py](../backend/pipeline/validators.py): valida esquema, hierarquia de títulos, links e texto de saída; `audit_canonical_document` classifica problemas estruturais e de acessibilidade como `BLOCKER` ou `WARNING`.
- [backend/export/pandoc_exporter.py](../backend/export/pandoc_exporter.py): coordenador único de exportação para validação, filtragem, criação do AST e despacho de renderizador; atua como guardiã determinística que interrompe a exportação quando a auditoria retorna qualquer `BLOCKER`.
- [backend/export/renderers/](../backend/export/renderers/): renderizadores para TXT, DOCX, PDF e HTML.
- [backend/export/exporters/](../backend/export/exporters/): os adaptadores de exportação chamados pelo worker, incluindo `audio_exporter.py`, que produz o MP3 via edge-tts, e `pdf_exporter.py`, que produz tanto o PDF comum quanto a variante PDF/UA.

---

## Empilhamento e Direção de Dependência

A base de código segue uma arquitetura em camadas pragmática com fluxo de cima para baixo: Interface → Orquestração → Extração → Documento Canônico → Saída. Os serviços de infraestrutura e as ferramentas compartilhadas sustentam várias camadas, mas não possuem decisões de negócio. Existem algumas exceções controladas: `backend/adapters/exporters` é um envelope fino de compatibilidade sobre `backend/export`, e o orquestrador coordena tanto preocupações de processamento quanto de infraestrutura (cache, histórico).

---

## Fluxo Principal de Processamento

1. O usuário envia um documento via API REST diretamente, ou por meio do bot Telegram, do painel Web ou da CLI (que chamam a API).
2. O manipulador de interface valida a extensão e o tamanho do arquivo.
3. O arquivo é salvo e colocado na `ProcessingQueue`.
4. O worker retira a tarefa da fila e executa o pipeline para o motor ativo (`PIPELINE_ENGINE`): o workflow `legacy` (`AccessibilityWorkflow.executar()`, descrito abaixo) ou o orquestrador `pddl` (manifesto → plano → execução). Ambos produzem o mesmo documento canônico. O fluxo legacy:
    - Registra a tarefa no `StateManager` e consulta o cache local de texto.
    - **`ReaderAgent`** divide as páginas, extrai o texto local (PyMuPDF/Docling) e classifica as regiões (imagens, tabelas, fórmulas, texto).
    - **`VisionAgent`** e **`DataAgent`** rodam em paralelo para descrever elementos visuais e estruturar dados usando instâncias de `Agent` do Agno.
    - **`EditorAgent`** higieniza os resultados, aplica a deduplicação por impressões digitais e insere as tags de acessibilidade na estrutura canônica final.
5. Os validadores canônicos verificam a adesão ao esquema, a hierarquia de títulos e a segurança da saída.
6. Os renderizadores e adaptadores de exportação constroem os artefatos de saída (TXT, DOCX, PDF, PDF/UA, HTML, MP3).
7. Os arquivos de saída são empacotados e entregues ao usuário (via mensagem Telegram, link de download na Web ou e-mail).

---

## Ativação de Interfaces

A variável de ambiente `ENABLED_INTERFACES` controla quais superfícies sobem na inicialização (padrão `"api,telegram,web"`):
- `api`: a API REST (`backend/api`) em `API_PORT` (padrão 8000) — o pipeline e a fila vivem aqui.
- `telegram`: o bot Telegram (um cliente da API).
- `web`: o painel Web HTML (`frontend/web`) em `WEB_PORT` (padrão 8001), também um cliente da API.

O runtime AgentOS não faz parte de `ENABLED_INTERFACES`; ele é iniciado separadamente com `python -m frontend.agent_os`.

---

## Dependências Externas

- **Framework Agno:** orquestração multiagente e interface unificada de LLM multimodal.
- **Provedores de IA:** API Ollama (modelos locais como LLaVA/Qwen-VL) ou API OpenRouter (modelos em nuvem como Claude/GPT-4o).
- **Bibliotecas de Processamento:** PyMuPDF, Docling, Pillow, OpenCV, reportlab, python-docx, pypdf, edge-tts, aiogram, FastAPI.

---

## Decisões Arquiteturais Principais

1. **Domínio independente de interface:** os pacotes de domínio — `backend/agents`, `ai`, `core`, `pipeline`, `export`, `services` e `tools` — não têm dependência de frameworks de interface (sem aiogram, sem FastAPI). A única exceção é `backend/api`, que é a camada FastAPI que expõe o domínio via HTTP; tudo em `frontend/` é um cliente dessa API. Manter a fronteira ali significa que uma nova interface nunca exige tocar no domínio.
2. **Arquitetura Multiagente Modular:** Separa leitura estrutural, descrição visual, formatação de dados e edição de texto em agentes distintos.
3. **Documento Canônico Fonte da Verdade:** Todos os renderizadores consomem o esquema do documento canônico validado para garantir compatibilidade com leitores de tela.
