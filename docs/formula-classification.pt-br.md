# Classificação de candidatos a fórmula

[English](formula-classification.md)

## Problema e sintomas

O rótulo `formula` de um extrator não comprova que uma região contenha matemática.
Um desenho molecular enviado a `math.recognize` pode produzir LaTeX plausível,
mas incorreto. O sucesso do OCR matemático não identifica sozinho esse engano.

## Política de processamento

Antes do enriquecimento de imagens e do reconhecimento matemático, o Core
inspeciona regiões de fórmula renderizáveis que ainda não possuem marcação
LaTeX. Utiliza a visão existente, um prompt específico de classificação e as
instruções químicas compartilhadas. O prompt de transcrição matemática usado
pelo agente de dados permanece intacto.

- **Matemática:** mantém o elemento e utiliza `math.recognize`. O LaTeX do
  classificador não substitui o resultado do reconhecedor matemático.
- **Conteúdo não matemático:** muda o elemento para `picture`, preserva sua
  localização, tipo, rótulo e texto originais e reaproveita a descrição acessível.
  O recorte lido pelo modelo vira a imagem (`metadata.src`), então a exportação
  mostra o desenho descrito. Reconcilia suas obrigações usando
  `reconcile_reclassified_element_processing_needs`, que também remove as
  necessidades exclusivas de fórmula (`normalize-formula`). A etapa de imagens
  ignora essa descrição já concluída, evitando uma segunda solicitação visual.
- **Indefinido** (o modelo marca `classification_uncertain`): preserva o
  conteúdo e a região originais, registra metadados, não executa reconhecimento
  matemático, restringe `verbalize-formula` à revisão humana e remove
  `normalize-formula`. Essa escalada explícita pode impedir a conclusão
  automática do job; ela não confirma que a região seja matemática.
- **Não classificado** (sem resposta: provedor bloqueado, recorte indisponível,
  falha da chamada visual): não é evidência contra matemática, então a região
  segue o caminho de fórmula que tinha antes desta checagem (`math.recognize` e
  depois o fallback visual). Uma indisponibilidade do provedor de visão não
  manda, portanto, todas as fórmulas do documento para revisão humana.

`metadata.formula_classification` registra `status` (`math`, `picture`,
`unresolved` ou `unclassified`), `reason`, a `confidence` do modelo e seus
`warnings`. A confiança informada pelo modelo continua sendo metadado, não um
critério calibrado de aceitação. Uma descrição útil devolvida pelo fallback
visual matemático também reclassifica a região como imagem, com
`reason: "recognition_fallback"` (`"candidate_inspection"` nesta checagem).

## Custo operacional e limites

Cada candidato acrescenta uma inspeção visual antes do OCR matemático. São
reutilizados os controles de concorrência, falha do provedor e cache dependente
do prompt. Classificação e reconhecimento podem solicitar o mesmo recorte
separadamente. Não é instalado um modelo químico, nem inferida a identidade
molecular a partir de um desenho.

Regiões que já contêm LaTeX (inclusive um rótulo como `\tag{1}`, registrado
em `metadata.latex_markup`) e tipos de origem não renderizáveis seguem seus
caminhos anteriores. A proteção não corrige moléculas já convertidas em LaTeX
pelo extrator antes de chegar ao Core.

Os testes usam classificações controladas e as transformações reais do Core
para reconciliar obrigações e gerar blocos de exportação. Forçar o rótulo
`formula` em um recorte químico não comprova que um extrator tenha emitido esse
rótulo em uma execução real. A validação real precisa registrar documento,
página, região, provedores, respostas e resultado exportado, conforme a
[issue #290](https://github.com/A11yDevs/acessilia/issues/290).
