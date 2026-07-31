# Agente Informacional-Estrutural — PMV 1.0.0

Este pacote deriva de
[`jhonata192/a11y-devs-describer`](https://github.com/jhonata192/a11y-devs-describer/)
no commit `f22e9ce02ed5f11fe3c6e6be10ceacb4157c2321`. O projeto original declara
licença MIT no `README.md`.

## Alterações do PMV

- conversão Docling única e reutilizável por documento;
- `InformationalStructuralAgent`;
- normalização de páginas, elementos, hierarquia, ordem de leitura,
  coordenadas e proveniência;
- geração determinística de observações e obrigações candidatas;
- modelo executável `ProcessingManifest` em Pydantic 2;
- JSON Schema Draft 2020-12 gerado do modelo;
- validação estrutural e semântica antes da gravação;
- CLI `a11y-manifest`;
- testes unitários e documentação de arquitetura.

## Validação realizada

- 53 testes do repositório aprovados;
- JSON Schema válido em Draft 2020-12;
- ensaio ponta a ponta com Docling 2.115.0 em PDF de 8 páginas;
- resultado do ensaio: 145 elementos, 139 elementos com caixas de
  proveniência, 144 vínculos hierárquicos resolvidos e 5 obrigações candidatas;
- manifesto resultante validado sem erros pelo Pydantic e pelo arquivo de
  JSON Schema.

O PDF usado no ensaio e o manifesto derivado não estão incluídos no pacote.
