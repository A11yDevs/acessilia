# Fixtures diferenciais da saída canônica (#849)

Você também pode ler esta documentação em **inglês**: [English](README.md)

As migrações da #640 levaram os passos de enriquecimento para dentro do plano,
um passo por pull request (M2, M1, M3, M4a, M4b). Cada uma manteve um teste
diferencial do passo, que mostra que o passo é equivalente depois de
planejado. Ele não mostra que o pipeline inteiro é: a lacuna do LaTeX das
fórmulas no M1 (#846) foi uma regressão entre passos. Estas fixtures comparam
o **documento canônico final** de uma execução desta árvore com o que o core
produzia antes de cada migração.

## Como um caso roda

`runner.py` roda um caso como o `backend/service.py` roda um job: o `execute`
do orquestrador PDDL com saída estruturada, a junção de parágrafos e depois
`build_canonical_document`. Ele só usa o que o core 0.3.11 já tinha, então o
mesmo runner funciona numa árvore mais antiga.

Toda chamada que o core faz sai dele por HTTP: os clientes de capacidade do
SDK e, com `AI_CLIENT=toolbox`, os chats dos agentes pelo gateway VLM do
Toolbox. `fake_toolbox.py` responde essa fronteira em processo: ele direciona
todo cliente `httpx` para um `MockTransport`, então nada dentro do core é
substituído. As respostas são determinísticas e vêm do caso:

| Chave do caso | Responde |
|---|---|
| `document` | `document.structure.extract`: um documento compatível com o ProcessingManifest |
| `vision` | o VLM, por id de elemento (ou `page-<n>`): uma descrição, o `kind` e o `formula_latex` de uma região, as `rows` de uma tabela; os campos que o caso omite recebem um padrão válido do schema da resposta |
| `latex` | `math.recognize`, por id de fórmula |
| `text_spans` | `document.text.spans`, por página |
| `tables` | `table.recognize`, por id de tabela |

Uma imagem renderizada não diz que região mostra, e um core mais novo pode
reduzi-la ou recodificá-la. Por isso cada `pdf.render` devolve uma cor sólida
que indexa o recorte renderizado. As respostas do VLM e do `math.recognize`
decodificam a cor de volta para o recorte e depois para o elemento cuja caixa
contém o seu centro.

`math.convert` e `math.verbalize` ecoam a LaTeX (`spoken <latex>`), então uma
mudança no que é enviado aparece na saída. Uma chamada que o falso não sabe
responder é registrada; o teste falha com qualquer uma.

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
antes de uma migração, e um `SOURCE.json` com o commit:

| Rótulo | Commit | Antes de |
|---|---|---|
| `core-0.3.11` | `9d433476` | M2 |
| `core-0.3.13` | `0cc303b5` | M1 |
| `core-0.3.14` | `da5c97b8` | M3 |
| `core-0.3.18` | `6781ff58` | M4a |
| `core-0.3.19` | `d2714cdf` | M4b |

A normalização descarta o que muda de uma execução para outra: datas,
durações, caminhos. Descarta também o que identifica ou precifica o estado de
planejamento: os ids de plano, execução e manifesto, o custo esperado e o id
do documento, que é um hash deles.

`tests/test_differential_canonical.py` roda cada caso uma vez nesta árvore e o
compara com cada referência. Uma diferença que uma release posterior fez de
propósito é declarada no `intended.json` da referência:

```json
{
  "*": [{"kind": "added", "path": "/metadata/pddl_toolbox_availability/optional",
         "reason": "core 0.3.16 (#848): optional capability calls"}],
  "formulas": [{"kind": "changed", "path": "/sections/0/blocks/*/alt_text",
                "reason": "..."}]
}
```

`kind` é `added`, `removed` ou `changed`. `path` é um JSON pointer em que `*`
casa qualquer sequência de caracteres. Entradas sob `*` valem para todo caso.
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
- **Contra `core-0.3.14`**, a figura que o modelo de visão lê como fórmula
  volta a ter o LaTeX da fórmula (`formula_recognition`). É a lacuna do M1
  (#846), que o M3 fechou na 0.3.15: `core-0.3.14` é a única release sem ele.
  Reintroduzir a lacuna faz o teste falhar contra todas as outras referências.

## Gravação

```bash
uv run python -m tests.differential.build_cases       # depois de editar um caso
uv run python scripts/record_differential_references.py --ref 9d433476 --label core-0.3.11
```

O script faz checkout do commit num git worktree temporário, copia este
harness para ele e roda todos os casos lá, com o ambiente travado daquela
árvore, mais o Pillow, de que o falso precisa. Grave de novo todas as
referências depois de mudar um caso. Acrescente uma referência antes de cada
migração futura que possa mudar a saída.

As fixtures ainda não cobrem uma retomada a partir de um checkpoint de
enriquecimento: uma retomada compara uma execução com ela mesma, não com um
core mais antigo, e o formato do checkpoint mudou entre estas releases (#836). Ela é a #874.
