# 0009. A reparação Unicode de PDFs legados é um estágio puro da docstruct orquestrado pelo core

Também disponível em **inglês (EUA)**: [English version](0009-legacy-unicode-repair.md)

- **Status:** Aceito
- **Data:** 2026-10-23
- **Componentes:** docstruct, core
- **Issues:** —

## Contexto

PDFs produzidos por toolchains TeX/dvips antigas podem não trazer um mapa
`/ToUnicode` confiável. Os extratores passam a inferir o texto da codificação
da fonte, e o resultado costuma ser NFD (`C` + U+0301) ou usar `ı` (U+0131, i
sem ponto) antes da marca combinante. `NFC` compõe a primeira forma, mas não a
segunda.

A amostra de referência (`velocidade-instantanea.pdf`, cinco páginas, `dvips +
MiKTeX GPL Ghostscript 9.05`) tem **211 marcas combinantes** e **8 ocorrências
de `ı` + U+0301** na camada textual, e nenhum acento espaçador. `pdftotext
-layout` devolve `Brası́lia`, `difı́cil`, `Cálculo` (NFD), `função` (NFD). O
PDF/UA gerado a partir dessa entrada exibe depois formas espaçadoras como
`C´ alculo` e `fun¸ c˜ ao`; são sintoma do texto corrompido chegando ao
renderer, não a forma que o extrator devolve.

Há três lugares para reparar: dentro do extrator da Toolbox (perde política e
proveniência), no renderer (tarde demais para HTML, DOCX e fala) ou no estágio
canônico do core. O core já concentra a política determinística de texto em
`docstruct.text.norm_fix` e nas obrigações v2.3, então a mesma divisão vale
aqui.

## Decisão

- **A função pura vive na docstruct.** `docstruct.text.unicode_repair` expõe
  `detect_legacy_unicode` e `repair_legacy_unicode`, usa apenas a biblioteca
  padrão e devolve a regra e o intervalo original de cada edição. Ligaduras,
  NBSP e hifenização continuam em `norm_fix`: um dono por transformação
  (ADR-0004).
- **O core decide quando executar.** O manifesto emite a obrigação
  `repair-legacy-unicode`, satisfeita pelo método determinístico
  `unicode-repair`. `LEGACY_UNICODE_REPAIR` escolhe o modo: `off` (default, sem
  observação nem obrigação), `detect` (observação e advertência técnica, sem
  reescrever) ou `repair`.
- **Só blocos de prosa são elegíveis.** `paragraph`, `heading`, `title`,
  `list_item`, `caption` e `footnote` podem ser reescritos; `formula`, `code`,
  `table` e `picture` nunca são. Código inline, URLs e trechos `$...$` ficam
  protegidos.
- **A fase B repara apenas o que é inequívoco.** Compõe runs combinantes (NFC)
  e reescreve `ı`/`ȷ` + marca quando o idioma não usa i sem ponto e a sequência
  realmente compõe. Acentos espaçadores (`C´ alculo`) são detectados, mas não
  reescritos até existir evidência de fonte/geometria.
- **A ambiguidade é reportada, não adivinhada.** A decisão carrega
  `confidence=None` até a calibração e marca `needs_review` quando um sinal
  conhecido fica sem reparo; o handler registra regras e contagens em
  `element.metadata["unicode_repair"]`.

## Consequências

- **O comportamento padrão não muda.** Habilitar o reparo é mudança de
  configuração; o modo entra na chave do cache de processamento, e alterar a
  descrição do domínio invalida entradas antigas como de costume.
- **Precisão antes de recall.** Uma palavra deixada em NFD é uma degradação
  conhecida; um acento legítimo ou um trecho de código reescrito por engano
  seria pior. Por isso a regra de acento espaçador só será ligada quando a
  Toolbox reportar `source_font_risk`.
- **Trabalho seguinte.** Preflight da Toolbox (`/ToUnicode`, fontes) para
  preencher `source_font_risk`; reparo por geometria e divergência entre
  providers para acentos espaçadores; gate de exportação comparando o texto
  canônico com o PDF/UA reextraído.
- **Conformidade.** `libs/docstruct/tests/test_unicode_repair.py` cobre as
  regras, os casos negativos (fórmula, código, URL, turco, marcas que não
  compõem) e a idempotência; `tests/test_legacy_unicode_repair.py` cobre a
  emissão no manifesto, o handler e o contrato de obrigação não crítica.
