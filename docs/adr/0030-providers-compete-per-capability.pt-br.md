# 0030. Providers competem por capacidade; as suítes de estrutura ficam estruturais

Também disponível em **inglês (EUA)**: [English version](0030-providers-compete-per-capability.md)

- **Status:** Proposto
- **Data:** 2026-11-23
- **Componentes:** core, SDK, Toolbox
- **Issues:** [#640](https://github.com/A11yDevs/acessilia/issues/640), [#818](https://github.com/A11yDevs/acessilia/issues/818), [#324](https://github.com/A11yDevs/acessilia/issues/324), [acessilia-toolbox#169](https://github.com/A11yDevs/acessilia-toolbox/issues/169)
- **Baseia-se em:** [ADR-0027](0027-mcp-core-toolbox-contract.pt-br.md), [ADR-0028](0028-operational-execution-in-the-toolbox.pt-br.md), [ADR-0029](0029-symbolic-core-every-step-planned.pt-br.md)

## Contexto

O bootstrap extrai a estrutura de um documento com o Docling (o provider
primário) e, em `FUSION_MODE=dual`, com o MinerU. Os dois são suítes: além da
detecção de layout, da ordem de leitura, do OCR e da estrutura das tabelas,
eles conseguem reconhecer fórmulas, descrever e classificar imagens e
enriquecer código.

A extração foi configurada de propósito para que as suítes se concentrem na
estrutura. O registro da Toolbox define só o `table_mode: accurate` do
Docling, o que deixa o enriquecimento de fórmulas, a descrição e a
classificação de imagens e o enriquecimento de código do Docling nos seus
padrões, que são desligados. Providers mais especializados fazem esse
trabalho:
- LaTeX das fórmulas: `math.recognize`, com o PP-FormulaNet;
- descrições de imagens: o modelo de visão;
- MathML e matemática falada: `math.convert` e `math.verbalize`, com o
  `math-speech`.

Os passos de enriquecimento do core só rodam onde a extração deixou algo
faltando ou duvidoso (`docs/architecture/workflow-actions.pt-br.md`).

Três fatos ainda não correspondem a essa intenção:
- **O MinerU reconhece fórmulas dentro da capacidade de estrutura.** O
  adaptador do MinerU 2.1 da Toolbox manda `formula_enable=true` por padrão.
  No modo dual, uma fórmula que chega com LaTeX passa pela condição do core e
  pula o PP-FormulaNet.
- **As opções são invisíveis para o core.** O core manda para
  `document.structure.extract` só o idioma e a flag de cache. As opções que
  mantêm as suítes estruturais vivem no registro da Toolbox e nos padrões dos
  providers, e o manifesto não as registra.
- **As tabelas são reconhecidas dentro da capacidade de estrutura.** O
  Docling roda o TableFormer (`accurate`) e o MinerU o seu modelo de tabelas
  durante `document.structure.extract`. A capacidade especializada já existe:
  `table.recognize@1`, com um provider, o VLM `qwen3-vl-8b`. O contrato dela é
  feito para um VLM. A entrada é um recorte (`artifact/image@1`), e a saída,
  `table-candidates@1`, exige uma geração greedy, amostras com semente,
  `temperature`, `top_p` e `model`. O core lê uma tabela com um modelo
  (`DataAgent`) só quando a extração a deixou sem estrutura utilizável, ou
  embaralhada.
- **O provider é fixo por implantação.** `CoreConfig.toolbox.providers` guarda
  um provider por chave, com padrões no registro do SDK. A Toolbox, porém, já
  registra providers concorrentes:
  - `document.structure.extract`: docling, mineru, nougat;
  - `math.recognize`: pp-formulanet, docling-math, rapid-latex-ocr;
  - `document.ocr`: docling-ocr, mineru-ocr;
  - `document.layout.analyze`: docling-layout, mineru-layout;
  - `audio.synthesize` e `music.omr` têm dois providers cada.

  Alguns desses providers são as outras habilidades das suítes, expostas como
  capacidade própria: `docling-math`, `docling-ocr`, `mineru-ocr`.

## Decisão

### As suítes de estrutura ficam estruturais

- Em `document.structure.extract`, uma suíte deve entregar estrutura:
  - detecção de layout, com rótulos e caixas, inclusive das tabelas como
    regiões;
  - a ordem de leitura;
  - o OCR de que o texto precisa.

  As opções dela que produzem outro conteúdo ficam desligadas ali:
  reconhecimento de tabelas (as células), reconhecimento de fórmulas,
  descrição e classificação de imagens, e enriquecimento de código.
- As outras habilidades de uma suíte são usadas **por capacidade**: a suíte
  vira um provider dessa capacidade (como o `docling-math` é para
  `math.recognize`), nunca um extra embutido na extração estrutural.
- As opções de pipeline das quais o core depende são explícitas e
  registradas. A extração informa as opções com que de fato rodou, e o
  manifesto as guarda como proveniência.

### Tabelas são uma capacidade especializada

- As células de uma tabela vêm de `table.recognize`, cujos providers competem
  como em qualquer outra capacidade. Docling e MinerU podem ser dois deles
  (`docling-table`, `mineru-table`), ao lado do VLM. Os dois serviços já
  aceitam uma imagem e rodam seu modelo de tabelas, e a Toolbox já traduz as
  tabelas das duas suítes para uma AST canônica de tabela: a grade do Docling
  e o HTML do MinerU.
- `table.recognize` precisa de uma versão de contrato neutra quanto ao
  provider. Um reconhecedor determinístico devolve uma tabela, não gerações a
  uma temperatura. A saída traz a tabela como a AST canônica de tabela
  (células, spans, cabeçalhos), que o core já lê como `table_ast`, e sua
  proveniência. As gerações continuam opcionais, para o VLM.
- A entrada deve preservar a camada de texto do PDF quando houver: uma região
  da página de origem, não só uma imagem. Num PDF nato-digital, o TableFormer
  tira o texto das células do próprio texto da página. Num recorte em imagem
  ele recorre ao OCR, que é pior.
- Ordem, para que a qualidade não caia:
  1. Docling e MinerU viram providers de `table.recognize` (versão 2 do
     contrato);
  2. o benchmark os compara por tabela, contra o VLM e contra as tabelas de
     hoje, reconhecidas dentro da extração;
  3. só então o reconhecimento de tabelas é desligado em
     `document.structure.extract`, e toda tabela detectada vai para
     `table.recognize`.

### Providers competem por capacidade

- Toda capacidade pode ter vários providers. Eles competem.
- O provider com melhor desempenho numa capacidade é **mantido por mérito**.
  Trocar o provider padrão exige evidência para aquela capacidade: o
  benchmark (`acessilia-benchmark`, drbench) ou a qualidade medida, não
  conveniência.
- Um provider não é mantido numa capacidade por causa dos seus resultados em
  outra.

### Depois: escolhido por contexto e histórico

- O alvo é escolher o provider de cada capacidade por contexto (tipo de
  mídia, idioma, escrita, tipo de documento) e a partir do histórico de
  execuções bem e malsucedidas. A investigação é a #818 (0.4.0).
- Até lá, a escolha continua sendo a configuração da implantação
  (`CoreConfig.toolbox.providers`), e toda execução registra o provider que
  usou.

## Consequências

- **acessilia-toolbox#169:** desligar o reconhecimento de fórmulas do MinerU
  em `document.structure.extract`, documentar o que o `--tier basic` do
  MinerU 4 liga, e informar as opções efetivas na `configuration` da
  extração. As tabelas seguem a ordem acima, pela acessilia-toolbox#170.
- **acessilia-toolbox#170:** `table.recognize@2`, neutro quanto ao provider,
  com `docling-table` e `mineru-table` como providers e uma entrada que
  preserva a camada de texto.
- **O core lê tabelas pela capacidade.** Hoje o core lê uma tabela com uma
  chamada de modelo (`DataAgent`), e o especialista de tabelas escolhe entre
  candidatos (`TableSpecialistAgent`, o medoide por similaridade). Os dois
  passam a consumir os providers concorrentes de `table.recognize`. Escolher
  entre candidatos por tabela é a primeira forma concreta de competição por
  capacidade.
- **Custo:** uma chamada por tabela, cada uma com sua própria detecção, custa
  mais que uma tabela reconhecida dentro da extração. O benchmark pesa isso
  contra a qualidade.
- **As condições do core continuam significativas.** Com as suítes
  estruturais, uma fórmula com LaTeX ou uma tabela com estrutura na extração
  significa que a suíte entregou estrutura, não um reconhecimento que pulou o
  provider especializado.
- **#818 (0.4.0):** a escolha por mérito, contexto e histórico. O domínio 2.4
  já modela providers como objetos (`(requires m c p)`, `(offered c p)`),
  então o plano pode depois escolher entre os providers oferecidos de uma
  capacidade, com custos vindos do histórico. Isso é uma mudança de domínio.
- **Contrapartida:** o reconhecimento embutido numa suíte pode ser mais
  barato que chamar outro provider. Quando ele for bom o bastante, deve
  competir como provider daquela capacidade, e não ser ligado dentro da
  extração estrutural.
- **Conformidade:** o registro da Toolbox e as opções informadas pela extração
  mostram a configuração das suítes; a evidência do benchmark acompanha a
  troca de provider padrão.
