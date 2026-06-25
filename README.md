# Bot Acess

Este repositório contém a aplicação **Bot Acess**, que pode ser executada como um bot do Telegram ou como um serviço FastAPI.

## Alterações recentes (branch code-quality-improvements)
- Atualização do PIL para usar `Image.Resampling.LANCZOS`.
- Conversão de objetos `Path` para `str` onde necessário.
- Verificações de `None` adicionadas antes de chamadas a `.strip` e `.split`.
- Correção da assinatura do middleware `PauseMiddleware`.
- Ajustes nos renderizadores `docx_renderer` e `pdf_renderer` para usar a API correta.
- Lint, type‑hints, remoção de código morto e testes com cobertura ≥ 90 %.
