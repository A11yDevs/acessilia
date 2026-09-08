# Documentação do Projeto Acessilia

Você também pode ler esta documentação em **inglês**: [English](README.md)

## Propósito
Esta documentação detalha a arquitetura do **Acessilia**, um sistema de acessibilidade de documentos que combina **planejamento determinístico** (ordenação e validação de tarefas baseada em PDDL) com **IA multiagente coordenada por Agno** para tarefas de visão, dados e descrição. As funções determinísticas são a fonte de verdade; os LLMs fornecem interpretação e descrição.

O sistema opera em um de dois motores de pipeline, selecionado pela opção `PIPELINE_ENGINE`: `legacy` (o pipeline orquestrado direto, padrão) ou `pddl` (o fluxo manifest → plan → execution). Veja [architecture.pt-br.md](architecture.pt-br.md).

---

## Navegação

1. [Constituição Arquitetural](constitution.pt-br.md) — princípios inegociáveis e regras de qualidade. (Inglês: [English version](constitution.md))
2. [Especificação de Arquitetura](architecture.pt-br.md) — camadas, os dois motores de pipeline e o fluxo de processamento. (Inglês: [English version](architecture.md))
3. [Padrões de Design e Integração](patterns.pt-br.md) — padrões recorrentes e sua justificativa. (Inglês: [English version](patterns.md))
4. [Casos de Uso](use_cases.pt-br.md) — atores e operações visíveis ao usuário. (Inglês: [English version](use_cases.md))
5. [Endpoints e APIs](endpoints.pt-br.md) — a API REST, o painel web e o runtime AgentOS. (Inglês: [English version](endpoints.md))
6. [Suíte de Testes Automatizada](../tests/README.pt-br.md) — estratégia e cobertura de testes. (Inglês: [README](../tests/README.md))
7. [Execução com Docker](docker-compose.pt-br.md) — construções locais somadas às imagens prontas do GHCR (`main`, `main-slim`, `sha-<commit>`). (Inglês: [English guide](docker-compose.md))
8. [Ambiente de homologação (systemd timer)](homologacao-systemd.pt-br.md) — como as atualizações de homologação incorporam novas imagens do Docker automaticamente. (Inglês: [English guide](homologacao-systemd.md))
9. [Relatório de revisão técnica — PR #14](pr-14-review.pt-br.md) — achados classificados por severidade e uma lista de verificação de aceite para a mudança de pipeline PDDL/Agno. (Inglês: [English report](pr-14-review.md))
10. [Internacionalização (i18n)](i18n.pt-br.md) — o que é localizado, onde os arquivos de strings por locale ficam e guias passo a passo para adicionar strings, internacionalizar um arquivo e adicionar um novo locale. (English: [English guide](i18n.md))

---

## Arquitetura PDDL + Agno

O pipeline baseado em planejamento e sua incorporação são documentados separadamente:

1. [PMV — Agno, manifest, PDDL e execução nominal](pmv_agno_pddl.pt-br.md) — o ciclo mínimo `documento → manifest → plano PDDL → relatório de execução → documento canônico` e como o Agno coordena as ferramentas determinísticas. (English: [English version](pmv_agno_pddl.md))
2. [Plano de incorporação PDDL + Agno](plano_incorporacao_pddl_agno.pt-br.md) — o plano bloco a bloco usado para trazer a camada de planejamento ao código-base. (English: [English plan](plano_incorporacao_pddl_agno.md))

---

## Diagramas UML (PlantUML)

Cada diagrama é um auxílio visual; a descrição vinculada resume seu conteúdo em texto.

1. **Arquitetura e Pipeline Multiagente:** [architecture/architecture.puml](architecture/architecture.puml) — estrutura de componentes e pacotes do pipeline do backend/frontend.
2. **Sequência de Processamento:** [sequence/document_processing_sequence.puml](sequence/document_processing_sequence.puml) — fluxo passo a passo de uma conversão de documento, incluindo os agentes de visão/dados paralelos.
3. **Máquina de Estados da Tarefa:** [state_machine/task_state_machine.puml](state_machine/task_state_machine.puml) — ciclo de vida de uma tarefa de processamento (processando, concluída, erro, cancelada).
4. **Casos de Uso:** [use_cases/use_cases.puml](use_cases/use_cases.puml) — atores e as principais operações visíveis ao usuário.

---

## Escopo Abrangido

- **`backend/`** — Lógica de negócio agnóstica da interface.
  - `core/` — a camada de planejamento: `manifest/` (extração Estrutural-Informational via Docling/PyMuPDF → `processing-manifest.json`), `planning/` (PlannerAgent → problema PDDL e `nominal-plan.json`), `execution/` (Executor via Agno Workflow → `execution-report.json`).
  - `agents/` — os agentes do pipeline (`ReaderAgent`, `VisionAgent`, `DataAgent`, `EditorAgent`) e os orquestradores legacy e PDDL.
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
