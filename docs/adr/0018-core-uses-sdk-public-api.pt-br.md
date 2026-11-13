# 0018. O core usa só a API pública do SDK

Também disponível em **inglês (EUA)**: [English version](0018-core-uses-sdk-public-api.md)

- **Status:** Proposto
- **Data:** 2026-11-13
- **Componentes:** core, SDK
- **Issues:** [#470](https://github.com/A11yDevs/acessilia/issues/470), [#402](https://github.com/A11yDevs/acessilia/issues/402)

## Contexto

A [ADR-0017](0017-operational-sdk-and-agentic-core.pt-br.md) faz do SDK uma
API pública e versionada: scripts, benchmarks e outros front-ends o chamam sem
o core, e as operações dele precisam de changelog e de depreciação. O core é um
desses chamadores. Se ele usasse partes internas do SDK, uma mudança interna no
SDK quebraria o core sem ser uma mudança incompatível da API, e o SDK não
poderia ser refatorado livremente. A #402 chamava isso de "ADR B": o core
depende só da API pública do SDK.

O que o código diz hoje, medido na develop em cfa45001:

- **Todo módulo do SDK já declara `__all__`**, menos o próprio pacote
  (`__version__`) e o ponto de entrada de `python -m`
  (`acessilia_sdk.__main__`). Essas listas são completas: cobrem tudo o que o
  SDK pretende oferecer, inclusive as classes de cliente, os ids de capacidade
  delas e os erros.
- **A tabela "API pública" do README as resume.** Todo nome que ela lista está
  no `__all__` do módulo, mas ela não lista todo nome exportado (por exemplo, o
  `ToolboxPdfValidateClient` é exportado e faltava na linha dos clientes).
- **O core já usa só nomes exportados.** Uma varredura de `backend/`,
  `scripts/` e `tests/` encontrou 181 usos de nomes do SDK em 52 arquivos. Ela
  cobriu imports, atributos lidos por um módulo do SDK importado e caminhos em
  string, como os alvos de `monkeypatch.setattr`, e nenhum está fora do
  `__all__` de um módulo. Ficar na API pública não custa nada hoje.

Opções consideradas:

1. **Nenhuma regra.** O core pode usar qualquer nome do SDK. Nada quebra hoje,
   mas nada impede o acoplamento.
2. **A tabela do README é a API pública.** Ela é prosa, resume e cita métodos e
   campos que não são nomes de módulo, então não pode ser conferida com
   exatidão.
3. **O `__all__` de cada módulo é a API pública**, com o README como resumo
   conferido contra ele.

## Decisão

Proposta: a opção 3.

- **A API pública do SDK é o que cada módulo do SDK lista em `__all__`**, mais
  os próprios módulos públicos do SDK. Um nome fora do `__all__` é interno: pode
  mudar ou sumir em qualquer release, sem entrada no changelog.
- **Todo módulo de API do SDK declara `__all__`.** O pacote (`acessilia_sdk`)
  e os pontos de entrada (`__main__`) não são módulos de API.
- **O core, os scripts e os testes dele usam só nomes públicos**: nos imports,
  nos atributos lidos por um módulo do SDK e nos caminhos em string, como um
  alvo de patch. Um método ou atributo de uma classe pública é público junto
  com a classe.
- **Uma exceção revisada** só é permitida no mapa `ALLOWED` do guarda, com o
  motivo; uma exceção que nada usa mais faz o guarda falhar. Hoje não há
  nenhuma.
- **A tabela "API pública" do README é um resumo**: todo nome que ela lista
  precisa estar no `__all__` do módulo, para que ela nunca prometa algo que o
  código não exporta.
- **Acrescentar um nome ao `__all__` o torna público** e entra no changelog do
  SDK. Quando o core precisa de um nome interno, a correção é exportá-lo (com
  entrada no changelog), e não acrescentar uma exceção.

## Consequências

- **Fica mais fácil:**
  - o SDK pode mudar o que é interno sem quebrar o core;
  - aquilo de que o core depende fica listado num lugar só, e quem revisa vê
    uma exportação nova no diff do SDK.
- **Fica mais difícil:**
  - o core não pode pegar emprestada uma função auxiliar do SDK sem exportá-la
    antes;
  - um módulo novo do SDK precisa declarar `__all__`.
- **Conformidade:**
  - `tests/test_sdk_public_api.py` (core): todo uso do SDK em `backend/`,
    `scripts/` e `tests/` é público; nenhum módulo de API do SDK fica sem
    `__all__`; nenhuma exceção está obsoleta. Um autoteste confere o guarda em
    cada tipo de uso;
  - `libs/sdk/tests/test_public_api.py` (SDK): todo nome que a tabela do README
    lista está no `__all__` do módulo. Ele roda também no job `SDK alone`.
- **Trabalho seguinte:** nenhum obrigatório. O guarda bloqueia desde o início,
  porque o custo medido é zero (decisão de 2026-11-13). Se esta ADR for
  rejeitada, os dois testes saem.
