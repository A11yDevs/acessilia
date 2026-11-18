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

`tests/test_boundary.py` verifica essa fronteira no código-fonte do pacote, e
`tests/test_smoke.py` verifica que o pacote instalado funciona sozinho: a CI
instala a partir do lock, fora do checkout, e executa o teste de smoke de lá.
Execute ambos com `uv run --extra dev pytest` nesta pasta (`make test-all`
também os executa).

`examples/table_stage.py` executa a etapa de estruturação de tabelas a partir de
um script, com `CoreConfig` explícito e executor próprio de chamadas de modelo,
sem importar o serviço nem FastAPI (prova de conceito do ADR-0016):

```bash
uv run --extra dev python examples/table_stage.py \
  examples/fixtures/tables_manifest.json tables.pdf tables.json
```

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
