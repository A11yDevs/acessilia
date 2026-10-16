# Integração de ferramentas da Toolbox ao core

Você também pode ler esta documentação em **inglês**: [English](toolbox_integration.md)

## Propósito

Este guia explica como integrar ao **core** (o backend de Acessilia) uma ferramenta
recém-disponibilizada na **Acessilia Toolbox** — o serviço remoto que oferece
capacidades de extração de estrutura, layout, OCR, matemática e PDF. Distingue os dois
cenários possíveis e define a política de implementação entre **tools locais**
(`libs/`) e **tools da Toolbox**.

> A Toolbox vive em um repositório separado (`A11yDevs/acessilia-toolbox`). Este
> documento cobre **só o lado do core**: como consumir uma capacidade nova, não como
> implementar a capacidade na Toolbox.

---

## 1. Contrato da Toolbox visto pelo core

O core conversa com a Toolbox por HTTP. Todos os clientes vivem em `backend/tools/` e
compartilham o mesmo padrão:

| Endpoint | Método | Uso |
|---|---|---|
| `/v1/health` | `GET` | Verificação de disponibilidade |
| `/v1/capabilities` | `GET` | Descoberta de capacidades e providers disponíveis |
| `/v1/capabilities/{capability}:execute` | `POST` | Executa uma capacidade (form: `file` ou `artifact_id`, `language`, `provider`, `no_cache`) |
| `/v1/artifacts` | `POST` / `GET` | Upload / download de artefatos (artifact store) |
| `/v1/datasets` | `GET` / `POST` | Listagem e sincronização de datasets |

Uma resposta de extração bem-sucedida tem a forma:

```json
{
  "status": "succeeded",
  "provider": "docling",
  "provenance": {
    "duration_ms": 1234,
    "provider_version": "1.2.3",
    "cache_key": "abc123"
  },
  "document": {
    "elements": [
      {"type": "text", "text": "...", "bbox": [0, 0, 100, 50], "page": 1, "reading_order": 0, "page_size": [595, 842], "coord_origin": "top-left"}
    ]
  }
}
```

**Ponto-chave:** o core **não registra quais providers existem**. A única tabela de
providers do core é `PROVIDER_DEFAULTS`, em `libs/sdk/src/acessilia_sdk/toolbox/capabilities.py`, que
guarda o provider padrão de cada capacidade. Ela não lista os providers existentes nem
faz roteamento. O `provider` é apenas uma string enviada no form; o roteamento real
acontece no `providers-config.yaml` da Toolbox. A validação de que um provider existe é feita do lado da Toolbox — quando
falha, o core recebe `ToolboxCapabilityError` ou `ToolboxContractViolation`.

### Hierarquia de exceções

Todas herdam de `ToolboxError` (definida no SDK, `acessilia_sdk.toolbox.errors`, e re-exportada por `backend/tools/toolbox_client.py`):

- `ToolboxProviderUnavailable` — serviço/provedor indisponível (ex.: HTTP 503)
- `ToolboxTimeout` — excedeu `toolbox_timeout_seconds`
- `ToolboxUnsupportedMediaType` — tipo de mídia não suportado
- `ToolboxArtifactNotFound` — artefato inexistente
- `ToolboxContractViolation` — resposta fora do contrato (ex.: `status != "succeeded"`)
- `ToolboxCapabilityError` — capacidade/provedor desconhecido
- `ToolboxAuthenticationError` — credenciais inválidas

---

## 2. Tools locais vs. tools da Toolbox

### 2.1 Diferença arquitetural

| Aspecto | Tool local (`libs/`) | Tool da Toolbox |
|---|---|---|
| **Onde roda** | No processo do core (mesma máquina/container) | Serviço remoto HTTP (`TOOLBOX_BASE_URL`, porta 8002) |
| **Exemplos** | `libs/docstruct/` — `docstruct.fusion`, `docstruct.policy.FusionPolicy`, `docstruct.types.CanonicalBlock`; fallback PyMuPDF em `backend/tools/structurer.py` | `document.structure.extract`, `document.layout.analyze`, `document.ocr`, `math.*`, `pdf.split` |
| **Interface** | Import Python direto (função/classe pura) | `ToolboxClient` / clientes especializados → `POST /v1/capabilities/{capability}:execute` |
| **Falha** | Exceção Python local | `ToolboxError` → subclasses tipadas |
| **Estado/cache** | Em memória / disco local | Artifact store (`/v1/artifacts`) + cache remoto (`cache_key` na provenance) |
| **Versionamento** | Acoplado ao repo do core (mesmo commit) | Independente (`provider_version` na provenance) |

### 2.2 Política de decisão

**Implementar local (`libs/`) quando:**

- É uma transformação pura sobre dados já canônicos (fusão de blocos, agrupamento,
  políticas de decisão) — não precisa de I/O de rede.
- Precisa rodar offline / sem dependência de rede.
- Precisa de garantia determinística e versionamento atômico com o core.

**Expor via Toolbox quando:**

- Exige modelo/infraestrutura pesada (GPU, motores de OCR, docling-serve, mineru-serve).
- Faz sentido compartilhar entre múltiplos consumidores (core, drbench, clientes futuros).
- Evolui em cadência própria (ex.: trocar a versão do MinerU sem tocar no core).

### 2.3 A ponte: wrapper com fallback local

Quando uma capacidade da Toolbox tem equivalente local, o core usa um **wrapper de
tool Agno com fallback local**: tenta a Toolbox primeiro e, se estiver indisponível,
degrada para a implementação local. É exatamente o padrão de `toolbox_ocr_tools.py`,
`toolbox_math_tools.py` e `toolbox_pdf_tools.py`.

```
                    ┌─────────────────────────────┐
                    │  Tool Agno (wrapper)        │
                    │  backend/tools/toolbox_*_tools.py │
                    └──────────────┬──────────────┘
                       tenta        │
                       Toolbox      ▼
                    ┌──────────────┐   falha →  ┌──────────────────┐
                    │ ToolboxClient │──────────▶│ Implementação     │
                    │ (remoto)      │            │ local (libs/)     │
                    └──────────────┘            └──────────────────┘
```

---

## 3. Cenário A — Novo provider de uma capacidade existente

Quando a Toolbox expõe um **novo provider** para uma capacidade que o core já consome
(ex.: um novo serviço de `document.structure.extract`), **não é necessário tocar código
no core**. Basta:

1. **Registrar o provider na Toolbox** (repo externo): adicionar o serviço ao
   `providers-config.yaml` da Toolbox, mapeando o nome do provider ao endpoint do
   serviço (ex.: `docling-serve`, `mineru-serve`).
2. **Apontar o core para o novo provider** via variável de ambiente:

   ```bash
   # Provider principal de extração de estrutura
   TOOLBOX_PROVIDER=mineru

   # Para fusão dual (FUSION_MODE=dual), provider secundário
   FUSION_SECONDARY_PROVIDER=mineru
   FUSION_MODE=dual
   ```

3. **Validar** que a Toolbox conhece o provider:

   ```bash
   curl -s "$TOOLBOX_BASE_URL/v1/capabilities" | jq
   ```

### Verificação

- Unit: `tests/test_toolbox_client.py` (mock respx) — verifica que o provider é
  enviado no form e que os erros HTTP são mapeados para as exceções tipadas.
- E2E: `tests/test_toolbox_e2e.py` (marcador `e2e`) — contra `TOOLBOX_BASE_URL` real.

---

## 4. Cenário B — Nova capacidade (novo endpoint)

Quando a Toolbox expõe uma **capacidade nova** (ex.: `document.layout.analyze`), o core
precisa de um cliente especializado. Siga o padrão de `toolbox_layout_client.py`:

### 4.1 Registrar a capacidade e escrever um cliente fino

Toda chamada à Toolbox passa por `execute_capability`
(SDK, `libs/sdk`: `acessilia_sdk.toolbox.transport`), que recusa qualquer capacidade fora do
registro. Adicionar uma capacidade tem dois passos.

**1. Declarar** em `libs/sdk/src/acessilia_sdk/toolbox/capabilities.py`:

```python
ToolboxCapability(
    "<capability>", 1, "<Rótulo>",               # id, versão do manifesto, rótulo de erro
    provider_key="toolbox_<x>_provider",     # atributo do Settings / TOOLBOX_<X>_PROVIDER
    output_schema="<schema>@1",                  # output.schema do manifesto
),
```

Se a configuração de provider for nova, acrescente o default em
`PROVIDER_DEFAULTS` e o atributo correspondente em `Settings`
(`os.getenv("TOOLBOX_<X>_PROVIDER", provider_default("toolbox_<x>_provider"))`).

**2. Escrever o cliente** como subclasse de `ToolboxCapabilityClient`, que já
cuida da conexão, do header Bearer, de `health()`, `close()`, do mapeamento de
erros de timeout/rede e da validação do envelope de resposta:

```python
"""Cliente especializado para a capacidade <capability> da Toolbox."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.tools.toolbox_client import ToolboxCapabilityClient

CAPABILITY = "<capability>"


class Toolbox<X>Client(ToolboxCapabilityClient):
    provider_key = "toolbox_<x>_provider"

    async def run(
        self,
        file_path: Path | None = None,
        artifact_id: str | None = None,
        *,
        use_remote_cache: bool | None = None,
    ) -> dict[str, Any]:
        return await self._execute(
            CAPABILITY,
            file_path=file_path,
            artifact_id=artifact_id,
            parameters={...},                      # opcional, enviado como JSON
            no_cache=use_remote_cache is False,
        )
```

Entradas de texto usam `upload=(nome, bytes, media_type)` no lugar de
`file_path` (veja `toolbox_math_client.py`). `scripts/check_capability_contract.py`
lê o registro, então o novo ID é conferido contra o catálogo da Toolbox sem
outras mudanças; `tests/test_toolbox_capability_registry.py` falha se um cliente
fixar uma rota `:execute` no código ou usar um ID não registrado.

### 4.2 Wrapper de tool Agno (opcional, com fallback local)

Se existir equivalente local, crie `backend/tools/toolbox_<x>_tools.py` seguindo o
padrão de `toolbox_ocr_tools.py`: expõe a capacidade como tool Agno, tenta a Toolbox
primeiro e degrada para a implementação local em caso de falha.

### 4.3 Integração no pipeline (se aplicável)

- **Structurer** (`backend/tools/structurer.py`): se a capacidade produz regiões por
  página, adicione um structurer novo em `get_structurer()` (ex.: `toolbox-layout` →
  `ToolboxLayoutStructurer`).
- **Fusão dual** (`backend/pipeline/fusion.py`): se a capacidade produz blocos
  canônicos, pode participar como provider em `extract_fused()`.
- **Método PDDL** (`backend/core/planning/toolbox_gate.py`): se o handler de um
  método de planejamento chama a capacidade, declare-a em
  `METHOD_TOOLBOX_REQUIREMENTS` (capacidade e provider). O gate de disponibilidade
  passa a conferi-la contra o catálogo vivo antes de cada documento ser planejado
  (veja abaixo).

#### Gate de disponibilidade

Antes de planejar um documento, o orquestrador tira um snapshot do catálogo
(`GET /v1/capabilities` + `/v1/providers`, em cache por
`TOOLBOX_CATALOG_REFRESH_SECONDS`) e confere cada método pedido que esteja em
`METHOD_TOOLBOX_REQUIREMENTS`: a capacidade precisa estar na allowlist do SDK, ser
publicada com a versão exata do contrato, e o provider configurado precisa estar
registrado e implementá-la. O catálogo só restringe; nunca torna um método
disponível.

| `TOOLBOX_AVAILABILITY_GATE` | Efeito |
|---|---|
| `observe` (padrão) | Registra no log o que seria removido e grava em `canonical_metadata.pddl_toolbox_availability`; o plano não muda |
| `enforce` | Remove esses métodos do plano e de todos os replanejamentos do documento. Quando o catálogo não pode ser lido e o último snapshot válido tem mais de `TOOLBOX_CATALOG_STALE_SECONDS`, todo método com requisitos da Toolbox é removido (fail closed) |
| `off` | Sem verificação |

### 4.4 Tests

- **Unit** (mock respx): no estilo de `tests/test_toolbox_client.py` — verifica o
  mapeamento de erros HTTP para exceções tipadas e o envio do provider.
- **E2E** (marcador `e2e`): no estilo de `tests/test_toolbox_e2e.py` — contra
  `TOOLBOX_BASE_URL` real; é ignorado se a variável não estiver definida.

### 4.5 Exemplo concreto: `media.inspect`

A capacidade `media.inspect` (provider `pure-media-inspect`, PR
`A11yDevs/acessilia-toolbox#33`) é consumida no core com o padrão do Cenário B:

- **Cliente:** `backend/tools/toolbox_media_inspect_client.py`
  (`ToolboxMediaInspectClient` → `POST /v1/capabilities/media.inspect:execute`).
- **Fallback local:** `backend/tools/media_inspect.py`
  (`inspect_source_media`, `inspect_media_payload`) — port determinístico em
  Pillow/PyMuPDF que replica o schema `artifact/media-inspection@1` quando a
  Toolbox está indisponível.
- **Integração:** `backend/agents/pddl_orchestrator.py` chama
  `inspect_source_media()` após a extração e usa o sinal
  `requires_visual_inspection` para injetar um elemento `picture` de página
  inteira quando a entrada é imagem isolada sem blocos visuais — garantindo a
  audiodescrição pelo VisionAgent.

  O fallback local não infere que uma imagem é uma página escaneada apenas por
  suas dimensões ou proporção; imagens de um único frame são encaminhadas para
  inspeção visual para não descartar infográficos ou ilustrações retrato.

Os predicados PDDL `media_inspected`/`media_profile_classified` pertencem ao
domínio da Toolbox; no core o sinal é consumido apenas como heurística de
enriquecimento e não entra no problema de planejamento.

---

## 5. Configuração (variáveis de ambiente)

Definidas em `backend/config/settings.py` e documentadas em `.env.example`:

| Variável | Padrão | Descrição |
|---|---|---|
| `TOOLBOX_BASE_URL` | `http://localhost:8002` | URL base do serviço |
| `TOOLBOX_PROVIDER` | `docling` | Provider principal de extração |
| `TOOLBOX_API_KEY` | *(vazio)* | Chave para `Authorization: Bearer` |
| `TOOLBOX_AVAILABILITY_GATE` | `observe` | Gate de disponibilidade: `observe`, `enforce` ou `off` (seção 4.3) |
| `TOOLBOX_CATALOG_REFRESH_SECONDS` | `60` | Por quanto tempo um snapshot do catálogo é reutilizado |
| `TOOLBOX_CATALOG_STALE_SECONDS` | `900` | Por quanto tempo o último snapshot válido é servido quando o catálogo não pode ser lido |
| `TOOLBOX_TIMEOUT_SECONDS` | `3600` | Timeout das requisições |
| `TOOLBOX_USE_ARTIFACT_STORE` | `true` | Envia o arquivo para `/v1/artifacts` antes de extrair |
| `TOOLBOX_USE_REMOTE_CACHE` | `true` | Usa o cache remoto (`no_cache=false`) |
| `TOOLBOX_MEDIA_INSPECT_PROVIDER` | `pure-media-inspect` | Provider da capacidade `media.inspect` |
| `TOOLBOX_MEDIA_INSPECT_ENABLED` | `true` | Executa `media.inspect` (Toolbox-first com fallback local) |
| `FUSION_MODE` | `single` | `single` (um provider) ou `dual` (dois providers + fusão) |
| `FUSION_SECONDARY_PROVIDER` | `mineru` | Provider secundário para `FUSION_MODE=dual` |
| `STRUCTURER` | `toolbox` | Motor de regiões por página (`toolbox`, `toolbox-layout`, `pymupdf`) |
| `TOOLBOX_PAGE_OCR_PROVIDER` | `qwen3-vl-page` | Transcrição VLM de página inteira (`document.ocr.page`) |
| `TOOLBOX_ADJUDICATE_PROVIDER` | `qwen3-vl-judge` | Juiz pareado / transcrição de região (`document.adjudicate.*`) |
| `TOOLBOX_ORIENTATION_PROVIDER` | `rapidocr-orient` | Detecção de rotação (`image.page.orient`) |
| `FUSION_HYBRID_PROVIDER` | `mineru-hyb` | Id do provider MinerU hybrid-VLM (a fonte B do melhor confirmado no leaderboard) |

> `TOOLBOX_USE_ARTIFACT_STORE` e `TOOLBOX_USE_REMOTE_CACHE` afetam diretamente o
> fluxo de extração: com o artifact store ativo, o core envia o arquivo uma vez e
> reutiliza o `artifact_id`; com o cache remoto ativo, a Toolbox pode responder a
> partir do `cache_key` sem reprocessar.

---

## 6. Fluxo completo (core → Toolbox)

```
service.py: _build_orchestrator()
  └─ PddlAccessibilityOrchestrator(extractor_backend="toolbox")
       └─ ToolboxManifestExtractor (backend/core/manifest/toolbox_extractor.py)
            ├─ [artifact store] upload_artifact() → /v1/artifacts
            └─ extract_structure(artifact_id=..., use_remote_cache=...)
                 → POST /v1/capabilities/document.structure.extract:execute
                 → ToolboxExtraction (configuration: toolbox_base_url, provider, artifact_id, cache_key)
       └─ InformationalStructuralAgent.process() → manifest
       └─ PlannerAgent → ExecutorAgent (MethodRegistry)
```

---

## 7. Referências de código

- `libs/sdk/src/acessilia_sdk/toolbox/` — registro de capacidades, transporte, classe base dos clientes e hierarquia de exceções (SDK)
- `backend/tools/toolbox_client.py` — liga a classe base do SDK ao settings do core; `ToolboxClient` genérico (extração, artefatos, datasets)
- `backend/tools/toolbox_layout_client.py` — modelo do Cenário B
- `backend/tools/toolbox_ocr_tools.py`, `toolbox_math_tools.py`, `toolbox_pdf_tools.py` — wrappers com fallback local
- `backend/tools/toolbox_page_ocr_client.py` — `document.ocr.page` (VLM de página inteira)
- `backend/tools/toolbox_adjudicate_client.py` — `document.adjudicate.page` / `.region`
- `backend/tools/toolbox_orientation_client.py` — `image.page.orient`
- `backend/tools/structurer.py` — `get_structurer()` e seleção de structurer
- `backend/core/manifest/toolbox_extractor.py` — `ToolboxManifestExtractor`
- `backend/pipeline/fusion.py` — `extract_fused()` (fusão dual)
- `backend/config/settings.py` — configuração da Toolbox
- `docs/drbench.pt-br.md` — benchmark de providers (Docling vs MinerU)

### 7.1 Capacidades adicionadas para o Dr.DocBench (PR #125)

| Capacidade | Cliente | Providers | Finalidade |
|---|---|---|---|
| `document.ocr.page` | `ToolboxPageOcrClient` | `qwen3-vl-page`, `dots-ocr-page`, `deepseek-ocr-page`, `teleocr-page` | Transcrição VLM de página inteira — a fonte B do híbrido de página |
| `document.adjudicate.page` | `ToolboxAdjudicateClient` | `qwen3-vl-judge` | Juiz pareado entre duas transcrições candidatas (as duas ordens, debiasing de posição) |
| `document.adjudicate.region` | `ToolboxAdjudicateClient` | `qwen3-vl-judge` | Transcrição exata de um recorte de região, convertida em decisão do differ |
| `image.page.orient` | `ToolboxOrientationClient` | `rapidocr-orient` | Detecção de rotação 0/90/180/270 |

Os registros de provider vivem no repositório da Toolbox; a configuração de job
do Dr.DocBench que os espelha é
`scripts/drbench/experiments/slurm/providers-config-vlm.yaml`.

O `mineru-hyb` (MinerU 3.x, `backend=hybrid-engine`) está registrado como
provider de `document.structure.extract` / `document.layout.analyze` /
`document.ocr`. É a fonte B do melhor confirmado no leaderboard
(`differ-v15-hyb`, EvalAI 70.37): o ganho real no test veio da ordem de leitura
(+16.4) com essa fonte, não do TEDS. Adote-o explicitamente com
`FUSION_SECONDARY_PROVIDER=mineru-hyb`; o default da fusão dual continua `mineru`.