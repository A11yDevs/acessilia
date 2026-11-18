# 0023. Empacotar o schema canônico com motor de validação injetado

Inglês, versão normativa: [English version](0023-packaged-canonical-schema.md).

- **Status:** Accepted (aceito)
- **Data:** 2026-11-17
- **Componentes:** docstruct, core
- **Issues:** [#371, E1.2a](https://github.com/A11yDevs/acessilia/issues/371), [#161, D1](https://github.com/A11yDevs/acessilia/issues/161)

## Contexto

O schema de documento acessível vive apenas em `schemas/` do checkout, embora a
docstruct seja dona dos schemas canônicos
([ADR 0004](0004-single-source-of-truth-for-contracts.pt-br.md)). Um consumidor
do wheel instalado não consegue carregá-lo. A docstruct deve continuar sem
dependências de runtime. A [revisão aprovada](https://github.com/A11yDevs/acessilia/issues/371#issuecomment-6731172790)
separa empacotamento e validação injetada do gate obrigatório de exportação:
o enum rejeita tipos personalizados que os exports existentes aceitam.

## Decisão

- O schema normativo, com bytes inalterados, é dado do pacote em
  `docstruct/schemas/accessible_document.schema.json`. Draft, identificador e
  restrições permanecem iguais. `accessible_document_schema()` lê apenas esse
  recurso fixo instalado e retorna um dicionário novo; não consulta diretório de
  trabalho, arquivo do consumidor ou rede.
- `docstruct.validation.validate_against_schema(document, validator)` recebe
  um callable `validator(document, schema)`, compatível com `jsonschema.validate`.
  Ele deve retornar `None` no sucesso e lançar exceção na falha. Exceções são
  propagadas; outros retornos causam `TypeError`, evitando descartar falhas
  booleanas ou iteradores de erros sob demanda. Callbacks recebem o documento
  original e devem tratá-lo como somente leitura. Cada chamada recebe seu
  próprio dicionário de schema.
- O runtime não importa um motor de validação; `jsonschema` é dependência apenas
  de desenvolvimento. Ler dados empacotados é o único acesso a arquivo do
  accessor; algoritmos estruturais mantêm suas garantias atuais de pureza.
- **Exceção restrita de infraestrutura (ADR 0017):** o dono docstruct permite
  `schemas/__init__.py:importlib.resources` apenas para ler esse recurso fixo
  quando chamado, nunca na importação. Não recebe argumento de caminho nem
  permite arquivos arbitrários, escritas, rede ou ambiente. Isso atende à API
  de schema instalado de D1; gerar outra representação do schema em Python
  acrescentaria um artefato para sincronizar. O guard estático permite só esse
  par exato módulo/import, e os guards de importação continuam aplicáveis.
  **Critério de saída:** remover a exceção se o accessor for removido ou
  substituído por dados embutidos gerados; o teste de exceções não utilizadas
  exige remoção quando o import deixar de existir. A revisão do PR deste ADR
  revisa também a exceção.
- `schemas/accessible_document.schema.json` da raiz continua como cópia gerada
  de compatibilidade, idêntica em bytes. O script
  `scripts/sync_accessible_document_schema.py` a regenera; seu modo `--check` e
  o teste de contrato do core detectam divergências.
- A API aditiva recebe a versão docstruct 0.5.2, na faixa `>=0.5,<0.6` já aceita
  pelo SDK. Este PR não altera pins externos nem publica release.

## Consequências

Consumidores instalados podem usar o schema canônico sem o repositório. Testes
validam contra ele saídas dos builders da biblioteca e do core, incluindo
seções aninhadas. A CI valida o recurso do wheel instalado fora do checkout e
mantém os gates de pureza dos imports de runtime e de caracterização dos exports.

Auditorias e exportadores existentes não chamam a nova API optativa. Entradas
aceitas e saídas congeladas permanecem iguais. Ativar validação estrita no gate
de exportação do core é a E1.2b, com decisão de compatibilidade e PR separados;
descontinuação de tipos públicos e catálogo de formatos também ficam em etapas
próprias.
