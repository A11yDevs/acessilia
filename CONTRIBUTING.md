# Contribuindo com o acessilia

Este guia descreve o mesmo fluxo de validação usado pelo GitHub Actions. Execute-o antes de abrir um pull request para reduzir diferenças entre o ambiente local e o CI.

## Pré-requisitos

- Python 3.11
- Poetry 1.8.3
- Git
- Pandoc
- XeLaTeX
- Dependências de sistema usadas por OCR e processamento de documentos

No Ubuntu/Debian, instale as dependências de sistema com:

```bash
sudo apt-get update
sudo apt-get install --yes --no-install-recommends \
  build-essential ffmpeg fonts-dejavu-core libgl1 libglib2.0-0 libmagic1 \
  pandoc poppler-utils tesseract-ocr texlive-xetex
```

No macOS, uma opção é usar Homebrew e MacTeX:

```bash
brew install pandoc ffmpeg libmagic poppler tesseract
brew install --cask mactex-no-gui
```

Depois da instalação do MacTeX, pode ser necessário abrir um novo terminal para que `xelatex` seja encontrado no `PATH`.

## Preparar o ambiente

Instale a versão de Poetry usada pelo projeto e todas as dependências, incluindo o grupo de desenvolvimento e os extras Docling/RapidOCR:

```bash
python3.11 -m pip install "poetry==1.8.3"
poetry install --with dev --extras docling
```

O CI usa o [poetry.lock](poetry.lock) sem atualizar versões. Mudanças em dependências devem atualizar `pyproject.toml` e o lockfile no mesmo pull request.

Nenhuma chave de API, token do Telegram ou credencial SMTP é necessária para executar a suíte atual.

## Executar os testes

O diretório `tests/` está configurado como raiz canônica da suíte. Portanto, o comando abaixo coleta e executa todos os testes:

```bash
poetry run pytest
```

Para verificar somente a descoberta, sem executar os casos:

```bash
poetry run pytest --collect-only -q
```

A quantidade de testes pode crescer ou diminuir conforme o projeto evolui. O importante é que todos os arquivos e casos coletados terminem sem falhas, erros ou skips.

Para reproduzir o relatório usado pelo CI:

```bash
poetry run pytest --junitxml=test-results.xml
```

## Fluxo de pull request

1. Atualize sua branch a partir da `main`.
2. Implemente a mudança e os testes correspondentes.
3. Execute `poetry run pytest` localmente.
4. Envie sua branch para o GitHub e abra um pull request para `main`.
5. Aguarde o status `CI / tests (Python 3.11)`.
6. Corrija eventuais falhas e envie novos commits. Execuções antigas do mesmo PR serão canceladas automaticamente.
7. Resolva as conversas da revisão e obtenha pelo menos uma aprovação.
8. Faça o merge somente quando todas as regras estiverem satisfeitas.

O workflow também roda após pushes na `main`, oferecendo uma verificação final do commit integrado. Ele pode ser executado manualmente na aba **Actions** por meio de `workflow_dispatch`.

## Como o CI decide se o PR está válido

Dois jobs de variante realizam estas etapas:

1. Prepara um runner Ubuntu limpo e Python 3.11.
2. Restaura caches compatíveis com o `poetry.lock`.
3. Instala ferramentas de sistema, Poetry 1.8.3 e as dependências da variante slim ou Docling.
4. Valida que o lockfile continua consistente.
5. Coleta explicitamente a suíte inteira.
6. Executa o pytest e gera um relatório JUnit.
7. Na variante Docling, converte um PDF real com PyTorch CPU e sem pacotes CUDA.
8. Analisa o relatório e falha se algum teste tiver sido pulado.

A variante slim exclui por marker apenas o teste que requer o extra Docling; isso aparece como teste desmarcado, não como skip. Um job agregador publica o status estável `CI / tests (Python 3.11)` somente quando as duas variantes passam.

## Solução de problemas

### `pandoc não encontrado`

Confirme a instalação:

```bash
pandoc --version
```

### `lualatex ou xelatex não encontrado`

Confirme que um engine LaTeX está acessível:

```bash
xelatex --version
```

### Erros de importação

Confirme a versão do Python e reinstale o ambiente a partir do lockfile:

```bash
python --version
poetry env info
poetry install --with dev --extras docling
```

### O CI passou localmente, mas falhou no GitHub

Abra o pull request, selecione o check `CI / tests (Python 3.11)` e expanda a primeira etapa com erro. O runner começa limpo, então falhas que só aparecem no GitHub geralmente revelam arquivo não versionado, dependência implícita ou estado local reaproveitado.

## CI e CD

O workflow **CI** implementa integração contínua: cada mudança é instalada e testada automaticamente antes do merge. Depois que o CI de um push na `main` passa, o workflow **Delivery** constrói, testa e publica duas variantes no GitHub Container Registry.

São publicadas quatro referências:

- `ghcr.io/a11ydevs/acessilia:main`, Docling atualizado a cada integração válida;
- `ghcr.io/a11ydevs/acessilia:sha-<commit>`, Docling imutável;
- `ghcr.io/a11ydevs/acessilia:main-slim`, variante sem Docling;
- `ghcr.io/a11ydevs/acessilia:sha-<commit>-slim`, slim imutável.

O Delivery comprova que as imagens não contêm modelos pré-carregados. Na variante Docling, uma conversão sem OCR baixa os modelos estruturais para um volume temporário e a segunda repete a conversão sem rede. O CI separado executa a conversão real com RapidOCR e PyTorch CPU. Os caches de produção ficam em `/app/var/cache/huggingface` e `/app/var/cache/rapidocr`, portanto `/app/var` deve ser um volume persistente.

Antes e depois do push, o workflow mede o tamanho total e a maior camada. O guardrail do projeto é 9 GB; o limite oficial relevante do GHCR é 10 GB por camada e o upload deve concluir em até 10 minutos.

Isso é **entrega contínua**: há um artefato pronto para uso, mas nenhum servidor é alterado automaticamente. Uma futura implantação contínua deve ficar em workflow separado e só será necessária quando existir um ambiente de hospedagem.

## Proteção da `main`

A proteção é configurada no GitHub, não no arquivo do workflow. Depois que o CI executar ao menos uma vez na `main`:

1. Abra **Settings > Rules > Rulesets**.
2. Importe [`.github/rulesets/main.json`](.github/rulesets/main.json) ou crie um **New branch ruleset** com estado **Active**.
3. Use a default branch `main` como alvo.
4. Não adicione bypass rotineiro.
5. Ative **Require a pull request before merging**.
6. Exija uma aprovação e descarte aprovações antigas quando novos commits forem enviados.
7. Ative a resolução obrigatória das conversas.
8. Ative **Require status checks to pass** e selecione `CI / tests (Python 3.11)`.
9. Ative **Require branches to be up to date before merging**.

Teste o ruleset com um pull request: o botão de merge deve permanecer bloqueado durante o CI, quando houver falha e enquanto faltar aprovação.
