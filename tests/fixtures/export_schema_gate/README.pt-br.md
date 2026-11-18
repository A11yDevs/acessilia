# Corpus de compatibilidade do gate estrito de exportação

Inglês, versão normativa: [English version](README.md).

`compatibility.json` captura o comportamento anterior em `9845d84d` (#576
mesclado). Documento sintético compartilhado e operações explícitas de caminho,
valor/remoção definem 17 entradas. `baseline_by_format` registra os 68 resultados
TXT/HTML/DOCX/PDF/UA; `baseline_text`, o TXT exato em UTF-8. Renderers DOCX/PDF/UA
foram simulados, sem providers. `baseline_commit` identifica o código;
`normalized_schema_valid` verifica o documento sanitizado contra o schema
empacotado inalterado. O JSON é sintético, sem dados de documentos reais.

| Antes do Core 0.2.0 | Depois do Core 0.2.0 | Casos |
|---|---|---|
| Exporta | Exporta | Documento aninhado válido, extensão de metadados, células numéricas convertidas pelo sanitizador existente |
| Exporta | Rejeita por schema | Blocos customizados na raiz/filhos/filtrados; IDs de bloco/seção ausentes; verbosidade, público, tipo do ID, título vazio, idioma e nível de filho inválidos |
| Rejeita por auditoria | Rejeita por auditoria | IDs de bloco duplicados, lista de seções vazia |

Caminho/palavra do schema e `strict_outcome` são a decisão de compatibilidade
revisada, não expectativas regeneradas. Testes materializam cada entrada a
partir de `base_document` e `changes` e exercitam o gate real nos quatro
formatos. Rejeições não podem construir AST, chamar renderer, criar diretório
ou sobrescrever destino; a entrada permanece intacta. A classificação após
normalização também é conferida com o schema empacotado.

```bash
make test-file F=tests/test_export_schema_gate.py
```

Mudanças intencionais de aceite exigem revisão de comportamento. Preservar
fixtures/goldens E1.0: o docstruct mantém o fallback. O dataset opcional de seis
documentos está ausente; não há resultado declarado de providers/dataset nem
novo teste pulado. Veja o
[ADR 0026](../../../docs/adr/0026-strict-canonical-export-gate.pt-br.md).
