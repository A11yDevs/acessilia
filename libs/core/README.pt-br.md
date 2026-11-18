# acessilia-core

O Core da Acessilia: pipeline PDDL que planeja e executa a acessibilização de
um documento com agentes, etapas de enriquecimento e exportadores
([ADR-0016](../../docs/adr/0016-core-package.pt-br.md)).

Inglês, versão normativa: [English version](README.md).

Não importa código do serviço (`backend`) ou das interfaces (`frontend`) e não
lê variáveis de ambiente. Seu chamador fornece:

- um `CoreConfig` por execução (`acessilia_core.config`);
- os `RunPorts`: cache de regiões, checkpoints do job e registro de operações
  remotas (`acessilia_core.ports`);
- o executor de chamadas de modelo (`acessilia_core.agents.model_calls`);
- a configuração do processo: logger, idiomas oferecidos e idioma do servidor
  (`acessilia_core.logger`, `acessilia_core.i18n`).

`tests/test_core_boundary.py`, na raiz, verifica essa fronteira.

## Catálogo de formatos

`acessilia_core.export.catalog` oferece registros imutáveis `FormatDelivery` em
`CATALOG` e a projeção `downloadable_formats()`. A identidade pura é
`docstruct.export.formats.FormatSpec`; a política de entrega pertence ao Core.
API, serviço de tokens e painel web reutilizam MIME types, nomes públicos e
rótulos. Tokens históricos de label da API são preservados e separados dos
msgids de exibição. DOCX/PDF/UA vinculam-se ao registro público de capacidades
do SDK.

O worker do serviço define ordem, flags, falhas opcionais, progresso e pacote
em `backend.api.export_plan`; o Core não importa código do serviço. PDF legado
é apenas baixável, Markdown de benchmark é interno e ZIP é empacotamento.
Filtros de perfil e validação existentes são preservados. Níveis de detalhe
descrevem a capacidade do formato, não a seleção de perfil. Veja o
[ADR 0025](../../docs/adr/0025-format-catalogue-ownership.pt-br.md).
