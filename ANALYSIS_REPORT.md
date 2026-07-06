# Relatório de Análise Completa – bot-acess

---

## Visão geral da arquitetura

```
Telegram Bot  <--->  interfaces/telegram  
                         |
                         v
FastAPI Web  <--->  interfaces/web/app.py
                         |
                         v
                      Queue (core/services/queue_service)
                         |
                         v
                Orquestrador (core/orchestrator.py)
                         |
          +--------------+--------------+--------------+
          |                             |              |
  Region Extraction (core/region_*)   |   Estruturador (core/structurer.py)
          |                             |              |
          v                             v              v
      Pipeline (pipeline/*)  -->  Documento Canônico (JSON)  -->  Exportadores (exporters/*)
                                                  |
                                                  v
                                            Renderizadores (renderers/*)
```

* O **bot do Telegram** e a **interface web** recebem arquivos (PDF, imagens, texto) e enviam para a fila compartilhada.
* O **orquestrador** consome a fila, executa OCR, classificação de regiões, estruturação e registra o histórico.
* O **pipeline** converte o texto bruto em um modelo canônico (hierarquia de blocos, metadados, perfis de verbosidade).
* **Exportadores** geram os formatos finais (PDF, DOCX, TXT, HTML, MP3) usando Pandoc quando disponível ou renderizadores nativos.
* O **renderizador** produz a saída final com TOC, metadados e estilos.

---

## Resumo dos módulos / pacotes

### `core/`
- **orchestrator.py** – driver principal do fluxo; gerencia cache, registro de histórico, chamada ao agente único e fallback de extração.
- **region_classifier.py** – regras de classificação de `Region` (texto, imagem, desconhecido) e utilitários de chave.
- **region_extractor.py** – `Region` dataclass e `extract_regions()` que transforma blocos PyMuPDF em regiões estruturadas.
- **structurer.py** – abstração `BaseStructurer`; implementações `PyMuPDFStructurer` e opcional `DoclingStructurer`.
- **agents/agente_unico.py** – classe `AgenteUnico` que coordena chamadas assíncronas a LLMs e serviços de visão.
- **services/** – `queue_service` (fila única), `cache` (memória simples), `history_service` (persistência de histórico de conversões).
- **utils/** – utilitários genéricos: `text_processor`, `validators`, `logger`, `pdf_splitter`, `image_enhancer`, `image_converter`.

### `pipeline/`
- **structure_parser.py** – tokeniza texto em blocos markdown.
- **canonical_builder.py** – cria o documento canônico (JSON) a partir dos blocos, aplica sanitização.
- **sanitizer.py** – limpa texto, remove artefatos de prompt, valida markdown.
- **validators.py** – validações de integridade (IDs duplicados, hierarquia de títulos, perfis de verbosidade).
- **pandoc_ast_builder.py** – converte o modelo canônico em AST do Pandoc.
- **verbosity_manager.py** – controla perfis de saída (básico, detalhado, técnico).

### `exporters/`
- **docx_exporter.py**, **pdf_exporter.py**, **txt_exporter.py**, **audio_exporter.py** – funções `export_<format>` que recebem o documento canônico e delegam ao `pandoc_exporter` ou renderizadores nativos.
- **pandoc_exporter.py** – orquestra chamada ao Pandoc (construção de AST, validação, renderização) e fallback para renderizadores internos.
- **exporters/audio_exporter.py** – gera MP3 usando TTS em chunks.

### `renderers/`
- **docx_renderer.py**, **html_renderer.py**, **pdf_renderer.py**, **txt_renderer.py** – funções `render_<format>` que recebem o AST ou estrutura canônica e produzem o arquivo final.

### `interfaces/`
- **Telegram** (`interfaces/telegram/*`): `bot.py` cria `Bot` e `Dispatcher`; `handlers/` tratam comandos (`/start`, `/ocr`, `/formatos`), documentos e fotos; `middlewares/pause_middleware.py` permite pausar a bot; `adapters/file_service.py` baixa e envia arquivos.
- **Web** (`interfaces/web/app.py`): aplicação FastAPI com rotas `/`, `/process`, `/download/{token}`; aceita upload de arquivos, enfileira tarefa e devolve ZIP com resultados.
- **CLI** (`interfaces/cli/run.py`): ponto de entrada único que habilita as interfaces configuradas, controla lock de execução e inicia o uvicorn/Web e/ou long‑polling do Telegram.

### `tests/`
- **Cobertura de áreas**: renderizadores (HTML, DOCX, PDF, TXT), pipeline de validação, exportadores, Pandoc filters, estrutura de parsing, clientes OpenRouter/Ollama (stubs).
- **Número de arquivos de teste**: 11 (inclui `__init__.py`).
- **Pontos cobertos**: geração de arquivos de saída, filtragem de verbosidade, detecção de blocos duplicados, validações de documento canônico.
- **Lacunas**: não há testes de integração end‑to‑end da fila/Orchestrator, nem de interfaces (Telegram/Web). Ausência de cobertura de segurança (validação de arquivos) e de performance.

---

## Principais achados (Key Findings)

| Impacto | Achado | Sugestão de correção |
|---|---|---|
| **Alto** | *Ausência de testes de integração* que exercitem o fluxo completo da fila ao exportador. | Criar testes de integração que enviem um PDF de exemplo através da fila e verifiquem a geração de todos os formatos. |
| **Alto** | *Validação de arquivos* limitada ao tamanho e extensão; falta de verificação de MIME e sanitização de nomes. | Expandir `core.utils.validators.validate_file` para validar MIME via `python-magic` e sanitizar nomes de arquivo antes de salvar. |
| **Médio** | *Duplicação de lógica* entre `exporters/pandoc_exporter.py` e renderizadores nativos (ex.: `render_html`). | Unificar via um wrapper que decide dinamicamente usar Pandoc ou renderizador interno conforme disponibilidade. |
| **Médio** | *Log de auditoria* apenas escrito em arquivos de texto; não há integração com sistemas de monitoramento. | Integrar logger ao serviço de observabilidade (ex.: Sentry ou CloudWatch) usando `structlog`. |
| **Baixo** | *Dependência de Pandoc* sem fallback claro quando o binário não está instalado. | Detectar ausência de Pandoc na fase de inicialização e desabilitar formatos que dependem dele, avisando o usuário. |
| **Baixo** | *Uso de `print` em alguns scripts de teste* pode poluir a saída. | Substituir por logging apropriado.

---

## Etapas de verificação (Verification steps)
```
# 1. Rodar a suíte completa de testes
! pytest -q

# 2. Executar um pipeline de exemplo (processa um PDF de amostra)
! python run.py --sample
```
* Verifique que os arquivos `output/sample.pdf`, `sample.docx`, `sample.txt`, `sample.html` e `sample.mp3` são criados.
* Confirme que o diretório `output/` contém um `zip` com todos os artefatos.
* Caso algum teste falhe, consulte a seção **Key Findings** para a causa provável.

---

## Conclusão
A base do projeto está bem estruturada, com separação clara entre extração, pipeline, exportação e interfaces. Os pontos críticos são a falta de testes de integração e algumas validações de segurança que podem ser reforçadas. Implementar as correções acima aumentará a confiabilidade, a cobertura de testes e facilitará a manutenção futura.

---
