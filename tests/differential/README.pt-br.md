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

- oito documentos sintéticos, de uma a três páginas;
- um provedor de extração, exceto em `dual-provider` (`FUSION_MODE=dual`), que
  exercita a adjudicação de página, o `select-table-source` e uma página
  roteada para o provedor secundário com o `rescue-omitted`. O
  `fuse-providers` e a fusão de texto (`dual-provider-fusion`) não são
  exercitados;
- um Toolbox que responde, exceto em `degraded`, em que `math.recognize` e
  `document.text.spans` estão indisponíveis e o modelo de visão falha numa
  figura. São falhas na chamada (HTTP 503); o gate de disponibilidade está
  desligado, então uma capacidade que o catálogo informa indisponível antes
  do planejamento (#848) não é exercitada;
- páginas que só existem na extração: todos os casos rodam sobre o mesmo
  `source.pdf` de uma página, e o falso responde a contagem de páginas e as
  renderizações, então `multi-page` testa o tratamento de páginas e
  elementos pelo pipeline, não a extração nem a renderização de um PDF real
  de várias páginas (os testes e2e com os documentos do dataset cobrem
  isso);
- o documento canônico normalizado: nem os exports, nem o número de chamadas.

A equivalência que as referências mostram vale só para estes casos. A
retomada a partir de um checkpoint é testada à parte, contra a mesma árvore
(veja abaixo).

## Como um caso roda

`runner.py` roda um caso como o `backend/service.py` roda um job: o `execute`
do orquestrador PDDL com saída estruturada, a junção de parágrafos e depois
`build_canonical_document`. Ele só usa o que o core 0.3.11 já tinha, então o
mesmo runner funciona numa árvore mais antiga.

**A execução é hermética** (`hermetic_environment`). Primeiro, toda variável
que as settings do backend podem ler é removida, inclusive o que o `.env`
carregou no processo, e o locale do servidor e da tarefa é fixado em
`en_US`, então as mensagens que uma saída traz (um aviso, um alt text de
fallback) não seguem o `LANG` nem um teste anterior. As settings recebem então os seus padrões mais o
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
| `secondary_document` | a extração do provedor secundário, com `FUSION_MODE=dual`. Só o provedor primário (`primary_provider`, `docling`) e o secundário (`FUSION_SECONDARY_PROVIDER`, senão `secondary_provider`, senão `mineru`) recebem uma; qualquer outro fica sem resposta. Uma região que só o secundário extraiu é casada com as caixas dele |
| `judge` | por página (`page-<n>`), o `pB` de `document.adjudicate.page` para a imagem daquela página |
| `failures` | o que falha de propósito: `capabilities` respondidas com 503, ids em `vision` que o modelo recusa; registrado em `refused`. O teste e a gravação exigem exatamente as falhas declaradas |
| `environment` | settings que o caso define sobre as do harness (`FUSION_MODE=dual`) |

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
| `multi-page` | uma figura, uma fórmula e uma tabela lida da sua imagem, cada uma na sua página |
| `dual-provider` | dois provedores em três páginas: uma página adjudicada, uma tabela adotada do secundário e marcada de novo (o `inline_math_stale` do M4b), uma página roteada para o secundário cujo parágrafo só do primário, com matemática inline, o `rescue-omitted` devolve (#887) |
| `degraded` | `math.recognize` e `document.text.spans` indisponíveis, e o modelo de visão falhando numa de duas figuras: a fórmula recai no modelo de visão, a matemática inline fica indisponível, uma figura fica sem descrição, com aviso |

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

**`refused`** e **`cacheable`** também são gravados. `refused` precisa ser
igual às `failures` do caso quando uma referência é gravada e nesta árvore;
`cacheable` (se o backend guardaria o resultado em cache) é conferido só
nesta árvore, porque o seu contrato pode evoluir: `degraded` não pode ir
para o cache.

**`calls`** conta as capacidades que cada execução pediu. É só diagnóstico e
não é comparado: um core mais novo pode chamar menos de propósito. Por
exemplo, o M4b deixou de ler a camada de texto de um documento sem prosa a
marcar.

**`served`** lista, para cada resposta de visão ou de `math.recognize` que o
falso deu depois de ela passar no schema, o tipo e o elemento a que se
referia. Como `calls`, é diagnóstico nas referências e nunca é comparado
entre cores; o teste de retomada abaixo o confere, só nesta árvore. O mesmo
vale para `converted` (conversões por expressão LaTeX).

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
  Use `*` só onde a posição, não o campo, varia. O casamento usa
  `fnmatchcase`: `*` inclui `/`, então `/blocks/*/text` também casa com
  `/blocks/0/children/1/text`. Use padrões restritos ou caminhos exatos quando
  a profundidade importar; o vínculo por id não muda essas regras.
  O ponteiro vazio `""` representa o documento inteiro, incluindo mudanças
  de tipo na raiz e reordenação de listas na raiz. `"/"` representa uma
  chave de propriedade vazia; não é um alias da raiz. Declarações antigas
  que usam `"/"` para uma mudança do documento inteiro devem usar `""`.
  Uma diferença na raiz não tem membro envolvente de lista, então uma
  declaração vinculada por id não pode explicá-la.
- `expected` é obrigatório para `added` e `changed`: uma mudança posterior do
  mesmo campo não é aceita com ele.
- `was` é opcional para `removed` e confere o valor que saiu.
- `id` é opcional: exige também que o membro envolvente mais próximo de
  uma lista com ids string distintos e não vazios tenha esse id. Membros
  identificados internos têm precedência sobre os externos; um `id` nos
  metadados comuns não substitui a identidade do bloco que os contém.
  Em `changed`, ambas as árvores precisam comprovar o mesmo membro no mesmo
  contexto de lista. Ancestrais identificados correspondentes precisam ter
  ids iguais; arrays comuns continuam posicionais. Uma lista que apresenta
  ids inválidos ou ambíguos impede o vínculo, mesmo se o outro lado é válido
  ou um id externo coincide. `added` usa a árvore atual; `removed`, a referência.
  Uma identidade ausente ou diferente deixa a diferença sem
  explicação e a declaração sem uso. Um vínculo inválido (não é string
  não vazia) é rejeitado mesmo quando não existem diferenças.
- Entradas sob `*` são candidatas para todo caso. O `id` restringe as
  diferenças que elas explicam; não suprime o relato de declarações sem uso.
  `explain` devolve a entrada como não utilizada num caso sem mudança
  correspondente. O corpus permite que uma entrada comum não seja usada em
  casos individuais, mas exige que ela explique ao menos uma diferença no
  conjunto de casos. Entradas sob o nome de um caso precisam ser usadas
  naquele caso. Prefira uma entrada específica para uma mudança pretendida
  somente para aquele caso.

Caminhos concretos consumidos por `resolve` são vazios ou começam com `/`.
Índices de listas devem ser `0` ou dígitos decimais ASCII sem zeros iniciais;
sinais, espaços, underscores e dígitos não ASCII são rejeitados. Um prefixo
ou índice inválido ou um valor ausente gera `KeyError` com o ponteiro original.
Essas verificações se aplicam a caminhos concretos, não aos padrões de
declaração casados por `fnmatchcase`. A validação de escapes de til inválidos
está registrada na [#920](https://github.com/A11yDevs/acessilia/issues/920).

A detecção de diferenças e `expected`/`was` usam a mesma regra recursiva de
igualdade JSON. Booleanos diferem de números: `true` não é `1`, e `false`
não é `0`, inclusive dentro de objetos e arrays. Números são comparados pelo
valor exato, então `1` e `1.0` (também `0` e `-0.0`) são equivalentes; não há
arredondamento, tolerância ou coerção de strings. A ordem das chaves de um
objeto não importa; a ordem dos arrays importa. O alinhamento por identidade
e a detecção de reordenação de listas continuam aplicáveis.

Uma diferença não declarada falha. Uma declaração específica que nada
explica naquele caso falha; uma declaração comum que nenhum caso usa
também falha.

Listas de objetos que trazem todos um `id` string, não vazio e distinto
(blocos, elementos) são alinhadas pelo id: um bloco inserido é um `added`, e
os mesmos blocos em outra ordem são um `changed` da lista. Uma diferença
dentro de um bloco que mudou de lugar também informa o seu
`reference_path`: a verificação de identidade segue esse caminho histórico
para comprovar correspondência, enquanto os padrões da declaração continuam
usando o `path` atual (o da referência, para `removed`).

O vínculo por id (#895) acrescenta uma condição; nunca substitui as
verificações de caminho ou valor. Por exemplo:

```json
{"kind": "changed", "path": "/sections/*/blocks/*/text", "id": "block-a",
 "expected": "Corrected text", "reason": "Intentional correction to block-a"}
```

Essa entrada não explica o mesmo texto em outro bloco que passou a ocupar
aquela posição. Use curinga de posição quando a posição desse objeto puder
variar: o mesmo id em outro lugar ainda precisa casar com `path`. Os ids
têm o escopo da lista que os contém; mantenha `path` específico o bastante
para distinguir listas que reutilizam ids. Entradas
sem `id` mantêm o significado posicional. Uma mudança de ordem da lista
continua sendo uma diferença `changed`; vincular a um dos membros dessa
lista não a explica, pois a busca de identidade examina objetos envolventes,
não seus descendentes.
Uma declaração pode explicar várias diferenças que casem: um id local não
é identidade global nem limite de cardinalidade.

Na avaliação científica (#619), registre o commit de avaliação ou os hashes
de `compare.py` e dos arquivos `intended.json`, além do commit do pipeline,
da configuração e da identidade do harness e das dependências. As saídas
gravadas e `SOURCE.json` descrevem evidência de execução; a política de
comparação descreve sua avaliação. Concordância diferencial mede preservação
em relação a saídas históricas, não qualidade documental absoluta nem
superioridade de uma abordagem de planejamento; essas alegações exigem
avaliação separada com ground truth.

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

Os casos acrescentados pela #876 (core 0.3.23) mostram:

- **`multi-page`** coincide com todas as referências.
- **`dual-provider`**:
  - a célula com matemática da tabela adotada é marcada de novo
    (`$s_0\in\mathbb{R}$`) por toda release desde a 0.3.12, em que a passada
    da #599 a marcava depois do plano; o M4b (0.3.20) faz isso como passo
    planejado, ao custo de uma revisão de manifesto a mais. `core-0.3.11`,
    antes da #599, deixava a célula sem marca: declarado;
  - a fórmula da página roteada para o secundário é lida da região do
    secundário do mesmo jeito por toda release;
  - toda release gravada perde o parágrafo que só o provedor primário manteve
    na página roteada; o core 0.3.24 (#887) o resgata, com a sua matemática
    inline, e todas as referências o declaram.
- **`degraded`** coincide com todas as referências, menos `core-0.3.14`, em
  que o texto ao redor das figuras difere, a mesma diferença do M3 que em
  `formulas`.

## Retomada a partir de um checkpoint (#874)

Uma retomada compara uma execução com ela mesma, então o oráculo é o mesmo
caso rodado sem interrupção, não um core mais antigo (o formato do
checkpoint também mudou entre as referências, #836).
`tests/test_differential_resume.py`:

- roda um caso uma vez, inteiro;
- roda de novo como um job, com os checkpoints do serviço
  (`FileJobCheckpoints`, arquivos num diretório de dados temporário), e o
  falso o interrompe na N-ésima requisição de visão ou de `math.recognize`
  com `Interrupted`, uma `BaseException` que nenhum handler de passo
  captura;
- lê de volta, dos arquivos, o checkpoint de execução: o passo continua
  aberto, e o seu `step_progress` guarda exatamente as respostas que a
  execução interrompida recebeu (a primeira figura descrita, a primeira
  fórmula lida);
- roda uma terceira vez, com um novo `FileJobCheckpoints` sobre os mesmos
  arquivos e o mesmo armazenamento do falso (os artefatos, como um Toolbox
  real os mantém, e as renderizações de que o falso precisa para saber o
  que uma imagem mostra), e exige o documento canônico da execução inteira,
  nenhuma obrigação insatisfeita, o mesmo resultado de cache e de falhas, e
  cada resposta, de todo tipo, servida uma vez entre a execução interrompida
  e a retomada: as classificações VLM do caso de fórmulas também não são
  pedidas de novo.

Cobre os dois passos que salvam o progresso dentro do passo: as descrições
de figuras (M1) e o LaTeX das fórmulas (M3), um de cada vez
(`VISION_CONCURRENCY=1`). Uma execução de controle sem checkpoints pede de
novo todas as respostas.

O teste de retomada torna a interrupção injetada terminal. Uma figura na fila
pode adquirir o semáforo enquanto a figura interrompida salva o progresso
em `finally`, antes de o TaskGroup cancelar as tarefas irmãs. Essa requisição
tardia também levanta `Interrupted`, preservando a comparação exata entre
as respostas salvas e servidas. Uma regressão força essa sequência de
requisições sem esperas temporizadas (#900). Essa guarda pertence ao teste
de retomada; as gravações usam diretamente o harness compartilhado.

O que ele não mostra: `Interrupted` para a execução, mas o processo
continua vivo, então os blocos `finally` rodam e nada é cortado no meio de
uma escrita. As garantias do próprio armazenamento (versão do schema, hash
do payload, arquivo corrompido) são testadas em `tests/test_job_resume.py`;
um processo morto pelo
sistema, uma queda entre uma resposta e o seu salvamento, uma interrupção
com várias requisições em andamento e a retomada de uma execução degradada
ficam para a #900.

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
