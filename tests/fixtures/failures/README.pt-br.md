# Fixtures de falha controlada

Também disponível em **inglês (EUA)**: [English version](README.md)

Documentos inertes e intencionalmente quebrados, usados apenas para reproduzir
o caminho de "o pipeline falhou" sem danificar um arquivo real. Eles ficam
versionados em `tests/` e nunca são referenciados pelo código de produção, então
não podem ser acionados por um upload em uma implantação em execução.

| Arquivo | O que há de errado |
|---------|--------------------|
| `empty.pdf` | Um arquivo de zero bytes com extensão `.pdf`. |
| `not-a-pdf.pdf` | Texto simples com extensão `.pdf`; nenhuma estrutura PDF. |
| `truncated.pdf` | Cabeçalho PDF e um objeto catalog que referencia um objeto `Pages` inexistente, sem tabela de referência cruzada. |

Eles exercitam o ramo de falha do worker (`backend/api/worker.py`,
`JobExecutor.run`) de ponta a ponta: o pipeline real recebe o documento
corrompido, aborta, e o usuário ainda precisa receber o e-mail de falha
(`send_failure_email`).

## Executando o cenário

Não existe nem é necessária uma chave de debug: as fixtures são arquivos
comuns na árvore de testes e o teste é limitado pelo marcador `e2e`, que a CI
exclui (`pytest -m "not e2e"`). Para rodá-lo contra uma Toolbox real:

```bash
TOOLBOX_BASE_URL=<url> uv run pytest -m e2e tests/test_job_failure_e2e.py -v
```

O teste substitui apenas o transporte SMTP por um registrador; o pipeline, o
worker, o job store e o histórico são as implementações reais. Ele verifica que
o job termina como `error`, que o diretório de saída é removido e que o e-mail
de falha nomeia o arquivo enviado.

A cobertura unitária do mesmo ramo (sem Toolbox) fica em
`tests/test_job_progress.py` e `tests/test_email_service.py`.
