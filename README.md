# acessilia

**acessilia** é um projeto de código‑aberto que extrai, classifica e torna documentos (PDF, DOCX, TXT, etc.) acessíveis usando LLMs (Ollama, OpenRouter) e um pipeline modular.

## Arquitetura (modular)

- **core** – lógica de domínio (agentes, clientes de IA, serviços, utilitários, pipeline).
- **adapters** – implementações concretas que adaptam o domínio a ferramentas externas (exportadores, renderizadores, filtros).
- **interfaces** – pontos de entrada (Web UI via FastAPI, bot do Telegram, CLI).
- **tests** – suíte de testes unitários cobrindo a maioria dos módulos.

O projeto segue a caminha *Domínio → Aplicação → Interface*, facilitando:
- Substituir o cliente de LLM (adicionar novos provedores).
- Adicionar novos formatos de exportação (implementar ``AbstractExporter``).
- Trocar o framework web ou adicionar uma nova interface sem tocar na lógica de domínio.

## Instalação

```bash
# usando Poetry (recomendado)
poetry install
poetry run acessilia   # executa a CLI / inicia as interfaces habilitadas
```

## Execução

- **CLI**: `poetry run acessilia`
- **Web**: habilite `web` em `ENABLED_INTERFACES` e acesse `http://localhost:8000`.
- **Telegram**: habilite `telegram` e forneça um `BOT_TOKEN` válido.

## Contribuindo

1. Fork o repositório.
2. Crie uma branch de feature.
3. Escreva testes para a nova funcionalidade.
4. Rode `pytest` – garanta que a cobertura permaneça alta.
5. Envie um pull request.

## Licença

MIT © 2026 Jhonata Fernandes Cordeiro