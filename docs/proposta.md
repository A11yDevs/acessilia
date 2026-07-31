# Proposta de Migração para Arquitetura Multiagentes com Agno

## 1. Contexto: Monolítico (`AgenteUnico`)

Anteriormente, o processamento principal estava centralizado no `AgenteUnico` (`core/agents/agente_unico.py`). Era uma classe de aproximadamente 650 linhas com excesso de responsabilidades. Ela cuidava de:

- Separar PDFs em páginas.
- Extrair e classificar regiões espaciais (tabelas, fórmulas, imagens, textos).
- Otimizar, recortar e aprimorar imagens para OCR.
- Fazer chamadas diretas às APIs de LLM.
- Tratar a deduplicação de strings e aplicar marcações de acessibilidade.
- Montar o documento de texto consolidado.

**Problema:** Esse acoplamento tornava a manutenção complexa e impedia a especialização dos agentes. Se a gente quisesse usar modelos diferentes para tarefas diferentes (por exemplo, um modelo mais leve para descrever imagens simples e um modelo mais robusto para tabelas), a alteração seria muito trabalhosa.

---

## 2. Nova Arquitetura: Orquestração em Python + Agentes Especialistas com Agno

A migração dividiu essa estrutura monolítica em componentes especializados. Após avaliar o ecossistema do Agno e comparar com arquiteturas de referência de projetos similares, foi definida a seguinte divisão de papéis:

```
                  Entrada do Documento (PDF/Imagem)
                                 │
                                 ▼
                     ┌───────────────────────┐
                     │      ReaderAgent      │ (Python Puro)
                     │  (Leitura/Estrutura)  │
                     └───────────┬───────────┘
                                 │
                                 ▼
              ┌─────────────────────────────────────┐
              │ Concorrência Assíncrona Nativa      │
              │                                     │
              │  ┌─────────────┐   ┌─────────────┐  │
              │  │ VisionAgent │   │  DataAgent  │  │ (Agentes Agno + LLM)
              │  │  (Imagens)  │   │  (Tabelas)  │  │
              │  └──────┬──────┘   └──────┬──────┘  │
              └─────────┼─────────────────┼─────────┘
                        │                 │
                        └────────┬────────┘
                                 │
                                 ▼
                     ┌───────────────────────┐
                     │      EditorAgent      │ (Python Puro)
                     │ (Consolidação/Tags)   │
                     └───────────┬───────────┘
                                 │
                                 ▼
                       Documento Acessível
```

---

## 3. Decisão Arquitetural: Orquestrador em Python Nativo vs. Agno Workflow

A principal decisão tomada durante o design foi manter a **orquestração do pipeline em Python Puro** (dentro do `AccessibilityOrchestrator`) em vez de envelopá-la na classe `Workflow` do Agno. As razões para essa escolha são técnicas e práticas:

1. **Paralelismo Nativo e Eficiente:** Acessília precisa descrever múltiplos elementos visuais de uma página ao mesmo tempo. Fazer isso em Python nativo usando `asyncio.gather` é direto e consome o mínimo de recursos. Utilizar as primitivas de paralelismo do Agno Workflow adicionaria uma camada desnecessária de abstração e complexidade.
2. **Componentes Determinísticos:** O `ReaderAgent` (que extrai blocos com bibliotecas matemáticas e estruturais) e o `EditorAgent` (que faz sanitização e deduplicação de strings) são processos puramente algorítmicos. Forçá-los a se comportarem como "Steps" de um framework de IA não traria nenhum benefício prático e geraria código redundante.
3. **Controle Total e Simplicidade:** Sem as restrições de ciclo de vida de um framework de workflow, o código permanece limpo, fácil de testar (usando ferramentas padrão como `pytest`) e o fluxo de dados entre os agentes é direto, eliminando wrappers e conversões de esquemas de dados.

---

## 4. O Uso do Agno no Nível de Agente

O Agno brilha exatamente onde a Inteligência Artificial é necessária. Os agentes **VisionAgent** e **DataAgent** foram encapsulados usando a classe `Agent` nativa do Agno:

```python
from agno.agent import Agent
from agno.media import Image
from core.models.ai_client import get_agno_model

agent = Agent(
    name="VisionAgent",
    model=get_agno_model(),
    telemetry=False,
)

response = await agent.arun(
    input=prompt,
    images=[Image(content=image_bytes)],
)
```

### Abordagem Multimodal Nativa
A classe `agno.media.Image` é utilizada para passar o conteúdo em bytes (`Image(content=image_bytes)`). O Agno se encarrega de ler e codificar esses bytes para o formato correto aceito pelas APIs subjacentes, garantindo compatibilidade entre diferentes provedores.

---

## 5. Divisão de Responsabilidades dos Agentes

Com a quebra do monolito, o sistema agora conta com quatro agentes com responsabilidades muito bem definidas:

| Agente | Tipo | Responsabilidade Principal |
|---|---|---|
| **ReaderAgent** | Python Puro | Divide o PDF em páginas individuais, roda a extração estrutural (via Docling ou PyMuPDF), classifica cada região e gera tarefas de processamento (`RegionTask`). |
| **VisionAgent** | Agno / IA | Recebe recortes de imagem comuns ou páginas inteiras escaneadas e gera audiodescrições detalhadas e acessíveis. |
| **DataAgent** | Agno / IA | Recebe recortes específicos de tabelas ou fórmulas complexas e gera sua representação textual estruturada (Markdown/LaTeX). |
| **EditorAgent** | Python Puro | Recebe os resultados dos outros agentes, aplica lógica de deduplicação temporal (fingerprints) e insere tags de acessibilidade no local correto do documento final. |

---

## 6. Centralização de Modelos (`ai_client.py`)

Para manter os agentes independentes da escolha do provedor de IA (Ollama local ou OpenRouter na nuvem), a inicialização dos modelos foi centralizada em `core/models/ai_client.py` com a função `get_agno_model()`:

*   **Para OpenRouter:** Cria uma instância do modelo `OpenRouter` do Agno, limpando o endpoint do sufixo de chat e injetando cabeçalhos HTTP adicionais para identificação da aplicação.
*   **Para Ollama:** Cria uma instância do modelo `Ollama` do Agno, ajustando a URL base da API para apontar diretamente para a porta do host executando o serviço localmente.

---

## 7. Organização de Arquivos e Ferramentas Compartilhadas

Para evitar duplicação de lógica (um erro comum no monolito antigo), o projeto agora está estruturado de forma modular. Toda a lógica auxiliar foi extraída para ferramentas em `core/tools/`:

```
core/
├── orchestrator.py             # Ponto de entrada original (instancia o orquestrador)
├── agents/
│   ├── reader_agent.py         # Extração e classificação estrutural (sem IA)
│   ├── vision_agent.py         # Descrições de imagem (Agno Agent)
│   ├── data_agent.py           # Processamento de tabelas/fórmulas (Agno Agent)
│   ├── editor_agent.py         # Formatação de tags e deduplicação (sem IA)
│   ├── team.py                 # Orquestrador assíncrono (AccessibilityOrchestrator)
│   └── types.py                # Definições de tipos comuns (RegionTask)
├── models/
│   └── ai_client.py            # Inicializador unificado dos modelos do Agno
├── prompts/                    # Arquivos markdown de prompts especializados
└── tools/                      # Ferramentas utilitárias (imagens, textos, PDF, OCR)
```

Esta arquitetura garante que a manutenção do sistema seja simples, os testes continuem passando de forma rápida, e a inclusão de novos tipos de processamento ou novos modelos de IA seja feita modificando apenas os agentes específicos.

---

## 8. Vantagens da Nova Estrutura com Agno

A adoção do Agno para gerenciar os agentes de IA traz benefícios muito claros para o Acessília:

- **Padronização Multimodal Simples (`agno.media.Image`):** Em vez de tratar a conversão, serialização e codificação de imagens em base64 manualmente para cada modelo de IA (o que gerava códigos extensos e repetitivos), basta passar `Image(content=image_bytes)`. O Agno se encarrega de empacotar e enviar no formato correto para qualquer provedor de visão.
- **Independência de Provedor (Ollama / OpenRouter):** Trocar do Ollama local para o OpenRouter na nuvem (ou qualquer outro modelo como OpenAI, Anthropic, Gemini) agora é uma questão de configuração. Os agentes consomem o modelo de forma transparente e unificada através da mesma interface do Agno.
- **Preparado para Crescer:** Se no futuro for necessário que os agentes usem ferramentas reais (como pesquisar um termo na internet com WebSearch, ou rodar código Python para decodificar um arquivo), o Agno permite acoplar ferramentas (Tools) diretamente nas instâncias de `Agent` de forma nativa e segura.
- **Organização Limpa do Código:** Ao isolar os prompts de instrução e as chamadas dos modelos dentro da estrutura de `Agent`, a poluição de requisições HTTP é removida do fluxo de execução principal do Acessília, deixando o projeto limpo e legível.
- **Gerenciamento Nativo de Retentativas e Parâmetros:** Parâmetros de controle de inferência (como `temperature`, `max_tokens`) e mecanismos de retentativas automáticas com recuo exponencial (`exponential_backoff`) são controlados diretamente no construtor do `Agent`/`Model` do Agno, eliminando a necessidade de escrever loops manuais de tratamento de falhas.
- **Saídas Estruturadas Garantidas (Pydantic/JSON):** O Agno possui suporte nativo para forçar o LLM a responder em formatos JSON estruturados (utilizando esquemas do Pydantic ou JSON Schema). Isso é perfeito para o `DataAgent` quando for necessário extrair tabelas ou dados em um formato estrito.
- **Memória e Histórico Prontos para Uso:** Se a aplicação evoluir para necessitar de memória ou histórico de conversas anteriores em processamentos de longo prazo, o Agno possui adaptadores de persistência de sessão (SQLite, PostgreSQL, etc.) integrados, sem necessidade de modelar tabelas adicionais.
- **Observabilidade e Tracing Facilitados:** O ecossistema do Agno se integra facilmente com ferramentas de monitoramento de LLM (como OpenInference, Arize Phoenix ou o painel do Agno), facilitando o acompanhamento de latência, custos e tokens consumidos.

---

## 9. Próximos Passos (Ideias futuras)

Com a arquitetura de multiagentes baseada no Agno consolidada, o Acessília está pronto para evoluir em direções estratégicas:

- **Limpeza do Repositório no GitHub:** Realizar uma revisão geral no repositório para remover documentações desatualizadas, diagramas de arquiteturas antigas e arquivos de testes obsoletos que não condizem mais com a nova estrutura modular de agentes.
- **Coleta e Monitoramento de Métricas:** Ativar a integração de telemetria do Agno com coletores OpenTelemetry/OpenInference. Isso permitirá monitorar o tempo de resposta de cada agente em tempo real, acompanhar a quantidade de tokens gerados e mensurar o custo por processamento de documento.
- **Uso de Saídas Estruturadas (Pydantic):** Evoluir o `DataAgent` para utilizar esquemas Pydantic para forçar respostas estruturadas do LLM em tarefas complexas. Isso será útil caso seja de interesse exportar tabelas detectadas diretamente para planilhas organizadas (`.xlsx`) ou alimentar bancos de dados relacionais.
- **Roteamento Inteligente de Modelos (Smart Routing):** Implementar um roteador dinâmico de modelos no orquestrador. Imagens simples com pouco texto podem ser enviadas para modelos locais mais leves rodando no Ollama (como LLaVA ou Qwen-VL), enquanto tabelas complexas e diagramas matemáticos podem ser direcionados para modelos mais potentes via OpenRouter (como Claude 3.5 Sonnet ou GPT-4o). Isso reduzirá drasticamente os custos operacionais e a latência de processamento.
- **Deduplicação Semântica com Embeddings:** Avaliar a viabilidade de substituir o hash MD5 (`content_fingerprint`) por busca de similaridade vetorial. Isso ajudaria a detectar elementos duplicados mesmo se mudarem levemente de tamanho ou pixels, embora seja necessário realizar testes práticos para medir se o custo extra de computação realmente compensa.
- **Agentes Especialistas Adicionais (Exploratório):** Desenvolver ideias para novos agentes especialistas, como um agente focado em OCR de textos manuscritos complexos ou um agente de Text-to-Speech (TTS) nativo para gerar a narração em áudio das páginas descritas de maneira automática.
- **Etapa de Aprovação Humana (Human-in-the-Loop):** Em processamentos de documentos muito extensos (onde a execução é naturalmente mais demorada), implementar um fluxo de aprovação. O sistema avisa o usuário (via notificação ativa, no estilo do Gemini Deep Search) quando terminar o processamento inicial para que um humano possa revisar, aprovar ou ajustar as audiodescrições sugeridas antes de exportar o arquivo final.
- **Knowledge Base e RAG de Normas:** Dependendo da decisão de implementar mais funções avançadas ou apenas manter o sistema simples, é possível acoplar bases de conhecimento (RAG) nos agentes do Agno contendo as diretrizes oficiais de acessibilidade (como o manual do WCAG). Isso ajudará a guiar os modelos a utilizarem termos e descrições técnicas padronizadas por lei.
- **Cache Refinado por Região/Elemento:** Evoluir o sistema de cache (que hoje atua por página inteira) para o nível de região individual (hashes visuais das imagens e tabelas recortadas). Isso evitaria gastar tokens reprocessando figuras idênticas se apenas o texto da página mudar.
- **Acessibilização Seletiva Inteligente (Processamento por Escopo):** Permitir que o usuário envie um documento massivo (como um livro completo ou a Bíblia) mas solicite a acessibilização de um escopo específico (ex: "apenas o capítulo X" ou "páginas 15 a 25"). O orquestrador identificaria automaticamente a estrutura/índice do documento e processaria apenas a fração solicitada, otimizando o tempo e custo da operação.
