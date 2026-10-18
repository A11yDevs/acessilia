# Constituição Arquitetural

Também disponível em **inglês (EUA)**: [English version](constitution.md)

- **Versão:** 2.0.0 (2026-10-18). Veja o [histórico de alterações](#9-histórico-de-alterações).

## 1. Propósito
Entregar a conversão de documentos e imagens para formatos acessíveis por meio de:
- **Extração e planejamento determinísticos** (ordenação e validação de tarefas baseada em PDDL)
- **Processamento de IA multiagente** (agentes especializados coordenados pelo Agno para visão, dados e descrições)
- Descrições de alta qualidade em inglês (EUA) ou português brasileiro (determinadas pelo locale do usuário)
- Simples experiência de usuário baseada no Telegram, com degradação progressiva em falhas de IA

## 2. Princípios inegociáveis
1. Alinhamento ao código-fonte: cada regra desta constituição deve ser rastreável até módulos reais.
2. Acessibilidade em primeiro lugar: todas as saídas devem suportar leitores de tela e estrutura semântica.
3. Tolerância a falhas: o sistema deve se degradar graciosamente com fallback textual quando a IA falha. A degradação é uma decisão de negócio visível e documentada. Uma capacidade operacional nunca cai silenciosamente para outra implementação (princípios P4 e P6).
4. Operação configurável: o comportamento deve ser dirigido por variáveis de ambiente e pastas locais. A configuração escolhe onde as capacidades rodam (por exemplo, o endpoint da Toolbox); ela não implica execução local (P4).
5. Extração determinística primeiro: PDFs com base textual devem preferir extração determinística antes de invocar IA. A extração determinística roda como capacidade da Toolbox ou como algoritmo da docstruct, e não como executor operacional local no core (P4).
6. Determinismo e inteligência híbridos: o sistema combina planejamento determinístico (processamento PDDL, geração do manifesto) com execução dirigida por IA para garantir confiabilidade e flexibilidade. Funções determinísticas são a fonte de verdade; LLMs fornecem interpretação e descrição.
7. Validação com container em primeiro lugar: a suíte de testes deve passar no container Docker (ambiente equivalente ao de produção) antes do merge. Testes no ambiente nativo são secundários e específicos de ambiente.
8. **Documentação com prioridade ao inglês e português brasileiro como língua oficial secundária**: todo o código-fonte (identificadores, comentários, docstrings, mensagens de log), documentação Markdown, issues, pull requests e mensagens de commit devem ser escritos em inglês — a língua obrigatória e autoritativa. O português brasileiro é a língua oficial secundária: desejável para toda a documentação, e todo espelho `*.pt-br.md` deve ser atualizado no mesmo PR sempre que sua fonte em inglês mudar. Em caso de divergência, a versão em inglês é autoritativa. Tradução e suporte a outras línguas é um objetivo secundário importante (internacionalização/i18n), voltado a uma audiência-alvo ampla e inclusiva; conteúdo localizado em outras línguas é bem-vindo, mas nunca bloqueia um merge. Conteúdo voltado ao usuário (mensagens do Telegram, saída renderizada, prompts para os modelos de IA) deve ser localizado conforme o locale do usuário — incluindo inglês e português brasileiro, e estendido a outras línguas conforme o esforço de i18n avança. Materiais educacionais são um domínio prioritário para a internacionalização: devem ser produzidos na língua da audiência sempre que possível, com inglês e português brasileiro como as línguas primárias suportadas.

## 3. Regras de qualidade arquitetural
1. Separação de camadas (atualizada para a arquitetura PDDL + multiagente Agno):

   a. **Camada de interface:**
      - Handlers e middlewares do Telegram
      - Endpoints de CLI (comandos manifest, plan, run, benchmark)
      - Rotas web FastAPI

   b. **Camada de orquestração:**
      - `core/execution/` – agente executor; aplica planos PDDL com Agno Workflow
      - `core/planning/` – PlannerAgent; gera problemas PDDL e valida planos
      - `core/manifest/` – InformationalStructuralAgent; extrai o manifesto de processamento

   c. **Camada de agentes (multiagente Agno):**
      - ReaderAgent (Python) – extração estrutural por meio de capacidades da Toolbox (Docling, MinerU…); o uso restante de PyMuPDF no próprio processo é um desvio registrado ([ADR-0003](adr/0003-remote-only-operational-capabilities.pt-br.md))
      - VisionAgent (Agno) – descrições de imagens
      - DataAgent (Agno) – representação textual de tabelas e fórmulas
      - EditorAgent (Python) – deduplicação e marcação de acessibilidade

   d. **Pipeline canônico:**
      - `pipeline/` – construção e validação do documento canônico
      - `export/filters` – filtros de AST do Pandoc para acessibilidade (transformações puras da docstruct; o Pandoc em si roda na Toolbox)
      - `export/renderers` – renderização determinística das saídas
      - `schemas/` – schemas JSON/PDDL de manifesto, plano e relatório de execução

   e. **Persistência e suporte:**
      - `services/` – cache, fila, histórico, limpeza
      - `ai/` – registro de modelos Agno e templates de prompt
2. Configuração centralizada em [backend/config/settings.py](../backend/config/settings.py).
3. Toda operação potencialmente demorada deve ser assíncrona no runtime do bot.
4. As validações de arquivo devem acontecer antes do pipeline de IA.
5. A persistência de histórico deve registrar o início e o fim da conversão.
6. O documento canônico é a fonte de verdade de todo formato exportado.
7. Estratégia de testes:
   - Validação primária: pytest dentro do container Docker (equivalente ao de produção)
   - Validação secundária: ambiente nativo (apenas checagem de sintaxe Python)
   - Todos os testes devem passar no container antes do merge (requisito de gate)
   - Os testes de regressão dos agentes existentes devem manter ou superar a cobertura atual

## 4. Contratos de domínio
1. Ciclo de vida do processamento de documentos (estendido para a fase de planejamento):
   - **Fase de extração:** documento → ReaderAgent → processing-manifest.json
   - **Fase de planejamento:** manifesto + restrições de domínio → PlannerAgent → nominal-plan.json
   - **Fase de execução:** plano + manifesto → executor (Agno Workflow) → execution-report.json
   - **Geração canônica:** resultados da execução → documento canônico (acessível)
   - **Fase de exportação:** documento canônico → renderizadores e adaptadores de exportação → artefatos de saída (txt/docx/pdf/pdf_ua/html/mp3), empacotados num zip
2. Contratos de manifesto de processamento e de plano:
   - O manifesto de processamento (1.1+) define regiões, tipos e obrigações de processamento
   - O domínio PDDL (v2.2+) codifica dependências e restrições de ordem entre tarefas
   - O plano é saída determinística do planejador (backend interno ou fast-downward)
   - O relatório de execução valida a aderência ao plano e registra o resultado das tarefas
3. O modo de processamento muda o comportamento dos prompts e da verbosidade. Os valores aceitos são `detalhado`, `medio` (com `normal` como alias), `baixo` e `ocr`; um valor desconhecido cai para `medio`. Eles correspondem aos prompts em `backend/ai/prompts` e aos perfis de verbosidade em `backend/pipeline/verbosity_manager.py`.
4. A extração é híbrida: extração de texto determinística primeiro, depois visão por IA para páginas escaneadas ou sem texto e para entradas de imagem (veja o princípio 2.5).
5. Os caches de página e de arquivo são otimizações, não fonte de verdade.
6. Os renderizadores só devem consumir dados canônicos validados.
7. Invariantes do planejador:
   - A geração do problema PDDL é determinística (sem envolvimento de LLM)
   - A validação do plano deve ter sucesso antes da execução
   - O modo de fallback (apenas extração determinística) é acionado em falha do planejador

## 5. Resiliência e segurança operacional
1. Retry de rede para canais externos (Telegram/OpenRouter/Ollama).
2. Lock de processo em [frontend/run.py](../frontend/run.py) para impedir várias instâncias no mesmo host.
3. Limpeza periódica de arquivos temporários para evitar crescimento descontrolado do disco.
4. Desligamento consistente, com atualização do status das tarefas e do histórico.
5. Resiliência do planejamento PDDL:
   - Timeout do planejador: TTL configurável para a geração do plano; fallback para execução sem plano se excedido
   - Problema inválido: se a geração manifesto → PDDL falhar, registrar o erro e pular a fase de planejamento; executar de forma determinística
   - Queda do planejador: se o planejador externo (fast-downward) falhar, trocar para o backend de planejamento interno
6. Indisponibilidade da Toolbox: a disponibilidade vem de réplicas da Toolbox atrás de um balanceador, com retries limitados no SDK para chamadas idempotentes ([ADR-0006](adr/0006-availability-and-failover.pt-br.md)). Quando uma capacidade continua indisponível, a etapa falha ou se degrada de forma visível, e a causa é registrada no job; não há fallback local.

## 6. Evolução arquitetural
1. Mudanças no pipeline devem atualizar os diagramas em docs/sequence e docs/state_machine, além dos documentos de visão geral da arquitetura.
2. Adicionar um novo agente Agno ou backend de planejamento exige:
   - Classe do agente em `core/agents/` ou `core/execution/`/`core/planning/`
   - Configuração em `config/settings.py` (seletor de modelo, timeouts)
   - Implementação do agente consumindo a classe base `agno.Agent`
   - Definições de ferramentas (para funções determinísticas como a extração do manifesto)
   - Arquivo de teste dedicado validando entradas, saídas e comportamento de fallback do agente
   - Atualizações em [architecture.pt-br.md](architecture.pt-br.md) e [patterns.pt-br.md](patterns.pt-br.md), e nos diagramas de sequência relevantes
   - Ao adicionar artefatos PDDL (novo domínio, novo planejador): atualizar `schemas/` e `core/planning/domains/`, além de `docs/pmv_agno_pddl.md`
3. Mudanças de PDDL/planejamento (schemas, domínio, backend do planejador):
   - Atualizações de domínio: modificar `core/planning/domains/domain_vX.Y.pddl` e incrementar a versão
   - Mudanças de schema: atualizar `schemas/processing_manifest.schema.json`, `schemas/nominal_plan.schema.json`, `schemas/execution_report.schema.json`
   - Backend do planejador: registrar em `core/planning/models.py` (enum PlannerBackend)
   - Validação: rodar `pytest tests/test_pddl_planning.py` (geração do plano) e `pytest tests/test_agno_executor.py` (execução)
   - Documentação: atualizar `docs/pmv_agno_pddl.md` com novos exemplos
4. Mudar o schema canônico ou os renderizadores exige atualizações em [README.pt-br.md](../README.pt-br.md), [architecture.pt-br.md](architecture.pt-br.md), [tests/README.pt-br.md](../tests/README.pt-br.md) e nos diagramas PlantUML.
5. Regressão de acessibilidade é tratada como defeito crítico.
6. Adicionar uma capacidade ou provider da Toolbox segue a seção 4 de [toolbox_integration.pt-br.md](toolbox_integration.pt-br.md), e decide onde cada parte do código fica com o guia do [ADR-0002](adr/0002-component-responsibilities.pt-br.md#decisão).
7. Uma decisão que muda responsabilidades ou dependências entre o core, o SDK, a docstruct e a Toolbox, que muda um contrato público, ou que abre uma exceção à seção 7, é registrada como ADR em [docs/adr/](adr/README.pt-br.md) antes da mudança ou junto com ela.

## 7. Princípios arquiteturais do ecossistema

Estes princípios regem como os quatro componentes do ecossistema dividem o
trabalho: o core (`backend/`), o SDK (`libs/sdk`), a docstruct
(`libs/docstruct`) e a [Acessilia Toolbox](https://github.com/A11yDevs/acessilia-toolbox).
Cada um aponta para o ADR que o detalha e diz como a conformidade é verificada.
Uma exceção exige um ADR com justificativa, escopo, responsável e critério de
saída ([processo de ADR](adr/README.pt-br.md#processo)), revisado pelos donos
dos componentes afetados.

**Em uma frase:** o core decide e orquestra; o SDK fornece interfaces e acesso;
a docstruct implementa algoritmos estruturais reutilizáveis; a Toolbox executa
capacidades operacionais.

1. **P1 — Um dono por funcionalidade.**
   - **Regra:** cada funcionalidade tem um único dono arquitetural e uma
     implementação de referência. Interfaces Python, REST e MCP podem expor a
     mesma implementação; os componentes reutilizam bibliotecas compartilhadas
     em vez de copiar código.
   - **Detalhe:** [ADR-0002](adr/0002-component-responsibilities.pt-br.md).
   - **Verificado por:** revisão e o inventário de duplicações da #152.
2. **P2 — Separação de responsabilidades.**
   - **Regra:** o core reúne agentes, planejamento, estratégias, políticas e
     fluxos. O SDK reúne contratos, clientes, adaptadores, referências de
     artefatos e acesso a bibliotecas reutilizáveis, sem dependências pesadas
     obrigatórias. A docstruct reúne algoritmos estruturais determinísticos e
     independentes de infraestrutura. A Toolbox reúne providers, conversão,
     renderização, OCR, validação, artefatos, jobs, sidecars e interfaces
     REST/MCP.
   - **Detalhe:** [ADR-0002](adr/0002-component-responsibilities.pt-br.md).
   - **Verificado por:** revisão, com o guia "onde fica o código novo?".
3. **P3 — Dependências direcionais.**
   - **Regra:** core → SDK, docstruct; SDK → docstruct e o contrato publicado da
     Toolbox; Toolbox → docstruct; docstruct → nada do ecossistema. Sem
     dependências circulares e sem dependência dos detalhes internos de outro
     componente.
   - **Detalhe:** [ADR-0002](adr/0002-component-responsibilities.pt-br.md).
   - **Verificado por:** `tests/test_architecture_layers.py`,
     `libs/docstruct/tests/test_purity.py` e `libs/sdk/tests/test_purity.py`.
4. **P4 — Core leve, execução remota.**
   - **Regra:** operações que exigem dependências pesadas ou infraestrutura
     especializada rodam na Toolbox. A política de produção é `remote_only`. O
     core não acrescenta fallbacks locais nem instala dependência pesada só
     para oferecer um.
   - **Detalhe:** [ADR-0003](adr/0003-remote-only-operational-capabilities.pt-br.md).
   - **Verificado por:** revisão e testes arquiteturais previstos que proíbem
     imports pesados e subprocessos de ferramentas no core, com uma allowlist
     que só pode diminuir.
5. **P5 — Processamento orientado a referências.**
   - **Regra:** artefatos persistidos são processados onde estão armazenados e
     trafegam como referências `ArtifactRef` tipadas e opacas. A materialização
     é explícita e verificada; as referências são imutáveis e têm escopo.
   - **Detalhe:** [ADR-0005](adr/0005-artifact-references.pt-br.md).
   - **Verificado por:** testes do SDK (`libs/sdk/tests/test_failover.py`) e
     testes de contrato quando a Toolbox publicar `artifact-ref@1`.
6. **P6 — Confiabilidade sem duplicação operacional.**
   - **Regra:** a disponibilidade vem de infraestrutura redundante (réplicas
     atrás de um balanceador, compartilhando o armazenamento), timeouts,
     retries limitados e tratamento explícito de falhas, e não de executores
     duplicados no core. Não há fallbacks silenciosos.
   - **Detalhe:** [ADR-0006](adr/0006-availability-and-failover.pt-br.md).
   - **Verificado por:** testes de failover do SDK e um teste ponta a ponta com
     réplicas, previsto.
7. **P7 — Uma fonte de verdade por contrato.**
   - **Regra:** a docstruct é dona dos modelos e schemas documentais canônicos.
     A Toolbox é dona dos contratos operacionais da API (`ArtifactRef`, jobs,
     capacidades). O SDK consome os contratos da Toolbox, de preferência
     gerados. O core usa os contratos públicos sem redefini-los.
   - **Detalhe:** [ADR-0004](adr/0004-single-source-of-truth-for-contracts.pt-br.md).
   - **Verificado por:** `scripts/check_capability_contract.py`.
8. **P8 — Evolução incremental.**
   - **Regra:** refatorações são pequenas e verificáveis. Extrair e reutilizar
     código antes de substituí-lo. Não misturar mudanças arquiteturais e
     comportamentais num mesmo pull request. Novas capacidades mantêm
     algoritmos, políticas e execução separados.
   - **Verificado por:** revisão e os testes de regressão, contrato e
     integração exigidos pela seção 3.7.
9. **P9 — Rastreabilidade e compatibilidade de contratos.**
   - **Regra:** contratos públicos são versionados e testados. Transformações
     documentais preservam proveniência. Os resultados identificam as versões
     relevantes de algoritmos, providers e parâmetros. Mudanças estruturais
     preservam compatibilidade ou declaram sua migração.
   - **Detalhe:** constituição da Toolbox, princípios 9 e 12.
   - **Verificado por:** as versões exatas de contrato no SDK
     (`TOOLBOX_CAPABILITIES`) e `scripts/check_capability_contract.py`.

## 8. Documentos relacionados

- [Registros de Decisão Arquitetural](adr/README.pt-br.md)
- [Bibliotecas (`libs/`)](../libs/README.pt-br.md)
- [Integração com a Toolbox](toolbox_integration.pt-br.md)
- [Constituição da Acessilia Toolbox](https://github.com/A11yDevs/acessilia-toolbox/blob/main/docs/constitution.md)

## 9. Histórico de alterações

- **2.0.0 (2026-10-18):** acrescentados os princípios arquiteturais do
  ecossistema P1–P9 (seção 7) e os ADRs que os detalham
  ([#152](https://github.com/A11yDevs/acessilia/issues/152)). Alinhados à
  execução remota os princípios 2.3–2.5, as descrições do ReaderAgent e dos
  filtros em 3.1, o contrato 4.4, a resiliência 5.6 e a evolução 6.6–6.7. O
  número de versão e este histórico começam aqui. O espelho em português
  brasileiro passa a cobrir o documento inteiro.
- **1.x:** revisões anteriores, sem versão; veja o histórico git deste arquivo.
