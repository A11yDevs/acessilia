# a11y-devs-describer

Bot Telegram para conversão de documentos em formatos acessíveis, com foco em estrutura semântica, previsibilidade de saída e suporte a leitores de tela.

Arquitetura canônica em 4 etapas: extração/normalização determinística -> JSON canônico validável -> AST intermediária compatível com Pandoc -> renderização determinística por formato.

## Funcionalidades

- Recebe PDFs e imagens (png, jpg, tiff, bmp, gif, webp)
- Pré-processa páginas com PyMuPDF, Pillow e OpenCV quando necessário
- Processa página a página com cache local e modo configurável
- Usa um JSON canônico validável como fonte principal da verdade do documento
- Valida o canônico com JSON Schema e validadores de consistência
- Converte o canônico para uma AST intermediária compatível com Pandoc
- Renderiza de forma determinística para TXT, DOCX, PDF e HTML
- Aplica perfis de saída para controlar verbosidade, interatividade e auditoria
- Mantém um fluxo compatível com cache legado durante a migração arquitetural

## Requisitos

- Python 3.12+
- Dependências Python listadas em `requirements.txt`
- Um backend de IA configurado em `config/settings.py` e nas variáveis de ambiente correspondentes
- [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) instalado no PATH ou em `C:\Program Files\Tesseract-OCR` quando o OCR for usado

## Instalação

### 1. Instalar dependências Python

```bash
pip install -r requirements.txt
```

### 2. Configurar

Copie `.env.example` para `.env` e configure o `BOT_TOKEN`.

### 3. Executar

```bash
python run.py
```

## Configuração

| Variável | Descrição | Padrão |
|---|---|---|
| `BOT_TOKEN` | Token do bot Telegram | obrigatório |
| `AI_CLIENT` | Cliente de IA ativo | `opencode` |
| `OPENROUTER_API_KEY` | Chave do OpenRouter, quando usado | vazio |
| `OPENCODE_URL` | URL do backend OpenCode, quando usado | configurado em runtime |
| `MAX_FILE_SIZE_MB` | Tamanho máximo de upload | 50 |
| `MAX_PAGES` | Número máximo de páginas | 50 |
| `AI_TIMEOUT` | Timeout por página/solicitação (segundos) | 300 |
| `LOG_LEVEL` | Nível de logging | `INFO` |

## Estrutura

```
a11y-devs-describer/
├── bot/
│   ├── agents/           # Agentes de processamento por página
│   ├── agente_mestre.py  # Orquestração, cache, histórico e fallback
│   ├── handlers/         # Comandos, mensagens e envio de arquivos
│   ├── exporters/        # Wrappers de compatibilidade para exportação
│   ├── services/         # Cache, fila, histórico, limpeza e arquivos
│   └── utils/            # Logger, validações, estado e conversão
├── exporters/            # Coordenador canônico de exportação
├── pipeline/             # JSON canônico, saneamento, validação e AST
├── renderers/            # Renderizadores determinísticos por formato
├── filters/              # Filtros de perfil e remoção de auditoria interna
├── schemas/              # JSON Schema do documento acessível
├── config/               # Configurações
├── tests/                # Testes
├── temp/                 # Arquivos temporários
└── logs/                 # Logs
```

## Arquitetura Nova

Entrada textual ou estrutural -> normalização determinística -> blocos estruturados -> JSON canônico -> saneamento e validação -> AST intermediária -> filtros por perfil -> renderização determinística para HTML, PDF, DOCX e TXT.

Os perfis de saída controlam verbosidade, interatividade e inclusão de auditoria por formato.

## Testes

```bash
pytest tests/
```
