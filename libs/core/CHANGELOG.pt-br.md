# Changelog do Core

Inglês, versão normativa: [English version](CHANGELOG.md).

## 0.2.0 — validação canônica estrita na exportação

**Mudança incompatível de validação:** TXT, HTML, DOCX e PDF/UA exigem que o
documento normalizado inteiro corresponda ao schema empacotado do docstruct,
após a auditoria existente e antes da seleção de perfil. Tipos customizados,
IDs de bloco/seção ausentes e valores inválidos antes aceitos passam a gerar
`ValueError` localizado antes do renderer. Falhas de auditoria têm precedência.

Antes de adotar 0.2.0, construa árvores com `docstruct.canonical` ou forneça
todos os IDs/campos necessários. Corrija valores inválidos; represente semântica
customizada com um dos onze tipos suportados e metadados. Blocos customizados
em nível filtrado pelo TXT não contornam o gate. Células numéricas continuam
convertidas em texto pelo sanitizador; extensões de metadados são válidas.
Texto/Markdown continuam passando pelo builder.

Mappings persistidos/em cache, incluindo jobs retomados, são conferidos ao
exportar. Artefatos existentes e tokens não são revalidados.

Serializadores puros, fallback, schema, contratos do SDK, perfis, nomes e
downloads legados não mudam. Não há nova flag ou fallback. Veja o
[ADR 0026](../../docs/adr/0026-strict-canonical-export-gate.pt-br.md) e o
[corpus de compatibilidade](../../tests/fixtures/export_schema_gate/README.pt-br.md).
