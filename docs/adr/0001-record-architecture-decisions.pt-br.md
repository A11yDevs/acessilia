# 0001. Registrar decisões arquiteturais

Também disponível em **inglês (EUA)**: [English version](0001-record-architecture-decisions.md)

- **Status:** Aceito
- **Data:** 2026-10-18
- **Componentes:** core, SDK, docstruct, Toolbox
- **Issues:** [#152](https://github.com/A11yDevs/acessilia/issues/152)

## Contexto

Decisões como "a Toolbox não depende do SDK" ou "o core não tem fallbacks
locais" estavam espalhadas por threads de issues, READMEs e revisões de pull
requests. São dois repositórios, cada um com a própria constituição.
Contribuidores e agentes de desenvolvimento não tinham um lugar único para
conferir uma decisão antes de propor uma mudança, e alguns documentos tinham
começado a se contradizer.

## Decisão

- As decisões arquiteturais que atravessam componentes são registradas como
  ADRs em `acessilia/docs/adr/`. Esse diretório é a fonte única de verdade
  delas.
- Cada repositório pode manter ADRs sobre os próprios detalhes internos. Eles
  apontam para os ADRs transversais em vez de copiá-los.
- O inglês é normativo, e todo ADR tem um espelho `.pt-br.md` escrito no
  mesmo pull request.
- Um ADR transversal é revisado pelos donos de todos os componentes que ele
  afeta.
- Um ADR aceito não é reescrito; um novo ADR o substitui.
- Uma exceção a um princípio da constituição exige um ADR (veja o
  [README](README.pt-br.md#processo)).

## Consequências

- A constituição enuncia os princípios e aponta para o ADR que detalha cada
  um, para que os dois não se distanciem.
- As revisões de pull request podem apontar para um ADR em vez de rediscutir
  uma decisão.
- Escrever um ADR acrescenta um pequeno custo às mudanças estruturais;
  mudanças pequenas e locais não precisam de um.
