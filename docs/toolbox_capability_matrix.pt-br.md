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

## Vereditos

Os vereditos por capacidade (integrar / manter opt-in / aposentar) e sua
justificativa são rastreados em `docs/toolbox_capability_verdicts.md`.
