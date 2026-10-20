# Dependências entre componentes

> Esta é a tradução para português brasileiro de
> [dependencies.md](dependencies.md). A versão em inglês é a fonte
> autoritativa em caso de divergência.

Diagrama: [dependencies.puml](dependencies.puml). Esta página o descreve em texto.

O ecossistema tem quatro componentes; a [ADR-0002](../adr/0002-component-responsibilities.pt-br.md) fixa qual pode depender de qual.

**Dependências permitidas:**

- **Core → SDK e docstruct.** O core (`backend/`, `frontend/`) planeja e orquestra. Importa o SDK para chegar à Toolbox e o docstruct para algoritmos estruturais puros.
- **SDK → docstruct.** O SDK (`libs/sdk`) reúne contratos e clientes da Toolbox; além do docstruct, sua única dependência de runtime é o `httpx`.
- **SDK → contrato HTTP publicado pela Toolbox.** O SDK chama a Toolbox por HTTP e nunca importa o código dela. O contrato (capacidades, schemas, `ArtifactRef`) é o que a Toolbox publica.
- **Toolbox → docstruct.** A Toolbox importa o docstruct como um wheel fixado, construído a partir deste repositório.
- **Toolbox → seus sidecars, por HTTP.** Ferramentas pesadas, como Pandoc com TeX Live, MathJax com MathCAT e veraPDF, rodam em containers sidecar.
- **docstruct → nada do ecossistema.** O docstruct não tem nenhuma dependência de runtime.

**Dependências proibidas, e os testes que as protegem:**

- O core não pode importar o pacote da Toolbox (`tests/test_architecture_layers.py`).
- O core não pode importar biblioteca operacional: PyMuPDF, Pillow, OpenCV, Docling, pypdf, python-docx ou RapidOCR (mesmo teste). O trabalho operacional roda na Toolbox ([ADR-0003](../adr/0003-remote-only-operational-capabilities.pt-br.md)).
- O docstruct não pode importar o core, o SDK nem a Toolbox (`libs/docstruct/tests/test_purity.py`).
- O SDK não pode importar o core nem a Toolbox (`libs/sdk/tests/test_purity.py`).
- A Toolbox não pode importar o SDK nem o core. Ainda não há teste para isso; está registrado na [#188](https://github.com/A11yDevs/acessilia/issues/188).

Não há ciclo de dependências.
