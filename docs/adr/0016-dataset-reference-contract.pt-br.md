# 0016. Propriedade e migração do contrato de referências do Dataset

Também disponível em **inglês (EUA)**: [English version](0016-dataset-reference-contract.md)

- **Status:** Aceito
- **Data:** 2026-11-11
- **Componentes:** Dataset, Core, Toolbox
- **Issues:** [Dataset #9](https://github.com/A11yDevs/acessilia-dataset/issues/9), [Core #388](https://github.com/A11yDevs/acessilia/issues/388), [Toolbox #141](https://github.com/A11yDevs/acessilia-toolbox/issues/141)

## Contexto

Os benchmarks de matemática e apresentação do Core e o provider do Dataset na
Toolbox usavam caminhos do layout legado. Alguns consumidores seguiam uma
revisão móvel. Mover as referências ou retirar os splits legados na mesma
revisão poderia quebrar esses consumidores. O manifesto de referências também
precisa distinguir a disponibilidade de um arquivo das anotações aplicáveis a
uma entrada e tarefa.

## Decisão

- O Dataset é responsável pelos esquemas dos manifestos de entradas e
  referências e pelos esquemas dos arquivos referenciados. Publica esses
  esquemas junto aos dados na mesma revisão e os valida no CI. Mudanças de
  contrato declaram a versão e a migração suportada.
- O Core é responsável pelos critérios dos benchmarks, pelos protocolos dos
  scorecards e pelas fixtures de comparação histórica. Seu CI fixa um commit
  do Dataset e verifica as referências sem o serviço da Toolbox. Os leitores
  públicos também aceitam cópias locais e registram o digest das referências e
  a revisão Git quando disponível. Para exportações verificadas pelo lock, o
  commit fixado é registrado em `expected_revision`. Comparações exigem a mesma identidade de referência, os mesmos
  critérios e o mesmo protocolo.
- A Toolbox é responsável pelos esquemas da sua API pública e resolve entradas
  e referências do Dataset no mesmo commit imutável. O commit efetivo integra
  as chaves de cache e a proveniência. A cobertura e os seletores ficam em
  metadados versionados do item. Mudanças em esquemas de resposta publicados
  passam por revisão de compatibilidade e seguem a política de versionamento
  de contratos da Toolbox. A revisão desta transição mantém os esquemas de
  resposta do Dataset em `@1`: `sha256` e `artifact_id` já eram anuláveis em
  `DatasetArtifactRef` e podiam ser serializados como null; portanto, a mudança
  corrige a declaração publicada. Os esquemas públicos de item, referência de
  artefato e split continuam aceitando propriedades adicionais. Os modelos
  produtores mantêm a validação existente. O campo opcional `deprecated`
  do split é aditivo. Os campos obrigatórios permanecem iguais, e todas as formas de
  resposta que o provider já emitia continuam válidas; o campo opcional
  acrescenta a informação de depreciação. Essas correções e essa adição não
  exigem bump da versão da capability. Remover um campo, tornar obrigatório um campo opcional,
  restringir um tipo de valor ou alterar o significado de um campo existente
  exige uma nova versão major do schema/capability e migração dos consumidores.
- O manifesto novo tem precedência quando a revisão declara o layout novo.
  Os consumidores sinalizam como erro a ausência, a invalidez ou a versão
  incompatível de um manifesto ou referência obrigatória. Uma coleção vazia
  válida, uma tarefa sem anotação e um negativo anotado têm significados distintos.

### Ordem da migração

1. Preparar e verificar os dois consumidores contra o commit legado publicado.
   Preservar as fixtures necessárias com revisões de origem e hashes.
2. Publicar e marcar com tag uma revisão compatível do Dataset que mantenha
   `references/` e os caminhos legados lado a lado. Com um pull request por
   repositório, a revisão de compatibilidade pode ser publicada antes do merge
   dos PRs dos consumidores porque preserva o layout legado.
3. Atualizar os dois consumidores para o mesmo commit exato do Dataset e
   executar o CI de ambos. Verificar que o commit fixado pode ser obtido do
   repositório de origem. Se a estratégia de merge mudar o SHA, manter a tag
   de transição no commit exato fixado ou atualizar os dois pins para o commit
   publicado.
4. Retirar os caminhos legados em outra revisão com tag, após a migração dos
   consumidores e a aprovação dos testes de regressão. Publicar o indicador de
   depreciação na Toolbox por pelo menos uma release antes de retirar os splits
   públicos do layout padrão. Manter acessíveis as revisões históricas
   explícitas conforme a política documentada do provider.

## Consequências

Os consumidores podem migrar de forma independente enquanto os dois layouts
coexistirem. O validador do Dataset verifica o esquema e os hashes dos
arquivos migrados. O smoke offline do Core e os testes de contrato da Toolbox
com a fixture fixada verificam a compatibilidade dos consumidores. A
publicação continua condicionada à revisão das permissões do Dataset. Os
testes de contrato não verificam direitos de redistribuição.
