# Avaliação: core, SDK e docstruct depois da refatoração (#470, fase 5)

Também disponível em **inglês (EUA)**: [English version](core-sdk-docstruct-evaluation.md)

A fase 5 da [#470](https://github.com/A11yDevs/acessilia/issues/470) pergunta o
que a refatoração da #402 e da #470 mudou, com medidas. Esta página compara o
código de antes da refatoração com o de depois, em seis itens:

1. o tamanho e a complexidade que sobrou no core;
2. o custo de instalar o docstruct e o SDK sozinhos;
3. as dependências externas de cada componente;
4. o tempo dos testes locais;
5. o reaproveitamento das operações do SDK por scripts e benchmarks;
6. regressões funcionais e estruturais.

No fim, ficam as consequências observadas e os próximos passos que elas
sugerem.

## Método

- **Referência:** `66a078b2`, a develop em 2026-11-09, pai do primeiro commit
  da #402 (`5e142e50`). O core ainda fazia parte do serviço, em `backend/`.
- **Agora:** `c22340d0`, a develop em 2026-11-18, depois do #609 e do #610.
- **Medidas do código:** [`scripts/architecture_metrics.py`](../../scripts/architecture_metrics.py).
  Ele lê cada arquivo do git numa revisão, então a referência é medida sem
  fazer checkout. Ele informa arquivos, linhas não vazias, funções, funções com
  mais de 100 linhas e funções com complexidade acima de 15. A complexidade é
  a de McCabe, aproximada pela AST: 1 por função, mais 1 por desvio, laço,
  `except`, `with`, expressão condicional, compreensão, `assert`, `match` e
  operando extra de `and`/`or`. Funções, lambdas e classes aninhadas não são
  percorridas (são medidas à parte). Para repetir uma linha, por exemplo:

  ```bash
  python scripts/architecture_metrics.py --rev 66a078b2 backend
  python scripts/architecture_metrics.py --rev HEAD backend libs/core/src
  ```

- **Medidas de instalação:** um ambiente virtual limpo de Python 3.11 por
  componente, instalado com `uv pip install` a partir do checkout local, sem o
  cache do uv para o docstruct, o SDK e o core. O tamanho é o `site-packages`
  do ambiente.
- **Tempo dos testes:** `make test-all`, rodado duas vezes num notebook de
  desenvolvimento (macOS, a suíte principal com `-n 4`). As duas rodadas
  diferem em até 20 %, por isso cada tempo aparece como uma faixa.

## 1. Tamanho e complexidade que sobrou

| Código | Arquivos | Linhas não vazias | Funções | Com mais de 100 linhas | Complexidade acima de 15 |
|---|---:|---:|---:|---:|---:|
| **Referência:** serviço e core (`backend/`) | 114 | 20.042 | 741 | 26 | 48 |
| **Agora:** serviço e core (`backend/`, `libs/core/src`) | 151 | 24.598 | 883 | 24 | 46 |
| dos quais o serviço (`backend/`) | 46 | 5.081 | 238 | 3 | 5 |
| dos quais o core (`libs/core/src`) | 105 | 19.517 | 645 | 21 | 41 |
| docstruct (`libs/docstruct/src`), referência → agora | 75 → 83 | 10.142 → 11.790 | 433 → 581 | 5 → 6 | 40 → 39 |
| SDK (`libs/sdk/src`), referência → agora | 28 → 44 | 2.484 → 5.289 | 95 → 208 | 0 → 1 | 1 → 3 |

- **O orquestrador foi de 6.103 linhas para 790.** O
  `backend/agents/pddl_orchestrator.py` virou o
  `libs/core/src/acessilia_core/pipeline/orchestrator.py`. Os handlers, as
  etapas de enriquecimento, o payload e o juiz viraram módulos próprios (#402,
  fase 3, passo 6).
- **O serviço agora é pequeno:** 5.081 linhas, com 3 funções longas e 5
  complexas. As decisões foram para o pacote do core, que o serviço chama com
  um `CoreConfig` e ports explícitos (ADR-0016).
- **O total cresceu 4.556 linhas (23 %),** por dois motivos:
  - **funcionalidades novas entraram nos mesmos nove dias.** Entre elas:
    identificadores e cancelamento de operações (ADR-0019), o diário dos jobs
    (ADR-0020), as chamadas de modelo com limite (ADR-0021), o gate estrito de
    exportação (ADR-0026), as identidades de checkpoint (#549), e o
    `CoreConfig` e os ports que substituíram as leituras de `settings` pelo
    core;
  - **cada módulo novo traz um docstring e imports.** O core tem 105 arquivos
    onde o código dele tinha 69.
- **O SDK dobrou,** com duas operações (cerca de 470 linhas), resultados e
  leitores tipados (#213), a linha de comando e o cancelamento (ADR-0019).
- **A complexidade residual permanece concentrada onde estava.** São 46 funções
  acima de 15 no serviço e no core somados (contra 48 na referência; 41 no
  core isolado), e a mais complexa continua sendo a mesma. A refatoração moveu
  responsabilidades de propósito, uma por pull request e sem mudar
  comportamento, então não simplificou a lógica interna das funções. As cinco
  funções mais complexas do core:

  | Função | Módulo | Complexidade | Linhas |
  |---|---|---:|---:|
  | `_derive_v23_processing_needs` | `manifest/builder.py` | 71 (73 na referência) | 269 |
  | `apply_page_routes` | `pipeline/fusion.py` | 35 | 100 |
  | `_execute_step` | `execution/executor.py` | 33 | 161 |
  | `_absorb_near_pictures` | `manifest/slides.py` | 33 | 80 |
  | `_extract_with` | `manifest/toolbox_extractor.py` | 33 | 234 |

  Das 41 funções complexas do core, 24 estão em `pipeline` e 9 em `manifest`.

## 2. Custo de uma instalação isolada

| Instalação | Pacotes | `site-packages` | Tempo |
|---|---:|---:|---:|
| docstruct sozinho | 1 | 0,75 MB | cerca de 1 s |
| SDK (com o docstruct) | 10 | 2 MB | cerca de 1 s |
| core (com o SDK e o docstruct) | 57 | 102 MB | cerca de 3 s |
| o serviço (as dependências de execução do repositório) | 75 | 119 MB | cerca de 3 s, com cache |

- **Um script que só precisa da Toolbox e dos algoritmos estruturais instala
  10 pacotes e 2 MB:** o `httpx` e as dependências dele, o SDK e o docstruct.
  Na referência, o SDK dependia só do `httpx`, e o core não podia ser
  instalado sem o serviço.
- **O core sozinho pesa quase o mesmo que o serviço.** O peso vem da pilha de
  agentes: `babel` (32 MB), `agno` (19 MB) e `openai` (10 MB) são os maiores
  pacotes. O serviço acrescenta 18 pacotes e 17 MB (FastAPI, uvicorn,
  aiogram, SQLAlchemy e o resto).
- **O CI confere cada um sozinho:** os jobs `docstruct alone`, `SDK alone` e
  `core alone` instalam a partir do próprio lock e recusam o que não pode ser
  importável junto deles.

## 3. Dependências externas por componente

Dependências de execução declaradas em cada `pyproject.toml`:

| Componente | Quantidade | Dependências |
|---|---:|---|
| docstruct | 0 | nenhuma: só a biblioteca padrão, com um acelerador opcional atrás de `except ImportError` |
| SDK | 2 | `httpx`, docstruct |
| core | 11 | docstruct, o SDK, `agno`, `openai`, `ollama`, `pydantic`, `loguru`, `babel`, `jsonschema`, `rapidfuzz`, `edge-tts` |
| serviço | 22 | o core, o SDK e o docstruct, mais a pilha de web, bot, e-mail, banco de dados e configuração |
| Toolbox | 5 | mais sete extras (`api`, `cache`, `media`, `music`, `pdf`, `storage`, `dev`) para os providers |

A direção das dependências é conferida por testes:
- o docstruct não importa nenhum pacote do projeto e não acessa rede,
  ambiente, arquivos nem processos (`test_purity.py`, `test_infrastructure.py`);
- o SDK não importa o core nem a Toolbox (`libs/sdk/tests/test_purity.py`);
- o core não importa nada do serviço (`libs/core/tests/test_boundary.py`) e
  usa só a API pública do SDK (ADR-0018, `tests/test_sdk_public_api.py`);
- a Toolbox não importa o SDK nem o core (o `test_architecture.py` dela).

## 4. Tempo dos testes locais

| Suíte | Funções de teste, referência → agora | Tempo agora |
|---|---:|---:|
| principal (`tests/`, `-n 4`) | 1.512 → 1.497 | 111 s |
| docstruct (`libs/docstruct/tests`) | 808 → 978 | 6–9 s |
| SDK (`libs/sdk/tests`) | 203 → 388 | 11–17 s |
| core (`libs/core/tests`) | nenhuma → 755 | 30 s |

- **As suítes das bibliotecas rodam sozinhas em segundos,** então uma mudança
  no docstruct ou no SDK tem retorno sem a suíte principal.
- **A suíte principal ainda é a maior parte do tempo**, mas agora tem os
  testes do serviço e da API; a suíte do core roda em cerca de 30 s no próprio
  ambiente. Os testes do core saíram de `tests/` para `libs/core/tests` no
  #613, junto com o de fronteira e o de fumaça.
- As suítes da referência não foram cronometradas: o ambiente delas não pode
  ser refeito como era, então só as contagens são comparadas.
- As contagens e os tempos de principal/core são a medição pós-#613/#612 (uma
  execução local); o resto desta página está em `ec3ddf0b`.

## 5. Reaproveitamento das operações

O SDK tem duas operações, a cadeia de fórmula e o juiz de página (ADR-0017).
Quem as chama fora do SDK:

| Chamador | Usa |
|---|---|
| o enriquecimento de fórmulas do core | `crop_formula_region`, `recognize_formula`, `convert_formula`, `verbalize_formula` (#507, #509) |
| o juiz de página do core | `render_judge_page`, `judge_page` (#607) |
| a linha de comando do SDK | o `python -m acessilia_sdk formula` roda a cadeia de fórmula a partir do wheel do próprio SDK |
| `scripts/bench` | clientes do SDK (datasets, o catálogo da Toolbox), mas nenhuma operação |

**Nenhum script ou benchmark deste repositório chama uma operação ainda.** O
juiz de página não tem um comando próprio. O repositório de benchmark não foi
medido aqui.

## 6. Regressões

**Estruturais:** cada mudança de lugar foi conferida por si, com a evidência no
seu pull request:
- AST idêntica, um teste diferencial de 20.000 casos e um mutante para cada
  mudança para fora do orquestrador (#454 a #493);
- testes diferenciais contra o código da develop para a cadeia de fórmula
  (#507, #509);
- testes de paridade ou de caracterização commitados para as mudanças mais
  recentes (#596, #600, #607), com qualquer diferença declarada.

**Funcionais:**
- **O caso 036 deu igual antes e depois de a cadeia de fórmula ir para o SDK**
  (aceitação da ADR-0017, #511): 0 diferenças nas 16 fórmulas.
- **Depois de o core ir para `libs/core` (#572),** o staging processou o caso
  036 em 2026-11-18 com todas as saídas entregues e o PDF/UA conforme. Um
  título regrediu, mas a causa é a extração da Toolbox
  (acessilia-toolbox#162): os manifestos do core são idênticos antes e depois
  da mudança.
- **Em aberto:** o caso 006 (slides) não foi comparado no staging desde a
  mudança.

## Consequências observadas

- **As fronteiras agora são regras testadas, não convenções.** Cada componente
  instala e roda sozinho no CI. A direção das dependências, a independência do
  core em relação ao serviço e o uso só da API pública do SDK são guardados
  por testes, e o core, o SDK e a Toolbox conferem os seus modelos contra um
  só catálogo de casos (`docstruct.manifest_cases`).
- **Os scripts ganharam um caminho leve:** 10 pacotes e 2 MB dão os clientes
  da Toolbox, duas operações e os algoritmos estruturais, sem agentes nem o
  serviço.
- **A refatoração não reduziu a complexidade de forma expressiva, de propósito.** Ela
  pôs o código onde ele pertence e manteve o comportamento. O número de funções
  complexas caiu levemente (48 → 46 no serviço e core somados; 41 no core
  isolado), mas as funções complexas continuam basicamente as mesmas, agora em
  módulos menores com uma responsabilidade cada, o que as torna os próximos alvos.
- **O core não é leve,** porque os agentes dele precisam do `agno`, do
  `openai` e do `babel`. Quem só quer as partes determinísticas do core ainda
  instala a pilha de agentes.

## Próximos passos sugeridos

1. ~~**Simplificar as funções complexas:** as cinco acima primeiro, começando
   pelo `_derive_v23_processing_needs` (complexidade 71). É a modularização
   interna que a #381 pedia, agora sobre módulos com fronteiras claras.~~
   Feito no #612 (`_derive_v23_processing_needs` → `manifest/detectors/`,
   mais `apply_page_routes`, `_execute_step`, `_absorb_near_pictures`,
   `_extract_with` e as demais funções complexas e longas; funções acima de 15
   no core: 41 → 0; funções acima de 100 linhas no core: 21 → 0; todos os
   módulos de `libs/core/src` abaixo do limite de 900 linhas).
2. ~~**Levar para o `libs/core/tests` os testes do core** que testam só o core,
   para a suíte dele rodar sem o serviço.~~ Feito no #613.
3. **Dar uso às operações:** um comando `judge` na linha de comando do SDK, e
   o benchmark de matemática (`scripts/bench`) sobre a cadeia de fórmula em vez
   do core.
4. **Comparar o caso 006 no staging** depois da mudança.
5. **Decidir se a pilha de agentes deve ser um extra do core,** caso algum
   chamador precise do core sem agentes. Nada pede isso hoje.
