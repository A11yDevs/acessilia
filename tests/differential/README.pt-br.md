# Fixtures diferenciais da saída canônica (#849)

Você também pode ler esta documentação em **inglês**: [English](README.md)

As migrações da #640 levaram os passos de enriquecimento para dentro do plano,
um passo por pull request (M2, M1, M3, M4a, M4b). Cada uma manteve um teste
diferencial do passo, que mostra que o passo é equivalente depois de
planejado. Ele não mostra que o pipeline inteiro é: a lacuna do LaTeX das
fórmulas no M1 (#846) foi uma regressão entre passos. Estas fixtures comparam
o **documento canônico final** de uma execução desta árvore com o que o core
produzia antes de cada migração.

Uma referência é um golden master, não ground truth: ela pode guardar um bug
da sua release. A qualidade semântica é medida em outro lugar, contra ground
truth (os benchmarks da #619).

## Escopo

O que os casos estabelecem se limita ao que eles rodam:

- cinco documentos sintéticos de uma página;
- um provedor de extração (`FUSION_MODE=single`), então `select-table-source`,
  `fuse-providers`, `rescue-omitted` e `adjudicate-page` nunca rodam. A
  tabela obsoleta, o replanejamento por um bloco resgatado e a invalidação
  das conversões de fórmula (M4b) são cobertos por testes unitários, não
  aqui;
- um Toolbox que sempre responde: sem falha, indisponibilidade ou
  degradação;
- o documento canônico normalizado: nem os exports, nem o número de chamadas.

A equivalência que as referências mostram vale só para estes casos. Casos com
dois provedores, várias páginas e degradação são a #876; a retomada a partir
de um checkpoint é a #874.

## Como um caso roda

`runner.py` roda um caso como o `backend/service.py` roda um job: o `execute`
do orquestrador PDDL com saída estruturada, a junção de parágrafos e depois
`build_canonical_document`. Ele só usa o que o core 0.3.11 já tinha, então o
mesmo runner funciona numa árvore mais antiga.

**A execução é hermética** (`hermetic_environment`). Primeiro, toda variável
que as settings do backend podem ler é removida, inclusive o que o `.env`
carregou no processo. As settings recebem então os seus padrões mais o
`ENVIRONMENT` do harness, com `DATA_DIR` e `TEMP_DIR` num diretório
temporário, e o ambiente inteiro é restaurado ao final. Uma referência gravada
num worktree limpo e uma execução na árvore de um desenvolvedor veem, por
isso, a mesma configuração.

**O Toolbox é um falso.** Toda chamada que o core faz sai dele por HTTP: os
clientes de capacidade do SDK e, com `AI_CLIENT=toolbox`, os chats dos agentes
pelo gateway VLM do Toolbox. `fake_toolbox.py` responde essa fronteira em
processo: ele direciona todo cliente `httpx` para um `MockTransport`, então
nada dentro do core é substituído. As respostas vêm do caso:

| Chave do caso | Responde |
|---|---|
| `document` | `document.structure.extract`: um documento compatível com o ProcessingManifest |
| `vision` | o VLM, por id de elemento (ou `page-<n>`): uma descrição, o `kind` e o `formula_latex` de uma região, as `rows` de uma tabela |
| `latex` | `math.recognize`, por id de fórmula (`""`: não lê nada) |
| `text_spans` | `document.text.spans`, por página |

**As regiões são associadas pela cor.** Uma imagem renderizada não diz que
região mostra, e um core mais novo pode reduzi-la ou recodificá-la. Por isso
cada `pdf.render` devolve uma cor sólida que indexa o recorte renderizado (até
512 por caso). O VLM e o `math.recognize` decodificam a cor de volta para o
recorte:
- um recorte que cobre a página é `page-<n>`;
- um recorte menor é o elemento com que mais se sobrepõe (interseção sobre
  união).

**O falso é estrito.** Ele recusa, e registra como não respondida, qualquer
uma destas chamadas:
- uma imagem que ele não renderizou;
- um recorte que nenhum elemento casa, ou que dois casam igualmente;
- um elemento para o qual o caso não dá resposta;
- uma resposta que o próprio schema de resposta do agente rejeita;
- uma capacidade que ele não serve.

Só os campos que a resposta de um caso omite recebem um padrão, e a resposta
inteira ainda é validada. O teste falha com qualquer chamada não respondida.

`math.convert` e `math.verbalize` ecoam a LaTeX (`spoken <latex>`), então uma
mudança no que é enviado aparece na saída.

## Os casos

`build_cases.py` escreve `cases/<nome>/case.json` a partir dos modelos do core:

| Caso | O que cobre |
|---|---|
| `text-and-picture` | uma figura descrita (M1) |
| `tables` | uma tabela lida da sua imagem e uma já estruturada (M2) |
| `formulas` | uma fórmula sem marcação LaTeX, classificada e lida (M4a, M3); uma com LaTeX; uma figura que o modelo de visão lê como fórmula (M1, #846) |
| `mostly-visual` | uma página sem conteúdo textual, cujos visuais de placeholder são descritos |
| `inline-math` | prosa marcada a partir das fontes da camada de texto (M4b), e uma fórmula que lê as suas variáveis |

## As referências

`references/<rótulo>/` guarda a saída normalizada de cada caso gravada no core
antes de uma migração:

| Rótulo | Commit | Antes de |
|---|---|---|
| `core-0.3.11` | `9d433476` | M2 |
| `core-0.3.13` | `0cc303b5` | M1 |
| `core-0.3.14` | `da5c97b8` | M3 |
| `core-0.3.18` | `6781ff58` | M4a |
| `core-0.3.19` | `d2714cdf` | M4b |

**A normalização** descarta só estes JSON pointers:
- `/source/path`, o caminho temporário da execução;
- os ids de plano, execução e manifesto e o custo esperado em `/metadata`,
  que identificam ou precificam o estado de planejamento e mudam a cada
  migração por desenho;
- o `/id` do documento, que é um hash deles.

Um campo de mesmo nome em qualquer outro lugar continua sendo comparado.

**`calls`** conta as capacidades que cada execução pediu. É só diagnóstico e
não é comparado: um core mais novo pode chamar menos de propósito. Por
exemplo, o M4b deixou de ler a camada de texto de um documento sem prosa a
marcar.

**`SOURCE.json`** registra o commit, a versão do core e a identidade do
harness (`runner.identity`): os SHA-256 do runner, do falso, dos casos e do
PDF de origem, e as versões dos pacotes que o falso acrescenta (Pillow e
jsonschema, fixadas). O teste recusa uma referência cuja identidade difere da
desta árvore, então mudar o harness exige gravar de novo. A comparação
(`compare.py`) não faz parte da identidade.

## Diferenças declaradas

`tests/test_differential_canonical.py` roda cada caso uma vez nesta árvore e o
compara com cada referência. Uma diferença que uma release posterior fez de
propósito é declarada no `intended.json` da referência, **com o valor que ela
permite**:

```json
{
  "*": [{"kind": "added", "path": "/metadata/pddl_toolbox_availability/optional",
         "expected": {}, "reason": "core 0.3.16 (#848): ..."}],
  "formulas": [{"kind": "changed", "path": "/metadata/pddl_manifest_revision",
                "expected": 3, "reason": "core 0.3.14 (M1): ..."}]
}
```

Os campos de uma entrada:
- `kind` é `added`, `removed` ou `changed`.
- `path` é um JSON pointer em que `*` casa qualquer sequência de caracteres.
  Use `*` só onde a posição, não o campo, varia.
- `expected` é obrigatório para `added` e `changed`: uma mudança posterior do
  mesmo campo não é aceita com ele.
- `was` é opcional para `removed` e confere o valor que saiu.
- Entradas sob `*` valem para todo caso.

Uma diferença não declarada falha, e uma declarada que não acontece mais
também.

## O que as referências mostram

Quando este harness foi criado (core 0.3.20):

- **M4a e M4b** não mudaram nenhuma saída: esta árvore coincide exatamente com
  `core-0.3.18` e `core-0.3.19`.
- **Contra `core-0.3.11` e `core-0.3.13`**, as diferenças são:
  - o relatório de disponibilidade da #848 (core 0.3.16);
  - uma revisão de manifesto a mais quando uma descrição retipa um elemento
    (M1, core 0.3.14).
- **Contra `core-0.3.14`**, as diferenças são:
  - o mesmo relatório de disponibilidade da #848;
  - a figura que o modelo de visão lê como fórmula volta a ter o LaTeX da
    fórmula (`formula_recognition`, `formula_text_layer`). É a lacuna do M1
    (#846), que o M3 fechou na 0.3.15: `core-0.3.14` é a única release sem
    ele;
  - o texto ao redor dessa figura volta a ter o texto extraído da fórmula
    vizinha, porque o M3 roda o LaTeX das fórmulas depois das descrições, como
    antes da 0.3.14.

Reintroduzir a lacuna da #846 faz o teste falhar contra todas as outras
referências.

## Gravação

```bash
uv run python -m tests.differential.build_cases       # depois de editar um caso
uv run python scripts/record_differential_references.py --ref 9d433476 --label core-0.3.11
```

O script faz checkout do commit num git worktree temporário, copia o harness
para ele e roda os casos lá, com o ambiente travado daquela árvore, mais os
pacotes fixados de que o falso precisa. Nada é publicado antes de todos os
casos rodarem e o falso responder toda chamada; então a referência é trocada
inteira.

- **Gravar todos os casos** substitui a referência e descarta os casos que
  não existem mais. O `intended.json`, escrito à mão, é mantido.
- **Gravar alguns casos** (`... core-0.3.11 formulas`) substitui só esses, e
  é recusado quando a referência foi gravada com outro commit ou harness.

## Manutenção das referências

- **Acrescentar uma referência.** Acrescente uma antes de cada migração
  futura, ou de qualquer mudança que possa mexer na saída. Grave-a do commit
  imediatamente anterior ao merge da mudança.
- **Atualizar uma referência.** Grave de novo só quando o harness ou um caso
  mudar (a verificação de identidade diz quando). Nunca grave de novo para
  deixar o CI verde: uma diferença nova é uma regressão a corrigir ou uma
  mudança intencional a declarar, com o seu valor e a release que a fez.
- **Aposentar uma referência.** Aposente uma quando uma referência mais nova
  cobrir a mesma migração e as suas declarações só repetirem as da mais
  nova. Registre isso no pull request.
