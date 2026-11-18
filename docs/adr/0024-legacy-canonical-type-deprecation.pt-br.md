# 0024. Descontinuar dataclasses canônicas legadas preservando compatibilidade

Inglês, versão normativa: [English version](0024-legacy-canonical-type-deprecation.md).

- **Status:** Accepted (aceito)
- **Data:** 2026-11-17
- **Componentes:** docstruct
- **Issue:** [#371, E1.3](https://github.com/A11yDevs/acessilia/issues/371)

## Contexto

`CanonicalDocument` e `CanonicalSection` são dataclasses públicas exportadas por
`docstruct.types` e `docstruct`. Descrevem um modelo antigo e menor: o documento
não tem versão de schema/id/idioma, e a seção não tem filhos. Core e SDK usam os
dicionários construídos por `docstruct.canonical`, cujo contrato serializado
pertence ao JSON Schema empacotado (ADR [0023](0023-packaged-canonical-schema.pt-br.md)),
em vez dessas dataclasses. Outros consumidores do wheel podem ainda usar os
nomes ou objetos persistidos. Removê-las ou substituí-las quebraria a API pública.

## Decisão

- Descontinuar apenas essas duas dataclasses legadas a partir da docstruct
  **0.5.3**. Docstrings e strings informativas de classe `__deprecated__`
  identificam versão e APIs de migração. Reexports da raiz e documentação
  marcam explicitamente seu status de compatibilidade.
- Preservar classes originais, caminhos de módulo, exports da raiz, construtores,
  campos/defaults, argumentos posicionais, igualdade, `asdict`, `blocks()` e
  comportamento de pickle. O marcador é atributo de classe sem anotação, não
  campo de dataclass nem estado da instância. Não é introduzido wrapper, alias
  ou reescrita do modelo de schema.
- Imports e construção continuam silenciosos. A descontinuação é documentada
  e exposta em metadados de introspecção; ferramentas podem consultar o marcador
  explicitamente. Emitir warnings ou diagnósticos estáticos automáticos não faz
  parte deste contrato. Isso mantém a etapa na paridade da #371 e na pureza da
  docstruct.
- Código novo de documentos/seções usa dicionários retornados por
  `build_canonical_document` e a estrutura descrita por
  `accessible_document_schema`. `asdict` de um objeto legado não fornece os
  campos ausentes do schema e não é migração automática.
- `CanonicalBlock`, `BBox` e demais objetos de valor dos algoritmos continuam
  ativos. A linha 0.5.x mantém os nomes descontinuados; remoção exige decisão
  separada de versão incompatível e migração de consumidores conforme a política
  de release. Nenhuma versão de remoção é agendada aqui.

## Consequências

Consumidores recebem uma direção de migração sem alterar execução ou
serialização existentes. Usuários externos devem ler a documentação ou consultar
metadados; não recebem novo warning em runtime. A versão patch registra essa
mudança compatível de status e fica na faixa `>=0.5,<0.6` já aceita pelo SDK.

Testes de compatibilidade preservam identidades das classes, campos do
construtor, defaults e estado serializado, carregam um pickle gerado com 0.5.2 e
importam/constroem objetos tratando warnings como erros. Os gates existentes de
pureza, wheel isolado e caracterização de exports continuam aplicáveis. Nenhuma
dependência de runtime, schema, política de exportação, pin externo ou publicação
de release muda nesta etapa.
