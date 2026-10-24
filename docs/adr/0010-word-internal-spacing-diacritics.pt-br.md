# 0010. Acentos espaçadores internos à palavra são reparados; os isolados exigem evidência no documento

Também disponível em **inglês (EUA)**: [English version](0010-word-internal-spacing-diacritics.md)

- **Status:** Aceito
- **Data:** 2026-10-24
- **Componentes:** docstruct, core
- **Issues:** #244
- **Emenda:** o escopo da fase B do [ADR-0009](0009-legacy-unicode-repair.pt-br.md): acentos espaçadores deixam de ser apenas detectados, e a premissa de `source_font_risk` é retirada.

## Contexto

O [ADR-0009](0009-legacy-unicode-repair.pt-br.md) entregou a fase B com reparo
de NFC e i sem ponto, deixando os acentos espaçadores (`C´ alculo`) apenas
detectados. A premissa era que a extração de um PDF TeX legado devolveria NFD e
`ı` sem ponto, e que as formas espaçadoras só apareceriam na saída renderizada.

A extração real do pipeline desmente essa premissa. O
`document.structure.extract` com o provider Docling na amostra de referência
devolve **206 acentos espaçadores** e apenas 6 marcas combinantes:

```text
Universidade de Bras´ ılia
Departamento de Matem´ atica
C´ alculo 1
n˜ ao ´ e dif´ ıcil notar que a fun¸ c˜ ao ...
```

A fase B pulava todo elemento cujo único sinal fosse acento espaçador; o texto
canônico chegava ao renderer sem alteração e o PDF/UA exportado mantinha o
defeito.

O renderer não é a causa. Exportar um AST em NFC (`Cálculo`, `Matemática`,
`função`) pela mesma capacidade `document.export.pdf_ua` produz uma camada
textual com os caracteres pré-compostos corretos. O defeito está a montante, no
texto que o core recebe.

## Decisão

- **O reparo de acentos espaçadores faz parte do modo `repair`.** Com
  `LEGACY_UNICODE_REPAIR=repair`, o core habilita o reparo de acentos
  espaçadores nos blocos de prosa (`paragraph`, `heading`, `title`,
  `list_item`, `caption`, `footnote`).
- **Duas camadas, conforme a posição do acento.**
  - *Interno à palavra*: o acento está colado à letra anterior (`C´ alculo`,
    `Bras´ ılia`). É a forma que a extração TeX legada produz; é reparado sempre
    que o bloco é elegível.
  - *Isolado*: o acento está separado da palavra anterior
    (`... posi¸ c˜ ao ´ e ...`, incluindo o verbo). A mesma forma aparece em
    prosa que discute um acento, então só é reparado quando o documento tem
    pelo menos `5` ocorrências internas à palavra, o que fornece evidência em
    nível de documento.
- **`ı` e `ȷ` são bases válidas.** O acento agudo espaçador sobre o i sem ponto
  (`Bras´ ılia`) compõe `í`; o mesmo vale para o circunflexo.
- **Nada mais muda.** Fórmulas, código, tabelas, imagens, código inline, URLs e
  trechos `$...$` nunca são reescritos. A decisão registra
  `needs_review=True` quando houve acento espaçador, para manter a ambiguidade
  visível na auditoria.
- **A evidência é textual, não metadado de fonte.** A forma interna à palavra é
  o sinal; `source_font_risk` é retirado do contexto de reparo. Um preflight
  futuro da Toolbox pode reintroduzir um gate de fonte com dados reais, mas
  esta decisão não finge tê-los.
- **A política é do core.** A API da docstruct expõe
  `allow_spacing_diacritics` e `allow_standalone_spacing_diacritics`; só o core
  decide quando a evidência do documento é suficiente.

## Consequências

- **A amostra de referência é reparada de ponta a ponta.** Na extração acima,
  os 206 acentos espaçadores são reescritos em 36 dos 53 elementos elegíveis;
  as palavras conhecidas (`Brasília`, `Cálculo`, `Matemática`, `função`,
  `não é`, `difícil`, `posição`, `Você`, `instantânea`, `Porém`) saem
  corretas.
- **Prosa sobre acentos fica protegida.** Um texto que discute acentos e não
  tem a forma interna à palavra mantém seus exemplos isolados intactos, porque
  o limiar de documento não é atingido.
- **O opt-in e a auditoria continuam.** `off` e `detect` mantêm o
  comportamento anterior. `needs_review` significa que sobrou um sinal sem
  reparo; um elemento totalmente reparado não é marcado, e o handler registra
  `edited` e os nomes das regras em `element.metadata["unicode_repair"]`.
- **Resultados em cache são invalidados.** A descrição do domínio muda, então
  seu SHA-256 (parte da chave do cache de processamento) muda também; um
  resultado produzido antes desta decisão não é reaproveitado.
- **A fase D continua necessária.** Um texto canônico limpo não prova que o
  PDF/UA exportado está limpo; comparar o canônico com a reextração da saída
  segue como o próximo gate.
- **Conformidade.** `libs/docstruct/tests/test_unicode_repair.py` cobre as duas
  camadas, a base sem ponto e os trechos protegidos;
  `tests/test_legacy_unicode_repair.py` cobre o handler, o limiar de documento
  e o comportamento dos acentos isolados.
