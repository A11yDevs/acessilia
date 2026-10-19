# 0003. Capacidades operacionais rodam remotamente, sem fallbacks locais

Também disponível em **inglês (EUA)**: [English version](0003-remote-only-operational-capabilities.md)

- **Status:** Aceito
- **Data:** 2026-10-18
- **Componentes:** core, SDK, Toolbox
- **Issues:** [#150](https://github.com/A11yDevs/acessilia/issues/150), [#152](https://github.com/A11yDevs/acessilia/issues/152)

## Contexto

Cinco pontos do core tentavam a Toolbox primeiro e depois caíam para uma
implementação local:

- exportação PDF/UA (pandoc + TeX Live);
- `media.inspect` (Pillow + PyMuPDF);
- divisão de PDF e renderização de página (PyMuPDF);
- os structurers de estrutura e de layout (PyMuPDF).

Cada ponto tinha a própria chave de ativação, a própria regra sobre quais
erros disparam o fallback e o próprio jeito de reportar falhas. Para sustentar
esses fallbacks, a imagem do core instala pandoc, TeX Live e a toolchain do
veraPDF. As cópias locais também divergiram: a inspeção de mídias do core não
consegue mais classificar páginas escaneadas, e o template PDF/UA do core
ignora o idioma pedido.

## Decisão

- **Capacidades operacionais rodam na Toolbox.** "Operacional" quer dizer
  tudo o que precisa de uma ferramenta externa, um modelo ou infraestrutura
  especializada: Pandoc, TeX Live, veraPDF, renderização com PyMuPDF,
  inspeção de mídias, Docling, MinerU, Nougat, modelos de IA.
- **A política de produção é `remote_only`.** O core não roda essas
  capacidades no próprio processo.
- **Sem fallbacks locais.** O core não acrescenta fallback local para uma
  capacidade operacional e não instala dependências pesadas só para oferecer
  um.
- **A indisponibilidade é explícita.** Quando uma capacidade está
  indisponível, o core faz a etapa falhar ou a degrada como decisão de negócio
  visível e documentada. Nos dois casos a causa é registrada (veja o
  [ADR-0006](0006-availability-and-failover.pt-br.md)). Ele nunca produz um
  resultado silenciosamente por outra implementação.
- **As chaves significam "executar ou pular".** As configurações
  `TOOLBOX_*_ENABLED` decidem se o core executa uma capacidade. Elas nunca
  escolhem uma implementação local.
- **Exceções exigem um ADR.** Um executor local ou offline precisa de um ADR
  com justificativa, escopo, responsável e critério de saída (veja o
  [processo de ADR](README.pt-br.md#processo)).
- **A docstruct não é afetada.** Algoritmos puros da docstruct chamados no
  próprio processo não são capacidades operacionais, então esta decisão não
  os cobre.

## Consequências

- A #150 remove os caminhos locais, uma capacidade por pull request, e depois
  tira pandoc, TeX Live e veraPDF/JRE do `infra/Dockerfile`. O tamanho da
  imagem é medido antes e depois.
- **Desvios conhecidos, registrados na auditoria da #152:** o core ainda
  importa o PyMuPDF em oito módulos, entre eles o `PyMuPDFStructurer`,
  o `pymupdf_extractor` e o `image_tools`. A renderização de páginas e regiões
  do orquestrador saiu dessa lista na F5 da #150: ela passa pelo
  `pdf.render@2`. Também importa o Pillow, o OpenCV (`image_enhancer`) e, sem
  declará-lo, o docling (`formula_worker`). Eles são removidos em issues de
  acompanhamento antes que `pymupdf`, `pillow` e `opencv-python` saiam do
  `pyproject.toml`.
- **Verificação prevista (#152):** um teste arquitetural no core que proíba
  imports de `fitz`, `PIL`, `cv2` e `docling` e chamadas `subprocess` a
  pandoc, engines de LaTeX ou veraPDF. Ele mantém uma allowlist dos ofensores
  atuais que só pode diminuir.
