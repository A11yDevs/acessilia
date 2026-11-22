# Changelog do Core

Inglês, versão normativa: [English version](CHANGELOG.md).

## 0.3.0 — o adaptador da Toolbox não reexporta mais o SDK

**Mudança incompatível** para quem importava nomes do SDK por
`acessilia_core.toolbox.toolbox_client`. Importe `PROVIDER_DEFAULTS`, os erros
`Toolbox*`, `ToolboxCapabilityClient`, `auth_headers`, `execute_capability` e
`require_capability` de `acessilia_sdk.toolbox`.

O comportamento em runtime não muda. O adaptador do Core agora só mapeia a
`ToolboxConfig` da execução para a configuração de cliente do SDK e constrói
clientes, então o Core não atua mais como fachada do SDK (#656).

## 0.2.6 — infraestrutura de i18n pelo SDK

Sem mudança de comportamento. A infraestrutura genérica de i18n agora vive em
`acessilia_sdk.i18n` (#712): parsing e normalização de locales, negociação,
contexto de requisição por tarefa, compilação de catálogo e lookup
gettext/plural. O core mantém seus catálogos, ids de mensagem, políticas de
locale e a API pública de tradução `t()`/`n()`. A fachada temporária
`acessilia_core.i18n.parse_locales` foi removida; os nomes existentes
`set_request_locale`/`reset_request_locale` permanecem como reexportações de
compatibilidade, e código novo deve importá-los do SDK. O core agora exige
`acessilia-sdk>=0.4,<0.5`. O novo piso também cobre as APIs do SDK que o Core
0.2.5 já consumia -- fusão dual, downscale/validação de render e `run_sync` --
que o SDK publica na 0.4.0; os metadados do 0.2.5 ainda apontavam para 0.3.x.

## 0.2.5 — fusão dual, downscale, validação de render e bridge sync/async via SDK e docstruct

Sem mudança de comportamento, exceto dois casos-limite menores descritos
abaixo. O core passa a delegar a extração com dois provedores, a
fusão/roteamento puro de payloads, a redução de escala de imagens, a
pré-validação de mídia renderizável e os bridges síncrono/assíncrono ao
`acessilia-sdk` e ao `acessilia-docstruct` (#612):

- `pipeline/fusion.py`: `extract_fused` delega para
  `acessilia_sdk.operations.fusion.extract_dual_fused` (preservando os logs de
  falhas por provedor e fallback de artefato via `DualFusionUnavailable`),
  enquanto `fuse_extraction_payloads` e `apply_page_routes` delegam para
  `docstruct.fusion.payload.fuse_extraction_payloads` e `route_pages`
  (preservando os logs de páginas roteadas e ausentes).
- `toolbox/vision_payload.py`: `downscale_image` delega a renderização para
  `acessilia_sdk.toolbox.clients.pdf.downscale_image`, mantendo no core o ciclo
  de vida do cliente com `ToolboxConfig`, o log localizado e o retorno `None`.
- `pipeline/toolbox.py` e `pipeline/judge.py`: substituem `_check_renderable`
  por `acessilia_sdk.toolbox.clients.pdf.check_renderable`.
- `pipeline/handlers/inspection.py` e `pipeline/handlers/fusion.py`: substituem
  os bridges síncrono/assíncrono duplicados por `acessilia_sdk.runtime.run_sync`.

Casos-limite menores:

- O `ValueError` de divergência de tipo de mídia em `check_renderable` passa a
  dizer `Source is <declared> but would be sent as <extension>` (sem o trecho
  `"in the manifest"`).
- `vision_payload.downscale_image` com `scale` não positivo ou não finito passa
  a devolver `None` sem construir cliente da Toolbox, em vez de renderizar uma
  imagem de 1 px.

O core passa a exigir `acessilia-docstruct>=0.5.8,<0.6` (#612).

## 0.2.4 — primitivas estruturais do docstruct 0.5.7

Sem mudança de comportamento, exceto um caso-limite mais estrito. As
implementações duplicadas do core passam a chamar o `acessilia-docstruct`
diretamente (#612): as verificações de tabela e o `DataOutput.table_ast`
(`docstruct.tables.structured`), a detecção e o reparo da hierarquia de
títulos (`docstruct.sections`), a ordenação pelo esqueleto
(`docstruct.fusion.skeleton`, mesmo limiar de 0.5), os helpers de caixa dos
slides (`docstruct.geometry.boxes`), a inspeção de cabeçalhos PNG/JPEG
(`docstruct.imaging`) e o `is_legitimate_text` (`docstruct.fusion.noise`).

O caso-limite mais estrito: um `table_ast` cujo `rowspan`/`colspan` traz um
booleano JSON sobrevivia ao `isinstance(span, int)`; o normalizador estrito o
descarta. Caracterizado em `libs/core/tests/test_docstruct_057_adoption.py`.

O core passa a exigir o docstruct 0.5.7 ou mais novo (#612).

## 0.2.3 — o juiz de página pela operação do SDK

O método `vlm-pairwise-judge` renderiza a página e consulta o juiz pela
operação do juiz de página do SDK (`acessilia_sdk.operations.page_judge`,
#470). O core mantém as suas decisões: a conferência da fonte, quais páginas, o
aviso de truncamento, o limiar e o que cada falha significa. As requisições,
as escolhas e as mensagens de falha não mudam, exceto num caso. Uma resposta
cujo documento não é um objeto (null, lista, texto, número, booleano) levantava
`AttributeError` para fora do método; agora faz o método falhar como uma
resposta sem `pB` válido.

## 0.2.2 — AST de tabela a partir das linhas, pelo docstruct

O construtor do payload e o preenchimento de tabelas montam o AST de uma tabela
a partir das linhas com o `docstruct.tables.ast.table_ast_from_rows`, em vez da
cópia do core (#470). Nas entradas do core, listas de células, as duas só
diferem nas linhas em que todas as células estão em branco: o docstruct as deixa de fora e devolve `None` quando não sobra
nenhuma. A única entrada que chega a isso é uma tabela cujo texto é só espaço
em branco e que não tem um AST de tabela aproveitável: o bloco dela no payload
passa a ter `table_ast: None` em vez de um AST de uma célula vazia. A tabela do
documento canônico e as exportações não mudam.

## 0.2.1 — geometria de caixas dos slides vinda do docstruct

Sem mudança de comportamento. O layout de slides (`manifest/slides.py`) usa a
geometria de caixas do docstruct em vez das suas próprias cópias:
`boxes_overlap` e `union_area`, novas em `docstruct.geometry.boxes`, e
`docstruct.fusion.similarity.area`. O core passa a exigir o docstruct 0.5.6 ou
mais novo (#470).

## 0.2.0 — validação canônica estrita na exportação

**Mudança incompatível de validação:** TXT, HTML, DOCX e PDF/UA exigem que o
documento normalizado inteiro corresponda ao schema empacotado do docstruct,
após a auditoria existente e antes da seleção de perfil. Tipos customizados,
IDs de bloco/seção ausentes e valores inválidos antes aceitos passam a gerar
`ValueError` localizado antes do renderer. Falhas de auditoria têm precedência.

Antes de adotar 0.2.0, construa árvores com `docstruct.canonical` ou forneça
todos os IDs/campos necessários. Corrija valores inválidos; represente semântica
customizada com um dos onze tipos suportados e metadados. Blocos customizados
em nível filtrado pelo TXT não contornam o gate. Células numéricas continuam
convertidas em texto pelo sanitizador; extensões de metadados são válidas.
Texto/Markdown continuam passando pelo builder.

Mappings persistidos/em cache, incluindo jobs retomados, são conferidos ao
exportar. Artefatos existentes e tokens não são revalidados.

Serializadores puros, fallback, schema, contratos do SDK, perfis, nomes e
downloads legados não mudam. Não há nova flag ou fallback. Veja o
[ADR 0026](../../docs/adr/0026-strict-canonical-export-gate.pt-br.md) e o
[corpus de compatibilidade](../../tests/fixtures/export_schema_gate/README.pt-br.md).
