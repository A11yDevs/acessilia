# Plano completo de integração Acessilia–Toolbox

**Data da validação:** 2026-10-14  
**Alvo remoto:** `https://www.acessilia3.inf.ufg.br/toolbox`  
**Imagem observada:** `develop`, commit `c2e528ddf27a57603404cafe4725708035e782b9`

## Escopo confirmado

O problema de uma capacidade/cliente não ser acionado deve ser tratado como
modelagem do domínio ou compilação da instância `problem.pddl`, não como motivo
para descartar capacidades. As capacidades, clientes e algoritmos representam
desafios reais do Dr.DocBench e dos scripts que os resolvem.

O trabalho seguirá a trilha:

```text
evidência observada na página
  → obrigação concreta no manifesto
  → roots/dependências selecionadas
  → métodos admissíveis e disponíveis em problem.pddl
  → handler real (cliente Toolbox ou algoritmo docstruct)
  → validação do efeito, registro de evidência e replanejamento se necessário
```

Operações de documento (extração, OCR, layout, orientação, acessibilidade,
fórmula/química, código, texto, tabelas, música e fusão) devem ser acionáveis
quando a página fornecer evidência. Artefatos, cache e dataset são infraestrutura
ou ferramentas de benchmark: entram nos pré/pós-passos e nos testes, não como
obrigações artificiais em cada documento.

## Plano de implementação

### 1. Inventariar a matriz cliente–capacidade–método

- Para cada operação de documento, mapear: ID da capacidade, contrato/provider,
  client ou algoritmo local, sinal no manifesto, obrigação, métodos, handler,
  pós-condição validável e fixture Dr.DocBench.
- Comparar as capacidades do catálogo da Toolbox com `DEFAULT_METHOD_COSTS`,
  `V23_OBLIGATION_BY_KIND`, `DETERMINISTIC_METHOD_HANDLERS` e o conteúdo
  efetivamente compilado no problema PDDL.
- Manter os recursos de infraestrutura fora do grafo de obrigações de conteúdo,
  sem removê-los do catálogo nem dos scripts de benchmark.

### 2. Modelar os gatilhos no `problem.pddl`

- Preservar evidência por elemento/página e derivar obrigações somente quando um
  sinal real indicar trabalho: OCR requerido, rotação, imagem sem descrição,
  química, partitura, fórmula, bloco de código, fragmentação/ruído textual,
  divergência de providers, repetição, cauda, ordem ou estrutura tabular.
- Acrescentar tipos de obrigação e relações causais apenas quando os 11 kinds
  v2.3 existentes não expressem o trabalho; não criar obrigações só porque uma
  capacidade existe no catálogo.
- Garantir que `selected` contenha raízes e fechamento causal, e que cada par
  `admissible` / `available` / `supports` tenha custo e handler real.
- Tornar os traces testáveis: fixture → obrigação esperada → PDDL emitido →
  método planejado → resultado aplicado no manifesto.

### 3. Tornar os métodos Dr.DocBench executáveis

- Implementar os três métodos ainda explicitamente indisponíveis
  (`rescue-omitted`, `table-specialist`, `vlm-pairwise-judge`) usando as
  funções/agents Dr.DocBench já existentes ou os clientes Toolbox
  correspondentes. `single-provider` e `rep-guard` já têm handlers registrados;
  a guarda também altera o texto e registra quantos tokens removeu.
- `table-smart-fusion`, `skeleton-order` e `agreement-rule` têm handlers que
  decidem entre os dois providers lendo a extração secundária que o extrator
  guarda como artefato (`provider-extraction`, com sha256) em `FUSION_MODE=dual`.
  As regras são as do Dr.DocBench, calibradas para docling + mineru; outro par
  falha explicitamente. Quando o roteador por página (`agreement-rule`) escolhe o
  provider secundário, a decisão fica em `page_route` e a obrigação segue para
  `human-review`: a troca de página inteira não é aplicada automaticamente.
- Fazer o client da página OCR usar um contrato realmente publicado pela
  Toolbox ou completar o manifesto/provider correspondente; não manter um ID
  que falha apenas em runtime.
- Fazer o juiz de página/região usar o provider Dr.DocBench correspondente e
  configurar sua execução na Toolbox; a falta atual desses IDs/provedores no
  catálogo remoto é uma pendência de integração, não um motivo para excluí-los
  do PDDL.
- Acionar `image.page.orient` quando a inspeção/observação indicar orientação
  necessária e preservar a evidência da rotação; chamar `accessibility.mark`,
  química, código, pós-processamento textual e OMR nas obrigações compatíveis.
- Remover handlers que apenas validam o resultado anterior quando a operação
  requerida ainda não foi executada. O método só retorna sucesso se produzir
  ou validar um efeito observável, caso contrário deve falhar e permitir
  replanejamento/escalonamento explícito.

### 4. Alinhar os dois repositórios

- Core: `backend/core/manifest/builder.py`,
  `backend/core/planning/domains/domain_v2.3.pddl`,
  `domain_description_v2.3.md`, `backend/core/planning/pddl_processor.py`,
  `backend/agents/pddl_orchestrator.py`, `backend/tools/` e configuração.
- Toolbox (`/Users/akira/dados/sync/dev/acessilia-toolbox`): manifests de
  capacidades, providers/configuração e adaptadores para os contratos
  Dr.DocBench que não existem no catálogo atual.
- Preservar compatibilidade dos IDs e schemas, e atualizar o verificador de
  contrato/snapshot nos dois lados sempre que o catálogo evoluir.

### 5. Testes orientados aos desafios reais

- Unit tests: todos os sinais, obligations, dependências, custos, métodos
  indisponíveis, resultados validados e fallbacks/replanning.
- Integration tests: client → endpoint/provider da Toolbox → schema de saída
  → manifesto/efeito confirmado.
- E2E Dr.DocBench: páginas reais que exercitam OCR/VLM, orientação, tabela,
  fórmula/química, código, caudas/versos/números de linha, repetição, ordem e
  música. Assertar método escolhido e efeito final, não apenas HTTP 200.
- Reexecutar a suíte local e a suíte E2E completa contra a imagem publicada.
- Registrar artefatos enviados ao storage remoto; os testes atuais não os
  removem automaticamente.

### 6. Publicação

- Revisar as alterações locais já presentes em `feat/pddl-actionability`.
- Validar e publicar primeiro os contratos/providers da Toolbox necessários;
  publicar o core compatível depois.
- Implantar em homologação e executar novamente health, contrato live e todos
  os E2E Dr.DocBench antes de declarar o plano concluído.

## Estado comprovado até aqui

### Progresso recente (15/10/2026)

- O extrator do PDDL agora consulta o provider secundário quando
  `FUSION_MODE=dual`, mantém o manifesto primário e anexa evidências da fusão
  por página. A conversão `page_number` (1-based) ↔ índice interno (0-based)
  foi alinhada; a evidência agora encontra os elementos da página no builder.
- Um teste percorre extração simulada → builder → `problem.pddl` e confirma a
  emissão das facts de `fuse-providers` e `dual-provider-fusion`.
- As estatísticas agora são isoladas por página e deixam de ser acumuladas duas
  vezes. Os gatilhos de adjudicação/fusão usam divergência real de conteúdo
  (independente de ordem ou segmentação), portanto providers com conteúdo
  equivalente não geram essas obrigações artificiais.
- A guarda de repetição agora aplica o texto corrigido ao resultado fundido
  (antes registrava tokens cortados sem alterar o texto); erros não relacionados
  aos contratos da Toolbox não são mais convertidos silenciosamente em fallback.
- O método PDDL `rep-guard` foi registrado como handler real; remove ocorrências
  degeneradas do texto dos alvos e registra a quantidade removida. Sem alteração
  observável, falha e permite replanejamento/escalonamento.
- Suíte local atual (sem os testes marcados como E2E remoto): 1186 passaram,
  42 foram excluídos e 1 teve resultado `xpassed`.
- Os 42 E2E remotos não foram reexecutados após estas alterações. A verificação
  remota anterior só comprova a imagem então implantada, não este código local.
- A REST/OpenAPI da Toolbox está publicada em
  `https://www.acessilia3.inf.ufg.br/toolbox/v1/openapi.json` (Swagger UI:
  `/toolbox/v1/docs`): é uma interface genérica de execução por
  `capability_id`. O catálogo ao vivo tem 26 capacidades; `document.ocr.page`,
  `document.adjudicate.page` e `document.adjudicate.region` não existem (GET de
  detalhe retorna 404), então o OpenAPI genérico não supre esses contratos de
  capacidade/provider ausentes.

| Frente | Resultado |
|---|---|
| E2E remoto anterior a este progresso | 42 passed, 0 failed |
| Testes locais atuais (`not e2e`) | 1186 passed, 42 deselected, 1 xpassed |
| Truncamento tabular | corrigido com `DATA_AGENT_MAX_TOKENS=8192`; caso `004.pdf` e suíte E2E completa passaram anteriormente |
| PDDL/P1 | removido fallback silencioso; execução real e replanejamento limitado cobertos |
| PDDL/P2 | obrigações v2.3 cobertas; evidência dual por página agora percorre o extrator de produção até `problem.pddl` quando `FUSION_MODE=dual` |
| Métodos v2.3 | `rep-guard`, `single-provider`, `table-smart-fusion`, `skeleton-order` e `agreement-rule` têm handler; três ainda indisponíveis (`rescue-omitted`, `table-specialist`, `vlm-pairwise-judge`) |
| Availability gate | indisponibilidade excluída do PDDL e plano externo inválido rejeitado por teste |
| Contrato ao vivo atual | OpenAPI 3.1 genérica disponível; 26 capacidades; 3 IDs OCR/adjudicação consultados pelo core retornam 404 |
| Estado de publicação | alterações deste progresso permanecem locais no core; sem push/deploy nesta etapa |

## Critérios de encerramento

- [x] Todos os testes locais atuais (`not e2e`) passarem.
- [ ] E2E Dr.DocBench da build integrada atual passarem em homologação após deploy.
- [x] Causa do truncamento tabular corrigida e documentada.
- [x] Capacidades/caminhos atuais inventariados e divergências medidas contra homologação.
- [ ] Toda operação Dr.DocBench pertinente possuir gatilho por evidência, obrigação,
      método acionável e pós-condição validada.
- [ ] Nenhum método relevante permanecer indisponível por falta de handler ou
      por ausência de fatos no `problem.pddl`.
- [ ] Contratos Toolbox necessários para OCR de página e adjudicação serem
      publicados, ou substituídos por IDs/providers compatíveis.
- [ ] E2E Dr.DocBench expandido cobrir cada método relevante com páginas reais.
- [ ] Core e Toolbox compatíveis publicados e implantados; contrato live sem drift.
