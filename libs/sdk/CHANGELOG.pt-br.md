# Histórico de alterações

Também disponível em **inglês (EUA)**: [English version](CHANGELOG.md)

O SDK é uma API pública para scripts e benchmarks (#402). As mudanças visíveis
para quem o usa ficam registradas aqui, das mais novas para as mais antigas.

## Não lançado

- **Adicionado** `convert_formula` e `verbalize_formula` em
  `acessilia_sdk.operations.formula`, um passo por capacidade (`math.convert`,
  nas duas direções, e `math.verbalize`), cada um devolvendo um `FormulaText`
  (o texto, `""` quando a resposta não traz nenhum, e o `Step` dele). O
  `speak_formula` passa a rodar os dois; o resultado dele não muda para
  respostas dentro do contrato. Quem trata
  as duas capacidades separadamente, como o core, chama os passos (fase 3 da
  #470).
- **Alterado** uma resposta do `math.convert` ou do `math.verbalize` fora do
  contrato (sem objeto `document`, ou com um valor que não é texto, `null`
  incluído) levanta `ToolboxContractViolation` nesses passos e no
  `speak_formula`, em vez de passar por uma fórmula sem esse texto. Uma
  resposta cujo documento não traz a chave continua sendo `""`. O
  `convert_formula` recusa uma `direction` diferente de `latex-to-mathml` e
  `mathml-to-latex` com `ValueError`.

- **Adicionado** `acessilia_sdk.operations.formula`, a primeira operação do SDK
  (ADR-0017, fase 3 da #470): `crop_formula_region` renderiza a caixa de uma
  fórmula a 200 dpi com o `pdf.render` (uma caixa inutilizável, ou um recorte
  mais fino que 4 unidades, não gera recorte, e nunca vira a página inteira);
  `recognize_formula` envia o recorte ao `math.recognize` e ordena os
  candidatos de LaTeX; `speak_formula` converte o LaTeX em MathML e o
  verbaliza; `formula_chain` roda os três para uma fórmula. Cada passo informa
  a capacidade, o provider e os parâmetros, e levanta os erros tipados sem
  alteração. A linha de comando ganha o `formula`, que roda a cadeia e imprime
  cada passo em JSON.
- **Alterado** o SDK passa a depender do `acessilia-docstruct` (`>=0.5,<0.6`),
  pelo `best_effort_clip` e pelo `ranked_latex_candidates`. O docstruct não está
  num índice de pacotes: instale `./libs/docstruct`, ou o wheel de release dele,
  antes do SDK. Dentro do repositório, o uv o resolve pelo caminho.

- **Alterado** `ToolboxEndpoint` agora recusa, na construção, um `base_url` cuja
  porta não é numérica ou está fora de 0–65535, e qualquer URL que o `httpx`
  não consiga interpretar, com `ValueError`. Um `TOOLBOX_BASE_URL` mal
  configurado passa a ser reportado pelo gate de disponibilidade como Toolbox
  indisponível, em vez de surgir depois como `httpx.InvalidURL`; a checagem de
  porta própria da linha de comando saiu, porque `parse_endpoints` já a cobre
  (#438).
- **Documentada** a API pública: o que cada módulo lista em `__all__`
  (ADR-0018). Um nome fora dele é interno e pode mudar em qualquer release. A
  tabela do README a resume, agora incluindo o `ToolboxPdfValidateClient`, e o
  `tests/test_public_api.py` a confere contra o `__all__`. Nenhum código mudou.
- **Adicionado** `page_judgement_probability(document)` em
  `acessilia_sdk.toolbox.clients.adjudicate`: o `pB` de uma resposta do
  `document.adjudicate.page` como float em [0, 1], ou `None` quando ausente,
  não numérico, NaN ou fora do intervalo. A leitura do core veio para cá
  (#402).
- **Adicionado** `RENDER_MEDIA_TYPES` em `acessilia_sdk.toolbox.clients.pdf`: as
  entradas que o `pdf.render@2` abre (PDF, PNG, JPEG), para quem chama conferir
  antes de enviar um arquivo. O próprio `render` não confere, como antes (#402).
- **Adicionado** `ToolboxPdfClient.text_spans_by_page(file_path, artifact_id, *, pages,
  use_remote_cache)`: a página `text-spans@1` de cada página pedida, por número
  de página. Pede cada página uma vez, em ordem, em chamadas de no máximo
  `TEXT_SPANS_MAX_PAGES` páginas, e não faz chamada sem páginas; cada resposta é
  conferida como `text_spans` confere. Os lotes do core vieram para cá (#402).

## 0.3.0 (2026-11-11)

- **Adicionados** `run` e `upload` à linha de comando. `run CAPACIDADE` chama
  qualquer capacidade `execute` do registro por
  `POST /v1/capabilities/{id}:execute`, com o provider e a versão de contrato
  do registro (a menos que `--provider` diga outro), uma entrada dada por
  `--file` ou `--artifact`, e `--language`, `--parameters` (um objeto JSON) e
  `--no-cache` opcionais; imprime o envelope da resposta. `upload ARQUIVO`
  armazena um arquivo e imprime seu id de artefato. `dataset list | describe
  | splits | items | item | artifact | sample | sync` alcançam as oito rotas
  `dataset.*` pelo `ToolboxDatasetClient`, então toda capacidade `rest` do
  registro tem um comando; `run` recusa uma capacidade `rest` antes de
  qualquer requisição e indica esse comando, e recusa uma capacidade fora do
  registro. Todo comando informa na saída de erro cada endpoint do qual faz
  failover (#402).
- **Alterado** `--timeout` sem valor: `catalog` mantém seus 10 s; `run`,
  `upload` e `download` usam o padrão dos clientes, porque uma capacidade pode
  rodar por minutos. Antes desta versão, `download` também usava 10 s.
- **Adicionada** uma linha de comando, `python -m acessilia_sdk`
  (`acessilia_sdk.cli`): `catalog` imprime o catálogo do primeiro endpoint em
  JSON, e `download` baixa um artefato armazenado, conferido contra o digest e
  gravado de forma atômica, tentando os endpoints em ordem. A configuração vem
  só de argumentos (`--endpoint`, `--api-key-file`, `--timeout`); código de
  saída 1 para falha da Toolbox ou do sistema de arquivos, 2 para argumentos
  inválidos (#402).
- **Adicionado** `recognized_formulas(document)` (`acessilia_sdk.toolbox.clients.math`):
  as fórmulas de um documento do `math.recognize@1` como uma lista, qualquer
  que seja o formato da resposta do provider (`artifact/latex@1` dos modelos de
  chip, uma lista `formulas` do `docling-math`). Veio sem mudança do
  `toolbox_math_tools` do core, que continua decidindo o que fazer com o
  resultado (#402).
- **Adicionados** `artifact_endpoint_urls(*clients)` e `one_artifact_endpoint(*clients)`
  (`acessilia_sdk.toolbox.artifacts`): as URLs que um conjunto de clientes pode
  usar, e se um id de artefato pode ser compartilhado entre eles (no máximo uma
  URL; ADR-0006, ADR-0013). Eram helpers privados do extrator do core, que
  continua decidindo entre enviar por upload ou mandar o arquivo (#402).
- **Adicionado** `ToolboxDatasetClient.list_all_items(dataset_id, split, *,
  revision, limit, page_size)`: todos os itens de um split, ou os primeiros
  `limit`, lidos página a página num só cliente (`MAX_PAGE_SIZE = 1000`, o
  limite da Toolbox); uma página que falha levanta seu erro tipado, em vez de
  devolver uma lista parcial. O harness de benchmark pagina com ele (#402).
- **Adicionado** `read_catalog` aceita um `api_key` opcional, usado quando o
  endpoint não tem chave própria, como fazem os clientes de capacidade. O gate
  de disponibilidade do core passa a chave dos seus clientes com o endpoint
  primário deles (#402).
- **Adicionado** `read_catalog(endpoint, *, timeout_seconds)`
  (`acessilia_sdk.toolbox.catalog`): lê o catálogo de um endpoint num cliente
  HTTP de vida curta, com o timeout por requisição do chamador e sem retries.
  O gate de disponibilidade do core passa a usá-lo, em vez de montar o próprio
  cliente (#402).
- **Adicionados** `ArtifactReference` (`acessilia_sdk.toolbox.reference`), o
  `artifact/reference@1` publicado, gerado a partir do schema da Toolbox; o
  `parse_reference`, que também confere `digest == artifact_id`; e o
  `ToolboxArtifactClient.upload_reference`. `upload()` e `ArtifactRef.parse`
  não mudam (#185).
- **Alterado** O `output_schema` e o `idempotent` do registro são gerados a
  partir do contrato publicado pela Toolbox, pelo
  `scripts/generate_sdk_bindings.py` do core (#213); os ids permitidos,
  versões, transportes, chaves de provider e rótulos continuam escritos à mão
  em `_selected(...)`. O `TOOLBOX_CAPABILITIES` não muda, campo a campo.
- **Alterado** Retries e failover valem só para capacidades que o registro
  marca como `idempotent` (ADR-0006, #406). Após um timeout ou uma instância
  indisponível, uma chamada a `dataset.sample` tem uma tentativa no primeiro
  endpoint e levanta o erro dessa tentativa; antes ela era reenviada, ao mesmo
  e a outro endpoint. As capacidades idempotentes mantêm retries, backoff e
  failover.
- **Alterado** `ToolboxCapability` tem um campo nomeado obrigatório `idempotent`,
  o `execution.idempotent` do manifesto na `contract_version`. Toda entrada do
  registro o define; só `dataset.sample` é `False` (#406). Quem monta o próprio
  `ToolboxCapability` precisa passá-lo.

## 0.2.0 (2026-11-09)

- **Adicionados** `ToolboxClientConfig` e `make_client` (`acessilia_sdk.toolbox.config`,
  também exportados por `acessilia_sdk.toolbox`). Quem chama monta toda a
  configuração do cliente como valores explícitos e recebe um cliente
  configurado, sem instalar o core. O `make_toolbox_client` do core passa a
  delegar a eles; os clientes que ele monta não mudam (#402, passo 1).
- **Adicionado** um teste que falha se algum módulo do SDK ler o ambiente do
  processo (`os.environ`, `os.getenv`, sob qualquer nome com que `os` seja
  importado), como pede a ADR-0002.
- `acessilia_sdk.__version__` informa 0.2.0, e um teste o mantém igual à
  versão do `pyproject.toml`.

## 0.1.0

A primeira versão, anterior a este histórico: o registro de capacidades, o
transporte, os clientes por capacidade, endpoints e failover, artefatos, o
catálogo, os helpers do gateway VLM e o `run_sync`.
