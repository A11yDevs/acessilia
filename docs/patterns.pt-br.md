# Padrões de Design e Integração

Também disponível em **inglês (EUA)**: [English version](patterns.md)

## Padrões Identificados

### 1. Pipeline de Documento Canônico
- Implementação: [backend/pipeline/canonical_builder.py](../backend/pipeline/canonical_builder.py), [backend/pipeline/validators.py](../backend/pipeline/validators.py), [backend/pipeline/structure_parser.py](../backend/pipeline/structure_parser.py), [backend/export/pandoc_exporter.py](../backend/export/pandoc_exporter.py)
- Papel: normalizar cargas de regiões estruturadas em um esquema de documento canônico, validar estrutura e hierarquia de títulos, construir o AST intermediário e despachar para os renderizadores.
- Benefício: saída determinística e uma única fonte da verdade para todos os exportadores de saída.

### 2. Orquestração de Pipeline Multiagente (motor legacy)
- Implementação: [backend/agents/orchestrator.py](../backend/agents/orchestrator.py) (`AccessibilityOrchestrator`), usada quando `PIPELINE_ENGINE=legacy` (o padrão). O motor `pddl` usa a orquestração baseada em planejamento do padrão 10 em vez disso.
- Papel: coordena o ciclo de vida multiagente: leitura estrutural local, processamento visual/de dados em paralelo, edição/deduplicação de texto, cache, registro de histórico e fallback.
- Benefício: centraliza as regras de negócio e isola as responsabilidades de cada etapa.

### 3. Estratégia e Abstração de Modelo para IA (Agno)
- Implementação: [backend/ai/models/ai_client.py](../backend/ai/models/ai_client.py) (`get_agno_model()`)
- Estratégias:
  - Ollama (modelos locais de pesos abertos como LLaVA/Qwen-VL)
  - OpenRouter (modelos de API em nuvem como Claude/GPT-4o)
- Benefício: o provedor de modelo de IA pode ser trocado sem embaraço via configuração de ambiente, sem alterar a lógica dos agentes.

### 4. Estratégia de Extração Local-First
- Implementação: [backend/agents/reader_agent.py](../backend/agents/reader_agent.py) usando PyMuPDF e Docling.
- Papel:
  - executar primeiro a extração determinística local de texto e regiões de PDF,
  - chamar os agentes de visão/dados do Agno apenas para páginas escaneadas, imagens, tabelas complexas e fórmulas,
  - manter cache em nível de página e de região.
- Benefício: menor latência, menor custo operacional e preservação de privacidade para PDFs com texto nativo.

### 5. Especialização Multiagente
- Implementação:
  - [backend/agents/reader_agent.py](../backend/agents/reader_agent.py) (`ReaderAgent` - divisão determinística de regiões)
  - [backend/agents/vision_agent.py](../backend/agents/vision_agent.py) (`VisionAgent` - alt-text visual e descrições em áudio via LLM do Agno)
  - [backend/agents/data_agent.py](../backend/agents/data_agent.py) (`DataAgent` - tabelas e fórmulas matemáticas via LLM do Agno)
  - [backend/agents/editor_agent.py](../backend/agents/editor_agent.py) (`EditorAgent` - higienização, deduplicação por impressão digital e tagging de acessibilidade determinísticos)
- Benefício: separação limpa de responsabilidades e execução em paralelo (`asyncio.gather`).

### 6. Adaptadores de Exportação e Renderizadores
- Implementação: [backend/export/pandoc_exporter.py](../backend/export/pandoc_exporter.py) com renderizadores em `backend/export/renderers/` (TXT, DOCX, PDF, HTML) e adaptadores de exportação em `backend/export/exporters/` (MP3 via edge-tts e a variante PDF/UA).
- Benefício: um documento canônico idêntico produz diversos formatos de saída de forma limpa.

### 7. Máquina de Estados em Memória e Cancelamento Cooperativo
- Implementação: [backend/agents/state_manager.py](../backend/agents/state_manager.py)
- Estados observados: `processing`, `done`, `error`, `cancelled`.
- Benefício: rastreamento de progresso em tempo real e suporte a cancelamento.

### 8. Padrão Cache-Aside
- Implementação:
  - cache global de arquivos em `backend/services/cache.py`
  - cache de regiões em `backend/agents/orchestrator.py`
- Benefício: elimina chamadas duplicadas de LLM para documentos ou imagens inalterados.

### 9. Execução em Instância Única e Travinha de Processo
- Implementação: [frontend/run.py](../frontend/run.py)
- Benefício: impede colisões de processos na máquina do host.

### 10. Planejamento Determinístico com PDDL (motor opcional)
- Implementação: [backend/core/manifest/](../backend/core/manifest/), [backend/core/planning/](../backend/core/planning/), [backend/core/execution/](../backend/core/execution/), coordenados por [backend/agents/pddl_orchestrator.py](../backend/agents/pddl_orchestrator.py). Ativo quando `PIPELINE_ENGINE=pddl`.
- Papel: separar *o que fazer* de *fazer*. Um manifesto determinístico descreve as regiões e obrigações do documento; um planejador PDDL o compila em um plano validado e ordenado; um executor Agno Workflow aplica o plano, chamando os agentes Vision/Data apenas onde o plano exige. Veja [pmv_agno_pddl.md](pmv_agno_pddl.md).
- Benefício: a ordem e as dependências das tarefas ficam explícitas e auditáveis, e o planejamento permanece determinístico (nenhum LLM escreve PDDL) enquanto a IA fica restrita à descrição. Faz fallback para extração determinística caso o planejamento falhe.

### 11. API REST com Clientes de Interface
- Implementação: [backend/api/](../backend/api/); clientes em [frontend/clients/api_client.py](../frontend/clients/api_client.py), consumidos pelo bot Telegram e pelo painel Web.
- Benefício: um único lugar possui a fila e o pipeline; toda interface (chamadores da API, Telegram, Web, CLI) é um cliente fino, de modo que o comportamento permanece consistente entre as superfícies.

---

## Roadmap de Evolução Arquitetural

1. **Orquestração Inteligente Dinâmica (Recurso Futuro):**
   - O motor de planejamento PDDL (padrão 10) é o primeiro passo rumo a um roteamento de tarefas explícito e determinístico. O objetivo restante é um roteador dinâmico que também pese a complexidade do documento, o orçamento e a SLA para rotear entre modelos locais Ollama e endpoints em nuvem OpenRouter.
2. **Escala de Agentes em Paralelo:**
   - Expandir a execução `asyncio.gather` para suportar filas de workers distribuídos em pipelines de documentos de alto volume.
