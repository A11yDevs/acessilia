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

Uma capacidade só é *acionável* no core quando os quatro elos existem. Uma capacidade
sem qualquer elo é uma capacidade morta do ponto de vista do produto.

| Elo | Artefato | Local |
|---|---|---|
| Cliente | `Toolbox*Client` com o id da capacidade | `backend/tools/toolbox_*_client.py` |
| Default de provider | `TOOLBOX_*_PROVIDER` (ou `TOOLBOX_PROVIDER`) | `backend/config/settings.py` |
| Manifest | `capabilities/*.yaml` | `acessilia-toolbox` |
| Registro do provider | entrada em `providers-config.yaml` com adapter | `acessilia-toolbox` |

Para o trabalho guiado por planejamento há dois elos adicionais: a entrada de
obrigação/método em `DEFAULT_METHOD_COSTS` (`backend/core/manifest/builder.py`) e um
handler registrado em `PddlAccessibilityOrchestrator._build_executor`
(`backend/agents/pddl_orchestrator.py`).

## Matriz

Legenda de **Caminho de chamada**: como o core alcança a capacidade.

| Capacidade | Cliente no core | Default de provider no core | Provider na Toolbox | Caminho de chamada |
|---|---|---|---|---|
| `document.structure.extract` | `toolbox_client.py` (URL inline) | `TOOLBOX_PROVIDER=docling` | `docling`, `mineru`, `nougat`, `teleocr` | `ToolboxManifestExtractor` → extração do PDDL |
| `document.layout.analyze` | `toolbox_layout_client.py` | `TOOLBOX_LAYOUT_PROVIDER=docling-layout` | `docling-layout`, `mineru-layout` | `ToolboxLayoutStructurer` via `STRUCTURER=toolbox-layout` |
| `document.ocr` | `toolbox_ocr_client.py` | `TOOLBOX_OCR_PROVIDER=docling-ocr` | `docling-ocr`, `mineru-ocr` | `toolbox_ocr_tools.py` (wrapper Agno) |
| `math.recognize` | `toolbox_math_client.py` | `TOOLBOX_MATH_RECOGNIZE_PROVIDER=docling-math` | `docling-math`, `rapid-latex-ocr` | `toolbox_math_tools.py` |
| `math.convert` | `toolbox_math_client.py` | `TOOLBOX_MATH_PROVIDER=pure-math` | `pure-math` | `toolbox_math_tools.py` |
| `math.verbalize` | `toolbox_math_client.py` | `TOOLBOX_MATH_PROVIDER=pure-math` | `pure-math` | `toolbox_math_tools.py` |
| `pdf.split` | `toolbox_pdf_client.py` | `TOOLBOX_PDF_PROVIDER=pymupdf-pdf` | `pymupdf-pdf` | `toolbox_pdf_tools.py` (valida e divide localmente) |
| `pdf.render` | `toolbox_pdf_client.py` | `TOOLBOX_PDF_PROVIDER=pymupdf-pdf` | `pymupdf-pdf` | `toolbox_pdf_tools.py` (fallback local via PyMuPDF) |
| `media.inspect` | `toolbox_media_inspect_client.py` | `TOOLBOX_MEDIA_INSPECT_PROVIDER=pure-media-inspect` | `pure-media-inspect` | `backend/tools/media_inspect.py`, controlado por `TOOLBOX_MEDIA_INSPECT_ENABLED` |
| `artifact.store` / `artifact.retrieve` | `toolbox_client.py` REST `/v1/artifacts` | — | `minio`, `filesystem` | upload antes da extração |
| `dataset.*` (8 capacidades) | `toolbox_client.py` REST `/v1/datasets` | — | `dataset-github`, `dataset-huggingface` | `toolbox_dataset_tools.py` (scripts do Dr.DocBench) |
| `document.ocr.page` | `toolbox_page_ocr_client.py` | `TOOLBOX_PAGE_OCR_PROVIDER=qwen3-vl-page` | **ausente** | **sem chamador** |
| `document.adjudicate.page` | `toolbox_adjudicate_client.py` | `TOOLBOX_ADJUDICATE_PROVIDER=qwen3-vl-judge` | **ausente** | **sem chamador** |
| `document.adjudicate.region` | `toolbox_adjudicate_client.py` | `TOOLBOX_ADJUDICATE_PROVIDER=qwen3-vl-judge` | **ausente** | **sem chamador** |
| `image.page.orient` | `toolbox_orientation_client.py` | `TOOLBOX_ORIENTATION_PROVIDER=rapidocr-orient` | `rapidocr-orient` | contrato válido, **ainda sem chamador de produção** |
| `accessibility.mark` | **ausente** | — | `pure-accessibility` | — |
| `chem.convert` | **ausente** | — | `pure-chem` | — |
| `chem.recognize` | **ausente** | — | `docling-chem` | — |
| `code.normalize` | **ausente** | — | `pure-code` | — |
| `text.postprocess` | **ausente** | — | `pure-text` | — |
| `music.omr` | **ausente** | — | `homr`, `audiveris` | — |
| `cache.get` / `cache.put` | — (interno) | — | `valkey` | cache interno da Toolbox; não é capacidade pública |

## Deriva confirmada (no momento da revisão)

Medida contra a Toolbox de homologação em execução com
`python scripts/check_capability_contract.py --snapshot tests/fixtures/toolbox-contract.json`:

1. Três capacidades são consumidas pelo core mas não existem no catálogo da
   Toolbox: `document.ocr.page`, `document.adjudicate.page`,
   `document.adjudicate.region`.
2. Dois defaults de provider em `settings.py` apontam para providers que a Toolbox
   não registra: `qwen3-vl-page`, `qwen3-vl-judge`.
3. Seis capacidades não têm nenhum cliente no core (ver a matriz).

A deriva de orientação foi resolvida: o cliente postava em
`document.orientation.detect` com provider `rapidocr-orientation`, nenhum dos dois
conhecido pela Toolbox, enquanto a Toolbox expõe `image.page.orient` implementada
por `rapidocr-orient`. O cliente e o default agora batem com o catálogo. O cliente
continua sem chamador de produção, então o veredito dele é
"integrar ou aposentar", não "concluído".

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
- **15 handlers registrados** (antes: 3 reais + 8 no-op): os 3 com modelo mais 12
  handlers determinísticos cobrindo `vision-description`, `pandoc-table`,
  `pandoc-code`, `pymupdf-region`, `latex-normalizer`, `norm-fix`,
  `line-number-extractor`, `verse-chunker`, `tailjoin`, `tailjoin-positioned`,
  `deterministic-heading-repair`. Eles *validam* o trabalho que o pipeline já
  realizou, em vez de fingir realizá-lo.
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

Nove métodos permanecem **declarados indisponíveis** em vez de implementados:
`skeleton-order`, `xycut-order`, `agreement-rule`, `rep-guard`, `rescue-omitted`,
`single-provider`, `table-smart-fusion`, `table-specialist`, `vlm-pairwise-judge`.
Todos são métodos v2.3 que dependem de divergência entre providers ou de um juiz
VLM; o planejador nunca emite um passo para eles hoje. Estão listados como catraca
em `KnownUnavailable` dentro do arquivo de teste, então implementar um deles quebra
o teste até que seja removido da lista.

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

### Pendente

`_validate_methods` só levanta quando uma obrigação tem **zero** candidatos
disponíveis. Quando um método declarado indisponível pelo compilador simplesmente
desaparece do problema compilado enquanto a lista admissível do manifesto ainda o
contém, o planejador ainda recebe um método que não pode rodar: o predicado
`available` só é emitido para `available_methods`, e o `InternalReferencePlanner`
filtra por ele, mas o `FastDownwardPlanner` depende da precondição do domínio.
Ainda não corrigido.

## Vereditos

Os vereditos por capacidade (integrar / manter opt-in / aposentar) e sua
justificativa são rastreados em `docs/toolbox_capability_verdicts.md`.
