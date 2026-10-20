# Inventário do modelo do processing manifest

> Esta é a tradução para português brasileiro de
> [manifest-model-inventory.md](manifest-model-inventory.md). A versão em inglês é a fonte
> autoritativa em caso de divergência.

Este é o primeiro passo da etapa 5 da [#203](https://github.com/A11yDevs/acessilia/issues/203). Ele classifica cada classe e campo do processing manifest em quatro domínios. Essa classificação decide o que vai para a docstruct ([ADR-0007](../adr/0007-manifest-model-and-mathml-conversion.pt-br.md), decisão 1), o que fica no core e o que a Toolbox envolve no próprio envelope. O inventário também lista como as duas cópias do modelo diferem hoje. Cada diferença precisa ser resolvida antes que uma definição compartilhada substitua as cópias.

- **Retrato:** `acessilia` `develop` em `316e49c`, `backend/core/manifest/models.py`; `acessilia-toolbox` `develop` em `85a53dd`, `src/acessilia_toolbox/core/normalization/models.py`.
- **Contrato de wire:** `urn:a11y-devs:schema:processing-manifest:1.1.0`. A Toolbox também o expõe como `artifact/structured-document@1`. Nenhuma das duas versões muda por causa desta migração ([ADR-0007](../adr/0007-manifest-model-and-mathml-conversion.pt-br.md), alcance da decisão 1).

## Domínios

| Domínio | Significado | Destino |
|---|---|---|
| **Documento** | Elementos, estrutura, hierarquia, localização e seus invariantes | docstruct (tipos puros e validação) |
| **Origem** | De onde vieram o documento e sua extração: arquivo, execução do extrator, referências do provider, confiança | Fica no modelo de cada componente; não é semântica estrutural por padrão |
| **Processo** | O que o core decidiu e fez: observações, obrigações, tentativas, status | Core |
| **Envelope** | Identidade, schema e versão do payload, contagens derivadas, artefatos armazenados | Core para o manifesto; Toolbox para `artifact/structured-document@1` |

## Classes e campos

| Classe | Campo(s) | Domínio | Observações |
|---|---|---|---|
| `BoundingBox` | todos, inclusive `coord_origin` | Documento | Já tem equivalente puro em `docstruct.geometry.OrientedBox` (#208). A origem acompanha a caixa. |
| `Provenance` | `page_number`, `bbox` | Documento | Localização de um elemento. |
| `Provenance` | `char_start`, `char_end` | Documento | Deslocamentos no texto do elemento. |
| `PageDescriptor` | `page_number`, `width`, `height`, `element_ids` | Documento | `element_ids` é recomposto depois da ordem de leitura (#209). |
| `ManifestElement` | `id`, `type`, `raw_label`, `reading_order`, `hierarchy_level`, `text`, `parent_id`, `page_number`, `provenance` | Documento | `ElementType` faz parte do vocabulário do documento. |
| `ManifestElement` | `source_ref`, `parent_ref` | Origem (híbrido) | Referências do provider (ponteiros JSON do Docling). Identificam uma origem, não uma estrutura. `parent_id` é o vínculo estrutural. |
| `ManifestElement` | `confidence` | Origem (híbrido) | Evidência do extrator sobre o elemento. Fica no elemento, mas não é invariante do documento. |
| `ManifestElement` | `metadata` | Híbrido | Um saco aberto. Guarda fatos do documento (`callout_*`, `table_ast`), marcas de processo (`unstructured_page`, `blank_page`) e dados do provider (`docling_class`). Continua aberto (`dict`). Suas chaves são documentadas por domínio antes que alguma ganhe campo tipado. |
| `SourceDocument` | `filename`, `media_type`, `byte_size`, `sha256` | Origem | Descreve o arquivo de entrada. |
| `SourceDocument` | `document_id` | Origem (híbrido) | A identidade do documento, derivada do `sha256`. |
| `SourceDocument` | `path` | Origem | Específico da máquina. Os manifestos golden (#205) o substituem. |
| `ExtractorRun` | todos | Origem | Metadados de execução da extração ([ADR-0007](../adr/0007-manifest-model-and-mathml-conversion.pt-br.md): fica com seu componente). |
| `Observation` | todos, e `Severity` | Processo | Achados do core. As mensagens vêm do catálogo de i18n do core. |
| `Obligation`, `ObligationAttempt` | todos, com os status | Processo | Política de planejamento, do core. A Toolbox mantém o campo só por compatibilidade com a 1.1.0 e sempre o deixa vazio. |
| `Artifact` | todos | Envelope | Arquivos que o core produziu numa execução. |
| `ManifestSummary` | `page_count`, `element_count`, `element_types` | Envelope (derivado do documento) | Contagens validadas contra as listas. |
| `ManifestSummary` | `observation_count`, `obligation_count` | Envelope (derivado do processo) | Contagens validadas contra as listas. |
| `ProcessingManifest` | `$schema` (`schema_ref`), `schema_version`, `manifest_id`, `revision`, `created_at` | Envelope | `$schema` é um alias; `populate_by_name=True`. |
| `ProcessingManifest` | `status` | Processo | Ciclo de vida da execução do core. |
| `ProcessingManifest` | `title`, `language` | Documento | Propriedades do documento. |
| `ProcessingManifest` | `pages`, `elements` | Documento | O documento em si. |
| `ProcessingManifest` | `observations`, `obligations` | Processo | |
| `ProcessingManifest` | `artifacts`, `summary` | Envelope | |

### Invariantes

| Invariante | Domínio | Core | Toolbox |
|---|---|---|---|
| IDs de elemento únicos | Documento | sim | **não** |
| `parent_id` existe, não é o próprio elemento, e a hierarquia não tem ciclo | Documento | sim | **não** |
| Números de página únicos | Documento | sim | sim |
| `page.element_ids` referenciam elementos conhecidos | Documento | sim | sim |
| A extração termina depois de começar | Origem | sim | **não** |
| IDs de observação, obrigação e artefato únicos | Processo, envelope | sim | **não** |
| Alvos, dependências e artefatos de tentativa existem; dependências sem ciclo; obrigação satisfeita tem predecessoras satisfeitas | Processo | sim | sim |
| `method_costs` só para métodos admissíveis | Processo | sempre | só quando as duas listas não estão vazias |
| Custos de método não negativos | Processo | sim | **não** |
| A tentativa termina depois de começar | Processo | sim | sim |
| As contagens de `summary` batem com as listas | Envelope | sim | sim |

## Diferenças entre as duas cópias

As duas cópias declaram o mesmo `$id`. Hoje elas publicam schemas diferentes e aceitam payloads diferentes:

1. **Texto do JSON Schema publicado.** A `description` difere. O core tem uma descrição em português; a Toolbox, uma em inglês, marcada como "literal: parte do schema 1.1.0 publicado". A Toolbox também acrescenta `"deprecated": true` a `obligations`. Um `$id` deveria nomear um único schema.
2. **A Toolbox aceita payloads que o core rejeita.** Sua cópia não tem os invariantes marcados **não** acima. Um payload da Toolbox com ID de elemento duplicado, `parent_id` pendente ou cíclico, ou intervalo do extrator invertido passa lá e falha no `ProcessingManifest.model_validate` do core.
3. **Mensagens de validação.** As do core estão em português (uma passa pela i18n); as da Toolbox, em inglês. Mensagens não fazem parte do contrato de wire.

## Consequências para os próximos passos da etapa 5

- **A docstruct recebe:** as linhas de documento acima, como tipos da biblioteca padrão, com os invariantes do documento numa função pura de validação que devolve achados, não exceções. Isso segue o `docstruct.validation`. Sem Pydantic, sem I/O.
- **O core mantém:** o `ProcessingManifest` como envelope e os modelos de processo com seus validadores. Seus modelos Pydantic da parte de documento viram adapters verificados contra a docstruct, e depois derivados dela. Cada passo é verificado contra os manifestos golden e o round trip da #205.
- **A Toolbox mantém:** seu envelope e o `artifact/structured-document@1`. Sua parte de documento converge para a mesma definição da docstruct quando ela passar para a docstruct 0.4.0 ([ADR-0004](../adr/0004-single-source-of-truth-for-contracts.pt-br.md)).
- **Decidir antes (D1):** como o JSON Schema da parte de documento é produzido a partir da docstruct (gerado ou verificado mecanicamente), e quais marcas de `description` e `deprecated` o schema 1.1.0 único mantém.
- **Decidir antes:** se a Toolbox adota os invariantes que faltam ainda dentro da 1.1.0. Eles apertam a validação, então alguns payloads que validam hoje deixariam de validar. A alternativa é mantê-los só no core até uma nova versão do schema.
