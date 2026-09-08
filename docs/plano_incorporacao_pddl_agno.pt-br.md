# Plano de Incorporacao PDDL + Agno

## Objetivo
Incorporar, de forma incremental e validada, as mudancas arquiteturais documentadas em:
- MVP_CHANGES.md
- PMV_2_CHANGES.md
- PMV_2_1_CHANGES.md

Referencia remota: https://github.com/marceloakira/acessilia

## Estado Atual
- [x] Branch de trabalho criada: feat/arquitetura-pddl-agno
- [x] Remoto adicionado: marceloakira
- [x] Changelogs importados e commitados
- [x] Bloco 1 importado (artefatos estaticos)
- [x] Bloco 2 importado (manifesto estrutural)
- [x] Bloco 3 importado (planejamento PDDL)
- [x] Bloco 4 importado (execucao/Agno)
- [ ] Consolidacao e hardening

## Registro de Execucao
- Bloco 1:
	- arquivos importados: `docs/pmv_agno_pddl.md`, `schemas/*.json`, `core/planning/domains/domain_v2.2.pddl`;
	- validacao: schemas JSON validos; testes focados sem dependencia externa aprovaram (`16 passed`).
- Bloco 2:
	- arquivos importados: `core/manifest/*`, `core/agno_support.py`, `core/agents/informational_structural.py`, scripts de schema e teste dedicado;
	- validacao: compilacao sintatica Python aprovada para todos os arquivos importados;
	- limitacao de ambiente: teste dedicado depende de stack Python 3.10+ com pacotes nao instalados no ambiente corrente de execucao.
- Bloco 3:
	- arquivos importados: `core/planning/*`, `interfaces/cli/pmv.py`, `tests/test_pddl_planning.py`;
	- validacao: compilacao sintatica Python aprovada para todos os arquivos importados.
- Bloco 4:
	- arquivos importados: `core/execution/*`, `interfaces/cli/manifest.py`, `interfaces/cli/run.py`, `tests/test_agno_executor.py`;
	- validacao: compilacao sintatica Python aprovada para todos os arquivos importados;
	- regressao rapida do nucleo existente permanece aprovada (`16 passed`).

## Estrategia de Incorporacao
### Bloco 1 — Artefatos estaticos e documentacao
Escopo:
- docs/pmv_agno_pddl.md
- schemas/*.json
- core/planning/domains/domain_v2.2.pddl

Validacao:
- Testes existentes do projeto passam sem regressao
- Schemas sao JSON validos

### Bloco 2 — Manifesto estrutural (PMV 1)
Escopo:
- core/manifest/*
- scripts de geracao de schema relacionados ao manifesto
- testes focados em processing manifest

Validacao:
- Testes de manifesto passam
- Compatibilidade com pipeline atual preservada

### Bloco 3 — Planejamento PDDL (PMV 2)
Escopo:
- core/planning/* (processor, planner, schema)
- adapters/backends de planner (quando aplicavel)
- testes de planejamento

Validacao:
- Geracao e validacao de plano nominal
- Verificacao de fechamento causal

### Bloco 4 — Execucao com Agno e comparacao de backends (PMV 2.1)
Escopo:
- core/execution/*
- comparacao de plano (both)
- execution report e planning comparison schemas
- testes de workflow/executor

Validacao:
- Fluxo planner internal|fast-downward|both
- Vereditos de comparacao (identical/equivalent/different/inconclusive)

### Bloco 5 — Consolidacao
Escopo:
- Integracao com CLI atual e servicos
- Ajustes de dependencias e configuracoes
- limpeza tecnica e documentacao final

Validacao:
- Suite de testes alvo
- Checagem de riscos e impactos arquiteturais

## Regras de Seguranca na Migracao
- Preferir adicao incremental antes de substituicao de modulos atuais.
- Rodar validacoes ao final de cada bloco.
- Evitar alteracoes massivas sem checkpoint de commit intermediario.
