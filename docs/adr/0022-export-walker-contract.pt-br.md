# 0022. Um walker de exportação compartilhado com política de renderização do consumidor

Inglês, versão normativa: [English version](0022-export-walker-contract.md).

- **Status:** Accepted (aceito)
- **Data:** 2026-11-17
- **Componentes:** docstruct
- **Issues:** [#371, E1.6](https://github.com/A11yDevs/acessilia/issues/371), [#161, D2](https://github.com/A11yDevs/acessilia/issues/161)

## Contexto

TXT, HTML, Markdown e AST Pandoc repetem a travessia de seções. Suas políticas
diferem: Markdown omite todo heading que coincida com o título da seção; os
outros formatos omitem apenas o primeiro título legado correspondente. Filtros
de perfil e propagação de rótulos também diferem. A linha de base E1.0 aprovada
no PR #567 congela essas diferenças. Compartilhar a travessia deve preservá-las,
conforme a [última revisão](https://github.com/A11yDevs/acessilia/issues/371#issuecomment-6731172790).

## Decisão

- `docstruct.export.walk` fornece um walker puro, sob demanda e em profundidade,
  e um visitor tipado sobre os dicionários existentes de seções/blocos. Não cria
  outro modelo canônico nem adiciona dependências de runtime (ADRs
  [0002](0002-component-responsibilities.pt-br.md) e [0004](0004-single-source-of-truth-for-contracts.pt-br.md)).
- O visitor tem onze callbacks de bloco opcionais, um `default` chamável
  obrigatório para tipos desconhecidos ou não registrados e hooks opcionais
  de entrada/saída de seção. Cada callback retorna um resultado ou `None`; a
  agregação pertence ao consumidor. Valores falsos diferentes de `None` são
  preservados.
- Um `select(block, context)` do consumidor controla a inclusão de blocos. Sem
  ele, todo bloco é visitado. Não poda seções filhas. Omissão de títulos, perfis,
  rótulos, metadados do documento e validação continuam políticas do consumidor.
- Contextos congelados expõem dicionários originais, caminhos/profundidade das
  seções e índices originais dos blocos. Propriedades de título legado/alias
  delegam sob demanda aos helpers existentes. Callbacks devem tratar os
  dicionários compartilhados como somente leitura; o walker não os modifica
  nem faz cópias defensivas. Exceções do consumidor são propagadas.
- A E1.6 introduz a API e composições com renderizadores apenas nos testes. A
  migração de produção é um PR E1.7 separado, após revisão. Correções de
  comportamento ficam na #161; validação estrita no export não é ativada aqui.

## Consequências

A travessia pode ser reutilizada sem impor a política de um formato aos demais.
Consumidores devem selecionar blocos e agregar resultados explicitamente.
Testes de contrato cobrem todos os tipos do schema, ordem, fallback e semântica
dos contextos; composições de teste comparam todas as 30 chamadas caracterizadas
enquanto o gate de referência original permanece inalterado. Ambos rodam contra
o wheel isolado e no contêiner de testes travado.

A API aditiva recebe a versão docstruct 0.5.1: assinaturas públicas e
comportamentos existentes não mudam, e ela continua na faixa `>=0.5,<0.6` do SDK.
A publicação segue o processo existente de release após merge; este PR não a
publica nem altera pins de consumidores externos.
