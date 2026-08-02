# Acessília

**Acessília** é um projeto de código aberto focado em promover a acessibilização de documentos para pessoas com deficiência, partindo da extração, classificação e conversão de documentos (PDF, DOCX, TXT, imagens escaneadas) em formatos acessíveis utilizando agentes inteligentes e um pipeline de orquestração modular e adaptável.

Atualmente, o projeto prioriza a acessibilização para **pessoas com deficiência visual**, fornecendo audiodescrições detalhadas de elementos visuais, suporte aprimorado para leitores de tela e geração de narração em áudio.

---

## Arquitetura do Projeto

O projeto é estruturado de forma desacoplada seguindo a divisão entre **Backend**, **Frontend** (Interfaces) e **Infraestrutura**:

```text
acessilia/
├── backend/            # Lógica de domínio, Agentes, serviços e exportadores
│   ├── agents/         # Agentes especialistas (Reader, Vision, Data, Editor) e Orquestrador
│   ├── ai/             # Integração com o Agno Framework (Ollama e OpenRouter)
│   ├── adapters/       # Adaptadores de domínio
│   ├── export/         # Exportadores de formato (TXT, DOCX, PDF, Audio/MP3, HTML)
│   ├── pipeline/       # Leitura e parsing estruturado de documentos
│   ├── services/       # Histórico, cache, fila de processamento, tokens e e-mail
│   └── tools/          # Ferramentas auxiliares (OCR, manipulação de imagem e PDF)
├── frontend/           # Interfaces de usuário e pontos de entrada
│   ├── cli/            # Interface de linha de comando (CLI)
│   ├── web/            # API REST e painel Web com FastAPI
│   └── telegram/       # Bot do Telegram (aiogram 3)
├── infra/              # Configurações de Docker, Dockerfile e containerização
├── docs/               # Documentação técnica e propostas de arquitetura
└── tests/              # Suíte de testes unitários automatizados
```

---

## Pipeline dos Agentes Inteligentes

O processamento principal utiliza uma **arquitetura de multiagentes** coordenada por um orquestrador responsável por gerenciar o fluxo de trabalho:

1. **`ReaderAgent`:** Processa o documento, divide as páginas e extrai as regiões estruturais (tabelas, fórmulas, imagens e texto) via Docling ou PyMuPDF.
2. **`VisionAgent` (Agno + LLM):** Processa recortes de imagens e páginas escaneadas utilizando a capacidade multimodal nativa (`agno.media.Image`), gerando audiodescrições detalhadas e acessíveis.
3. **`DataAgent` (Agno + LLM):** Processa tabelas e fórmulas complexas para gerar representações estruturadas em Markdown e LaTeX.
4. **`EditorAgent`:** Sanitiza o conteúdo, aplica deduplicação semântica/temporal via *fingerprints* e insere as marcações de acessibilidade no documento final.

---

## Instalação e Execução via Docker

Toda a aplicação roda em ambiente containerizado. Todas as dependências do sistema são gerenciadas e configuradas automaticamente pelo Docker.

### Pré-requisitos
- [Docker](https://www.docker.com/) instalado.
- [Docker Compose](https://docs.docker.com/compose/) instalado.

---

### Passo a Passo para Executar

#### 1. Clonar o repositório
```bash
git clone https://github.com/A11yDevs/acessilia.git
cd acessilia
```

#### 2. Configurar o arquivo de ambiente (`.env`)
Crie o arquivo `.env` a partir do modelo de exemplo:
```bash
cp .env.example .env
```
Edite o arquivo `.env` ajustando suas credenciais:
- Provedor de IA: `OPENROUTER_API_KEY` ou `OLLAMA_BASE_URL`
- Interfaces ativas: `ENABLED_INTERFACES=web,telegram`
- Token do Telegram (caso utilize): `BOT_TOKEN`

#### 3. Subir a aplicação com Docker Compose (Recomendado)
Execute o comando na raiz do projeto para compilar e iniciar os serviços (aplicação + banco MariaDB):
```bash
docker compose up -d --build
```
A aplicação estará disponível em `http://localhost:8000/`.

---

### Execução com Docker CLI (Alternativo)

Caso prefira compilar e rodar a imagem diretamente sem o Docker Compose:

```bash
# Build da imagem Docker
docker build -f infra/Dockerfile -t acessilia:latest .

# Execução do container montando os volumes de persistência
docker run -d -p 8000:8000 \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/output:/app/output \
  -v $(pwd)/temp:/app/temp \
  --name acessilia-instance acessilia:latest
```

---

## Formas de Interface Habilitadas

No arquivo `.env`, você pode habilitar quais interfaces deseja que o container execute através da variável `ENABLED_INTERFACES`:

- **Web UI / REST API (FastAPI)**: Acesse `http://localhost:8000` (painel web e Swagger em `/docs`).
- **Telegram Bot**: Responde a comandos e envio de documentos diretamente no aplicativo do Telegram.
- **CLI**: Execução via linha de comando no container (`docker exec -it acessilia-instance python -m frontend.cli.run`).

---

## Testes

Para rodar a suíte de testes unitários no container:
```bash
docker exec -it acessilia-instance pytest
```

---

## Contribuindo

1. Faça um **Fork** do repositório.
2. Crie uma branch para sua funcionalidade (`git checkout -b feature/nova-funcionalidade`).
3. Escreva testes unitários cobrindo as mudanças.
4. Garanta que a suíte de testes passe.
5. Abra um **Pull Request**.

---

## Licença

MIT © 2026 Jhonata Fernandes Cordeiro & Contribuidores do Acessília