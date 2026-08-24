---
name: main
description: Agente principal de desenvolvimento do Acessilia (pipeline de acessibilizacao de documentos). Use para implementar features, corrigir bugs, rodar testes e scripts de benchmark neste repositorio.
argument-hint: Uma tarefa a implementar ou uma pergunta sobre o pipeline (extracao, agentes, exportacao, PDDL).
# tools: ['vscode', 'execute', 'read', 'agent', 'edit', 'search', 'web', 'todo'] # specify the tools this agent can use. If not set, all enabled tools are allowed.
---

Voce trabalha no **Acessilia**, um pipeline Python (Poetry, Python 3.11) que converte
documentos (PDF, imagens, DOCX) em conteudo acessivel (HTML, DOCX, PDF/UA, TXT),
para pessoas com deficiencia visual.

## Ambiente de execucao
- **Maquina alvo tem GPU (CUDA).** Docling/PyTorch (CodeFormula, RapidOCR) usam
  `AcceleratorOptions` com deteccao automatica de dispositivo (`AUTO`); nao assuma
  CPU-only ao estimar tempo de inferencia ou ao definir `max_new_tokens` /
  batch size — os limites conservadores adicionados durante benchmarks em CPU
  (ex.: `max_new_tokens=512` em `backend/tools/formula_tools.py`) podem ser
  relaxados quando há GPU disponivel.
- Ambiente Python: Poetry (`poetry install --with dev --extras docling`).
  Se `poetry`/`python` nao estiverem no PATH, procure o virtualenv em
  `~/Library/Caches/pypoetry/virtualenvs/` (ou equivalente Linux) e invoque o
  interpretador diretamente.
- Testes: `poetry run pytest` (ou `pytest -m "not docling"` para pular testes
  que exigem os modelos pesados do Docling). CI exige o check
  `CI / tests (Python 3.11)` antes do merge em `main` (branch protegida).

## Arquitetura (visao rapida)
- `backend/agents/`: `reader_agent` (classifica regioes de pagina),
  `vision_agent` (descricao de imagens), `data_agent` (tabelas/formulas),
  `editor_agent` (consolida texto), `orchestrator`/`pddl_orchestrator`
  (pipeline legado vs. planejamento PDDL).
- `backend/tools/formula_tools.py`: cascata local (OCR + CodeFormula) para
  extrair LaTeX de imagens sem LLM, alem de LaTeX→MathML e verbalizacao pt-BR.
- `backend/pipeline/`: `structure_parser` (texto→blocos), `canonical_builder`
  (documento acessivel canonico), `pandoc_ast_builder`/`validators`.
- `backend/export/renderers/`: HTML, DOCX, PDF, PDF/UA (Pandoc), TXT.
- `schemas/`: JSON Schemas do documento canonico e do manifesto PDDL.

## Regras de trabalho
- Prefira editar codigo existente a criar abstracoes novas; siga os padroes
  ja usados nos agentes (fallback gracioso com `try/except` + log, nunca
  lancar excecao para o chamador do pipeline).
- Ao alterar o pipeline de formulas, rode os benchmarks em `scripts/` para
  validar antes/depois (nao sao testes automatizados, sao ferramentas de
  diagnostico manual).
- Nao crie arquivos de documentacao markdown a menos que solicitado.