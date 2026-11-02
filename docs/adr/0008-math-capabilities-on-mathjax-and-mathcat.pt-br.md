# 0008. As capacidades de matemática rodam sobre MathJax e MathCAT

Também disponível em **inglês (EUA)**: [English version](0008-math-capabilities-on-mathjax-and-mathcat.md)

- **Status:** Aceito
- **Data:** 2026-10-20
- **Componentes:** Toolbox, SDK, core
- **Issues:** [toolbox#64](https://github.com/A11yDevs/acessilia-toolbox/issues/64), [toolbox#65](https://github.com/A11yDevs/acessilia-toolbox/pull/65), [toolbox#66](https://github.com/A11yDevs/acessilia-toolbox/pull/66), [#184](https://github.com/A11yDevs/acessilia/issues/184), [#193](https://github.com/A11yDevs/acessilia/pull/193)
- **Substitui:** o provider citado na decisão 2 da [ADR-0007](0007-manifest-model-and-mathml-conversion.pt-br.md) (`pure-math` com `latex2mathml`); o restante da ADR-0007 continua valendo.

## Contexto

A [ADR-0007](0007-manifest-model-and-mathml-conversion.pt-br.md) decidiu que
o core obtém MathML e o texto falado das fórmulas só pelas capacidades
`math.convert` e `math.verbalize` da Toolbox, via SDK. Ela também citou a
implementação por trás delas: o provider `pure-math`, com o `latex2mathml`
para a conversão e um verbalizador baseado em expressões regulares.

Antes de o core passar a usar essas capacidades, a Toolbox mediu se elas eram
pelo menos tão boas quanto o código local do core que iam substituir
([toolbox#64](https://github.com/A11yDevs/acessilia-toolbox/issues/64)):

- 48 fórmulas foram convertidas por cinco ferramentas: as fórmulas de teste do
  core e mais 30 construções comuns em material didático.
- Os resultados foram falados pelo MathCAT em pt-BR.

A medição mostrou que:

- **Os dois verbalizadores perdiam conteúdo em silêncio.** As regras de
  expressões regulares do `pure-math` e o `formula_tools` do próprio core
  perdiam. Por exemplo, `\frac{d}{dx}\sin x=\cos x` virava
  "d, dividido por d x x igual a x" no core.
- **O `latex2mathml` gerava MathML inválido.** Falhava em `aligned`, que a
  saída do Nougat usa, e não suporta mhchem (`\ce`) nem `\operatorname`.
- **O MathJax 3 teve a melhor cobertura.** Tratou tudo, inclusive mhchem. O
  único problema restante foi `\xrightarrow`, que é um bug do MathCAT.
- **O MathCAT fala a partir da estrutura do MathML.** Tem licença MIT e é o
  motor que está substituindo o MathPlayer no NVDA. Ganhou regras em
  português brasileiro e também produz braille matemático, incluindo o CMU,
  código usado no Brasil.

## Decisão

**O `math.convert` (`latex-to-mathml`) e o `math.verbalize` são servidos pelo
provider `math-speech`, um adaptador HTTP para o sidecar `math-speech`.** O
sidecar roda o **MathJax 3** para LaTeX → MathML e o **MathCAT** para MathML →
fala (e braille). O provider `pure-math`, seu verbalizador de expressões
regulares e o `latex2mathml` saem da Toolbox, sem fallback: há um conversor e
um verbalizador.

- **Contratos inalterados.** O `math.convert@1` continua devolvendo
  `mathml@1`, e o `math.verbalize@1` continua devolvendo `verbalized@1` em
  pt-BR (ADR-0007). O `math.verbalize` aceita os parâmetros opcionais `style`
  (`ClearSpeak` por padrão, ou `SimpleSpeak`) e `verbosity` (`Terse`, `Medium`
  por padrão, ou `Verbose`).
- **Versões fixadas e rastreáveis.** O MathJax e o commit do MathCAT ficam
  fixados na imagem. O `/version` do sidecar entra na chave de cache da
  execução, e um arquivo de referência com a fala exata em pt-BR de 24
  fórmulas quebra o build da imagem quando uma atualização muda alguma delas.
  Assim, fala nova é revisada de propósito.
- **Entrada endurecida.** O MathJax roda sem os pacotes de TeX que chegariam
  às exportações HTML ou carregariam código em tempo de execução (`html`,
  `require`, `autoload`, `setoptions`), e sem `noerrors`/`noundefined`, para
  que LaTeX inválido seja um erro que o chamador possa tratar.
- **Erros explícitos.** LaTeX que não pode ser lido gera `400`
  (`invalid_input`), e sidecar indisponível gera `503`. Os dois chegam ao
  core como erros do SDK; o core decide o que fazer, sem fallback local
  ([ADR-0003](0003-remote-only-operational-capabilities.pt-br.md)).
- **A direção inversa fica no processo.** O `mathml-to-latex` mantém o
  mapeador existente, de melhor esforço, dentro da Toolbox
  (`providers/mathml_latex.py`), porque o MathJax não gera TeX.

## Consequências

- **Nada muda no código do core.** O core continua chamando as capacidades, e
  não um provider. O `toolbox_math_provider` padrão do SDK é `math-speech`
  (#193).
- **A fala melhora já.** As alternativas faladas que o core coloca nas
  exportações seguem a estrutura da fórmula, por exemplo "d sobre d x, seno
  de x; é igual a cosseno de x".
- **O sidecar precisa rodar onde a matemática estiver ativa.** Sua imagem é
  construída e publicada pela workflow `Sidecars` da Toolbox, como a dos
  outros sidecars (achado A7 da auditoria). Até ele rodar, as duas
  capacidades respondem `503`.
- **As lacunas conhecidas das regras em português do MathCAT** ficam
  registradas no arquivo de referência como estão. Exemplos: "maiúscula e" em
  vez de "E maiúsculo", e `\mid` falado como "divide". O `\xrightarrow` falha
  em qualquer idioma. Essas lacunas se corrigem no upstream ou com ajustes
  locais, nunca reintroduzindo um segundo verbalizador.
- **Em aberto, não decidido aqui:**
  - O sidecar já produz braille CMU, mas nenhuma capacidade o expõe ainda. Uma
    capacidade `math.braille`, ou um parâmetro numa nova versão do
    `math.verbalize`, precisa de decisão própria.
  - Verbalizar idiomas além do pt-BR exige um parâmetro de idioma numa nova
    versão do `math.verbalize` (ADR-0007).
