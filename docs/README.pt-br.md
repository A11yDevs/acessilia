# Documentação do Projeto Acessilia

Você também pode ler esta documentação em **inglês**: [English](README.md)

## Propósito
Esta documentação detalha a arquitetura do **Acessilia**, um sistema de acessibilidade de documentos que combina **planejamento determinístico** (ordenação e validação de tarefas baseada em PDDL) com **IA multiagente coordenada por Agno** para tarefas de visão, dados e descrição. As funções determinísticas são a fonte de verdade; os LLMs fornecem interpretação e descrição.

O sistema opera com o motor de pipeline `pddl` (o fluxo manifest → plan → execution), selecionado pela opção `PIPELINE_ENGINE`, cujo padrão é `pddl`. O antigo motor `legacy` está desativado: `backend/service.py` aceita apenas `pddl` (o antigo alias `pmv` é normalizado para ele) e recusa qualquer outro valor; o código dele foi removido. Veja [architecture.pt-br.md](architecture.pt-br.md).

---

## Navegação

1. [Constituição Arquitetural](constitution.pt-br.md) — princípios inegociáveis e regras de qualidade, incluindo os princípios do ecossistema P1–P9 (seção 7), que dividem o trabalho entre o core, o SDK, a docstruct e a Toolbox. (Inglês: [English version](constitution.md))
2. [Especificação de Arquitetura](architecture.pt-br.md) — camadas, o motor de pipeline PDDL e o fluxo de processamento. (Inglês: [English version](architecture.md))
3. [Padrões de Design e Integração](patterns.pt-br.md) — padrões recorrentes e sua justificativa. (Inglês: [English version](patterns.md))
4. [Casos de Uso](use_cases.pt-br.md) — atores e operações visíveis ao usuário. (Inglês: [English version](use_cases.md))
5. [Endpoints e APIs](endpoints.pt-br.md) — a API REST, o painel web e o runtime AgentOS. (Inglês: [English version](endpoints.md))
6. [Suíte de Testes Automatizada](../tests/README.pt-br.md) — estratégia e cobertura de testes. (Inglês: [README](../tests/README.md))
7. [Execução com Docker](docker-compose.pt-br.md) — construções locais somadas às imagens prontas do GHCR (`main`, `main-slim`, `sha-<commit>`). (Inglês: [English guide](docker-compose.md))
8. [Ambiente de homologação (systemd timer)](homologacao-systemd.pt-br.md) — como as atualizações de homologação incorporam novas imagens do Docker automaticamente. (Inglês: [English guide](homologacao-systemd.md))
9. [Relatório de revisão técnica — PR #14](pr-14-review.pt-br.md) — achados classificados por severidade e uma lista de verificação de aceite para a mudança de pipeline PDDL/Agno. (Inglês: [English report](pr-14-review.md))
10. [Internacionalização (i18n)](i18n.pt-br.md) — o que é localizado, onde os arquivos de strings por locale ficam e guias passo a passo para adicionar strings, internacionalizar um arquivo e adicionar um novo locale. (English: [English guide](i18n.md))
11. [Harness de benchmark](bench.pt-br.md) — roda e pontua o core no Dr.DocBench (e em outros datasets) com `python -m scripts.bench`. (English: [English guide](bench.md))
12. [Benchmark Dr.DocBench](drbench.pt-br.md) — benchmark de provedores de extração de estrutura (Docling vs MinerU), métricas e resultados. (English: [English guide](drbench.md))
13. [Integração de ferramentas da Toolbox](toolbox_integration.pt-br.md) — como integrar ao core uma ferramenta nova da Toolbox: contrato HTTP, bibliotecas vs. capacidades da Toolbox e os dois cenários de integração. (English: [English guide](toolbox_integration.md))
14. [Registros de Decisão Arquitetural](adr/README.pt-br.md) — decisões que atravessam componentes (responsabilidades, execução remota, contratos, referências de artefatos, disponibilidade) e como propor uma nova. (English: [English version](adr/README.md))
15. [Auditoria de arquitetura, outubro de 2026](architecture/audit-2026-10.pt-br.md) — o que ainda está implementado duas vezes entre os componentes, as dependências operacionais restantes, as proteções arquiteturais e as métricas iniciais, com dono e destino para cada achado. (English: [English version](architecture/audit-2026-10.md))

---

## Arquitetura PDDL + Agno

O pipeline baseado em planejamento e sua incorporação são documentados separadamente:

1. [PMV — Agno, manifest, PDDL e execução nominal](pmv_agno_pddl.pt-br.md) — o ciclo mínimo `documento → manifest → plano PDDL → relatório de execução → documento canônico` e como o Agno coordena as ferramentas determinísticas. (English: [English version](pmv_agno_pddl.md))
2. [Plano de incorporação PDDL + Agno](plano_incorporacao_pddl_agno.pt-br.md) — o plano bloco a bloco usado para trazer a camada de planejamento ao código-base. (English: [English plan](plano_incorporacao_pddl_agno.md))
3. [Algoritmos de docstruct](docstruct_algorithms.pt-br.md) — como funcionam os algoritmos determinísticos (fusão multi-provider / Tree Differ, auditoria canônica, classificação de regiões, re-inferência) e como os agentes os invocam. (English: [English version](docstruct_algorithms.md))
4. [Ordem de leitura por XY-cut em páginas multicoluna](reading_order_xycut.pt-br.md) — etapa opcional da fusão que corrige a ordem de leitura em páginas multicoluna: o problema, os portões, como ligar, o experimento em lote pequeno no Dr.DocBench e as limitações. (English: [English version](reading_order_xycut.md))
---

## Diagramas UML (PlantUML)

Cada diagrama é um auxílio visual; a descrição vinculada resume seu conteúdo em texto.

1. **Arquitetura:** [architecture/architecture.puml](architecture/architecture.puml) — componentes do motor PDDL, os frontends e os serviços de Toolbox e IA que eles chamam.
2. **Sequência de Processamento:** [sequence/document_processing_sequence.puml](sequence/document_processing_sequence.puml) — fluxo passo a passo de uma conversão de documento: extração do manifesto na Toolbox, planejamento, execução do plano e exportação.
3. **Máquina de Estados da Tarefa:** [state_machine/task_state_machine.puml](state_machine/task_state_machine.puml) — ciclo de vida de uma tarefa de processamento (processando, concluída, erro, cancelada).
4. **Casos de Uso:** [use_cases/use_cases.puml](use_cases/use_cases.puml) — atores e as principais operações visíveis ao usuário.

---

## Escopo Abrangido

- **`backend/`** — Lógica de negócio agnóstica da interface.
  - `core/` — a camada de planejamento: `manifest/` (extração Informacional-Estrutural pela Toolbox → `processing-manifest.json`), `planning/` (PlannerAgent → problema PDDL e `nominal-plan.json`), `execution/` (Executor via Agno Workflow → `execution-report.json`).
  - `agents/` — o orquestrador PDDL e os agentes que ele usa (`VisionAgent`, `DataAgent`).
  - `api/` — a API REST standalone (jobs, download, history, health).
  - `pipeline/` + `export/` — construção, validação e renderizadores de formato do documento canônico.
  - `ai/`, `services/`, `tools/` — registro de modelos Agno e prompts, serviços de infraestrutura (cache, queue, history, cleanup, email, tokens) e utilidades compartilhadas.
- **`frontend/`** — Clientes da API: bot do Telegram (`frontend/telegram/`), painel web (`frontend/web/`), CLI (`frontend/cli/`), o cliente compartilhado `frontend/clients/api_client.py` e o runtime AgentOS (`frontend/agent_os.py`).
- **`infra/`** — Dockerfile e configurações do Docker Compose.
- **`tests/`** — Suíte de testes unitário e de integração (`pytest`).

---

## Matriz de Rastreabilidade

- **Casos de Uso para Implementação:** [use_cases.pt-br.md](use_cases.pt-br.md)
- **Padrões de Design e Evolução:** [patterns.pt-br.md](patterns.pt-br.md)
- **Estratégia e Cobertura de Testes:** [../tests/README.pt-br.md](../tests/README.pt-br.md)
