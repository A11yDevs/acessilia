# Classificação de duplicatas e primeira consolidação, novembro de 2026

> [duplication-consolidation.md](duplication-consolidation.md). A versão em inglês é a fonte.

Este é o PR 2 da [issue #656](https://github.com/A11yDevs/acessilia/issues/656). Ele classifica os grupos de duplicatas do [baseline de novembro](quality-baseline.pt-br.md) e implementa a primeira consolidação de baixo risco. O snapshot que originou a triagem é `develop` em `b00636fc`: **23 grupos, 57 funções e 699 linhas**.

## Método

- Um grupo estrutural só é acionável quando as funções são semanticamente intercambiáveis para os mesmos chamadores. Fluxo de controle normalizado igual não basta.
- Código gerado é alterado pelo gerador, nunca editando o arquivo gerado.
- Fluxos sensíveis a comportamento (seleção dos agentes, startup do frontend) precisam de teste de caracterização antes da extração.
- Uma duplicata entre componentes precisa de dono. Parsing de locale é semântica de i18n, então o core é o dono; o serviço lê o ambiente e delega o parse.

## Primeira consolidação: o parser de lista de locales

Antes deste PR, duas funções de 15 linhas implementavam a mesma regra — dividir por vírgulas, aparar cada entrada, descartar vazias e duplicatas, preservar a ordem da primeira ocorrência:

- `backend/config/settings.py::_locales_from_env`;
- `libs/core/src/acessilia_core/i18n/__init__.py::_locales_from_raw`.

Depois:

- o core expõe `acessilia_core.i18n.parse_locales`;
- `Settings.i18n_locales_active` a chama com `I18N_LOCALES_ACTIVE`;
- a cópia privada do backend foi removida;
- `configure_locales` continua filtrando a lista contra `SUPPORTED_LOCALES`, então uma lista vazia ou sem locale suportado mantém o fallback “oferecer todos os locales suportados”.

O comportamento é fixado por `tests/test_i18n_locales.py`: entradas vazias, duplicatas, ordem e o caminho de ambiente de `Settings`. O core é dono do parser porque é dono de i18n; o serviço já importa o core no process setup (ADR-0016) e o ADR-0002 permite a dependência.

**Delta medido no commit de código deste PR:** 23 grupos / 57 funções / 699 linhas → **22 grupos / 55 funções / 669 linhas**. Apenas o grupo `_locales_*` desaparece. O [JSON do baseline](quality-baseline.json) inicial permanece como snapshot histórico; esta página registra a primeira mudança contra ele.

## Classificação dos grupos restantes

Ordem do `docs/architecture/quality-baseline.json`; “candidato” significa que a próxima consolidação pode avaliá-lo com testes, não que seja seguro unir imediatamente.

| # | Grupo | Disposição |
|---:|---|---|
| 0 | Handlers do Telegram `cmd_detailed`, `cmd_low`, `cmd_medium`, `cmd_normal`, `cmd_ocr` (5/39) | Adiar para um PR de frontend: confirmar diferenças de texto e menu antes de extrair um helper de comando. |
| 1 | Leitores de dataset gerados do SDK (5/15) | Arquivo gerado (`_dataset_generated.py`): corrigir o gerador, não as funções geradas. |
| 2 | Escritores de schema do core `write_*_schema` (4/33) | Candidato: helper compartilhado de escrita JSON com testes de caminho de schema. |
| 3 | Helpers de config do core `_tool_config`, `_export_config`, `_toolbox_config` (3/17) | Adiar: os dataclasses de configuração ao redor diferem. |
| 4 | Leitores de resultado do SDK em adjudicate/pdf/pdf_validate (3/48) | Candidato: leitor genérico tipado após os testes de contrato do SDK. |
| 5 | Leitores de resultado do SDK em math/media_inspect (3/38) | Candidato: o mesmo leitor genérico. |
| 6 | `_locales_from_env` / `_locales_from_raw` (2/30) | **Consolidado neste PR.** |
| 7 | `JobOperations.__init__` / `_FurnitureView.__init__` (2/6) | Trivial; sem ação. |
| 8 | `_is_process_running` do frontend (2/26) | Follow-up de frontend junto com lock/startup. |
| 9 | `acquire_lock` do frontend (2/36) | Follow-up de frontend junto com lock/startup. |
| 10 | `startup` do frontend (2/107) | Follow-up de alto valor; precisa de caracterização do startup. |
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

Os próximos candidatos de maior valor são o trio startup/lock do frontend (grupos 8–10), os leitores de resultado do SDK (4, 5, 21) e os escritores de schema do core (2). Cada um deve ter seu próprio PR focado com os testes de caracterização relevantes; nenhum foi alterado aqui.

## Reprodução

```bash
python scripts/architecture_quality.py --rev b00636fc   # baseline inicial
python scripts/architecture_quality.py --rev HEAD       # números atuais
python -m pytest tests/test_i18n_locales.py
```

O snapshot inicial legível por máquina permanece em [quality-baseline.json](quality-baseline.json). A classificação é intencionalmente sobre candidatos; o PR 5 decidirá quais medidas restantes viram guarda de CI.
