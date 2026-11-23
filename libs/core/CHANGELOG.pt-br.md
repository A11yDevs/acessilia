# Changelog do Core

Inglês, versão normativa: [English version](CHANGELOG.md).

## 0.3.9 — o catálogo da Toolbox como fatos de planejamento (domínio 2.4)

A ADR-0029 torna a disponibilidade de capacidades e providers predicado do
problema de planejamento (#640, PR 1). O domínio PDDL vai para **2.4**:
- tipos `capability` e `provider`;
- fatos `(requires m c p)` e `(offered c p)`;
- um `(runnable m)` derivado: o método está `available` (o Core tem um
  handler) e o catálogo oferece todo requisito.

`execute-obligation` passa a exigir `runnable` no lugar de `available`. O
domínio 2.3 continua distribuído.

`PddlProblemCompiler.compile`, `PlannerAgent` e `PlanningProblem` recebem um
`catalogue` (`CatalogueFacts`). O gate de disponibilidade o monta a partir do
snapshot do catálogo (`AvailabilityDecision.catalogue_facts()`):
- em `observe`, todo requisito é oferecido, então o catálogo fica visível no
  problema e os planos não mudam. Esses fatos são presumidos, não observados:
  o metadado do gate diz `offered_source: assumed` e lista os métodos que o
  snapshot descarta (`assumed_runnable_methods`); `off` não acrescenta fatos
  de catálogo;
- em `enforce`, o snapshot decide o que é oferecido, e sem snapshot nada é
  (falha fechada). O gate não exclui mais métodos pelo nome
  (`unavailable_methods` fica vazio), e os mesmos métodos são excluídos pelos
  fatos.

Os requisitos e os pares oferecidos da decisão são salvos com o checkpoint
do plano (`AvailabilityDecision.from_metadata`, que substitui o
`_availability_from` do orquestrador), então um replanejamento depois de um
reinício vê o mesmo catálogo. Um checkpoint anterior à 2.4 mantém sua própria
lista de métodos excluídos.

A identidade do checkpoint de planejamento passa a incluir os hashes do
domínio. O executor recusa um plano feito com outro domínio, então, depois
deste deploy, um job retomado planeja de novo em vez de falhar.
Um job retomado reutiliza a decisão de catálogo do checkpoint de plano e não
lê o catálogo de novo (revalidação na retomada: #640, PR 3).

Os símbolos PDDL são únicos no problema inteiro: valores de tipos diferentes
que se normalizam igual (um método e um provider chamados `docling`) recebem
símbolos distintos, e o validador recusa um objeto declarado duas vezes.

O planejador interno é testado com o domínio 2.4. O Fast Downward 26.6 foi
conferido localmente e concorda com ele; o CI ainda não o roda (#790). `tests/test_fast_downward_domain.py` compara os dois
backends quando `ACESSILIA_FAST_DOWNWARD` está definido.

## 0.3.8 — o compilador PDDL recusa dependências cíclicas e desconhecidas

O modelo do manifesto recusa dependências cíclicas e desconhecidas entre
obrigações, mas um replanejamento altera o manifesto no lugar. Antes, o
compilador deixava as duas passarem:
- um ciclo compilava, e só o planejador interno o recusava, ao ordenar; o
  Fast Downward apenas não encontrava plano;
- uma dependência desconhecida levantava um `KeyError` cru.

O `PddlProblemCompiler` agora recusa as duas antes de qualquer planejador
rodar, com um `ValueError` que nomeia o ciclo ou a obrigação ausente (#783).
A verificação cobre o fecho selecionado: um ciclo abaixo de uma raiz nomeia só
o ciclo, e uma dependência desconhecida nomeia a obrigação que a tem. O modelo e
o compilador compartilham um percurso (`acessilia_core.manifest.dependencies`),
então reportam o mesmo ciclo; a mensagem do modelo agora também o nomeia.

## 0.3.7 — uma interface de motor de planejamento

Os planos padrão não mudam. `acessilia_core.planning.engine` cria a interface
entre o planejamento e a coordenação do workflow (#632, PR 3; ADR-0029):
- `PlanningProblem` (manifesto, raízes selecionadas, métodos indisponíveis);
- `PlanningResult` (plano, problema compilado, comparação opcional);
- o protocolo `PlanningEngine`;
- `PddlPlanningEngine`, o adaptador sobre o `PlannerAgent`.

O adaptador agora concentra a escolha do backend (`internal`,
`fast-downward`, `both`), que antes ficava no orquestrador. O
`PddlAccessibilityOrchestrator` planeja por `planning_engine`: um motor passado
ao construtor ou, por padrão, um `PddlPlanningEngine` montado a partir das suas
opções de backend a cada chamada de planejamento. Assim, um teste pode
substituir o planejador por um fake.

O contrato do motor:
- `plan` é síncrono e o motor não guarda estado entre chamadas; a propriedade
  aceita atribuição e rejeita um objeto que não segue o protocolo.
- Um motor tem uma `identity`. O `mode` do relatório é `pddl-<identity>`, que
  para o motor padrão é `pddl-<backend>`, como antes. A identidade de um motor
  injetado também entra na identidade do checkpoint de planejamento, então um
  job retomado com outro motor planeja de novo. Os checkpoints do motor padrão
  mantêm sua identidade.
- O coordenador rejeita um resultado cujo plano não confere com o hash do
  problema compilado.
- `PlanningProblem` e `PlanningResult` são imutáveis só superficialmente:
  compartilham o manifesto e o plano (#751).

Duas mudanças menores:
- O `PlannerAgent` é construído no primeiro uso, então um orquestrador com motor
  injetado não carrega o domínio PDDL para ele.
- A regra do plano preferido no modo both agora é `PlannerAgent.preferred`,
  compartilhada com o caminho da CLI; a mensagem de erro da CLI passa a ser a
  do catálogo.

Os padrões `DEFAULT_PLANNER_BACKEND` e `DEFAULT_FAST_DOWNWARD_SEARCH` ficam em
`planning.models`.

## 0.3.6 — descrições canônicas para os schemas PDDL

As descrições dos schemas PDDL agora usam as constantes canônicas em inglês em
vez do lookup do locale ativo, então gerar os schemas é determinístico
independentemente do locale do servidor. Os schemas de execution report,
nominal plan e planning comparison foram regenerados com essas descrições; suas
versões e estruturas não mudam. Os três msgids de descrição de schema foram
removidos dos catálogos de tradução porque são texto canônico de schema, não
strings localizadas. Um teste na raiz agora confere os quatro schemas
versionados contra seus geradores, nos dois locales suportados (#737).

## 0.3.5 — um único writer para os arquivos JSON Schema

Sem mudança de comportamento. As quatro funções `write_*_schema` agora delegam
para `acessilia_core.schema_files.write_schema`, que concentra a criação do
diretório pai e a formatação JSON em UTF-8 (#656).

## 0.3.4 — findings estruturados renderizados pelo SDK

Sem mudança de comportamento. `acessilia_core.pipeline.validators` renderiza
seus findings `(msgid, kwargs)` por
`acessilia_sdk.i18n.translation.resolve_findings` em vez de manter o loop de
formatação no Core. O core agora exige `acessilia-sdk>=0.6,<0.7` (#656).

## 0.3.3 — metadados de timeout da Toolbox pelo SDK

Sem mudança de comportamento. O Core lê os timeout keys próprios dos clientes
por `acessilia_sdk.toolbox.clients.client_timeout_keys()` em vez de introspectar
os internos do módulo de clientes do SDK; `TIMEOUT_KEYS` continua o nome público
do Core usado pela configuração do serviço. O core agora exige
`acessilia-sdk>=0.5,<0.6` (#656).

## 0.3.2 — reexportações da docstruct em formula_tools depreciadas

Sem mudança de comportamento para consumidores migrados; os nomes antigos agora
emitem `DeprecationWarning`. `acessilia_core.formula_tools` mantém `wrap_latex`
e `label_spoken_formula`. Importe os substitutos de `docstruct.text.latex`:
`bare_latex` para `normalize_latex` e `ensure_math_delimiters` para o nome
homônimo. Os consumidores do repositório foram migrados, e os nomes de
compatibilidade ficam até uma versão incompatível posterior removê-los (#656).

## 0.3.1 — reexportações da docstruct depreciadas nas bridges do pipeline

Sem mudança de comportamento. `acessilia_core.pipeline.table_ast` e
`acessilia_core.pipeline.validators` mantêm suas funções localizadas, mas as
funções puras e os msgids da docstruct que eles reexportavam agora emitem
`DeprecationWarning`; importe de `docstruct.tables.ast` e
`docstruct.validation`. Os consumidores do repositório foram migrados, e os
nomes de compatibilidade ficam até uma versão incompatível posterior removê-los
(#656).

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
