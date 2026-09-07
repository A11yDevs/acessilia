# Registro de bugs e testes — Acessilia

Registro de bugs levantados durante a auditoria.
Para reportar um bug novo, copie o [`BUG_TEMPLATE.md`](BUG_TEMPLATE.md) para `NNNN-slug.md`.

Base verificada: [release/0.1.0](https://github.com/A11yDevs/acessilia/tree/release/0.1.0), commit [`7a5e70f`](https://github.com/A11yDevs/acessilia/commit/7a5e70f4809dd4bae29cfb772042d12784fc48b6), em **2026-09-06**. A referência remota foi consultada no GitHub e corresponde ao código local utilizado nas verificações.

**Na base verificada, os 20 bugs estavam presentes:** 18 reproduções isoladas com assertions e duas verificações estáticas (BUG-0017 e BUG-0020). No estado atual desta branch, os 20 bugs foram corrigidos. Serviços externos foram simulados; não houve build Docker ou publicação real. O BUG-0008 foi revalidado no legacy, sem repetir a comparação integrada com PDDL/Docling. Estes resultados são verificações direcionadas dos achados, não uma nova execução da suíte completa.

Os campos Motor, Estruturador e IA descrevem o papel de cada componente no cenário: configuração usada, execução real ou simulada e motivo de não aplicação. Um componente configurado não implica que tenha sido executado, nem que outros motores tenham sido testados.

As fichas preservam os IDs e a origem histórica dos defeitos, mas Ambiente, Resultado obtido e Evidências referem-se à release acima. Os dados observados estão nos blocos JSON das respectivas fichas Markdown. Permanecem excluídos os problemas já registrados na branch de homologação, seus desdobramentos e avaliações de qualidade de modelos de IA.

## Findings

| ID | Título | Severidade | Status |
|---|---|---|---|
| [0001](0001-premature-done-history-mismatch.md) | Sucesso antes dos artefatos e histórico divergente | 🟠 Alta | Corrigido nesta branch |
| [0002](0002-queued-cancellation-ignored.md) | Job cancelado na fila é executado | 🟠 Alta | Corrigido nesta branch |
| [0003](0003-export-cancellation-ignored.md) | Cancelamento durante exportação permite publicação do resultado | 🟠 Alta | Corrigido nesta branch |
| [0004](0004-zip-download-filename-mismatch.md) | Nome do ZIP incompatível com a descoberta dos downloads | 🟠 Alta | Corrigido nesta branch |
| [0005](0005-dotted-filename-downloads.md) | Segundo `stem` quebra arquivos com pontos no nome | 🟠 Alta | Corrigido nesta branch |
| [0006](0006-email-false-delivery-confirmation.md) | Falso aviso de e-mail enviado e ausência de alternativa | 🟠 Alta | Corrigido nesta branch |
| [0007](0007-telegram-health-wrong-provider.md) | Health do Telegram ignora o provedor configurado | 🟡 Média | Corrigido nesta branch |
| [0008](0008-legacy-docx-html-as-image.md) | DOCX e HTML não funcionam no caminho legacy anunciado | 🟠 Alta | Corrigido nesta branch |
| [0009](0009-thinking-mode-no-effect.md) | Thinking mode é uma opção sem efeito no legacy | 🟡 Média | Corrigido nesta branch |
| [0010](0010-empty-table-cells-column-shift.md) | Células vazias eliminadas corrompem alinhamento de tabelas | 🟠 Alta | Corrigido nesta branch |
| [0011](0011-tts-failure-silent-success.md) | Falha de áudio fica invisível no resultado público | 🟠 Alta | Corrigido nesta branch |
| [0012](0012-early-failure-stuck-queued.md) | Falha inicial deixa tarefa eternamente na fila | 🟠 Alta | Corrigido nesta branch |
| [0013](0013-web-download-wrong-origin.md) | Página web gera links para a porta errada | 🟠 Alta | Corrigido nesta branch |
| [0014](0014-output-retention-too-short.md) | Retenção real é de 24 horas, promessa é de sete dias | 🟠 Alta | Corrigido nesta branch |
| [0015](0015-expired-token-still-valid.md) | Expiração não é validada na consulta do token | 🟡 Média | Corrigido nesta branch |
| [0016](0016-web-upload-missing-size-limit.md) | Limite de upload aplicado somente depois de gravar no frontend | 🟡 Média | Corrigido nesta branch |
| [0017](0017-compose-builds-test-stage.md) | Compose local constrói o estágio test | 🟠 Alta | Corrigido nesta branch |
| [0018](0018-staging-ignores-dotenv-branch.md) | Staging ignora branch do .env se token já estiver no ambiente | 🟠 Alta | Corrigido nesta branch |
| [0019](0019-staging-fallback-unreachable.md) | Fallback de atualização não cobre falha HTTP ou rede | 🟡 Média | Corrigido nesta branch |
| [0020](0020-delivery-not-gated-by-ci.md) | Publicação não aguarda os testes de CI | 🟠 Alta | Corrigido nesta branch |
