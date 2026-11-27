# Padrões de Design e Integração

Também disponível em **inglês (EUA)**: [English version](patterns.md)

## Padrões Identificados

### 1. Pipeline de Documento Canônico
- Implementação: [libs/core/src/acessilia_core/pipeline/canonical_builder.py](../libs/core/src/acessilia_core/pipeline/canonical_builder.py), [libs/core/src/acessilia_core/pipeline/validators.py](../libs/core/src/acessilia_core/pipeline/validators.py), [libs/core/src/acessilia_core/export/pandoc_exporter.py](../libs/core/src/acessilia_core/export/pandoc_exporter.py)
- Papel: normalizar cargas de regiões estruturadas em um esquema de documento canônico, validar estrutura e hierarquia de títulos, construir o AST intermediário e despachar para os renderizadores.
- Benefício: saída determinística e uma única fonte da verdade para todos os exportadores de saída.

### 2. Estratégia e Abstração de Modelo para IA (Agno)
- Implementação: [libs/core/src/acessilia_core/agents/ai_client.py](../libs/core/src/acessilia_core/agents/ai_client.py) (`get_agno_model(models, toolbox)`, a partir da `ModelConfig` e da `ToolboxConfig` da execução)
- Estratégias:
  - Ollama (modelos locais de pesos abertos como LLaVA/Qwen-VL)
  - OpenRouter (modelos de API em nuvem como Claude/GPT-4o)
- Benefício: o provedor de modelo de IA pode ser trocado sem embaraço via configuração de ambiente, sem alterar a lógica dos agentes.

### 3. Especialização Multiagente
- Implementação:
  - [libs/core/src/acessilia_core/agents/vision_agent.py](../libs/core/src/acessilia_core/agents/vision_agent.py) (`VisionAgent` - alt-text visual e descrições em áudio via LLM do Agno)
  - [libs/core/src/acessilia_core/agents/data_agent.py](../libs/core/src/acessilia_core/agents/data_agent.py) (`DataAgent` - tabelas e fórmulas matemáticas via LLM do Agno)
- Benefício: separação limpa de responsabilidades e execução em paralelo (`asyncio.gather`).

### 4. Adaptadores de Exportação e Renderizadores
- Implementação: [libs/core/src/acessilia_core/export/pandoc_exporter.py](../libs/core/src/acessilia_core/export/pandoc_exporter.py) com renderizadores em `libs/core/src/acessilia_core/export/renderers/` (TXT, HTML) e adaptadores de exportação em `libs/core/src/acessilia_core/export/exporters/` (MP3 via edge-tts; DOCX e PDF/UA, o único PDF, renderizados na Toolbox, que também audita o PDF/UA com o veraPDF).
- Benefício: um documento canônico idêntico produz diversos formatos de saída de forma limpa.

### 5. Máquina de Estados em Memória e Cancelamento Cooperativo
- Implementação: [backend/agents/state_manager.py](../backend/agents/state_manager.py)
- Estados observados: `processing`, `done`, `error`, `cancelled`.
- Benefício: rastreamento de progresso em tempo real e suporte a cancelamento.

### 6. Padrão Cache-Aside
- Implementação:
  - cache global de arquivos em `backend/services/cache.py`
- Benefício: elimina chamadas duplicadas de LLM para documentos ou imagens inalterados.

### 7. Execução em Instância Única e Travinha de Processo
- Implementação: [frontend/run.py](../frontend/run.py)
- O lock é um lock exclusivo do sistema operacional (`fcntl.flock` no POSIX, `msvcrt.locking` no Windows) sobre `frontend/bot.lock.v2`, mantido durante toda a vida do processo; o PID gravado no arquivo é diagnóstico. O runtime também grava seu PID no `frontend/bot.lock` anterior ao #903, para que um runtime antigo recuse iniciar enquanto o novo roda e para que a remoção desse caminho por um runtime antigo não libere o lock autoritativo.
- O modo `0600` é aplicado na criação e, no POSIX, restringido quando possível. É best-effort: não protege o arquivo contra remoção por quem tem permissão de escrita no diretório. A exclusão mútua é o lock do SO, não o modo.
- Benefício: impede colisões de processos na máquina do host, e duas inicializações concorrentes não podem ambas adquirir o lock.

### 8. Planejamento Determinístico com PDDL
- Implementação: [libs/core/src/acessilia_core/manifest/](../libs/core/src/acessilia_core/manifest/), [libs/core/src/acessilia_core/planning/](../libs/core/src/acessilia_core/planning/), [libs/core/src/acessilia_core/execution/](../libs/core/src/acessilia_core/execution/), coordenados por [libs/core/src/acessilia_core/pipeline/orchestrator.py](../libs/core/src/acessilia_core/pipeline/orchestrator.py). É o único motor ativo; o manifesto é extraído pela Toolbox.
- Papel: separar *o que fazer* de *fazer*. Um manifesto determinístico descreve as regiões e obrigações do documento; um planejador PDDL o compila em um plano validado e ordenado; um executor Agno Workflow aplica o plano, chamando os agentes Vision/Data apenas onde o plano exige. Veja [pddl_pipeline.pt-br.md](pddl_pipeline.pt-br.md).
- Benefício: a ordem e as dependências das tarefas ficam explícitas e auditáveis, e o planejamento permanece determinístico (nenhum LLM escreve PDDL) enquanto a IA fica restrita à descrição. Uma falha no planejamento faz a tarefa falhar; não há fallback para extração determinística.

### 9. API REST com Clientes de Interface
- Implementação: [backend/api/](../backend/api/); clientes em [frontend/clients/api_client.py](../frontend/clients/api_client.py), consumidos pelo bot Telegram e pelo painel Web.
- Benefício: um único lugar possui a fila e o pipeline; toda interface (chamadores da API, Telegram, Web, CLI) é um cliente fino, de modo que o comportamento permanece consistente entre as superfícies.

### 10. Agente de Fusão Determinístico (ferramentas docstruct)
- Implementação: [libs/core/src/acessilia_core/agents/fusion_agent.py](../libs/core/src/acessilia_core/agents/fusion_agent.py) (`FusionAgent`), envolvendo a biblioteca pura `docstruct` (`libs/docstruct`).
- Papel: expõe quatro ferramentas determinísticas ao Agno — `fuse_providers` (funde dois providers de toolbox via `docstruct.fusion`), `audit_document` (auditoria do documento canônico), `classify_block` (classificação de regiões) e `needs_reinfer` (decide se uma região precisa de re-inferência de visão/orientação). Cada capacidade tem um método `process_*` puro (testável sem Agno) mais um envelope JSON fino.
- Benefício: segue o padrão `InformationalStructuralAgent` — núcleo determinístico, envelope Agno opcional — de modo que a lógica de fusão/auditoria permanece testável e o LLM só seleciona qual ferramenta chamar. O método PDDL `dual-provider-fusion` (padrão 8) reutiliza `acessilia_core.pipeline.fusion.extract_fused` e só é admissível quando `FUSION_MODE=dual`. Veja [docstruct_algorithms.pt-br.md](docstruct_algorithms.pt-br.md) para os detalhes dos algoritmos.

---

## Roadmap de Evolução Arquitetural

1. **Orquestração Inteligente Dinâmica (Recurso Futuro):**
   - O motor de planejamento PDDL (padrão 8) é o primeiro passo rumo a um roteamento de tarefas explícito e determinístico. O objetivo restante é um roteador dinâmico que também pese a complexidade do documento, o orçamento e a SLA para rotear entre modelos locais Ollama e endpoints em nuvem OpenRouter.
2. **Escala de Agentes em Paralelo:**
   - Expandir a execução `asyncio.gather` para suportar filas de workers distribuídos em pipelines de documentos de alto volume.
