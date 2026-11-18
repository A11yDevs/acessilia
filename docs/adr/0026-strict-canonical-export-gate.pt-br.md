# 0026. Validar o schema canônico no gate de exportação do Core

Inglês, versão normativa: [English version](0026-strict-canonical-export-gate.md).

- **Status:** Accepted (aceito)
- **Data:** 2026-11-18
- **Componentes:** Core, docstruct
- **Issues:** [#371, E1.2b](https://github.com/A11yDevs/acessilia/issues/371), [#161, D1](https://github.com/A11yDevs/acessilia/issues/161)

## Contexto

O ADR [0023](0023-packaged-canonical-schema.pt-br.md) empacotou o schema e a API
com validador injetado sem alterar exports. A [revisão aprovada](https://github.com/A11yDevs/acessilia/issues/371#issuecomment-6731172790)
exige decisão de compatibilidade separada antes da ativação obrigatória: a
auditoria atual aceita tipos de bloco customizados e outros valores inválidos
pelo schema. As etapas neutras terminaram no PR #576; esta muda a validação.

O corpus de compatibilidade registra 17 casos em `9845d84d`, antes deste gate:
15 exportam e dois falham na auditoria, em TXT, HTML, DOCX e PDF/UA (renderers
remotos simulados). Dos 15, doze documentos normalizados violam o schema:
tipos customizados na raiz/em filhos/em conteúdo filtrado, IDs de bloco/seção
ausentes, verbosidade/público/tipo do ID inválidos, título vazio, idioma curto
e nível de filho inválido. Três continuam aceitos: documento aninhado válido,
extensões de metadados e células numéricas já convertidas em texto pelo
sanitizador existente.

## Decisão

- O Core 0.2.0 torna obrigatória a validação em `export_accessible_document`,
  compartilhado por TXT/HTML/DOCX/PDF/UA públicos. Usa
  `validate_against_schema(document, validator)` do docstruct com
  `jsonschema.validate` injetado pelo Core e o schema empacotado inalterado.
  Nenhuma dependência de desenvolvimento passa ao runtime do docstruct.
- A ordem é **normalização existente → auditoria estrutural/acessibilidade
  existente → schema estrito → seleção/verificação de perfil → AST/renderer**.
  Bloqueios da auditoria mantêm precedência. Validar o documento normalizado
  inteiro, incluindo seções/filhos e blocos que o formato filtraria; o perfil
  não pode esconder um bloco canônico malformado.
- O gate não acrescenta normalização, restrição ao schema, flag, fallback ou
  desvio. Texto/Markdown ainda passam pelo builder; dicionários, pelo
  sanitizador. Entradas malformadas ainda podem falhar nessas etapas anteriores.
  Normalização de tabelas numéricas e extensões de metadados continuam aceitas.
  “Estrito” aplica as restrições reais do schema: campos adicionais e strings
  de versão do schema não recebem restrições extras.
- Nova falha de schema gera `ValueError` localizado com JSON Pointer e palavra
  de validação. Valores do documento e exceção extensa do jsonschema não
  aparecem no diagnóstico/traceback. A chamada direta ao exportador do Core
  rejeita antes de construir AST, criar diretório de destino, escrever localmente
  ou chamar renderer remoto. Arquivos existentes ficam intactos. O worker do
  serviço cria o diretório do job antes de chamar o exportador; uma rejeição no
  TXT obrigatório registra erro, remove esse diretório e não cadastra token de
  download. O ciclo de diretório do serviço permanece igual.
- Como restringe entradas públicas aceitas, o Core pré-1.0 passa de **0.1.1
  para 0.2.0**. Consumidores devem fornecer mappings conformes: usar o builder
  para IDs/estrutura de documento/seções, corrigir campos inválidos e representar
  extensões com tipo de bloco suportado e metadados. Não se descarta conteúdo
  silenciosamente para obter conformidade.
- Serializadores puros mantêm fallback e goldens E1.0. Markdown interno de
  benchmark continua fora do gate. Áudio e ZIP usam as saídas já validadas do
  worker. Schema, contratos do SDK, perfis e sufixos permanecem iguais. Este ADR
  implementa a ativação separada prevista no ADR 0023; decisões de empacotamento
  e pureza permanecem válidas.

## Consequências

Mappings canônicos inválidos antes aceitos passam a falhar, incluindo os
persistidos/em cache de jobs retomados. Downloads existentes não são
revalidados. A revisão deste PR
aprova essa mudança de compatibilidade; não é refatoração neutra nem publicação.
Changelog e corpus bilíngue explicam a migração. Schema complementa a auditoria:
IDs duplicados e seções vazias ainda falham mesmo permitidos pelo JSON Schema.

Testes cobrem 68 resultados antes/depois, filhos/conteúdo filtrado, normalização,
TXT preservado exatamente, entrada imutável, destino preservado, ausência de
execução de renderer, diagnóstico localizado sem valores e falha do worker.
Gates de isolamento, builder/schema e paridade continuam aplicáveis. O dataset
opcional de seis documentos não está neste checkout: não é evidência declarada
nem gera teste pulado.
