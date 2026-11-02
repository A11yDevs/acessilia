# 0002. Responsabilidades dos componentes e direção das dependências

Também disponível em **inglês (EUA)**: [English version](0002-component-responsibilities.md)

- **Status:** Aceito
- **Data:** 2026-10-18
- **Componentes:** core, SDK, docstruct, Toolbox
- **Issues:** [#150](https://github.com/A11yDevs/acessilia/issues/150), [#152](https://github.com/A11yDevs/acessilia/issues/152)

## Contexto

O ecossistema tem quatro componentes. As fronteiras entre eles eram em grande
parte implícitas, e o código foi migrando de um para outro. Por exemplo, o
`media.inspect` foi copiado da Toolbox para o core e depois divergiu. O caminho
local de PDF/UA no core reimplementava, com menos proteções, o que o sidecar
da Toolbox já faz. O `libs/README.md` justificava manter a docstruct fora do
SDK com "a Toolbox depende da docstruct, não do SDK", enquanto um rascunho
inicial da #152 permitia que a Toolbox instalasse o SDK.

## Decisão

**Em uma frase:** o core decide e orquestra; o SDK fornece interfaces e
acesso; a docstruct implementa algoritmos estruturais reutilizáveis; a Toolbox
executa capacidades operacionais.

| Componente | É dono de | Não deve |
|---|---|---|
| **Core** (`backend/`) | Agentes, planejamento PDDL, estratégias, políticas, fluxos; quando chamar uma capacidade, qual perfil usar, se deve degradar | Implementar algoritmos documentais genéricos ou executores operacionais; importar o pacote da Toolbox; redefinir contratos |
| **SDK** (`libs/sdk`) | Contratos como os clientes os consomem, clientes e transporte da Toolbox, referências de artefatos, regras de disponibilidade e failover, acesso no próprio processo aos algoritmos puros da docstruct | Conter política de planejamento ou lógica de agentes; exigir dependências operacionais pesadas; ler settings ou ambiente; importar o core ou o pacote da Toolbox |
| **docstruct** (`libs/docstruct`) | Modelos e schemas documentais canônicos, normalização, comparação, matching, fusão, validação estrutural: determinísticos e livres de infraestrutura | Depender do core, do SDK, da Toolbox, de Docker, REST, MCP, rede, arquivos, subprocessos ou armazenamento remoto |
| **Toolbox** (repositório separado) | Providers, conversão, renderização, OCR, validação, processamento especializado; artefatos, jobs, sidecars; interfaces REST e MCP; os contratos operacionais publicados | Reimplementar algoritmos da docstruct; depender do SDK ou da lógica de agentes do core; fazer escolhas semânticas que cabem ao core |

**Dependências permitidas** (as setas apontam para quem é usado):

```
core ──→ SDK ──(contrato HTTP publicado)──→ Toolbox
  │        │                                   │
  └────────┴──────────→ docstruct ←────────────┘
```

- O core depende do SDK e da docstruct.
- O SDK depende da docstruct e **apenas do contrato publicado** da Toolbox
  (IDs de capacidade, versões, schemas), nunca do pacote dela.
- A Toolbox depende da docstruct e de nada mais deste ecossistema.
- A docstruct não depende de nada do ecossistema.
- Dependências circulares são proibidas.

**Interfaces.** Uma implementação pode ser exposta por várias interfaces. O
core chega às capacidades da Toolbox pelo SDK, que fala o contrato REST da
Toolbox. Os bindings MCP e REST são gerados a partir dos mesmos metadados de
capacidade na Toolbox (constituição da Toolbox, princípio 7). A docstruct é
chamada como biblioteca Python.

**Onde fica o código novo?** Pergunte nesta ordem:

1. Ele decide *o que* fazer ou *quando*: planejamento, política, estratégia,
   fluxo do usuário? Então vai para o **core**.
2. É um algoritmo determinístico sobre a estrutura do documento, sem I/O e
   sem dependência pesada? Então vai para a **docstruct**.
3. Precisa de uma ferramenta externa, um modelo, um sidecar, armazenamento ou
   outra infraestrutura? Então é uma capacidade ou provider da **Toolbox**.
4. Trata de *como* chegar a uma capacidade: um cliente, um binding de
   contrato, mapeamento de erros, retries, referências de artefatos? Então vai
   para o **SDK**.

Se duas respostas parecerem valer, divida o código por essas linhas (por
exemplo, um classificador puro na docstruct e o adaptador Pillow/PyMuPDF dele
num provider da Toolbox).

## Consequências

- **Garantido hoje:**
  - `tests/test_architecture_layers.py` (o core não importa a Toolbox).
  - `libs/docstruct/tests/test_purity.py` (a docstruct não importa o core, o
    SDK nem a Toolbox, não declara dependência de runtime e não importa nada
    fora da biblioteca padrão, exceto aceleradores opcionais protegidos, como
    o `rapidfuzz`).
  - `libs/sdk/tests/test_purity.py` (o SDK não importa o core nem a Toolbox,
    e suas dependências ficam restritas a `httpx` e à docstruct).
- **Previsto na #152:**
  - um teste na Toolbox que proíba imports de `acessilia_sdk` e `backend`.
- **Desvios conhecidos, registrados na [#203](https://github.com/A11yDevs/acessilia/issues/203):**
  - O core ainda roda dois executores operacionais, o renderizador de PDF com
    `reportlab` e o exportador de áudio com `edge-tts` (veja o
    [ADR-0003](0003-remote-only-operational-capabilities.pt-br.md)).
  - O agrupamento de callouts está implementado no builder de normalização
    da Toolbox e em `docstruct.regions.grouping`
    ([acessilia-toolbox#72](https://github.com/A11yDevs/acessilia-toolbox/issues/72)).
- **Resolvido pela #203:** as cópias que o core tinha dos perfis de
  exportação, da normalização conservadora de LaTeX, da ordem de leitura do
  manifesto e da sua geometria agora delegam à docstruct, e o
  `tests/test_docstruct_bridges.py` falha diante de qualquer cópia nova. O
  modelo documental e os invariantes do manifesto ficam em
  `docstruct.manifest`. Os modelos Pydantic do core e da Toolbox permanecem
  só como modelos de wire da 1.1.0, verificados contra ele.
  - A classificação de mídias não está mais duplicada: o `media.inspect` roda
    só na Toolbox desde a #160. Ele inspeciona mídias e artefatos, um papel
    diferente do de `docstruct.regions.classify`, que classifica regiões
    estruturais.
