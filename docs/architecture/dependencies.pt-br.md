# Dependências entre componentes

> Esta é a tradução para português brasileiro de
> [dependencies.md](dependencies.md). A versão em inglês é a fonte
> autoritativa em caso de divergência.

Diagrama: [dependencies.puml](dependencies.puml). Esta página o descreve em texto.

O ecossistema tem quatro componentes; a [ADR-0002](../adr/0002-component-responsibilities.pt-br.md) fixa qual pode depender de qual.

**Dependências permitidas:**

- **Core → SDK e docstruct.** O core (`backend/`, `frontend/`) planeja e orquestra. Importa o SDK para chegar à Toolbox e o docstruct para algoritmos estruturais puros.
- **SDK → docstruct, permitida mas sem uso hoje.** O SDK (`libs/sdk`) reúne contratos e clientes da Toolbox. A ADR-0002 permite que ele chame os algoritmos puros do docstruct no próprio processo, mas nenhum módulo do SDK importa o docstruct ainda, e o `libs/sdk/pyproject.toml` lista o `httpx` como sua única dependência de runtime. O docstruct precisa entrar ali antes da primeira importação desse tipo.
- **SDK → contrato HTTP publicado pela Toolbox.** O SDK chama a Toolbox por HTTP e nunca importa o código dela. O contrato (capacidades, schemas, `ArtifactRef`) é o que a Toolbox publica.
- **Toolbox → docstruct.** A Toolbox importa o docstruct como um wheel fixado, construído a partir deste repositório.
- **Toolbox → seus sidecars, por HTTP.** Ferramentas pesadas rodam em containers sidecar, configurados no repositório acessilia-toolbox, não aqui. Dois são citados neste repositório: `pdf-ua-render` (Pandoc com TeX Live, para PDF/UA e DOCX; veja a [matriz de capacidades](../toolbox_capability_matrix.pt-br.md)) e `math-speech` (MathJax com MathCAT; veja a [ADR-0008](../adr/0008-math-capabilities-on-mathjax-and-mathcat.pt-br.md)).
- **docstruct → nada do ecossistema.** O docstruct não tem nenhuma dependência de runtime.

**Dependências proibidas, e os testes que as protegem.** Para manter a legibilidade, o diagrama desenha só três delas em vermelho; a lista abaixo é completa.

- O core não pode importar o pacote da Toolbox (`tests/test_architecture_layers.py`).
- O core não pode importar biblioteca operacional: PyMuPDF, Pillow, OpenCV, Docling, pypdf, python-docx ou RapidOCR (mesmo teste). O trabalho operacional roda na Toolbox ([ADR-0003](../adr/0003-remote-only-operational-capabilities.pt-br.md)).
- O docstruct não pode importar o core, o SDK nem a Toolbox (`libs/docstruct/tests/test_purity.py`).
- O SDK não pode importar o core nem a Toolbox (`libs/sdk/tests/test_purity.py`).
- A Toolbox não pode importar o SDK nem o core. Ainda não há teste para isso; está registrado na [#188](https://github.com/A11yDevs/acessilia/issues/188).

Não há ciclo de dependências.
