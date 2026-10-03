# Arquitetura

Também disponível em **inglês (EUA)**: [English version](architecture.md)

## Visão geral
O sistema converte documentos em formatos acessíveis por meio de um pipeline de extração multiagente (extração estrutural via Acessilia Toolbox, mais agentes de visão e de dados de IA multimodal conduzidos por Agno), um pipeline de documento canônico, validação determinística e renderizadores específicos de formato. A arquitetura é modular: **backend/** guarda a lógica de domínio e a API REST que a expõe, **frontend/** guarda os clientes de interface (Telegram, Web, CLI) que conversam com essa API, e **infra/** guarda o Dockerfile (o arquivo Compose fica na raiz do repositório).

O sistema combina **planejamento determinístico com execução por IA**. O único motor é `pddl`: extrai um manifesto via Acessilia Toolbox, enriquece-o com Vision/Data e gera um plano PDDL, com validação opcional em dry-run por Agno Workflow. `PIPELINE_ENGINE` aceita `pddl` e o alias `pmv`; `legacy` e nomes desconhecidos são rejeitados. Veja [pmv_agno_pddl.pt-br.md](pmv_agno_pddl.pt-br.md).

---

## Camadas

### 0. Backend (`backend/`) — lógica de negócio agnóstica de interface e pipeline de IA

#### 0.1. Pipeline Multiagente e Orquestração (`backend/agents/`)
- [backend/agents/pddl_orchestrator.py](../backend/agents/pddl_orchestrator.py): coordena extração via Toolbox, planejamento PDDL e execução validada.
- [backend/agents/vision_agent.py](../backend/agents/vision_agent.py): `VisionAgent` utiliza o Agno (`agno.agent.Agent`) e as capacidades multimodais do LLM (`agno.media.Image`) para produzir alt-text detalhado e descrições em áudio para elementos visuais e páginas escaneadas.
- [backend/agents/data_agent.py](../backend/agents/data_agent.py): `DataAgent` utiliza o Agno (`agno.agent.Agent`) e as capacidades do LLM para converter tabelas complexas e fórmulas matemáticas em representações Markdown e LaTeX estruturadas.
- [backend/agents/state_manager.py](../backend/agents/state_manager.py): máquina de estados em memória para tarefas com suporte a cancelamento cooperativo.

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
- [backend/tools/toolbox_pdf_tools.py](../backend/tools/toolbox_pdf_tools.py): divisão/renderização remota de PDF com fallback local PyMuPDF.
- [backend/tools/text_processor.py](../backend/tools/text_processor.py): normalização de texto e parsing de Markdown.
- [backend/tools/prompt_tools.py](../backend/tools/prompt_tools.py): carregador de prompt e resolutor de templates.

#### 0.5. Camada de Planejamento (`backend/core/`) — motor PDDL

O motor PDDL extrai o manifesto via Toolbox e enriquece imagens/tabelas com Vision/Data antes de gerar o plano. A compilação do problema PDDL e os contratos dos métodos são determinísticos; o executor valida o plano em dry-run quando habilitado. `pmv` é um alias de `pddl`.

- `backend/core/manifest/`: o agente Informacional-Estrutural extrai um `processing-manifest.json` do documento (regiões, tipos e obrigações de processamento) via Acessilia Toolbox.
- `backend/core/planning/`: o `PlannerAgent` compila o manifesto mais um domínio PDDL em um problema, gera um `nominal-plan.json` (planejador interno ou backend Fast Downward) e o valida. A geração do problema PDDL é determinística — nenhum LLM escreve PDDL.
- `backend/core/execution/`: o Executor percorre o plano validado em um Agno Workflow e, no dry-run opcional da aplicação, produz um `execution-report.json` sem executar os métodos reais.
- `backend/core/agents/fusion_agent.py`: o `FusionAgent` expõe ferramentas Agno determinísticas sobre a biblioteca pura `docstruct` — `fuse_providers`, `audit_document`, `classify_block` e `needs_reinfer`. O método PDDL `dual-provider-fusion` reutiliza `backend.pipeline.fusion.extract_fused` e só é admissível quando `FUSION_MODE=dual`. Veja [docstruct_algorithms.pt-br.md](docstruct_algorithms.pt-br.md) para saber como funcionam esses algoritmos.
- `backend/agents/pddl_orchestrator.py`: coordena extração → enriquecimento → plano → dry-run opcional → saída. Erros de planejamento são propagados.

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
- [frontend/web/templates/base.html](../frontend/web/templates/base.html): moldura compartilhada, estilos e rodapé; as páginas básica, avançada e de download mantêm seu conteúdo próprio.

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

A base de código segue uma arquitetura em camadas pragmática com fluxo de cima para baixo: Interface → Orquestração → Extração → Documento Canônico → Saída. Os serviços de infraestrutura e as ferramentas compartilhadas sustentam várias camadas, mas não possuem decisões de negócio. O serviço de processamento coordena o workflow, o cache e o histórico; o worker chama os exportadores de `backend/export` diretamente.

---

## Fluxo Principal de Processamento

1. O usuário envia um documento via API REST diretamente, ou por meio do bot Telegram, do painel Web ou da CLI (que chamam a API).
2. O manipulador de interface valida a extensão e o tamanho do arquivo.
3. O arquivo é salvo e colocado na `ProcessingQueue`.
4. O worker executa `backend.service.process()`, que registra a tarefa e consulta o cache. O orquestrador PDDL extrai o manifesto via Toolbox, gera e valida o plano e executa as etapas selecionadas. Vision/Data enriquecem as regiões previstas; os resultados alimentam o documento canônico.
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
- **Bibliotecas de Processamento:** PyMuPDF, Docling, Pillow, OpenCV, reportlab, python-docx, edge-tts, aiogram, FastAPI.

A divisão e renderização locais de PDFs usam PyMuPDF. A divisão preserva ordem das páginas, geometria, links, anotações e campos de formulário, com limite padrão de 50 páginas. Links para outras páginas extraídas apontam para os PDFs individuais na mesma pasta; links além do limite apontam para a fonte original. A versão mínima suportada do PyMuPDF é 1.28.2, validada para copiar campos de formulário e navegação em páginas rotacionadas e recortadas. Destinos nomeados e sumários do documento não são exportados nessa operação por página.

---

## Decisões Arquiteturais Principais

1. **Domínio independente de interface:** os pacotes de domínio — `backend/agents`, `ai`, `core`, `pipeline`, `export`, `services` e `tools` — não têm dependência de frameworks de interface (sem aiogram, sem FastAPI). A única exceção é `backend/api`, que é a camada FastAPI que expõe o domínio via HTTP; tudo em `frontend/` é um cliente dessa API. Manter a fronteira ali significa que uma nova interface nunca exige tocar no domínio.
2. **Arquitetura Multiagente Modular:** Separa leitura estrutural, descrição visual, formatação de dados e edição de texto em agentes distintos.
3. **Documento Canônico Fonte da Verdade:** Todos os renderizadores consomem o esquema do documento canônico validado para garantir compatibilidade com leitores de tela.
