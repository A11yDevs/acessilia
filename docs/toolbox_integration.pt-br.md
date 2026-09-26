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

**Ponto-chave:** o core **não tem registro de providers**. O `provider` é apenas uma
string enviada no form; o roteamento real acontece no `providers-config.yaml` da
Toolbox. A validação de que um provider existe é feita do lado da Toolbox — quando
falha, o core recebe `ToolboxCapabilityError` ou `ToolboxContractViolation`.

### Hierarquia de exceções

Todas herdam de `ToolboxError` (definida em `backend/tools/toolbox_client.py`):

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

### 4.1 Cliente especializado

Crie `backend/tools/toolbox_<x>_client.py`:

```python
"""Cliente especializado para a capacidade <capability> da Toolbox."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from backend.config.settings import settings
from backend.tools.toolbox_client import (
    ToolboxContractViolation,
    ToolboxProviderUnavailable,
    ToolboxTimeout,
    _media_type,
    _raise_for_error,
)

CAPABILITY = "<capability>"
EXECUTE_PATH = f"/v1/capabilities/{CAPABILITY}:execute"


class Toolbox<X>Client:
    """Cliente para <capability> via Acessilia Toolbox."""

    def __init__(
        self,
        base_url: str | None = None,
        provider: str | None = None,
        timeout_seconds: int | None = None,
        api_key: str | None = None,
    ) -> None:
        self.base_url = (base_url or settings.toolbox_base_url).rstrip("/")
        self.provider = provider or settings.toolbox_provider
        self.timeout_seconds = timeout_seconds or settings.toolbox_timeout_seconds
        self.api_key = api_key if api_key is not None else settings.toolbox_api_key
        headers: dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(self.timeout_seconds),
            headers=headers,
        )

    async def execute(
        self,
        file_path: Path | None = None,
        artifact_id: str | None = None,
        *,
        language: str = "pt-BR",
        use_remote_cache: bool | None = None,
    ) -> dict[str, Any]:
        if file_path is None and artifact_id is None:
            raise ValueError("Forneça file_path ou artifact_id")

        url = f"{self.base_url}{EXECUTE_PATH}"
        try:
            if artifact_id:
                data: dict[str, Any] = {
                    "artifact_id": artifact_id,
                    "language": language,
                    "provider": self.provider,
                }
                if use_remote_cache is False:
                    data["no_cache"] = True
                response = await self._client.post(url, data=data)
            else:
                with open(file_path, "rb") as f:
                    files = {"file": (file_path.name, f, _media_type(file_path))}
                    params: dict[str, Any] = {
                        "language": language,
                        "provider": self.provider,
                    }
                    if use_remote_cache is False:
                        params["no_cache"] = True
                    response = await self._client.post(url, files=files, data=params)

            _raise_for_error(response, CAPABILITY)
            result = response.json()
            if result.get("status") != "succeeded":
                raise ToolboxContractViolation(
                    f"{CAPABILITY}: status inesperado {result.get('status')!r}"
                )
            return result
        except httpx.TimeoutException as exc:
            raise ToolboxTimeout(f"{CAPABILITY}: timeout") from exc
        except httpx.HTTPStatusError as exc:
            raise ToolboxProviderUnavailable(
                f"{CAPABILITY}: HTTP {exc.response.status_code}"
            ) from exc
```

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

### 4.4 Testes

- **Unit** (mock respx): no estilo de `tests/test_toolbox_client.py` — verifica o
  mapeamento de erros HTTP para exceções tipadas e o envio do provider.
- **E2E** (marcador `e2e`): no estilo de `tests/test_toolbox_e2e.py` — contra
  `TOOLBOX_BASE_URL` real; é ignorado se a variável não estiver definida.

---

## 5. Configuração (variáveis de ambiente)

Definidas em `backend/config/settings.py` e documentadas em `.env.example`:

| Variável | Padrão | Descrição |
|---|---|---|
| `TOOLBOX_BASE_URL` | `http://localhost:8002` | URL base do serviço |
| `TOOLBOX_PROVIDER` | `docling` | Provider principal de extração |
| `TOOLBOX_API_KEY` | *(vazio)* | Chave para `Authorization: Bearer` |
| `TOOLBOX_TIMEOUT_SECONDS` | `3600` | Timeout das requisições |
| `TOOLBOX_USE_ARTIFACT_STORE` | `true` | Envia o arquivo para `/v1/artifacts` antes de extrair |
| `TOOLBOX_USE_REMOTE_CACHE` | `true` | Usa o cache remoto (`no_cache=false`) |
| `FUSION_MODE` | `single` | `single` (um provider) ou `dual` (dois providers + fusão) |
| `FUSION_SECONDARY_PROVIDER` | `mineru` | Provider secundário para `FUSION_MODE=dual` |
| `STRUCTURER` | `toolbox` | Motor de regiões por página (`toolbox`, `toolbox-layout`, `pymupdf`) |

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

- `backend/tools/toolbox_client.py` — cliente base e hierarquia de exceções
- `backend/tools/toolbox_layout_client.py` — modelo do Cenário B
- `backend/tools/toolbox_ocr_tools.py`, `toolbox_math_tools.py`, `toolbox_pdf_tools.py` — wrappers com fallback local
- `backend/tools/structurer.py` — `get_structurer()` e seleção de structurer
- `backend/core/manifest/toolbox_extractor.py` — `ToolboxManifestExtractor`
- `backend/pipeline/fusion.py` — `extract_fused()` (fusão dual)
- `backend/config/settings.py` — configuração da Toolbox
- `docs/drbench.pt-br.md` — benchmark de providers (Docling vs MinerU)