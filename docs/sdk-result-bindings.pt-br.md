# Bindings de resultados do SDK: schemas consumidos e escopo da migração

Você também pode ler esta documentação em **inglês**: [English](sdk-result-bindings.md).

Este é o inventário solicitado pela [revisão mais recente da #213][review],
sob a #380. Ele define o escopo proposto dos dois próximos PRs de implementação;
não introduz modelos de resultados nem altera clientes. A issue permanece aberta
até os bindings selecionados serem gerados, utilizados e verificados contra desvios.

## Evidências e responsabilidades

O inventário compara o `develop` do core/SDK em
`2d5e885e5fb57ea0d94835ef124c3ddcec741129` com o [contrato][contract],
[diretório de schemas][schemas] e [OpenAPI][openapi] publicados pela Toolbox em
**`c536c2007912e0ce2f20bd930215d96e6f4c09be`**. Esses links imutáveis identificam
as evidências, não uma promessa sobre uma implantação posterior da Toolbox.
A geração deve ler contratos e schemas publicados; não deve importar código
Python da Toolbox nem inferir schemas de `capabilities/*.yaml`.

Esta atualização substitui a evidência `77c7df7`, anterior à publicação.
Os PRs [#160][dataset-publication] e [#161][layout-publication] da Toolbox
foram mesclados, e as issues [#158][dataset-followup] e [#159][layout-followup]
foram encerradas. As saídas de datasets e layout abaixo são contratos
publicados, com trabalho explícito nos PRs 2/3, em vez de dependências de
contratos ausentes.

A [allowlist do SDK](../libs/sdk/src/acessilia_sdk/toolbox/capabilities.py)
seleciona **28 versões de capacidades: 18 execute e 10 REST**. Todas aparecem
abaixo. Seus ids permitidos, versões exatas selecionadas, transportes, chaves e
defaults de providers e rótulos de erros continuam sendo escolhas do SDK.
O bloco gerado do registro contém atualmente apenas a projeção publicada de
`output_schema` e `idempotent`; entradas REST mantêm `output_schema=None`
deliberadamente. Atualizar o contrato não deve autorizar outra capacidade
automaticamente.

O [gerador](../scripts/generate_sdk_bindings.py) e o
[script de captura](../scripts/capture_toolbox_contract.py) selecionam atualmente
apenas `reference@1.json`. `ArtifactReference` é o único modelo de resultado
gerado. A fixture local normalizada do contrato omite `schema_refs`,
`dataset_routes`, entradas e a maior parte dos metadados de execução; seu comentário identifica `develop`,
não um SHA imutável. Portanto, as classificações de publicação abaixo vêm do
contrato público fixado, não de inferências sobre essa fixture ou seu registro.

Pelas [ADR-0002](adr/0002-component-responsibilities.pt-br.md) e
[ADR-0004](adr/0004-single-source-of-truth-for-contracts.pt-br.md), a Toolbox é
dona dos contratos operacionais; o SDK deriva os bindings selecionados;
a docstruct é dona da estrutura e geometria canônicas; o core interpreta
resultados e decide políticas. A geração de novos modelos deve preservar
essas fronteiras.

## Saídas execute

A coluna de schema identifica a referência de saída `artifact/…`, omitindo
esse prefixo. Essas referências normalmente descrevem
**`ExecutionResponse.document`**, não o envelope da resposta, sua proveniência
ou os bytes binários baixados.

Os links dos clientes abaixo são relativos a
[`acessilia_sdk.toolbox.clients`](../libs/sdk/src/acessilia_sdk/toolbox/clients).
“Selecionado” indica o conjunto proposto para o PR 2. “Adiado” indica publicação
existente fora desse conjunto inicial: há uma API de passagem de resultados
brutos no SDK/CLI, mas nenhum leitor atual do core justifica gerar toda essa
família de resultados nesta mudança.

| Capacidade selecionada | Referência de saída publicada | Leitor e formato retornado atualmente | Classificação / próxima ação |
|---|---|---|---|
| `document.structure.extract@1` | `structured-document@1` | [Cliente de estrutura](../libs/sdk/src/acessilia_sdk/toolbox/clients/structure.py) retorna envelope; [extração do core](../backend/core/manifest/toolbox_extractor.py), [fusão](../backend/core/pipeline/fusion.py) e [benchmark](../scripts/bench/toolbox.py) o leem | **Reutilizar docstruct**, incluindo `StructuredDocument` e adaptadores de payload; não gerar outro modelo canônico de manifesto/elementos |
| `document.layout.analyze@1` | `layout-analysis@1` | [Cliente de layout](../libs/sdk/src/acessilia_sdk/toolbox/clients/layout.py) retorna envelope; helpers existentes toleram listas/mapas de páginas, mas não extraem classificações do MinerU | **Publicado, selecionado para o PR 2**: binding do SDK que distingue variantes; definições operacionais geradas e reuso da docstruct no ramo de manifesto, conforme detalhado abaixo |
| `math.recognize@1` | `latex@1` | [Cliente matemático](../libs/sdk/src/acessilia_sdk/toolbox/clients/math.py), `recognized_formulas`, [operações de fórmulas](../libs/sdk/src/acessilia_sdk/operations/formula.py), [binding matemático do core](../backend/core/toolbox/toolbox_math_tools.py) | **Selecionado**: `LatexResult`; preservar o adaptador de listas de fórmulas legadas e os resultados de expressão única |
| `math.convert@1` | `mathml@1` | Cliente matemático retorna envelope; operações de fórmulas e bindings do core leem `mathml` ou `latex`, conforme a direção | **Selecionado**: `MathmlResult`; caracterizar primeiro as duas direções de conversão e o comportamento quando falta texto |
| `math.verbalize@1` | `verbalized@1` | Cliente matemático retorna envelope; operações de fórmulas e bindings do core leem `verbalized` | **Selecionado**: `VerbalizedResult` |
| `document.adjudicate.page@1` | `page-judgement@1` | [Cliente de adjudicação](../libs/sdk/src/acessilia_sdk/toolbox/clients/adjudicate.py), `page_judgement_probability`, [juiz do core](../backend/core/pipeline/judge.py) | **Selecionado**: `PageJudgement`; manter o comportamento de coerção/falha do adaptador de probabilidades |
| `document.adjudicate.region@1` | `region-transcription@1` | `transcribe_region` do cliente de adjudicação retorna envelope com `text`/`model` | **Selecionado**: `RegionTranscription`, pequeno resultado complementar do mesmo cliente do SDK |
| `pdf.validate.pdf_ua@1` | `pdf-validation-report@1` | [Cliente de validação](../libs/sdk/src/acessilia_sdk/toolbox/clients/pdf_validate.py) retorna o documento; [auditoria do core](../backend/core/toolbox/pdf_ua_audit.py) lê conformidade, falhas e contagens | **Selecionado**: `PdfValidationReport`; não conformidade continua sendo um relatório bem-sucedido |
| `media.inspect@1` | `media-inspection@1` | [Cliente de mídia](../libs/sdk/src/acessilia_sdk/toolbox/clients/media_inspect.py) retorna o documento; [binding do core](../backend/core/toolbox/media_inspect.py) lê dimensões, natureza, contagem e sinal de inspeção visual | **Selecionado**: `MediaInspection`; distinguir medidas desconhecidas/nulas de valores medidos |
| `pdf.render@2` | `image@2` | [Cliente de PDF](../libs/sdk/src/acessilia_sdk/toolbox/clients/pdf.py) retorna `RenderedPage(image, clip, document)`, do SDK; [binding de renderização do core](../backend/core/pipeline/toolbox.py) e operações de fórmulas o leem | **Selecionado**: `RenderedPageMetadata` apenas para o documento; preservar a leitura verificada do PNG e as verificações do recorte aplicado |
| `document.text.spans@1` | `text-spans@1` | `text_spans` do cliente de PDF retorna o documento, `text_spans_by_page` o indexa; [binding do core](../backend/core/toolbox/text_spans.py) alimenta leitores de matemática inline | **Selecionado**: `TextSpansResult`; preservar lotes de páginas, coordenadas e validação dos spans |
| `document.ocr@1` | `ocr-result@1` | [Cliente de OCR](../libs/sdk/src/acessilia_sdk/toolbox/clients/ocr.py) retorna envelope; SDK/CLI o expõem | **Publicado, adiado**: itens de OCR aninhados e caixas de tamanho fixo |
| `document.ocr.page@1` | `page-transcription@1` | [Cliente de OCR de página](../libs/sdk/src/acessilia_sdk/toolbox/clients/page_ocr.py) retorna envelope; SDK/CLI o expõem | **Publicado, adiado**: schema plano já representável pelo gerador atual |
| `image.page.orient@1` | `page-orientation@1` | [Cliente de orientação](../libs/sdk/src/acessilia_sdk/toolbox/clients/orientation.py) retorna envelope; SDK/CLI o expõem | **Publicado, adiado**: enum numérico, limites e dimensões anuláveis |
| `table.recognize@1` | `table-candidates@1` | [Cliente de tabelas](../libs/sdk/src/acessilia_sdk/toolbox/clients/table.py) retorna envelope; SDK/CLI expõem gerações greedy/amostradas | **Publicado, adiado**: referências locais e arrays de gerações; esses candidatos operacionais não são o AST canônico de tabelas da docstruct |
| `pdf.split@1` | `page-collection@1` | `split` do cliente de PDF retorna envelope com imagens de páginas; SDK/CLI o expõem | **Publicado, adiado**: arrays com metadados de páginas e payloads base64 aninhados |
| `document.export.pdf_ua@1` | `pdf-export@1` | [Base de exportação](../libs/sdk/src/acessilia_sdk/toolbox/clients/pandoc_export.py) verifica/baixa o artefato e retorna envelope; [exportador do core](../backend/core/export/pandoc_exporter.py) a chama | **Publicado, adiado**: as verificações existentes de artefatos cobrem os campos lidos atualmente; a geração de metadados pode vir separadamente |
| `document.export.docx@1` | `docx-export@1` | Mesma base de exportação, configurada pelo [cliente DOCX](../libs/sdk/src/acessilia_sdk/toolbox/clients/docx.py) | **Publicado, adiado**: mesma família limitada de metadados da exportação de PDF |

`structured-document@1.json` identifica-se como
`processing-manifest:1.1.0`. Seus campos estruturais pertencem a
[`docstruct.manifest`](../libs/docstruct/src/docstruct/manifest.py), enquanto
origem/estado do processo ficam com seus produtores. O
[adaptador de documento do core](../backend/core/manifest/document_adapter.py) e os
[testes de contrato semântico](../tests/test_manifest_semantic_contract.py)
já exercitam essa fronteira. Reutilizá-la não exige que o SDK dependa dos modelos
Pydantic do core nem que o modelo da docstruct seja gerado de um schema da Toolbox.

### Binding de layout no PR 2

O [contrato de layout publicado][layout-contract] é uma união Draft 2020-12
com `anyOf`/`allOf`. Docling emite `pages`/`page_count`/`region_count` compactos;
MinerU emite um manifesto de processamento com os campos obrigatórios
`extractor.configuration.layout_regions`, `region_count` e `backend`.
Ambos publicam arrays de páginas. O gerador atual rejeita a união; apenas
acrescentar seu arquivo a `MODELS` não produz um binding correto.

O PR 2 inclui esse binding junto aos nove modelos execute selecionados para
geração, com este plano limitado:

1. Capturar `layout-analysis@1.json` completo e publicado. Ampliar a seleção
   de modelos, pertencente ao SDK, para identificar destinos locais explícitos
   em `$defs`: `LayoutPages` e seus registros operacionais aninhados, e
   `MineruLayoutConfiguration` e seus registros de classificação. Gerar esses
   formatos operacionais das definições capturadas, não de código de providers.
2. Usar um adaptador do SDK para as duas representações conhecidas. Reutilizar
   adaptadores de payload de `docstruct.manifest`, `StructuredDocument` e
   geometria canônica nos campos de documento do manifesto; manter separados
   os campos do produtor e metadados de layout. Não gerar o `ProcessingManifest`
   incorporado nem suas definições canônicas de página/elemento/caixa como
   modelos do SDK.
3. Usar esse adaptador por leitores/acessores tipados aditivos de layout.
   Preservar o envelope bruto atual e a compatibilidade legada dos helpers com
   mapas de páginas. Caracterizar ambos os providers, resultados vazios,
   metadados obrigatórios e origens não resolvidas; índices de página dos
   metadados são baseados em zero, números de páginas canônicas em um, e
   MinerU não fornece confiança de classificação.
4. Manter sem suporte a compilação geral de uniões/interseções. O adaptador
   explícito de layout deve ser testado contra a união publicada completa,
   incluindo rejeição de manifestos genéricos sem metadados de layout.
   Selecionar uma definição conhecida não pode descartar silenciosamente
   restrições do ramo que a contém.

Esse é um binding selecionado de layout, não um décimo manifesto canônico
gerado. Qualquer ramo que não atenda a essas verificações deve ser declarado
incompleto no PR 2, em vez de ser achatado silenciosamente ou declarado coberto.

## Saídas REST

São rotas dedicadas: **não há envelope execute** para desembrulhar. A referência
declarada pela capacidade, sozinha, não basta para atribuir um modelo Python
a uma resposta REST. `dataset_routes` do contrato fixado e
`x-toolbox-dataset-binding` do OpenAPI agora publicam método/caminho/capacidade/
versão e schema de resposta exatos para as oito rotas de datasets. Usar o
schema da rota para REST e os metadados de saída da capacidade para resultados
execute. A coluna de schemas abaixo mostra ambas as referências quando diferem.
A [documentação publicada do contrato de datasets][dataset-contract] e os
[exemplos de conformidade de providers/REST/MCP][dataset-examples] acompanham os schemas.

| Capacidade selecionada | Saída da capacidade / schema REST preciso | Rota dedicada / resultado no SDK | Classificação / próxima ação |
|---|---|---|---|
| `artifact.store@1` | `reference@1` | `POST /v1/artifacts`; [cliente de artefatos](../libs/sdk/src/acessilia_sdk/toolbox/clients/artifact.py): `upload_reference` retorna `ArtifactReference`, `upload` retorna o id | **Gerado atualmente**; preservar a compatibilidade de `upload` com respostas antigas de registro armazenado |
| `artifact.retrieve@1` | `binary@1` | `GET /v1/artifacts/{id}`; bytes verificados ou download pelo cliente de artefatos | **Descritor**; nenhum modelo de resultado JSON para bytes |
| `dataset.list@1` | `dataset-list@1` | `GET /v1/datasets`; [cliente de datasets](../libs/sdk/src/acessilia_sdk/toolbox/clients/dataset.py) retorna lista | **Publicado, selecionado para o PR 3**: `list[DatasetInfo]`; preservar o formato da rota e sua compatibilidade |
| `dataset.describe@1` | `dataset-info@1` | `GET /v1/datasets/{id}`; retorna objeto | **Publicado, selecionado para o PR 3**: `DatasetInfo`; preservar o formato da rota e sua compatibilidade |
| `dataset.list_splits@1` | `dataset-splits@1` | `GET /v1/datasets/{id}/splits`; retorna lista de objetos de splits | **Publicado, selecionado para o PR 3**: `list[SplitInfo]`; preservar o formato da rota e sua compatibilidade |
| `dataset.list_items@1` | `dataset-item-list@1` → `dataset-item-summary-list@1` | `GET /v1/datasets/{id}/splits/{split}/items`; lista paginada de resumos; `list_all_items` agrega páginas | **Publicado, selecionado para o PR 3**: `list[ItemSummary]`; preservar o formato da rota e sua compatibilidade |
| `dataset.get_item@1` | `dataset-item@1` | `GET /v1/datasets/{id}/splits/{split}/items/{item}`; objeto de item completo | **Publicado, selecionado para o PR 3**: `DatasetItem`; preservar o formato da rota e sua compatibilidade |
| `dataset.get_artifact@1` | `binary@1` | `GET /v1/datasets/{id}/splits/{split}/items/{item}/artifacts/{path}`; bytes | **Descritor**; preservar codificação do caminho e bytes brutos |
| `dataset.sample@1` | `dataset-item-list@1` → `dataset-sample@1` | `GET /v1/datasets/{id}/splits/{split}/sample`; lista de itens completos | **Publicado, selecionado para o PR 3**: `list[DatasetItem]`; preservar o formato da rota e sua compatibilidade |
| `dataset.sync@1` | `dataset-sync-report@1` | `POST /v1/datasets/{id}/sync`; SDK atualmente repassa qualquer JSON | **Publicado, selecionado para o PR 3**: `list[DatasetSyncEntry]`; preservar o formato da rota e sua compatibilidade |

O pré-requisito de contrato [Toolbox #158][dataset-followup] foi concluído
pelo [#160][dataset-publication]. O PR 3 agora seleciona seis bindings de registros:
`DatasetInfo`, `SplitInfo`, `ItemSummary`, `DatasetItem`, `DatasetArtifactRef`
e `DatasetSyncEntry`, de seus respectivos schemas publicados de objetos.
Também seleciona cinco bindings/leitores de arrays na raiz: `dataset-list@1`,
`dataset-splits@1`, `dataset-item-summary-list@1`, `dataset-sample@1` e
`dataset-sync-report@1`. Manter arrays como arrays, incluindo `[]`; nenhum
envelope ou objeto agregado de sync é introduzido.

A família execute compartilhada `dataset-item-list@1` aceita resumos ou itens
completos. Capturá-la para checar capacidade/rota, mas não usá-la para gerar
nenhum dos leitores REST dedicados nem acrescentar compilação geral de uniões.
Schemas de registros incorporados nas coleções devem coincidir com seus
objetos de origem publicados. O trabalho sobre providers/referências da
Toolbox #141 permanece separado.
A [CLI do SDK](../libs/sdk/src/acessilia_sdk/cli.py) utiliza as oito rotas;
[helpers de benchmark](../scripts/bench/toolbox.py) leem resumos de itens,
itens completos e bytes de artefatos.

A definição local de `DatasetArtifactRef` em `dataset-item@1` descreve um
caminho do dataset com metadados opcionais. Ela não é `artifact/reference@1`,
que exige digest e store. Da mesma forma, um documento de renderização/exportação
com `artifact_id` não é automaticamente um `ArtifactReference`. Reutilizar um
tipo apenas quando os formatos e as semânticas publicados realmente coincidirem.

## Trabalho necessário no gerador, limitado aos resultados selecionados

Os nomes propostos de classes/leitores são bindings do SDK, não uma nova fonte
de verdade contratual. O PR 2 seleciona os **nove modelos execute mais o binding
de layout** descrito acima. O PR 3 seleciona os **seis modelos de registros de
datasets e cinco bindings precisos de arrays REST**, capturando a família
execute compartilhada apenas para checagem. Ampliar `MODELS`/`SDK_MODEL_SCHEMAS`
e a seleção explícita de definições nesses PRs após validar consumidores e
compatibilidade. Este inventário não altera gerador, seleção de modelos nem
fixtures capturadas.

O gerador atual foi exercitado com os 26 arquivos JSON distintos publicados de
schemas execute/REST do inventário, excluindo a referência já gerada. Apenas
`verbalized@1`, `region-transcription@1` e o adiado `page-transcription@1`
são renderizados com sucesso atualmente. Os demais falham com `BindingError`;
a primeira palavra-chave rejeitada não é necessariamente o único construto
sem suporte naquele arquivo. As quatro fontes adicionais de registros de
datasets (`dataset-split`, `dataset-item-summary`, `dataset-artifact`,
`dataset-sync-entry`) também foram inspecionadas: somente `dataset-artifact@1`
é renderizado pelo leitor plano atual; as demais precisam dos construtos abaixo.

| Schema(s) selecionado(s) | Construtos adicionais necessários além do leitor plano atual |
|---|---|
| `verbalized@1`, `region-transcription@1` | Nenhum; strings, campos anuláveis/opcionais e restrições de strings existentes bastam |
| `mathml@1`, `page-judgement@1` | `enum`; `maximum` para probabilidades |
| `latex@1` | `maximum`, arrays com itens tipados e tamanho fixo (`minItems`/`maxItems`) |
| `image@2` | `const`, `exclusiveMinimum`, objetos aninhados e propriedades obrigatórias |
| `media-inspection@1` | `enum`, objetos aninhados anuláveis, arrays e objetos abertos de metadados, `exclusiveMinimum` |
| `pdf-validation-report@1` | `enum`, objetos/arrays aninhados, propriedades obrigatórias e mapas de strings tipados (`additionalProperties`) |
| `text-spans@1`, `dataset-item@1` | As regras de objetos/arrays acima, mais `definitions`/`$ref` locais; arrays de coordenadas de tamanho fixo para spans; metadados abertos para itens |
| `dataset-info@1` | `enum` de strings e arrays de strings |
| `layout-analysis@1` | Seleção explícita de `$defs` locais; registros operacionais aninhados, campos anuláveis, enums e limites. Adaptador do SDK para os ramos conhecidos da união; reuso da docstruct nos campos canônicos, sem compilar `anyOf`/`allOf` gerais |
| `dataset-split@1`, `dataset-item-summary@1`, `dataset-artifact@1` | Arrays tipados, objetos abertos de metadados, limites de inteiros e escalares anuláveis; o registro de artefato já cabe no leitor plano |
| Cinco schemas precisos de arrays de datasets | Arrays na raiz, referências tipadas de elementos, `definitions`/`$ref` locais e anotações como `$comment`; preservar arrays vazios e compartilhar bindings dos registros de origem |
| `dataset-sync-entry@1` / `dataset-sync-report@1` | Leitor limitado por status para os ramos publicados de `anyOf` (`const` de `status` e campos `required` por ramo), incluindo eventos globais ignorados com apenas status/motivo; rejeitar padrões condicionais sem suporte |

Continuar falhando explicitamente em restrições desconhecidas, referências
não locais/não resolvidas ou recursivas e famílias de schemas fora desse
conjunto. Não acrescentar suporte geral a `anyOf`/`oneOf`/`allOf`, resolução de
referências pela rede ou geração de manifestos canônicos apenas para fazer
esse inventário passar. Reutilizar os tipos canônicos da docstruct nas
fronteiras dos adaptadores, incluindo tipos de documentos/geometria quando
suas semânticas coincidirem; não gerar modelos concorrentes de elementos,
caixas ou tabelas canônicas. Modelos operacionais gerados devem usar apenas
dependências da biblioteca padrão.

## Compatibilidade e verificação antes da migração

Cada PR de implementação deve demonstrar como um modelo gerado chega ao
leitor pretendido, com respostas e falhas representativas. Gerar uma
dataclass não utilizada não completa um binding. Preservar os formatos
públicos de retorno e as classes de erros do SDK, usando leitores/acessores
tipados aditivos quando uma substituição quebraria compatibilidade. Um
contrato deliberadamente mais estrito ou um novo tipo de retorno exige
decisão própria e documentada de compatibilidade.

Em particular:

- O cliente matemático e seus [testes](../libs/sdk/tests/clients/test_math.py)
  aceitam documentos de expressão única e listas legadas em `formulas`.
  Estas não correspondem ao schema plano publicado `latex@1`. Preservar o
  adaptador de normalização; a conformidade da saída dos providers permanece
  na [Toolbox #117][provider-followup].
- As [operações de fórmulas](../libs/sdk/src/acessilia_sdk/operations/formula.py)
  distinguem uma chave de texto ausente de um valor não textual e suportam
  as duas direções de conversão. Um leitor gerado não deve transformar esses
  casos silenciosamente em outra política de retry/degradação.
- `page_judgement_probability` aceita atualmente probabilidades coercíveis,
  incluindo strings numéricas, e retorna `None` para respostas inutilizáveis.
  Seus [testes](../libs/sdk/tests/clients/test_adjudicate_probability.py) são
  uma base de compatibilidade, distinta da validação estrita de schema.
- Digests de artefatos binários, assinaturas PNG/PDF/DOCX, limites de tamanho,
  afinidade de endpoint e recortes aplicados continuam sendo verificações
  existentes dos artefatos/clientes; um modelo gerado de metadados não pode
  substituí-las.
- Preservar medidas ausentes versus nulas, campos de extensão desconhecidos
  e metadados abertos. `ArtifactReference.from_dict` ignora campos desconhecidos
  atualmente, mesmo com `additionalProperties:false` em seu schema;
  a geração a partir do schema não deve mudar silenciosamente essa política
  de compatibilidade futura.

- Sync de datasets agora tem contrato publicado de array; mocks do SDK com
  objetos são uma caracterização legada, não a fonte de geração. Acrescentar
  exemplos baseados no schema e leitores tipados sem mudar silenciosamente a
  compatibilidade existente de passagem de resultados brutos. Cobrir
  espelhamento desativado, eventos de itens/artefatos ignorados e arrays vazios.
  Preservar nulos emitidos em registros de info/artefatos e distinguir erros de
  listagem lançados pelos providers do comportamento existente de manifesto/
  diretório ausente que retorna `[]`.

As verificações de `from_dict` geradas devem ser comparadas com o JSON Schema
publicado usando exemplos válidos e inválidos. Cobrir limites, inteiros versus
booleanos, campos anuláveis/ausentes, arrays/objetos aninhados e referências
inválidas. Manter a [pureza do SDK](../libs/sdk/tests/test_purity.py), as
verificações de desvio dos arquivos gerados em
[`test_sdk_bindings.py`](../tests/test_sdk_bindings.py) e a checagem de
[`check_capability_contract.py`](../scripts/check_capability_contract.py)
contra a branch de implantação. Transporte, retries, escolha de providers e
políticas dos agentes não fazem parte desta sequência.

## Atualização do snapshot e sequência de revisão

O conjunto de fontes revisado deve ser reproduzível. Para cada PR de geração:

1. Revisar as referências selecionadas no contrato público da Toolbox e em
   `schema_refs`/`dataset_routes`, registrando o commit exato da fonte. Antes de
   atualizar, ampliar a captura para preservar esses campos e a proveniência
   imutável; a fixture normalizada atual os descarta.
2. Acrescentar apenas os nomes de schemas e destinos de modelos revisados a
   `SDK_MODEL_SCHEMAS` e `MODELS`. Capturar o contrato e esses schemas
   **do mesmo SHA imutável da Toolbox**, pelo script de captura.
3. Regenerar; nunca editar manualmente o bloco gerado, os módulos de modelos
   ou os schemas capturados. Commitar juntos a proveniência da captura e as
   mudanças geradas, inspecionando separadamente o diff de allowlist/transporte.
4. Executar verificações de desvio, regressões de schemas/consumidores,
   pureza e `make test-all`. A checagem de CI do contrato da branch de
   implantação continua independente do snapshot fixado de geração e deve
   continuar sendo executada.

Na raiz do repositório, após as mudanças explícitas de seleção do passo 2:

```bash
python scripts/capture_toolbox_contract.py --ref <immutable-toolbox-sha>
python scripts/generate_sdk_bindings.py
python scripts/generate_sdk_bindings.py --check
python scripts/check_capability_contract.py --snapshot tests/fixtures/toolbox-contract.json
make test-all
```

Este PR de documentação é o **PR 1: inventário e escopo**. Revisá-lo antes do
**PR 2: nove modelos operacionais selecionados e o binding de layout que distingue
variantes**, seguido pelo **PR 3: seis bindings de registros de datasets e cinco
bindings precisos de arrays REST**. Os pré-requisitos de publicação de datasets/
layout estão resolvidos no SHA fixado. A #213 só fecha quando o conjunto selecionado
acordado estiver sendo usado e testado contra desvios; as sete famílias
execute publicadas e adiadas, capacidades não relacionadas, respostas de
catálogo/controle/gateway e dataclasses de operações derivadas pelo SDK não
entram automaticamente no escopo da geração.

[review]: https://github.com/A11yDevs/acessilia/issues/213#issuecomment-6904046274
[contract]: https://github.com/A11yDevs/acessilia-toolbox/blob/c536c2007912e0ce2f20bd930215d96e6f4c09be/contract/toolbox-contract.json
[schemas]: https://github.com/A11yDevs/acessilia-toolbox/tree/c536c2007912e0ce2f20bd930215d96e6f4c09be/schemas
[openapi]: https://github.com/A11yDevs/acessilia-toolbox/blob/c536c2007912e0ce2f20bd930215d96e6f4c09be/docs/openapi.json
[dataset-examples]: https://github.com/A11yDevs/acessilia-toolbox/blob/c536c2007912e0ce2f20bd930215d96e6f4c09be/tests/unit/test_dataset_contracts.py
[dataset-followup]: https://github.com/A11yDevs/acessilia-toolbox/issues/158
[layout-followup]: https://github.com/A11yDevs/acessilia-toolbox/issues/159
[provider-followup]: https://github.com/A11yDevs/acessilia-toolbox/issues/117

[dataset-publication]: https://github.com/A11yDevs/acessilia-toolbox/pull/160
[layout-publication]: https://github.com/A11yDevs/acessilia-toolbox/pull/161
[dataset-contract]: https://github.com/A11yDevs/acessilia-toolbox/blob/c536c2007912e0ce2f20bd930215d96e6f4c09be/docs/dataset-contracts.pt-br.md
[layout-contract]: https://github.com/A11yDevs/acessilia-toolbox/blob/c536c2007912e0ce2f20bd930215d96e6f4c09be/docs/layout-contract.pt-br.md
