# Classificação de duplicatas e consolidações, novembro de 2026

> [duplication-consolidation.md](duplication-consolidation.md). A versão em inglês é a fonte.

Este é o PR 2 da [issue #656](https://github.com/A11yDevs/acessilia/issues/656). Ele classifica os grupos de duplicatas do [baseline de novembro](quality-baseline.pt-br.md) e registra as consolidações de baixo risco implementadas até aqui. O snapshot que originou a triagem é `develop` em `b00636fc`: **23 grupos, 57 funções e 699 linhas**.

## Método

- Um grupo estrutural só é acionável quando as funções são semanticamente intercambiáveis para os mesmos chamadores. Fluxo de controle normalizado igual não basta.
- Código gerado é alterado pelo gerador, nunca editando o arquivo gerado.
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

**Delta medido no commit de código deste PR:** 23 grupos / 57 funções / 699 linhas → **22 grupos / 55 funções / 669 linhas**. Apenas o grupo `_locales_*` desaparece. O [JSON do baseline](quality-baseline.json) inicial permanece como snapshot histórico; esta página registra as mudanças contra ele.

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
(`frontend/bot.lock`). Iniciar um dos entry points com o outro já rodando agora é
recusado, em vez de usar dois locks separados. O runtime também reconhece o lock
legado `frontend/cli/bot.lock`: se ele apontar para um processo vivo, o startup é
recusado; se estiver obsoleto ou malformado, é removido.

O comportamento de startup e lock é fixado por `tests/test_frontend_startup.py`:
cada interface habilitada, as saídas por token ausente e por nenhuma interface, o
ciclo do lock (arquivo vivo, obsoleto e malformado) e as sondagens de PID em
POSIX/Windows. `tests/test_process_setup.py` continua conferindo que o runtime
configura o processo antes de obter o lock.

**Delta medido no commit de código deste PR:** 23 grupos / 55 funções / 672
linhas → **20 grupos / 49 funções / 499 linhas**. Os grupos `_is_process_running`,
`acquire_lock` e `startup` desaparecem.

## Classificação dos grupos restantes

Ordem do `docs/architecture/quality-baseline.json`; “candidato” significa que a próxima consolidação pode avaliá-lo com testes, não que seja seguro unir imediatamente.

| # | Grupo | Disposição |
|---:|---|---|
| 0 | Handlers do Telegram `cmd_detailed`, `cmd_low`, `cmd_medium`, `cmd_normal`, `cmd_ocr` (5/39) | Adiar para um PR de frontend: confirmar diferenças de texto e menu antes de extrair um helper de comando. |
| 1 | Leitores de dataset gerados do SDK (5/15) | Arquivo gerado (`_dataset_generated.py`): corrigir o gerador, não as funções geradas. |
| 2 | Escritores de schema do core `write_*_schema` (4/33) | **Consolidado:** `schema_files.write_schema` compartilhado, com testes de writer/schema. |
| 3 | Helpers de config do core `_tool_config`, `_export_config`, `_toolbox_config` (3/17) | Adiar: os dataclasses de configuração ao redor diferem. |
| 4 | Leitores de resultado do SDK em adjudicate/pdf/pdf_validate (3/48) | Candidato: leitor genérico tipado após os testes de contrato do SDK. |
| 5 | Leitores de resultado do SDK em math/media_inspect (3/38) | Candidato: o mesmo leitor genérico. |
| 6 | `_locales_from_env` / `_locales_from_raw` (2/30) | **Consolidado neste PR.** |
| 7 | `JobOperations.__init__` / `_FurnitureView.__init__` (2/6) | Trivial; sem ação. |
| 8 | `_is_process_running` do frontend (2/26) | **Consolidado:** um runtime atrás dos dois entry points, com testes da sondagem de PID. |
| 9 | `acquire_lock` do frontend (2/36) | **Consolidado:** o console script compartilha `frontend.run` e o lock dele. |
| 10 | `startup` do frontend (2/107) | **Consolidado:** a caracterização cobre composição das interfaces e shutdown. |
| 11 | `ApiClient._admin_headers` / `_operations_headers` (2/10) | Candidato a helper pequeno; baixa prioridade. |
| 12 | Telegram `cmd_ativar` / `cmd_desativar` (2/20) | Adiar: texto de comando visível ao usuário. |
| 13 | `select_page` em adjudication/page-level (2/56) | Sensível a comportamento: caracterizar a política de seleção primeiro. |
| 14 | `swap_low_agreement` (2/52) | Sensível a comportamento: caracterizar a política de troca primeiro. |
| 15 | `process_join_tail` em fusion/page-level (2/30) | Avaliar junto com o follow-up dos agentes. |
| 16 | Normalizadores de output schema (2/10) | Candidato a helper pequeno. |
| 17 | `select_greedy` / `select_table` do table specialist (2/40) | Sensível a comportamento: testes de seleção de tabela primeiro. |
| 18 | `_sha256` do core em builder/domain bundle (2/12) | Candidato a consolidação de utilitário. |
| 19 | Wrappers async de math (2/12) | Candidato a helper pequeno. |
| 20 | Pandoc `_contains_math` / `_count_math_nodes` (2/18) | Candidato a helper pequeno. |
| 21 | Leitores de layout/structure do SDK (2/32) | Candidato: mesmo leitor genérico dos grupos 4–5. |
| 22 | `_check_artifact_id` / `_check_digest` (2/12) | Candidato a helper pequeno de validação. |

A tabela é ancorada no baseline de novembro. O tool atual também reporta dois
grupos introduzidos por PRs posteriores: `pause_chat`/`resume_chat` (2/14) e as
duas funções de depreciação `__getattr__` em `table_ast`/`validators` (2/20);
eles são acompanhados separadamente das linhas do baseline.

O próximo candidato de maior valor são os leitores de resultado do SDK (grupos
4, 5 e 21). O trio startup/lock do frontend foi consolidado neste PR. Cada
consolidação deve manter seu próprio PR focado e testes de caracterização; os
grupos restantes não foram alterados aqui.

## Reprodução

```bash
python scripts/architecture_quality.py --rev b00636fc   # baseline inicial
python scripts/architecture_quality.py --rev HEAD       # números atuais
python -m pytest tests/test_i18n_locales.py libs/core/tests/test_schema_files.py tests/test_frontend_startup.py
```

O snapshot inicial legível por máquina permanece em [quality-baseline.json](quality-baseline.json). A classificação é intencionalmente sobre candidatos; o PR 5 decidirá quais medidas restantes viram guarda de CI.
