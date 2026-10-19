# 0004. Uma fonte de verdade por contrato

Também disponível em **inglês (EUA)**: [English version](0004-single-source-of-truth-for-contracts.md)

- **Status:** Aceito
- **Data:** 2026-10-18
- **Componentes:** core, SDK, docstruct, Toolbox
- **Issues:** [#152](https://github.com/A11yDevs/acessilia/issues/152) (P7)

## Contexto

Os mesmos modelos existem em vários lugares. Exemplos:

- Os modelos e o schema do Processing Manifest 1.1 existem tanto no core
  (`backend/core/manifest/models.py`, `schema.py`) quanto na Toolbox
  (`core/normalization/`).
- O vocabulário de layout é definido pelo provider de layout docling da
  Toolbox e mapeado de volta à mão no core (`toolbox_layout_structurer.py`).
- O SDK mantém uma allowlist escrita à mão com os IDs e versões das
  capacidades. O `scripts/check_capability_contract.py` a compara com o
  catálogo da Toolbox.

Fazer a Toolbox depender do SDK para compartilhar esses tipos foi considerado
e rejeitado: o servidor dependeria do próprio pacote cliente, e os dois
precisariam ser lançados juntos.

## Decisão

Cada contrato tem exatamente um dono. Os demais o consomem e não o redefinem:

| Contrato | Fonte de verdade | Consumidores |
|---|---|---|
| Modelos e schemas documentais canônicos (documento canônico, estrutura do manifesto, tabelas, geometria) | **docstruct** | core, SDK, Toolbox |
| Contratos operacionais da API: manifestos de capacidade, schemas de entrada e saída, `ArtifactRef`, jobs, erros | **Toolbox**, publicados como OpenAPI e JSON Schema | SDK (e, por meio dele, o core) |
| Bindings de contrato do lado cliente (allowlist, resultados tipados) | **SDK**, derivados dos contratos publicados pela Toolbox, de preferência gerados, e nunca editados à mão depois que a geração existir | core |

- A Toolbox continua dependendo da docstruct e não depende do SDK.
- O core usa as interfaces públicas do SDK e não redefine contratos.
- O `scripts/check_capability_contract.py` verifica se os contratos que o SDK
  consome batem com os que a Toolbox publica (IDs, versões exatas,
  providers). A compatibilidade é exata: uma nova versão maior é um novo
  contrato.
- Um pacote separado `acessilia-contracts` só é considerado se surgir uma
  necessidade concreta que esta divisão não atenda.

## Consequências

- Os modelos duplicados vão para o seu dono. O manifest builder é primeiro
  dividido em modelos, algoritmos puros e integrações, e só então migrado; ele
  não é movido inteiro. Isso está registrado na auditoria da #152.
- A allowlist escrita à mão no SDK continua até existir a geração a partir dos
  schemas da Toolbox; enquanto isso, o script de contrato a mantém honesta.
- As releases da docstruct são coordenadas: a Toolbox fixa uma wheel da
  docstruct por versão e hash. Hoje ela fixa a v0.1.0 enquanto o core usa a
  0.2.0, então uma release e um bump na Toolbox são necessários antes que os
  modelos compartilhados possam convergir.
