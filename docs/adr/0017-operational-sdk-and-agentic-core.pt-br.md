# 0017. Fronteiras entre o SDK operacional e o core agêntico

Também disponível em **inglês (EUA)**: [English version](0017-operational-sdk-and-agentic-core.md)

- **Status:** Proposto
- **Data:** 2026-11-12
- **Componentes:** core, SDK, docstruct, Toolbox
- **Issues:** [#470](https://github.com/A11yDevs/acessilia/issues/470), [#402](https://github.com/A11yDevs/acessilia/issues/402)
- **Emenda, quando aceita:** [ADR-0002](0002-component-responsibilities.pt-br.md) (a linha do SDK e as perguntas de "onde fica o código novo?"); esclarece a [ADR-0003](0003-remote-only-operational-capabilities.pt-br.md) e complementa a [ADR-0016](0016-core-package.pt-br.md)

## Contexto

A ADR-0002 dá ao SDK "contratos como os clientes os consomem, clientes e
transporte da Toolbox, referências de artefato, regras de disponibilidade e
failover, acesso em processo aos algoritmos puros do docstruct". A quarta
pergunta dela manda para o SDK só o que diz respeito a *como* chegar a uma
capacidade. Assim, uma sequência de chamadas de capacidades com parâmetros
explícitos não tem outro lugar além do core. A cadeia de fórmula é um exemplo:
renderizar uma região e depois `math.recognize`, `math.convert` e
`math.verbalize`. No core, ela fica misturada com a política que decide quando
executá-la. Um script, um benchmark ou outro front-end não consegue rodar essa
sequência sem o core.

A [#470](https://github.com/A11yDevs/acessilia/issues/470) propõe:
- o SDK oferece operações reutilizáveis e workflows determinísticos;
- o core mantém a autoridade para decidir estratégias e objetivos;
- a portabilidade do docstruct e o papel dele como contrato estrutural
  compartilhado viram princípios explícitos e testáveis.

O [inventário da fase 1 da #470](../architecture/operational-boundaries-inventory.pt-br.md)
mediu a situação:

- **Boa parte da #470 já está decidida e verificada.**
  - O docstruct usa só a biblioteca padrão, com um acelerador opcional
    protegido, o `rapidfuzz`; o `libs/docstruct/tests/test_purity.py` confere
    isso. Ele não confere que o docstruct fica longe da rede, do ambiente, de
    arquivos e de subprocessos: permite toda a biblioteca padrão.
  - O `docstruct.manifest` é o modelo normativo do documento (ADR-0007), e os
    modelos pydantic ficam como modelos de transporte conferidos.
  - A ADR-0002 já permite SDK → docstruct.
  - O teste da Toolbox proíbe imports do SDK e do core.
- **Restam quatro lacunas** (como medidas; a fase 2 da #470 fechou três
  depois, marcadas abaixo):
  - o SDK não depende do docstruct, e o job isolado do CI o recusa;
  - o docstruct não tem job de instalação isolada (**fechada pela #495**, o
    job `docstruct alone`);
  - nada testa a independência de infraestrutura do docstruct (**fechada pela
    #497**, `test_infrastructure.py`);
  - nada confere se a versão do docstruct fixada pela Toolbox acompanha a do
    core. Os branches concordam hoje (0.4.0 nas duas `main`, 0.5.0 nas duas
    `develop`), mas só por convenção (**fechada pela #498** quanto ao pin,
    `scripts/check_docstruct_pin.py`).
- **O core guarda seis operações determinísticas ao lado da política que as
  executa:**
  - a cadeia de fórmula;
  - o juiz de página;
  - a inspeção de mídia;
  - a auditoria PDF/UA;
  - os text spans (já no SDK, #455);
  - as exportações.

Opções consideradas:

1. **Manter o SDK como transporte.** Toda composição fica no core, e todo uso
   de uma composição carrega o core.
2. **O SDK oferece operações e workflows determinísticos; o core mantém toda
   decisão** (#470).
3. **O SDK executa planos operacionais** recebidos como dados. Rejeitada por
   ora: é o caminho mais curto para um segundo orquestrador, o primeiro risco
   que a #470 lista.

## Decisão

Proposta: a opção 2.

- **O critério é a autoridade para decidir, não a presença de IA nem de
  condicionais.**
  - **Mecanismo:** uma função que executa capacidades e algoritmos do
    docstruct numa ordem fixa, com parâmetros explícitos, e informa o que
    aconteceu. Vai para o SDK.
  - **Política:** uma função que escolhe objetivos, estratégias, providers,
    limiares, novas tentativas ou o valor de um resultado. Fica no core.
  - **Código misto:** uma função que faz as duas coisas é dividida nessa
    linha.
- **O que o SDK pode oferecer**, além da lista da ADR-0002:
  - operações reutilizáveis e workflows determinísticos compostos de
    capacidades da Toolbox e algoritmos do docstruct;
  - validação das entradas e saídas, erros tipados e a proveniência de cada
    passo (P10 da #470): a capacidade e a versão, os parâmetros efetivos, o
    provider, as referências de entrada e de saída.

  Uma operação pode chamar uma capacidade probabilística pela Toolbox (um
  modelo), desde que os passos e os parâmetros sejam explícitos.
- **O que o SDK não pode fazer**, além da lista da ADR-0002:
  - planejar, escolher objetivos, replanejar ou guardar uma política;
  - depender do core;
  - executar localmente uma capacidade pesada que pertence à Toolbox
    ([ADR-0003](0003-remote-only-operational-capabilities.pt-br.md)).

  Compor capacidades remotas não muda a política `remote_only`.
- **Os princípios do docstruct**, como regras testadas:
  - **só a biblioteca padrão:** aceleradores opcionais só são permitidos
    quando protegidos por `except ImportError`, listados no teste de pureza e
    com uma implementação equivalente na biblioteca padrão. É a alternativa A
    da #470, que já está em vigor;
  - **o docstruct é a fonte normativa dos modelos estruturais e de seus
    invariantes** (ADR-0007). Compartilhar modelos Python não substitui os
    contratos de transporte versionados: os schemas REST e MCP mantêm suas
    próprias versões e testes de contrato;
  - **sem infraestrutura:** nada de rede, ambiente, arquivos, subprocessos nem
    imports do core, do SDK ou da Toolbox. O `test_purity.py` testa os
    imports, e o `test_infrastructure.py` (#470, fase 2), o resto, para os
    módulos, built-ins e atributos de `sys` que lista.
- **Dependências:** as mesmas da ADR-0002.
  - O SDK pode depender do docstruct, e passa a depender quando a primeira
    operação dele compuser um algoritmo do docstruct.
  - A instalação-base do SDK continua leve: sem framework de agentes e sem
    biblioteca operacional pesada.
- **Onde fica o código novo**, substituindo as quatro perguntas da ADR-0002:

  | Pergunta | Componente |
  |---|---|
  | Um algoritmo estrutural puro, independente de infraestrutura? | docstruct |
  | Uma operação ou composição reutilizável, com parâmetros explícitos? | SDK |
  | Precisa de um modelo, um conversor, um sidecar ou uma biblioteca operacional pesada? | Toolbox |
  | Decide objetivos, estratégias, qualidade ou replanejamento? | core |
  | Gerencia a API, os jobs, a autenticação ou a infraestrutura do serviço? | o serviço (`backend/`, ADR-0016) |

  Quando um código responde a mais de uma pergunta, ele é dividido.
- **A primeira operação é a cadeia de fórmula**, como evidência para aceitar
  esta ADR:
  - o SDK a executa a partir de um script, sem o core nem o serviço;
  - o enriquecimento de fórmulas do core a reutiliza, mantendo suas decisões;
  - os manifestos do caso 036 são iguais antes e depois.

## Consequências

- **Fica mais fácil:**
  - scripts, benchmarks e outros front-ends executam as operações sem o core;
  - o core fica só com as decisões;
  - a fronteira entre mecanismo e política tem um critério escrito.
- **Fica mais difícil:**
  - uma operação do SDK é API pública: precisa de versionamento, changelog e
    depreciação;
  - o job isolado do SDK no CI muda quando o SDK passar a depender do
    docstruct.
- **Trabalho seguinte**, em pull requests próprios:
  - um job de CI que instala o docstruct sozinho num ambiente limpo (feito,
    #495);
  - um teste de que nenhum módulo do docstruct lê o ambiente ou arquivos, abre
    um socket ou inicia um subprocesso (fase 2 da #470). O job de instalação
    isolada não confere isso (feito, #497);
  - uma verificação de que a versão do docstruct fixada pela Toolbox acompanha
    a release do core, ou fixtures compartilhadas contra as quais os dois
    testam (P8 da #470). A verificação do pin está feita (#498); as fixtures
    compartilhadas continuam em aberto;
  - a cadeia de fórmula no SDK (a evidência acima);
  - as outras operações do inventário, uma por pull request, cada uma com
    caracterização e comparação dos manifestos antes e depois.
- **Relação com a ADR-0016.** O passo 6 da fase 3 da #402 não leva para
  `backend/core/` os módulos que guardam essas operações, para que eles não
  mudem de lugar duas vezes: o juiz de página, os adaptadores da Toolbox em
  `backend/tools` e a cadeia de fórmula. Cada um vai para o seu lugar quando a
  divisão em mecanismo (SDK) e política (core) for decidida. O core continua
  ligando a sua configuração (`CoreConfig`) aos parâmetros explícitos de cada
  operação. Por isso, a ligação do core com o render (`_source_artifact_id` e
  `_toolbox_render`, que ligam as configurações ao `ToolboxPdfClient.render` e
  decidem se a origem guardada pode ser referenciada) não fica retida: o passo
  6 a leva para `backend/core/pipeline/toolbox.py`.
- **Ainda em aberto:**
  - quais operações vêm depois da cadeia de fórmula, e em que ordem;
  - qual é a API pública estável do docstruct. A proposta é: o que cada módulo
    lista em `__all__` e nas tabelas do README;
  - um contrato de plano operacional, adiado;
  - se o docstruct também precisa ser determinístico: sem relógio,
    aleatoriedade ou threads. O `test_infrastructure.py` os deixa de fora,
    porque não são infraestrutura; o docstruct não usa nenhum deles hoje.
- **Conformidade:**
  - o `libs/docstruct/tests/test_purity.py` e o `libs/sdk/tests/test_purity.py`
    (já existem);
  - o teste de arquitetura da Toolbox (já existe);
  - os jobs de instalação isolada do docstruct (novo) e do SDK (ajustado);
  - o teste de infraestrutura do docstruct (novo);
  - um item de revisão: uma operação do SDK não tem nenhuma decisão que
    pudesse tomar de outro jeito para outro chamador.
- **Quando for aceita:**
  - a ADR-0002 ganha uma linha "Emendada pela ADR-0017", e a linha do SDK e as
    quatro perguntas dela passam a apontar para cá;
  - a ADR-0003 ganha uma linha "Esclarecida pela ADR-0017".

  Nenhuma das duas é reescrita (processo do [índice das ADRs](README.pt-br.md)).
