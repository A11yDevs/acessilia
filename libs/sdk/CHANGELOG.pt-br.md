# Histórico de alterações

Também disponível em **inglês (EUA)**: [English version](CHANGELOG.md)

O SDK é uma API pública para scripts e benchmarks (#402). As mudanças visíveis
para quem o usa ficam registradas aqui, das mais novas para as mais antigas.

## 0.6.0 (2026-11-22)

- **Adicionado** `resolve_findings` em `acessilia_sdk.i18n.translation`:
  formata findings estruturados `(msgid, kwargs)` por um lookup de locale
  fornecido pelo chamador, para localizar resultados de validação sem
  reconstruir argumentos a partir de strings formatadas (#656).

## 0.5.0 (2026-11-22)

- **Adicionado** `client_timeout_keys()` em `acessilia_sdk.toolbox.clients`: o
  `timeout_key` de cada cliente exportado que tem timeout próprio, para quem
  monta um `ToolboxClientConfig` a partir das suas configurações (#656).

## 0.4.0 (2026-11-22)

- **Adicionado** `acessilia_sdk.i18n.translation` com `compile_catalog`,
  `catalog_for`, `gettext` e `ngettext`: compilação de `.po` em memória,
  fallback para o locale default/identidade em inglês e lookup gettext/plural.
  O dono fornece o diretório de catálogos e a política de locale (#712).
- **Adicionado** `acessilia_sdk.i18n.context` com o override de locale por
  tarefa (`request_locale`, `set_request_locale`, `reset_request_locale`); o
  core mantém a política do locale do servidor e compõe os dois (#712).
- **Adicionado** `acessilia_sdk.i18n.negotiation` com expansão de candidatos,
  dicas do shell e negociação via Babel (`negotiate_locale`,
  `negotiate_server_locale`); quem chama fornece os locales disponíveis e o
  default, então o SDK não impõe política de aplicação (#712). O SDK agora
  depende de Babel para essa infraestrutura genérica.
- **Adicionado** `acessilia_sdk.i18n` com `parse_locales` e `normalize_locale`,
  o parser e o normalizador genéricos de listas de locales compartilhados pelo
  core e pelo serviço. O core mantém seus catálogos e políticas; o restante da
  infraestrutura mudou no mesmo release (#712).
- **Corrigido** `extract_dual_fused` rejeita uma resposta de
  `document.structure.extract` cujo `status` não seja `succeeded`, mesmo que
  traga um objeto `document`; ela é registrada como
  `ToolboxContractViolation`, sem `Step`, alinhada ao contrato do transporte
  (#698).
- **Corrigido** `acessilia_sdk.runtime.run_sync` também fecha a corrotina quando
  `asyncio.run` falha antes de um event loop assumir a posse -- por exemplo uma
  política de event loop personalizada cujo `new_event_loop` levanta erro, ou
  esgotamento de recursos -- para que o caminho sem loop não a deixe vazar
  para um `RuntimeWarning: coroutine ... was never awaited` posterior (#668).
  A docstring agora cobre os dois caminhos.
- **Corrigido** `extract_dual_fused` trata uma resposta de
  `document.structure.extract` fora do envelope (não é um objeto JSON, ou não
  traz o objeto `document`) como `ToolboxContractViolation` registrada em
  `failures`, sem emitir um `Step`, em vez de um passo bem-sucedido com um
  payload inválido; no caminho de artefato, a violação não dispara nova
  tentativa de upload. Assim, `DualFusionUnavailable` deixa de ser levantada com
  `failures` vazio (#635).
- **Corrigido** `acessilia_sdk.runtime.run_sync` agora fecha a corrotina quando
  o preparo do worker falha -- cópia do contexto, criação do executor ou envio
  do trabalho -- em vez de deixá-la sem `await` e emitir depois
  `RuntimeWarning: coroutine ... was never awaited` (#634). A docstring agora
  documenta que, dentro de um event loop em execução, a chamada bloqueia esse
  loop até a worker thread terminar.
- **Alterado** `acessilia_sdk.runtime.run_sync` agora copia o contexto
  `contextvars` do chamador para a worker thread quando chamado dentro de um
  event loop em execução, propagando `operation_context` e variáveis de escopo
  de requisição através da fronteira síncrono/assíncrono (#612).
- **Adicionados** `check_renderable` e `downscale_image` em
  `acessilia_sdk.toolbox.clients.pdf` (#612): pré-validação de tipos de mídia
  contra `RENDER_MEDIA_TYPES` e redução de escala de PNG/JPEG compondo
  `docstruct.imaging.image_dimensions` com `ToolboxPdfClient.render`.
- **Adicionado** `acessilia_sdk.operations.fusion` (`extract_dual_fused`,
  `DualFusionResult`, `DualFusionUnavailable`, ADR-0017, #612): extração
  paralela com dois provedores em `document.structure.extract` (reutilizando
  `artifact_id` com fallback para upload em `ToolboxArtifactNotFound`) composta
  com `docstruct.fusion.payload.fuse_extraction_payloads`; quando os dois
  provedores falham com `ToolboxError`, levanta `DualFusionUnavailable`
  (subclasse de `ToolboxProviderUnavailable`) preservando `failures` e
  `artifact_fallbacks`. Piso da dependência `acessilia-docstruct` ajustado para
  `>=0.5.8,<0.6`.

- **Adicionado** o subcomando `judge` em `python -m acessilia_sdk` e o auxiliar
  `judge_document` em `acessilia_sdk.cli` (ADR-0017, #614): renderiza uma
  página com `page_judgement`, envia duas transcrições candidatas (em texto
  direto ou a partir de arquivos UTF-8) para `document.adjudicate.page`, grava
  opcionalmente o PNG renderizado (`--page-output`) e imprime o julgamento e a
  proveniência dos passos em JSON sem aplicar um limiar de decisão.

- **Corrigido** um `502` que a Toolbox responde com
  `code: "provider_execution_failed"` (o provider foi alcançado e falhou no
  documento) levantando `ToolboxProviderUnavailable`. Agora ele levanta um
  `ToolboxError` simples, como um `500`, e por isso não é repetido nem enviado a
  outro endpoint. Um `502` sem esse código, de um gateway que não alcança a
  Toolbox, continua levantando `ToolboxProviderUnavailable` (#608).

- **Adicionado** o juiz de página, a segunda operação do SDK (ADR-0017, #470
  fase 4): `acessilia_sdk.operations.page_judge`. O `render_judge_page`
  renderiza uma página inteira para o juiz (`pdf.render`, 144 dpi, lado maior
  de 1600 px); o `judge_page` pergunta ao `document.adjudicate.page` qual de
  duas transcrições a página contém e lê `pB` (como o
  `page_judgement_probability` lê), `pB_ab`, `pA_ba` e `model`; o
  `page_judgement` roda os dois e repassa aos passos `dpi`, `max_side`,
  `prompt` e `use_remote_cache`. Uma resposta sem `pB` válido é um julgamento
  cujo `p_b` é `None`. Os erros tipados são levantados sem alteração.

- **Adicionado** registros REST e leitores de arrays de datasets gerados, com métodos tipados adicionais que preservam paginação, nulls, caminhos de artefatos e compatibilidade da sincronização bruta (#213).

- **Corrigido** os leitores tipados de estrutura e layout MinerU agora executam
  a validação canônica do docstruct após validar o payload. IDs de elementos
  duplicados, referências a pais ou páginas inexistentes e outros problemas
  canônicos geram `ToolboxContractViolation` (#585).

- **Adicionado** leitores tipados de layout e estrutura que reutilizam documentos e geometria canônicos do docstruct, preservam metadados do produtor e validam as duas variantes publicadas de layout (#213).

- **Corrigido** `ToolboxMathClient.recognize_result` agora informa envelopes ou
  documentos inválidos como `ToolboxContractViolation` e preserva os campos de
  extensão de registros completos de expressões individuais. Listas legadas de
  fórmulas mantêm a normalização existente (#583).
- **Corrigido** a serialização de resultados gerados converte recursivamente
  extensões que contêm modelos, incluindo arrays e mapas aninhados, em valores
  compatíveis com JSON (#583).

- **Adicionado** bindings gerados para nove documentos execute selecionados da Toolbox, acessores tipados adicionais e metadados de renderização, com validação limitada aos schemas e sem novas dependências de execução (#213).


- **Adicionado** identificadores de operação e cancelamento (ADR-0019):
  `operation_context` e `operation_attempt` anexam `task_id`, um
  `operation_id` estável e um `attempt_id` novo aos cabeçalhos de capacidade e
  artefato da Toolbox, sem ler configuração. `ToolboxOperationClient.cancel`
  pede a todos os endpoints configurados que parem uma operação, com um único
  timeout curto, e devolve `OperationCancelResult` (`cancel_requested`,
  `cancelled`, `finished`, `failed` ou `not_found`) em vez de levantar;
  `not_found` só quando todos os endpoints responderam 404, e um endpoint
  inconclusivo torna o resultado `failed`. Um cancelamento que falha fica para
  o chamador registrar (#409).
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
