# Arquitetura

Também disponível em **inglês (EUA)**: [English version](architecture.md)

## Visão geral
O sistema converte documentos em formatos acessíveis por meio de um pipeline de extração multiagente (extração estrutural por meio das capacidades da Acessilia Toolbox, mais agentes de visão e de dados de IA multimodal conduzidos por Agno), um pipeline de documento canônico, validação determinística e renderizadores específicos de formato. A arquitetura é modular: **backend/** guarda a lógica de domínio e a API REST que a expõe, **frontend/** guarda os clientes de interface (Telegram, Web, CLI) que conversam com essa API, e **infra/** guarda o Dockerfile (o arquivo Compose fica na raiz do repositório).

O sistema combina **planejamento determinístico com execução guiada por IA**: as funções determinísticas (extração, geração do problema PDDL, validação de contrato) são a fonte da verdade, e os LLMs fornecem interpretação e descrição. Os documentos passam pelo motor de pipeline **`pddl`** (`PIPELINE_ENGINE`, padrão `pddl`): um manifesto de processamento é extraído, um plano PDDL é gerado e validado, e um executor Agno Workflow o aplica. Veja [pmv_agno_pddl.md](pmv_agno_pddl.md).

O antigo motor **`legacy`** (`AccessibilityOrchestrator`: Reader → Vision/Data → Editor) está desativado: `backend/service.py` aceita apenas `pddl` (o antigo alias `pmv` é normalizado para ele) e recusa qualquer outro valor. O código dele foi removido.

---

## Camadas

### 0. Backend (`backend/`) — lógica de negócio agnóstica de interface e pipeline de IA

#### 0.1. Pipeline Multiagente e Orquestração (`backend/agents/`)
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
- [backend/tools/text_processor.py](../backend/tools/text_processor.py): normalização de texto e parsing de Markdown.
- [backend/tools/prompt_tools.py](../backend/tools/prompt_tools.py): carregador de prompt e resolutor de templates.

#### 0.5. Camada de Planejamento (`backend/core/`) — motor PDDL

Este é o único motor ativo. Ele transforma a estrutura do documento em um plano explícito antes de qualquer IA rodar, de modo que a ordem e as dependências das tarefas sejam determinísticas e auditáveis.

- `backend/core/manifest/`: o agente Informacional-Estrutural extrai um `processing-manifest.json` do documento (regiões, tipos e obrigações de processamento) pela Toolbox (`ToolboxManifestExtractor`, capacidade `document.structure.extract`). Os extratores locais Docling/PyMuPDF estão desativados neste motor.
- `backend/core/planning/`: o `PlannerAgent` compila o manifesto mais um domínio PDDL em um problema, gera um `nominal-plan.json` (planejador interno ou backend Fast Downward) e o valida. A geração do problema PDDL é determinística — nenhum LLM escreve PDDL.
- `backend/core/execution/`: o Executor aplica o plano validado como um Agno Workflow, invocando os agentes Vision/Data onde o plano os exige, e produz um `execution-report.json`.
- `backend/core/agents/fusion_agent.py`: o `FusionAgent` expõe ferramentas Agno determinísticas sobre a biblioteca pura `docstruct` — `fuse_providers`, `audit_document`, `classify_block` e `needs_reinfer`. O método PDDL `dual-provider-fusion` reutiliza `backend.pipeline.fusion.extract_fused` e só é admissível quando `FUSION_MODE=dual`. Veja [docstruct_algorithms.pt-br.md](docstruct_algorithms.pt-br.md) para saber como funcionam esses algoritmos.
- `backend/agents/pddl_orchestrator.py`: `PddlAccessibilityOrchestrator.executar()` coordena as fases manifesto → plano → execução. Uma falha no planejamento faz a tarefa falhar; não há fallback para extração determinística.

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
- [backend/pipeline/validators.py](../backend/pipeline/validators.py): valida esquema, hierarquia de títulos, links e texto de saída; `audit_canonical_document` classifica problemas estruturais e de acessibilidade como `BLOCKER` ou `WARNING`.
- [backend/export/pandoc_exporter.py](../backend/export/pandoc_exporter.py): coordenador único de exportação para validação, filtragem, criação do AST e despacho de renderizador; atua como guardiã determinística que interrompe a exportação quando a auditoria retorna qualquer `BLOCKER`.
- [backend/export/renderers/](../backend/export/renderers/): renderizadores para TXT e HTML (DOCX e PDF/UA são renderizados na Toolbox).
- [backend/export/exporters/](../backend/export/exporters/): os adaptadores de exportação chamados pelo worker, incluindo `audio_exporter.py`, que produz o MP3 via edge-tts, e `pdf_exporter.py`, que produz o PDF/UA, o único PDF. [backend/tools/pdf_ua_audit.py](../backend/tools/pdf_ua_audit.py) o audita com o veraPDF na Toolbox (`pdf.validate.pdf_ua`) para o e-mail de resultado.

---

## Empilhamento e Direção de Dependência

A base de código segue uma arquitetura em camadas pragmática com fluxo de cima para baixo: Interface → Orquestração → Extração → Documento Canônico → Saída. Os serviços de infraestrutura e as ferramentas compartilhadas sustentam várias camadas, mas não possuem decisões de negócio. Existem algumas exceções controladas: `backend/adapters/exporters` é um envelope fino de compatibilidade sobre `backend/export`, e o orquestrador coordena tanto preocupações de processamento quanto de infraestrutura (cache, histórico).

### Bibliotecas e a Toolbox (`libs/`)

Os modelos pesados rodam num serviço separado, a [Acessilia Toolbox](https://github.com/A11yDevs/acessilia-toolbox). Entre ela e este core ficam duas bibliotecas, mantidas em `libs/`. As dependências só apontam para baixo:

| Camada | Pacote | Papel | Pode depender de |
|---|---|---|---|
| 0 | `libs/docstruct` (`acessilia-docstruct`) | Algoritmos puros de estrutura de documentos (fusão, tabelas, ordem de leitura), sem dependências próprias | nada |
| 1 | Toolbox (repositório separado) | Providers pesados, armazenamento de artefatos, execução de capacidades por REST/MCP | docstruct |
| 2 | `libs/sdk` (`acessilia-sdk`) | Allowlist de capacidades, transporte HTTP, verificações do catálogo, referências de artefatos, retries e failover; a configuração é injetada | o **contrato publicado** da Toolbox (IDs de capacidade, versões, schemas), nunca o pacote dela |
| 3 | Core (`backend/`) | Agentes, planejamento PDDL, obrigações, políticas | SDK, docstruct |

- **O core decide o que fazer e quando; o SDK define como acessar uma operação; a Toolbox fornece onde e com quais recursos ela roda.** Obrigações, métodos admissíveis e custos são política de planejamento do core: a Toolbox relata o que encontrou, e o core deriva as obrigações ([#138](https://github.com/A11yDevs/acessilia/pull/138)).
- **Capacidades operacionais rodam só na Toolbox.** A política de produção é `remote_only`: o core não mantém fallback local para Pandoc, TeX Live, veraPDF, renderização com PyMuPDF, inspeção de mídias ou OCR, e a Toolbox não depende do SDK ([ADR-0002](adr/0002-component-responsibilities.pt-br.md), [ADR-0003](adr/0003-remote-only-operational-capabilities.pt-br.md)).
- **A disponibilidade vem de réplicas da Toolbox** atrás de um balanceador, que compartilham o armazenamento de artefatos, com retries limitados no SDK; o failover multi-endpoint do SDK fica reservado a deploys independentes ([ADR-0006](adr/0006-availability-and-failover.pt-br.md)). Artefatos persistidos trafegam como referências `ArtifactRef` ([ADR-0005](adr/0005-artifact-references.pt-br.md)).
- **Uma fonte de verdade por contrato:** a docstruct é dona dos modelos documentais canônicos; a Toolbox, dos contratos operacionais da API; o SDK os consome ([ADR-0004](adr/0004-single-source-of-truth-for-contracts.pt-br.md)). Decisões que atravessam componentes ficam registradas em [docs/adr/](adr/README.pt-br.md).
- **O catálogo da Toolbox só restringe.** Os métodos que chamam a Toolbox são conferidos contra o catálogo vivo antes de cada documento ser planejado (`TOOLBOX_AVAILABILITY_GATE`); uma capacidade fora da allowlist do SDK nunca fica disponível. Veja [toolbox_integration.pt-br.md](toolbox_integration.pt-br.md).
- **A docstruct é distribuída como wheel de release.** O core a instala a partir deste checkout. A Toolbox fixa a wheel de um GitHub Release `docstruct-vX.Y.Z` pela URL e pelo `#sha256=` ([Releases](../libs/docstruct/README.pt-br.md#releases)). O SDK tem um único consumidor, o core, e ainda não é publicado.
- **Garantido por testes:** `libs/docstruct/tests/test_purity.py` e `libs/sdk/tests/test_purity.py` importam todos os módulos com as camadas de cima bloqueadas; `tests/test_architecture_layers.py` falha se o `backend` importar o pacote da Toolbox.

---

## Fluxo Principal de Processamento

1. O usuário envia um documento via API REST diretamente, ou por meio do bot Telegram, do painel Web ou da CLI (que chamam a API).
2. O manipulador de interface valida a extensão e o tamanho do arquivo.
3. O arquivo é salvo e colocado na `ProcessingQueue`.
4. O worker retira a tarefa da fila; `backend/service.py::process` a registra no `StateManager` e consulta o cache de processamento.
5. Se não houver cache, executa o orquestrador PDDL (`PddlAccessibilityOrchestrator.executar()`):
    - Extrai o manifesto de processamento pela Toolbox (`document.structure.extract`) e inspeciona a mídia de origem (`media.inspect`).
    - Enriquece imagens e tabelas, monta e valida um plano PDDL para as obrigações do manifesto e o executa, replanejando quando um método falha.
    - Constrói o documento canônico a partir do manifesto executado.
6. Os validadores canônicos verificam a adesão ao esquema, a hierarquia de títulos e a segurança da saída.
7. Os renderizadores e adaptadores de exportação constroem os artefatos de saída (TXT, DOCX, PDF/UA, HTML, MP3).
8. Os arquivos de saída são empacotados e entregues ao usuário (via mensagem Telegram, link de download na Web ou e-mail).

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
- **Bibliotecas de Processamento:** edge-tts, aiogram, FastAPI.
- **Não restam executores locais** ([ADR-0003](adr/0003-remote-only-operational-capabilities.pt-br.md), [#150](https://github.com/A11yDevs/acessilia/issues/150)): o manifesto é extraído só pelo `ToolboxManifestExtractor`, e o PyMuPDF é uma dependência de desenvolvimento, usada pelos testes para gerar PDFs. O `tests/test_architecture_layers.py` falha se `backend/` ou `frontend/` importar uma biblioteca operacional (PyMuPDF, Pillow, OpenCV, Docling, pypdf, python-docx, RapidOCR). Pandoc, TeX Live, veraPDF e as bibliotecas de OCR e de mídia já saíram da imagem, porque o DOCX e o PDF/UA só são renderizados na Toolbox; o NumPy e o OpenCV saíram das dependências junto com os scripts de experimento do Dr.DocBench (tag `drbench-2026-snapshot`); o Pillow e o pypdf saíram das dependências de execução junto com o reportlab e o renderizador PDF local, e o Pillow ficou só no extra `dev`, para as imagens de página que os testes ponta a ponta da Toolbox enviam.

---

## Decisões Arquiteturais Principais

1. **Domínio independente de interface:** os pacotes de domínio — `backend/agents`, `ai`, `core`, `pipeline`, `export`, `services` e `tools` — não têm dependência de frameworks de interface (sem aiogram, sem FastAPI). A única exceção é `backend/api`, que é a camada FastAPI que expõe o domínio via HTTP; tudo em `frontend/` é um cliente dessa API. Manter a fronteira ali significa que uma nova interface nunca exige tocar no domínio.
2. **Arquitetura Multiagente Modular:** Separa leitura estrutural, descrição visual, formatação de dados e edição de texto em agentes distintos.
3. **Documento Canônico Fonte da Verdade:** Todos os renderizadores consomem o esquema do documento canônico validado para garantir compatibilidade com leitores de tela.
