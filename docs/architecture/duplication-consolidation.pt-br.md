# Classificação de duplicatas e consolidações, novembro de 2026

> [duplication-consolidation.md](duplication-consolidation.md). A versão em inglês é a fonte.

Este é o PR 2 da [issue #656](https://github.com/A11yDevs/acessilia/issues/656). Ele classifica os grupos de duplicatas do [baseline de novembro](quality-baseline.pt-br.md) e registra as consolidações de baixo risco implementadas até aqui. O snapshot que originou a triagem é `develop` em `b00636fc`: **23 grupos, 57 funções e 699 linhas**. O JSON do baseline foi medido de novo na mesma revisão depois que a [#749](https://github.com/A11yDevs/acessilia/issues/749) mudou o detector; os números de 23 grupos abaixo continuam sendo a medição original, e a seção da política de uma instrução registra os novos totais.

## Método

- Um grupo estrutural só é acionável quando as funções são semanticamente intercambiáveis para os mesmos chamadores. Fluxo de controle normalizado igual não basta.
- Código gerado é alterado pelo gerador, nunca editando o arquivo gerado.
- O detector de duplicatas calcula o fingerprint de um corpo de uma instrução quando o próprio corpo atinge `MIN_DUPLICATE_NODES`; funções com várias instruções mantêm o piso histórico da função inteira. Um wrapper de repasse, portanto, continua visível depois que o temporário é embutido ([#749](https://github.com/A11yDevs/acessilia/issues/749)), e seu grupo é classificado como reclassificado, não consolidado.
- Fluxos sensíveis a comportamento (seleção dos agentes, startup do frontend) precisam de teste de caracterização antes da extração.
- Uma duplicata entre componentes precisa de um único dono. Parsing de locale é semântica de i18n e o parser genérico agora vive no SDK (`acessilia_sdk.i18n`); o core mantém catálogos e políticas, o SDK é dono do contexto de requisição e da tradução, e o serviço lê o ambiente e delega o parse.

## Primeira consolidação: o parser de lista de locales

Antes deste PR, duas funções de 15 linhas implementavam a mesma regra — dividir por vírgulas, aparar cada entrada, descartar vazias e duplicatas, preservar a ordem da primeira ocorrência:

- `backend/config/settings.py::_locales_from_env`;
- `libs/core/src/acessilia_core/i18n/__init__.py::_locales_from_raw`.

Depois:

- `acessilia_sdk.i18n` expõe `parse_locales` e `normalize_locale` como infraestrutura genérica;
- `acessilia_core.i18n.parse_locales` existiu durante a migração como fachada temporária de compatibilidade, importando a implementação do SDK; o PR final da #712 a removeu;
- `Settings.i18n_locales_active` chama o SDK diretamente com `I18N_LOCALES_ACTIVE`;
- a cópia privada do backend foi removida;
- `configure_locales` continua filtrando a lista contra `SUPPORTED_LOCALES`, então uma lista vazia ou sem locale suportado mantém o fallback “oferecer todos os locales suportados”.

O comportamento é fixado por `tests/test_i18n_locales.py` e pelo `tests/test_i18n.py` do SDK: entradas vazias, duplicatas, ordem, normalização, o caminho de ambiente de `Settings` e a ausência de reexportação no core. O SDK é dono do parsing/normalização genéricos; o core mantém catálogos e políticas. A migração do restante da infraestrutura de i18n foi concluída na [#712](https://github.com/A11yDevs/acessilia/issues/712). Isso evita tornar o core dono obrigatório de um utilitário transversal e permite que o serviço o consuma sem importar o core.

A fachada do core era um nome novo de compatibilidade, não um chamador pré-existente preservado: `_locales_from_raw` era código morto antes deste PR. Ela existiu para a migração restante acontecer sem um flag day; a #712 a removeu e moveu o pin do core para `acessilia-sdk>=0.4,<0.5` quando o SDK 0.4.0 publicou a API completa de i18n.

**Delta medido no commit de código deste PR:** 23 grupos / 57 funções / 699 linhas → **22 grupos / 55 funções / 669 linhas**. Apenas o grupo `_locales_*` desaparece. Esses deltas são contra o snapshot original de 23 grupos; o [JSON do baseline](quality-baseline.json) é o snapshot regerado descrito na seção da política de uma instrução.

## Segunda consolidação: o writer de JSON Schema

As quatro funções `write_*_schema` em `execution/schema.py`, `manifest/schema.py`
e `planning/schema.py` repetiam a criação do diretório pai, a codificação UTF-8,
o `json.dumps(ensure_ascii=False, indent=2)` e a quebra de linha final. Agora
delegam para `acessilia_core.schema_files.write_schema`, enquanto cada módulo
mantém sua função de schema e seu nome público de writer. Os testes comparam a
saída de cada writer com sua função de schema e cobrem criação do diretório pai
e JSON não-ASCII.

A formatação dos arquivos de schema versionados não muda; o PR do writer não
regenera o conteúdo deles. Um follow-up (#737) tornou as descrições canônicas em
inglês, regenerou os três arquivos defasados e adicionou um teste de frescor. O
grupo `write_*_schema` sai dos candidatos restantes.

**Delta medido no commit de código deste PR:** 24 grupos / 59 funções / 705
linhas → **23 grupos / 55 funções / 672 linhas**. Apenas o grupo
`write_*_schema` desaparece.

## Terceira consolidação: o ponto de entrada do frontend

O `frontend/cli/run.py` era uma cópia quase integral do `frontend/run.py`: a
mesma sondagem de PID, o mesmo lock de processo e o mesmo startup de interfaces,
mudando apenas a formatação, o local do arquivo de lock e a presença de uma
função `main()`. O ponto de entrada dos console scripts agora importa `main` de
`frontend.run`, então o runtime tem uma única implementação e um único lock
autoritativo (`frontend/bot.lock.v2`). Iniciar um dos entry points com o outro já
rodando agora é recusado, em vez de usar dois locks separados. O runtime toma um
lock exclusivo do sistema operacional sobre `frontend/bot.lock.v2`
(`fcntl.flock` no POSIX, `msvcrt.locking` no Windows) e o mantém por um handle
aberto durante toda a vida do processo, então duas aquisições concorrentes não
podem ambas ter sucesso; o PID no arquivo é diagnóstico. Ele também grava seu
PID nos dois caminhos antigos, `frontend/bot.lock` (frontend anterior ao #903)
e `frontend/cli/bot.lock` (console anterior ao #741), para que esses runtimes
continuem recusando iniciar enquanto o novo roda. O runtime reconhece os dois
caminhos antigos: se um deles apontar para um processo vivo, o startup é
recusado; se o dono não puder ser inspecionado, como um processo de outro
usuário, o lock é mantido e o startup é recusado; se estiver obsoleto ou
malformado, é removido.

O modo `0600` é best-effort: é aplicado na criação e restringido no POSIX quando
possível, e não protege o arquivo contra remoção por quem tem permissão de
escrita no diretório. O lock do SO, não o modo, é o mecanismo de exclusão mútua.

Um frontend anterior ao #903 ainda remove `frontend/bot.lock`, e um console
anterior ao #741 remove `frontend/cli/bot.lock`, ao sair. Esses caminhos agora
são apenas anúncios de compatibilidade, então a remoção não libera o
`frontend/bot.lock.v2` autoritativo. Uma instância antiga que inicia antes de o
novo runtime gravar seus PIDs de compatibilidade ainda pode sobrepor; se essa
instância sair depois, ela remove seu anúncio, então inícios antigos posteriores
podem sobrepor até o novo runtime parar. Pare as instâncias antigas antes do
upgrade.

O comportamento de startup e lock é fixado por `tests/test_frontend_startup.py`:
cada interface habilitada, as saídas por token ausente e por nenhuma interface, o
ciclo do lock (arquivo vivo, obsoleto e malformado, e duas aquisições
concorrentes), o anúncio e a limpeza da compatibilidade, o isolamento do unlink
do caminho antigo, o caminho de compatibilidade não gravável, o tratamento
conservador de um dono não inspecionável e as sondagens de PID em
POSIX/Windows. `tests/test_process_setup.py` continua conferindo que o runtime
configura o processo antes de obter o lock.

**Delta medido no commit de código do #656:** 23 grupos / 55 funções / 672
linhas → **20 grupos / 49 funções / 499 linhas**. Os grupos `_is_process_running`,
`acquire_lock` e `startup` desaparecem.

## Quarta triagem: os wrappers tipados do SDK

Os três grupos do SDK são falsos positivos para consolidação. A validação já
vivia nos leitores compartilhados: `read_result`/`read_document` para resultados
de execute, `read_layout`/`read_manifest` para os documentos de layout e
estrutura. A duplicata era só a forma de encaminhamento em duas instruções
(`await` no método bruto, guardar num temporário e passá-lo ao leitor). Os
acessadores agora colocam a chamada aguardada dentro do leitor, mantendo
assinaturas públicas e comportamento de validação, sem o temporário.
`judge_page_result`, que ficava fora dos grupos, segue o mesmo formato por
consistência.

Isso cobre `judge_page_result`, `transcribe_region_result`, `text_spans_result`,
`validate_result`, `convert_result`, `verbalize_result`, `inspect_result`,
`analyze_result` e `extract_structure_result`. Os testes existentes de result
readers e de layout readers exercitam saídas válidas e inválidas.

A queda medida de 20 grupos / 49 funções / 499 linhas para **17 grupos / 41
funções / 381 linhas** era uma isenção do detector na época, não extração de
comportamento compartilhado: cada corpo reescrito tinha uma instrução, e
`_fingerprint` então ignorava corpos com menos de duas. Desde a
[#749](https://github.com/A11yDevs/acessilia/issues/749) esses corpos voltam a
receber fingerprint, então as três linhas continuam reclassificadas, não
consolidadas: os leitores compartilhados já fazem a validação, e não há mais
nada a extrair.

## Quinta consolidação: os helpers de comandos do Telegram

Os cinco comandos de modo (`/ocr`, `/detalhado`, `/medio`, `/baixo` e `/normal`)
repetiam os mesmos dois passos: guardar o modo do próximo arquivo para o chat e
tópico do remetente e enviar a confirmação localizada. Agora compartilham
`_set_mode`. O par pausar/retomar compartilha `_set_pause`, que recebe a ação
(`pause_chat` ou `resume_chat`) e o id da resposta. Nomes, aliases e textos
visíveis não mudam; os testes parametrizados cobrem todos os modos e as duas
ações de pausa.

**Delta medido no commit de código deste PR:** 17 grupos / 41 funções / 381
linhas → **15 grupos / 34 funções / 324 linhas**. O grupo dos cinco modos e o
grupo de comandos pausar/retomar desaparecem; as funções `pause_chat`/`resume_chat`
do middleware continuam como um grupo separado.

## Sexta consolidação: o middleware de pausa do Telegram

`pause_chat` e `resume_chat` repetiam os mesmos três passos: atualizar o cache
de chats pausados em memória, persistir a mudança no `TelegramStateStore` e
registrar um warning quando o SQLite não estava disponível. Agora compartilham
`_set_paused`, que mantém a atualização do cache antes da chamada ao store e
preserva o caminho de falha. Os testes de sobrevivência do estado e de falha do
store cobrem as duas ações.

**Delta medido no commit de código deste PR:** 16 grupos / 36 funções / 333
linhas → **15 grupos / 34 funções / 319 linhas**. O grupo de pausa/retomada do
middleware desaparece.

## Sétima consolidação: o normalizador de strings opcionais em branco

`VisionOutput.normalize_empty_formula_latex` e
`DataOutput.normalize_empty_optional_strings` implementavam a mesma regra: uma
string opcional em branco vinda do provider significa campo ausente. Os dois
validadores agora delegam para `_blank_to_none`; os testes existentes cobrem
`formula_latex`, `latex` e `caption`.

**Delta medido no commit de código deste PR:** 15 grupos / 34 funções / 319
linhas → **14 grupos / 32 funções / 309 linhas**. O grupo de normalizadores do
output schema desaparece. Os dois validadores delegadores agora têm uma
instrução; o detector anterior à #749 os escondia, e eles voltam como um grupo
reclassificado de uma instrução sob a política abaixo. Diferente do caso dos
wrappers do SDK, esta é uma extração real: os dois validadores compartilham
`_blank_to_none`.

## Oitava consolidação: o helper de SHA-256 de arquivo

O builder de manifesto e o bundle de domínio do planejamento repetiam a mesma
implementação de SHA-256 em blocos. Ambos agora chamam
`acessilia_core.hashing.file_sha256`, que usa `hashlib.file_digest`; o equivalente
`_source_sha256` do extrator da Toolbox também foi removido. Os testes cobrem
arquivos vazios, pequenos, com múltiplos blocos e ausentes, além de caminhos
`Path` e `str`.

**Delta medido no commit de código deste PR:** 14 grupos / 32 funções / 309
linhas → **13 grupos / 30 funções / 297 linhas**. O grupo `_sha256` desaparece;
a cópia do extrator da Toolbox não formava grupo, então não altera esse delta.

## Nona consolidação: o helper de headers de autenticação da API

`ApiClient._admin_headers` e `_operations_headers` repetiam a cópia dos headers
base e a regra do bearer token. Ambos agora delegam para `_auth_headers`; um
teste fixa o token de observabilidade junto com a API key, e os testes existentes
do token de operações cobrem o outro ramo. Outro teste configura os dois tokens e
verifica que rotas admin recebem só o de observabilidade enquanto `/cache/clear`
recebe só o de operações.

**Delta medido no commit de código deste PR:** 13 grupos / 30 funções / 297
linhas → **12 grupos / 28 funções / 287 linhas**. O grupo de headers de
autenticação desaparece.

## Décima consolidação: a caminhada de nós Math do Pandoc

`_count_math_nodes` e `_contains_math` repetiam a mesma travessia de listas e
dicionários do Pandoc. Ambos agora usam `_math_nodes`, um gerador em pré-ordem;
a contagem o consome e a verificação para no primeiro match. Testes diretos da
caminhada, de contagem e de degradação cobrem a travessia compartilhada.

**Delta medido no commit de código deste PR:** 12 grupos / 28 funções / 287
linhas → **11 grupos / 26 funções / 269 linhas**. O grupo de nós Math do Pandoc
desaparece.

## Décima primeira consolidação: o ciclo de vida do cliente de math

Reconhecimento, conversão e verbalização criavam um `ToolboxMathClient`,
aguardavam uma operação do SDK e fechavam o cliente. Os três agora usam
`_with_math_client`; o callback mantém a mesma chamada ao SDK e o cliente é
fechado no `finally`.

**Delta medido no commit de código deste PR:** 11 grupos / 26 funções / 269
linhas → **10 grupos / 24 funções / 257 linhas**. O grupo de wrappers async de
math desaparece.

## Décima segunda consolidação: os leitores gerados de dataset

Os cinco leitores de coleções de dataset em `_dataset_generated.py` repetiam o
import local de `decode` e a chamada. O gerador agora emite um helper `_read`
compartilhado; cada leitor público mantém sua regra e nome e fica com uma linha.
O teste de atualidade do arquivo gerado fixa a saída, e os testes de leitores e
schema de dataset cobrem documentos válidos, vazios e malformados.

**Delta medido no commit de código deste PR:** 10 grupos / 24 funções / 257
linhas → **9 grupos / 19 funções / 242 linhas**. O grupo de leitores gerados de
dataset desaparece. Cada leitor agora tem uma instrução e continua como um grupo
reclassificado de uma instrução; o helper compartilhado é a extração real, não o
corpo reduzido.

## Décima terceira consolidação: os shims de atributos depreciados

`table_ast.__getattr__` e `validators.__getattr__` repetiam a mesma busca, aviso
e lógica de `AttributeError`, diferindo apenas no nome do módulo e no import
substituto. Os dois agora delegam a `_deprecated_attribute`; o aviso continua
apontando para o chamador do shim, e a mensagem, o valor retornado e o erro de
atributo desconhecido permanecem iguais. Os testes de depreciação cobrem os
dois módulos.

**Delta medido no commit de código deste PR:** 9 grupos / 19 funções / 242
linhas → **8 grupos / 17 funções / 222 linhas**. O grupo de `__getattr__` de
depreciação desaparece. Cada shim agora tem uma instrução e continua como um
grupo reclassificado de uma instrução; o helper compartilhado é a extração real,
não o corpo reduzido.

## Décima quarta consolidação: o planejador construído sob demanda

`PddlPlanningEngine.planner` e `PddlAccessibilityOrchestrator.planner`
repetiam a mesma construção preguiçosa de `PlannerAgent`. Os dois agora chamam
`_lazy_planner`; o orchestrator mantém o setter e a propriedade pública do
engine não muda. Os testes de planejamento cobrem o cache no primeiro uso e o
planejador injetado.

**Delta medido no commit de código deste PR:** 8 grupos / 17 funções / 222
linhas → **7 grupos / 15 funções / 213 linhas**. O grupo da propriedade
`planner` desaparece. Cada propriedade agora tem uma instrução e continua como
um grupo reclassificado de uma instrução; o helper compartilhado é a extração
real, não o corpo reduzido.

## Décima quinta consolidação: os checkers gerados de reference

O modelo gerado `ArtifactReference` tinha dois checkers,
`_check_artifact_id` e `_check_digest`, idênticos exceto pelo nome do campo. O
gerador agora agrupa propriedades com o mesmo template de restrições e emite
um `_check_shared_N(value, name)` mais wrappers de uma linha por campo. As
mensagens de erro continuam carregando o nome do campo, e a API pública do
modelo não muda. O teste de atualidade do arquivo gerado e os testes de
reference cobrem o comportamento; um teste direto do gerador fixa o checker
compartilhado.

**Delta medido no commit de código deste PR:** 7 grupos / 15 funções / 213
linhas → **6 grupos / 13 funções / 201 linhas**. O grupo de checkers gerados
desaparece. Cada wrapper agora tem uma instrução e continua como um grupo
reclassificado de uma instrução; o checker compartilhado é a extração real, não
o corpo reduzido.

## Décima sexta consolidação: os envelopes de ferramentas dos agentes

Os envelopes de seleção de página nos agentes de adjudicação e de página e o
método de junção final nos agentes de fusão e de página repetiam os mesmos
corpos. `agents/_tool_mixins.py` agora concentra `select_page_tool`,
`swap_low_agreement_tool` e `join_tail_tool`; cada método público mantém
assinatura, docstring e registro Agno e delega ao helper. Os callables usam
protocolos, então as assinaturas dos processos e do docstruct continuam
verificadas.

**Delta medido contra a base comum dos três PRs paralelos:** 6 grupos / 13
funções / 201 linhas → **3 grupos / 7 funções / 63 linhas**. Os três grupos de
agentes desaparecem.

## Décima sétima consolidação: a exigência de configuração

Os helpers do agente e do exportador repetiam a mesma checagem de configuração
ausente. `config_helpers._require_config` agora a centraliza; `_tool_config`,
`_export_config`, `_toolbox_config` e o guard de `fuse_providers` mantêm tipo
de exceção e mensagem.

**Delta medido contra a base comum dos três PRs paralelos:** 6 grupos / 13
funções / 201 linhas → **5 grupos / 10 funções / 184 linhas**. O grupo de
helpers de config desaparece.

## Décima oitava consolidação: o envelope de seleção de tabela

`TableSpecialistAgent.select_table` e `select_greedy` repetiam o mesmo
empacotamento de decisão/estatísticas. Os dois agora delegam a `_select_tool`;
assinaturas, docstrings, registro de ferramentas e a conversão de `Counter`
para `dict` não mudam.

**Delta medido contra a base comum dos três PRs paralelos:** 6 grupos / 13
funções / 201 linhas → **5 grupos / 11 funções / 161 linhas**. O grupo de
seleção de tabela desaparece.

Juntos, os três PRs paralelos deixam **1 grupo / 2 funções / 6 linhas** sob o
detector da época: o par trivial de construtores, reclassificado abaixo como sem
ação. A #749 depois tornou os delegadores de uma instrução visíveis de novo.

## Política de uma instrução (#749)

O detector não isenta mais um corpo com menos de duas instruções. Um corpo de
uma instrução recebe fingerprint quando o próprio corpo atinge
`MIN_DUPLICATE_NODES`; funções com várias instruções mantêm o piso da função
inteira do baseline original. Medir o caso de uma instrução no corpo evita
transformar uma assinatura longa em evidência, mantendo comparável todo grupo do
baseline original.

A consequência é que os oito acessadores tipados do SDK da quarta triagem voltam
a ser reportados, junto com os outros delegadores de uma linha criados pelas
consolidações acima. Eles são clones estruturais, mas não candidatos a
consolidação: o leitor, helper ou checker compartilhado já é dono do
comportamento. O [baseline regerado](quality-baseline.json) em `f812032a`
reporta **38 grupos / 91 funções / 1.147 linhas**, e o código atual reporta
**19 grupos / 43 funções / 550 linhas**. O ratchet de duplicação registra esses
19 grupos revisados em `tests/fixtures/duplication-allowlist.json`, então um novo
clone de uma instrução falha na CI em vez de baixar a métrica em silêncio. Os
testes de regressão em `tests/test_architecture_quality.py` fixam um wrapper de
repasse multilinha e o piso de tamanho do corpo.

## Classificação dos grupos restantes

Ordem do snapshot original de 23 grupos; “candidato” significa que a próxima consolidação pode avaliá-lo com testes, não que seja seguro unir imediatamente. O baseline regerado acrescenta os grupos de uma instrução descritos acima.

| # | Grupo | Disposição |
|---:|---|---|
| 0 | Handlers do Telegram `cmd_detailed`, `cmd_low`, `cmd_medium`, `cmd_normal`, `cmd_ocr` (5/39) | **Consolidado:** `_set_mode` compartilhado; textos e aliases não mudam. |
| 1 | Leitores de dataset gerados do SDK (5/15) | **Consolidado:** o gerador emite `_read` compartilhado; leitores mantêm suas regras. |
| 2 | Escritores de schema do core `write_*_schema` (4/33) | **Consolidado:** `schema_files.write_schema` compartilhado, com testes de writer/schema. |
| 3 | Helpers de config do core `_tool_config`, `_export_config`, `_toolbox_config` (3/17) | **Consolidado:** `_require_config` compartilhado; tipo de exceção e mensagem preservados. |
| 4 | Leitores de resultado do SDK em adjudicate/pdf/pdf_validate (3/48) | **Reclassificado:** falso positivo; o leitor compartilhado já faz a validação. |
| 5 | Leitores de resultado do SDK em math/media_inspect (3/38) | **Reclassificado:** falso positivo; o inlining é estilo, não extração. |
| 6 | `_locales_from_env` / `_locales_from_raw` (2/30) | **Consolidado neste PR.** |
| 7 | `JobOperations.__init__` / `_FurnitureView.__init__` (2/6) | **Reclassificado:** atribuições de campos independentes; sem comportamento compartilhado. O único grupo restante sob o detector anterior à #749. |
| 8 | `_is_process_running` do frontend (2/26) | **Consolidado:** um runtime atrás dos dois entry points, com testes da sondagem de PID. |
| 9 | `acquire_lock` do frontend (2/36) | **Consolidado:** o console script compartilha `frontend.run` e o lock dele. |
| 10 | `startup` do frontend (2/107) | **Consolidado:** a caracterização cobre composição das interfaces e shutdown. |
| 11 | `ApiClient._admin_headers` / `_operations_headers` (2/10) | **Consolidado:** `_auth_headers` compartilhado. |
| 12 | Telegram `cmd_ativar` / `cmd_desativar` (2/20) | **Consolidado:** `_set_pause` compartilhado; textos não mudam. |
| 13 | `select_page` em adjudication/page-level (2/56) | **Consolidado:** `select_page_tool` compartilhado; registro de ferramentas e docstrings não mudam. |
| 14 | `swap_low_agreement` (2/52) | **Consolidado:** `swap_low_agreement_tool` compartilhado. |
| 15 | `process_join_tail` em fusion/page-level (2/30) | **Consolidado:** `join_tail_tool` compartilhado. |
| 16 | Normalizadores de output schema (2/10) | **Consolidado:** `_blank_to_none` compartilhado. |
| 17 | `select_greedy` / `select_table` do table specialist (2/40) | **Consolidado:** `_select_tool` compartilhado; contrato de decisão/estatísticas não muda. |
| 18 | `_sha256` do core em builder/domain bundle (2/12) | **Consolidado:** `hashing.file_sha256` compartilhado. |
| 19 | Wrappers async de math (2/12) | **Consolidado:** ciclo de vida `_with_math_client` compartilhado. |
| 20 | Pandoc `_contains_math` / `_count_math_nodes` (2/18) | **Consolidado:** caminhada `_math_nodes` compartilhada. |
| 21 | Leitores de layout/structure do SDK (2/32) | **Reclassificado:** falso positivo; a extração do envelope já é compartilhada. |
| 22 | `_check_artifact_id` / `_check_digest` (2/12) | **Consolidado:** o gerador compartilha um checker para restrições idênticas. |

A tabela é ancorada no baseline de novembro. A propriedade `planner`
compartilhada pelo orchestrator e pelo planning engine introduzida pela #632 e
as duas funções de depreciação `__getattr__` em `table_ast`/`validators` foram
consolidadas acima; elas eram acompanhadas separadamente das linhas do
baseline.

Os 19 grupos aceitos hoje são o par trivial de construtores anterior à #749 mais
os delegadores de uma instrução e as formas incidentais que a #749 revelou;
nenhum precisa de outra extração. Os grupos de agentes, config e tabela foram
consolidados em três PRs paralelos; os grupos de planner e depreciação foram
consolidados antes. O ratchet da #656 agora impõe o restante revisado, e um novo
clone de uma instrução falha nele.

## Reprodução

```bash
python scripts/architecture_quality.py --rev b00636fc   # baseline inicial
python scripts/architecture_quality.py --rev HEAD       # números atuais
python scripts/check_duplication_ratchet.py             # restante da CI
python -m pytest tests/test_i18n_locales.py libs/core/tests/test_schema_files.py libs/core/tests/test_hashing.py libs/docstruct/tests/test_pandoc_ast_degrade.py tests/test_api_client.py tests/test_frontend_startup.py tests/test_telegram_client.py tests/test_telegram_state.py tests/test_structured_agent_outputs.py tests/test_toolbox_math_tools.py tests/test_sdk_bindings.py tests/test_sdk_dataset_schema.py libs/sdk/tests/test_dataset_readers.py libs/sdk/tests/test_reference.py libs/sdk/tests/test_result_readers.py libs/sdk/tests/test_layout_readers.py libs/core/tests/test_deprecation_shims.py libs/core/tests/test_table_ast.py libs/core/tests/test_pipeline_validation.py libs/core/tests/test_planning_engine.py libs/core/tests/test_orchestration_planning_characterization.py libs/core/tests/test_adjudication_agent.py libs/core/tests/test_page_level_agent.py libs/core/tests/test_fusion_agent.py tests/test_core_config.py tests/test_docx_export.py tests/test_pdf_ua_export.py libs/core/tests/test_table_specialist_agent.py tests/test_architecture_layers.py
```

O snapshot inicial legível por máquina permanece em [quality-baseline.json](quality-baseline.json). A classificação é intencionalmente sobre candidatos; o PR 5 decidirá quais medidas restantes viram guarda de CI.
