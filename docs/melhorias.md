# Melhorias e Correções — Acessília (revisão dos agentes vs. Agno 2.0)

> Revisão dos agentes implementados comparando com a documentação/lógica do Agno 2.0
> e boas práticas de programação. Nenhuma alteração foi feita no código — este
> documento é apenas um roteiro de revisão.

---

## 🔴 Prioridade alta

### 1. `OpenRouter` sem `max_tokens` → audiodescrições truncadas
- **Onde:** `core/models/ai_client.py` (ramo do OpenRouter).
- **Problema:** o ramo do OpenRouter não define `max_tokens`. No código-fonte do Agno o
  **default é `max_tokens=1024`**. Para audiodescrições detalhadas e tabelas grandes,
  1024 tokens corta a saída no meio. O `Ollama` não tem esse teto, então o bug só
  aparece com `AI_CLIENT=openrouter` — silencioso e difícil de perceber.
- **Sugestão:** expor um `max_tokens` no `settings` e passá-lo ao `OpenRouter(...)`
  (ex.: 4096–8192).

### 2. Recriar `Agent` + modelo + cliente HTTP a cada região
- **Onde:** `core/agents/vision_agent.py`, `core/agents/data_agent.py`.
- **Problema:** cada chamada de `describe_region` / `process_region` executa
  `get_agno_model()` e `Agent(...)` do zero. Como `_dispatch_tasks` dispara isso em
  paralelo via `asyncio.gather`, uma página com 10 regiões cria 10 modelos + 10 clientes
  (httpx/openai/ollama), cada um abrindo suas próprias conexões.
- **Contexto Agno 2.0:** os agentes são **stateless por design** — reutilizar a mesma
  instância é seguro e é a prática recomendada.
- **Sugestão:** instanciar `self.agent` uma vez no `__init__` do `VisionAgent`/`DataAgent`
  (ou compartilhar o modelo) e reusar. Ganho direto de latência e menos pressão de
  conexões.

### 3. `OLLAMA_BASE_URL` no `.env.example` incompatível com o cliente nativo
- **Onde:** `.env.example` + `core/models/ai_client.py` (ramo do Ollama).
- **Problema:** o `.env.example` sugere `OLLAMA_BASE_URL=.../v1/chat/completions`, mas o
  `Ollama` do Agno usa o **cliente nativo `ollama`** (não o endpoint OpenAI-compatível) e
  espera o host-raiz (`http://host:11434`). O `ai_client` faz `.replace("/api/chat", "")`,
  que **não** remove o sufixo `/v1/chat/completions` — o host fica quebrado se alguém
  copiar o exemplo literalmente.
- **Sugestão:** no `.env.example`, usar `OLLAMA_BASE_URL=http://localhost:11434` e
  ajustar/remover o `.replace` correspondente.

---

## 🟡 Prioridade média

### 4. Concorrência sem limite no `_dispatch_tasks`
- **Onde:** `core/agents/team.py`.
- **Problema:** `asyncio.gather` de todas as tarefas de visão da página sem semáforo. Em
  páginas densas pode estourar rate-limit do OpenRouter ou saturar o Ollama local.
- **Sugestão:** `asyncio.Semaphore(N)` (N configurável) envolvendo as chamadas de IA.

### 5. Usar os retries nativos do Agno em vez de engolir a exceção
- **Onde:** `core/agents/vision_agent.py`, `core/agents/data_agent.py`.
- **Problema:** ambos capturam `except Exception` e retornam `""` / `fallback_text`, o que
  mascara falhas transitórias (timeout, 429). Uma falha de rede vira silenciosamente
  "[Pagina X: resposta vazia]".
- **Contexto Agno 2.0:** o modelo já tem `retries`, `delay_between_retries`,
  `exponential_backoff`, `retry_with_guidance`.
- **Sugestão:** configurar retries no `get_agno_model()` e reservar o `except` só para o
  fallback final.

### 6. Separar `instructions` de `input`
- **Onde:** `core/agents/vision_agent.py`, `core/agents/data_agent.py`.
- **Problema:** hoje o prompt completo (persona + regras + tarefa) vai como `input=prompt`.
- **Contexto Agno 2.0:** o idioma é persona/regras fixas em `instructions=` (ou
  `system_message`) e só o conteúdo da tarefa em `input=`. Melhora clareza e o
  aproveitamento de prompt-cache do provedor.
- **Sugestão:** `Agent(..., instructions=system_prompt)` fixo por modo, e `input` só com a
  instrução específica da região.

### 7. `DataAgent` como candidato natural a `output_schema` (Pydantic)
- **Onde:** `core/agents/data_agent.py`.
- **Problema/oportunidade:** tabelas/fórmulas se beneficiam de saída tipada
  (`output_schema=TabelaModel`) — elimina parsing frágil e garante Markdown/LaTeX
  bem-formado. Com `output_schema`, `response.content` já retorna o objeto validado.
- **Obs.:** já consta no roadmap do `proposta.md`.

---

## 🟢 Prioridade baixa (estilo / manutenção)

### 8. Config morta do tesseract
- **Onde:** `config/settings.py:35` (`tesseract_cmd`) e `.env.example` (`TESSERACT_CMD`).
- **Problema:** `tesseract_cmd` é declarado mas **nunca é lido** por ninguém. O OCR real do
  pipeline não usa tesseract (PyMuPDF extrai texto embutido; Docling usa `rapidocr`;
  páginas escaneadas são lidas pelo próprio LLM de visão). O `'tesseract'` em
  `history_service.py:37` é apenas o valor default de uma coluna no SQLite.
- **Sugestão:** remover `tesseract_cmd` do `settings.py` e a linha `TESSERACT_CMD` do
  `.env.example`.

### 9. Nome do arquivo `team.py` induz a erro
- **Onde:** `core/agents/team.py`.
- **Problema:** o arquivo hospeda `AccessibilityOrchestrator`, não um `Team`. Como o Agno
  tem uma classe `Team` real, o nome confunde. Além disso já existe
  `core/orchestrator.py` — dois orquestradores no projeto.
- **Sugestão:** renomear/documentar a diferença entre os dois orquestradores.

### 10. `RegionTask` com `__slots__` manual
- **Onde:** `core/agents/types.py`.
- **Sugestão:** `@dataclass(slots=True)` é mais legível e mantém a otimização.

### 11. Deduplicação por fingerprint duplicada
- **Onde:** `core/agents/reader_agent.py` (3 pontos) e `core/agents/editor_agent.py`.
- **Problema:** mesma lógica de `content_fingerprint`/dedup espalhada.
- **Sugestão:** centralizar num helper para reduzir divergência futura.

### 12. `import traceback` dentro do `except`
- **Onde:** `core/agents/vision_agent.py`, `core/agents/data_agent.py`.
- **Sugestão:** subir o import para o topo do módulo.

### 13. `response.content.strip()` assume string
- **Onde:** `core/agents/vision_agent.py`, `core/agents/data_agent.py`.
- **Problema:** ao adotar `output_schema` (item 7), `content` passa a ser objeto Pydantic
  e o `.strip()` quebra.
- **Sugestão:** tratar o tipo ao introduzir saída estruturada.

---

## ✅ O que já está correto e aderente ao Agno 2.0
- Uso de `arun(input=..., images=[Image(content=bytes)])`.
- Leitura via `response.content`.
- `telemetry=False`.
- `Image(content=...)` para bytes.
- `extra_headers` (OpenRouter) e `options` (Ollama) no `ai_client` — ambos são campos
  válidos, verificados no código-fonte do Agno.

---

## ℹ️ Nota sobre o AgentOS
O **AgentOS não está no projeto** — decisão de arquitetura (Agno usado só no nível de
`agno.agent.Agent`; orquestração em Python puro). Não há `AgentOS(...).serve()` no código.
Para ver o painel do AgentOS (UI em os.agno.com apontando para um runtime FastAPI local),
seria um acréscimo novo e dependeria antes de refatorar para agentes reutilizáveis
(ver item 2), já que hoje não há instância de `Agent` de primeira classe para registrar.
