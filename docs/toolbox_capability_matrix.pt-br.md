# Matriz de capacidades Toolbox × core

> Você também pode ler esta documentação em **inglês**: [English](toolbox_capability_matrix.md)

Esta é a fonte de verdade única para o contrato entre o core
(`A11yDevs/acessilia`) e o gateway de capacidades (`A11yDevs/acessilia-toolbox`).
Ela é verificada mecanicamente por `scripts/check_capability_contract.py` e por
`tests/test_toolbox_contract_drift.py`.

## Por que isto existe

O core alcança a Toolbox fixando em código ids de capacidade e de provider que são
declarados em outro repositório. Nada verificava se os dois lados continuavam de
acordo, então renomear uma capacidade no lado da Toolbox produzia um cliente que só
podia falhar em tempo de execução — a falha aparecia como `ToolboxCapabilityError` em
um documento de usuário, não como build quebrado.

A matriz abaixo é o *contrato*. O verificador a compara com uma Toolbox em execução
(`--url`) ou com o fixture capturado (`tests/fixtures/toolbox-contract.json`,
regerado com `scripts/capture_toolbox_contract.py`).

## Pontos de acionamento exigidos por capacidade

Uma capacidade só é *acionável* no core quando os quatro elos existem. A falta
de um elo identifica uma lacuna de integração; não prova que a capacidade seja
morta. Para capacidades Dr.DocBench, investigue especialmente o caminho
evidência → obrigação → `problem.pddl` → método → handler → efeito verificável,
sem descartar a capacidade por falta de acionamento atual.

| Elo | Artefato | Local |
|---|---|---|
| Entrada no registro | `ToolboxCapability` (id, versão, configuração de provider, schema de saída) | `libs/sdk/src/acessilia_sdk/toolbox/capabilities.py` |
| Cliente | subclasse de `ToolboxCapabilityClient` chamando o id registrado, criada no core com `make_toolbox_client` | `libs/sdk/src/acessilia_sdk/toolbox/clients/*.py` |
| Default de provider | `PROVIDER_DEFAULTS`, lido por `TOOLBOX_*_PROVIDER` no `Settings` | `libs/sdk/src/acessilia_sdk/toolbox/capabilities.py` |
| Manifest | `capabilities/*.yaml` | `acessilia-toolbox` |
| Registro do provider | entrada em `providers-config.yaml` com adapter | `acessilia-toolbox` |

Para o trabalho guiado por planejamento há dois elos adicionais: a entrada de
obrigação/método em `DEFAULT_METHOD_COSTS` (`backend/core/manifest/builder.py`),
um handler registrado em `PddlAccessibilityOrchestrator._build_executor`
(`backend/agents/pddl_orchestrator.py`) e uma evidência real que faça o
compilador emitir os fatos necessários em `problem.pddl`.

## Matriz

Legenda de **Caminho de chamada**: como o core alcança a capacidade.

| Capacidade | Cliente | Default de provider no core | Provider na Toolbox | Caminho de chamada |
|---|---|---|---|---|
| `document.structure.extract` | `acessilia_sdk/toolbox/clients/structure.py` | `TOOLBOX_PROVIDER=docling` | `docling`, `mineru`, `nougat`, `teleocr` | `ToolboxManifestExtractor` → extração do PDDL; com `FUSION_MODE=dual`, também compara o provider secundário e repassa evidências por página ao builder do manifesto |
| `document.layout.analyze` | `acessilia_sdk/toolbox/clients/layout.py` | `TOOLBOX_LAYOUT_PROVIDER=docling-layout` | `docling-layout`, `mineru-layout` | `ToolboxLayoutStructurer` via `STRUCTURER=toolbox-layout` |
| `document.ocr` | `acessilia_sdk/toolbox/clients/ocr.py` | `TOOLBOX_OCR_PROVIDER=docling-ocr` | `docling-ocr`, `mineru-ocr` | `toolbox_ocr_tools.py` (wrapper Agno) |
| `math.recognize` | `acessilia_sdk/toolbox/clients/math.py` | `TOOLBOX_MATH_RECOGNIZE_PROVIDER=docling-math` | `docling-math`, `rapid-latex-ocr` | `toolbox_math_tools.py` |
| `math.convert` | `acessilia_sdk/toolbox/clients/math.py` | `TOOLBOX_MATH_PROVIDER=pure-math` | `pure-math` | `toolbox_math_tools.py` |
| `math.verbalize` | `acessilia_sdk/toolbox/clients/math.py` | `TOOLBOX_MATH_PROVIDER=pure-math` | `pure-math` | `toolbox_math_tools.py` |
| `pdf.split` | `acessilia_sdk/toolbox/clients/pdf.py` | `TOOLBOX_PDF_PROVIDER=pymupdf-pdf` | `pymupdf-pdf` | sem chamador no core; o split local (`pdf_splitter.py`, pypdf) segue como caminho de produção |
| `pdf.render` | `acessilia_sdk/toolbox/clients/pdf.py` | `TOOLBOX_PDF_PROVIDER=pymupdf-pdf` | `pymupdf-pdf` | método PDDL `vision-page-inspection` (páginas sem estrutura extraída); `pymupdf-region` e o juiz ainda renderizam páginas localmente com PyMuPDF (desvio, ADR-0003) |
| `media.inspect` | `acessilia_sdk/toolbox/clients/media_inspect.py` | `TOOLBOX_MEDIA_INSPECT_PROVIDER=pure-media-inspect` | `pure-media-inspect` | `backend/tools/media_inspect.py` (só na Toolbox; sem fallback local, ADR-0003), pulado quando `TOOLBOX_MEDIA_INSPECT_ENABLED=false` |
| `document.export.pdf_ua` | `acessilia_sdk/toolbox/clients/pdf_ua.py` | `TOOLBOX_PDF_UA_PROVIDER=pandoc-pdf-ua` | `pandoc-pdf-ua` (sidecar `pdf-ua-render`) | `backend/export/pandoc_exporter.py` (só na Toolbox, PDF baixado e verificado de `/v1/artifacts`; sem fallback local, ADR-0003), pulado quando `TOOLBOX_PDF_UA_ENABLED=false` |
| `artifact.store` / `artifact.retrieve` | `acessilia_sdk/toolbox/clients/artifact.py` (REST `/v1/artifacts`) | — | `minio`, `filesystem` | upload antes da extração |
| `dataset.*` (8 capacidades) | `acessilia_sdk/toolbox/clients/dataset.py` (REST `/v1/datasets`) | — | `dataset-github`, `dataset-huggingface` | `toolbox_dataset_tools.py` (scripts do Dr.DocBench) |
| `document.ocr.page` | `acessilia_sdk/toolbox/clients/page_ocr.py` | `TOOLBOX_PAGE_OCR_PROVIDER=qwen3-vl-8b` | `qwen3-vl-8b` (acessilia-toolbox#50) | publicada; nenhum método PDDL a chama ainda |
| `document.adjudicate.page` | `acessilia_sdk/toolbox/clients/adjudicate.py` | `TOOLBOX_ADJUDICATE_PROVIDER=qwen3-vl-8b` | `qwen3-vl-8b` (acessilia-toolbox#50) | `vlm-pairwise-judge` em `adjudicate-page`; limiares a revalidar no modelo 8B |
| `document.adjudicate.region` | `acessilia_sdk/toolbox/clients/adjudicate.py` | `TOOLBOX_ADJUDICATE_PROVIDER=qwen3-vl-8b` | `qwen3-vl-8b` (acessilia-toolbox#50) | publicada; handler do `rescue-omitted` pendente |
| `table.recognize` | `acessilia_sdk/toolbox/clients/table.py` | `TOOLBOX_TABLE_PROVIDER=qwen3-vl-8b` | `qwen3-vl-8b` (acessilia-toolbox#50) | publicada; handler do `table-specialist` pendente (regra de seleção a decidir) |
| `image.page.orient` | `acessilia_sdk/toolbox/clients/orientation.py` | `TOOLBOX_ORIENTATION_PROVIDER=rapidocr-orient` | `rapidocr-orient` | contrato válido; falta gatilho PDDL e validação do efeito em produção |
| `accessibility.mark` | **ausente** | — | `pure-accessibility` | pendente: cliente e obrigação/método/handler acionados por evidência |
| `chem.convert` | **ausente** | — | `pure-chem` | pendente: cliente e obrigação/método/handler acionados por evidência |
| `chem.recognize` | **ausente** | — | `docling-chem` | pendente: cliente e obrigação/método/handler acionados por evidência |
| `code.normalize` | **ausente** | — | `pure-code` | pendente: cliente e obrigação/método/handler acionados por evidência |
| `text.postprocess` | **ausente** | — | `pure-text` | pendente: cliente e obrigação/método/handler acionados por evidência |
| `music.omr` | **ausente** | — | `homr`, `audiveris` | pendente: cliente e obrigação/método/handler acionados por evidência |
| `cache.get` / `cache.put` | — (interno) | — | `valkey` | cache interno da Toolbox; não é capacidade pública |

## Deriva confirmada (no momento da revisão)

Medida contra a Toolbox de homologação em execução com
`python scripts/check_capability_contract.py --snapshot tests/fixtures/toolbox-contract.json`:

1. A REST genérica publicada expõe
   `POST /v1/capabilities/{capability_id}:execute`; os schemas específicos ficam
   disponíveis em `GET /v1/capabilities/{capability_id}`. OpenAPI ao vivo:
   `https://www.acessilia3.inf.ufg.br/toolbox/v1/openapi.json` (UI:
   `/toolbox/v1/docs`). Ela não define rotas específicas por capacidade.
2. Resolvido pelo acessilia-toolbox#50: `document.ocr.page`,
   `document.adjudicate.page` e `document.adjudicate.region` são publicadas pelo
   provider `qwen3-vl-8b`, e os defaults do SDK apontam para ele (antes citavam
   `qwen3-vl-page` e `qwen3-vl-judge`, do perfil de 32B dos experimentos).
3. O `KNOWN_DRIFT` está vazio contra o catálogo do develop da Toolbox; a
   homologação ainda roda uma imagem anterior ao #50 até ser reimplantada.
4. Seis capacidades não têm nenhum cliente no core (ver a matriz).

A deriva de contrato de orientação foi resolvida: o cliente postava em
`document.orientation.detect` com provider `rapidocr-orientation`, nenhum dos dois
conhecido pela Toolbox, enquanto a Toolbox expõe `image.page.orient` implementada
por `rapidocr-orient`. O cliente e o default agora batem com o catálogo. O cliente
continua sem gatilho PDDL de produção; isso é uma lacuna de modelagem/integração,
não motivo para aposentar uma capacidade Dr.DocBench.

A deriva conhecida está fixada em `tests/test_toolbox_contract_drift.py`; qualquer
deriva *nova* quebra a suíte, e corrigir um achado exige removê-lo da lista fixada.

## Acionabilidade do PDDL (medida contra a Toolbox real)

### Estado antes da correção

Rodar o pipeline PDDL localmente contra a Toolbox de homologação com
`PDDL_EXECUTE_DRY_RUN=false` falhava na primeira obrigação:

```
obligations: 7  kinds: {preserve-code-semantics: 6, describe-image: 1}
plan steps: 9
  1 execute-obligation describe-image vision-description cost=20
REAL execution status: failed   failed_step: 1   replan_required: False
  step 1 vision-description status=failed msg='RuntimeError: No handler registered for vision-description'
```

`PddlAccessibilityOrchestrator._build_executor` registrava 3 handlers reais
(`mathml`, `latex-verbalizer`, `dual-provider-fusion`) mais um fallback no-op para
8 nomes, ou seja, 11 dos 24 métodos de `DEFAULT_METHOD_COSTS` estavam registrados e
20 não estavam. O conjunto admissível é um pouco menor que a tabela de custos: as
tabelas de obrigação (`OBLIGATION_BY_TYPE` e `V23_OBLIGATION_BY_KIND`) admitem 23
métodos, dos quais 19 não tinham handler. Todo passo de plano cujo método fosse um
desses levantava exceção em tempo de execução, sem retentativa nem degradação.

Pior: o fallback no-op retornava `success=True, validated=True` com a mensagem
*"Handler padrão (sem operação real)"*. Oito nomes de método, portanto, marcavam
obrigações como **satisfeitas** sem fazer absolutamente nada — uma mentira silenciosa
que fazia a suíte passar na `develop`.

`replan_required` permanecia `False` por um motivo diferente de "alternativas
esgotadas": o `Executor` levanta `EXE_NO_HANDLER_REGISTERED` quando `handler is None`,
e esse raise fica *fora* do `try/except` que calcula `alternatives` e liga a flag. A
flag nunca era avaliada para um método não registrado.

Além disso, `executar()` só invocava o executor dentro de `if self.execute_dry_run:`,
então `PDDL_EXECUTE_DRY_RUN=false` produzia **execução nenhuma** e
`execution_report=None`. O default de dry-run era o que mantinha o pipeline parecendo
saudável; desligá-lo pulava a execução em vez de expor a lacuna.

### Estado depois da correção

- **Todo método admissível está contabilizado.** Cada um resolve para um handler
  registrado ou é reportado ao planejador como indisponível;
  `tests/test_pddl_actionability.py` falha para qualquer método que não seja nenhum
  dos dois.
- **18 handlers registrados** (antes: 3 reais + 8 no-op): os 3 com modelo,
  `single-provider` como fallback executável e 13 handlers determinísticos
  cobrindo `vision-description`, `pandoc-table`,
  `pandoc-code`, `pymupdf-region`, `latex-normalizer`, `norm-fix`, `rep-guard`,
  `line-number-extractor`, `verse-chunker`, `tailjoin`, `tailjoin-positioned`,
  `xycut-order` e `deterministic-heading-repair`; `human-review` é o handler
  explícito de escalonamento terminal.
  `single-provider` é selecionado pelo replanejamento após a rejeição de uma
  fusão dual; o teste de regressão verifica a execução e o artefato produzido.
- **O no-op silencioso foi eliminado.** Um handler que declara sucesso precisa
  marcar `validated=True` sobre trabalho real.
- **`human-review` tem semântica própria.** É o escalonamento terminal que toda
  obrigação lista por último. Ele reporta `success=False` com mensagem explícita de
  escalonamento, em vez de marcar como satisfeita uma obrigação que nenhum método
  automático cumpriu.
- **O planejador sabe o que está indisponível.** `_unavailable_methods(manifest)`
  restringe o conjunto aos métodos que o manifesto realmente declara (o compilador
  rejeita nomes desconhecidos), então `_validate_methods` falha cedo, em tempo de
  plano, em vez de deixar um passo inexequível chegar ao executor.
- **`PDDL_EXECUTE_DRY_RUN` agora escolhe o modo, não se a execução acontece.**
- **`replan-required` deixou de ser terminal.** `executar()` replaneja até
  `PDDL_MAX_REPLANS` vezes (padrão 2), reutilizando o estado `(tried ?o ?m)` que o
  executor registrou, de modo que um método que falhou passa para o próximo
  admissível.

### P2: obrigações v2.3 baseadas em evidências

O builder do manifesto agora deriva obrigações v2.3 de evidências determinísticas:
mudanças reais de normalização de texto/fórmula, reordenação de leitura, junções
elegíveis de cauda, fragmentação de verso e extração de números marginais. As
obrigações de fusão entre providers só são emitidas quando a extração carrega
evidências de fusão por página; divergência de texto, blocos descartados, decisões
de fonte de tabela e cortes de repetição não são inferidos a partir de um manifesto
de provider único. As obrigações já fornecidas pela Toolbox são preservadas, e as
novas são deduplicadas por tipo e alvo.

O pipeline de fusão agora exporta contadores de decisão por página e a contagem de
cortes por repetição, sem copiar o texto dos providers para o manifesto. Essas
evidências permitem distinguir um problema observado de uma capacidade que apenas
existe no catálogo PDDL. Sete métodos ainda não têm handler executável e continuam
fora dos planos até os dados candidatos ou contratos REST necessários estarem
disponíveis. Isso é uma pendência de integração, não uma decisão de descartar as
capacidades Dr.DocBench. A especificação REST própria para OCR de página e
adjudicação está pendente do responsável pelos serviços.

### Evidência ao vivo

Contra a Toolbox de homologação, `001.pdf`, `PDDL_EXECUTE_DRY_RUN=false`:

```
plan steps: 9
status: completed
  [0] start-job                          -> succeeded
  [1] execute-obligation vision-description -> succeeded
      "Descrição validada para 1 imagem(ns)"
```

Antes da correção a mesma entrada produzia `failed` com
`RuntimeError: No handler registered for vision-description`.

### Gate de disponibilidade do planejador

Métodos indisponíveis continuam na lista admissível do manifesto para manter a
rastreabilidade, mas o compilador não emite `(available <método>)` para eles. A
ação PDDL `execute-obligation` exige `(available ?m)`, então o Fast Downward não
pode selecioná-los. O planejador interno aplica a mesma projeção diretamente, e
o runtime valida planos externos contra ela antes da execução.
`tests/test_pddl_planning.py::test_fast_downward_respects_unavailable_methods`
regrede tanto os fatos de disponibilidade compilados quanto a rejeição de um
plano externo inválido.

## Vereditos

Os vereditos por capacidade (integrar / manter opt-in / aposentar) e sua
justificativa são rastreados em `docs/toolbox_capability_verdicts.md`.
