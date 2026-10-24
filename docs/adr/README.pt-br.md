# Registros de Decisão Arquitetural

Também disponível em **inglês (EUA)**: [English version](README.md)

Um Registro de Decisão Arquitetural (ADR, do inglês *Architecture Decision
Record*) documenta uma decisão arquitetural relevante: o contexto, a decisão em
si e suas consequências. Este diretório é a **fonte única de verdade das
decisões que atravessam as fronteiras entre componentes** do ecossistema
Acessilia: o core (`backend/`), o SDK (`libs/sdk`), a docstruct
(`libs/docstruct`) e a [Acessilia Toolbox](https://github.com/A11yDevs/acessilia-toolbox).

Cada repositório pode manter ADRs sobre seus próprios detalhes internos. Esses
ADRs apontam para os daqui em vez de repeti-los.

## Índice

| ADR | Título | Status |
|---|---|---|
| [0001](0001-record-architecture-decisions.pt-br.md) | Registrar decisões arquiteturais | Aceito |
| [0002](0002-component-responsibilities.pt-br.md) | Responsabilidades dos componentes e direção das dependências | Aceito |
| [0003](0003-remote-only-operational-capabilities.pt-br.md) | Capacidades operacionais rodam remotamente, sem fallbacks locais | Aceito |
| [0004](0004-single-source-of-truth-for-contracts.pt-br.md) | Uma fonte de verdade por contrato | Aceito |
| [0005](0005-artifact-references.pt-br.md) | Processamento orientado a referências com `ArtifactRef` | Aceito |
| [0006](0006-availability-and-failover.pt-br.md) | Disponibilidade por réplicas; failover no SDK como mecanismo secundário | Aceito |
| [0007](0007-manifest-model-and-mathml-conversion.pt-br.md) | Modelo canônico do manifesto, e conversão para MathML e verbalização de fórmulas | Aceito |
| [0008](0008-math-capabilities-on-mathjax-and-mathcat.pt-br.md) | As capacidades de matemática rodam sobre MathJax e MathCAT | Aceito |
| [0009](0009-legacy-unicode-repair.pt-br.md) | A reparação Unicode de PDFs legados é um estágio puro da docstruct orquestrado pelo core | Aceito |

## Processo

1. **Quando escrever um ADR.** Para uma decisão que muda responsabilidades ou
   dependências entre componentes, acrescenta ou remove um modo de execução
   (por exemplo, um executor local), muda um contrato público ou abre uma
   exceção a um princípio da [constituição](../constitution.pt-br.md).
2. **Formato.** Copie o [template.md](template.md) (o
   [template.pt-br.md](template.pt-br.md) serve para o espelho). Use o próximo
   número livre e um slug curto em kebab-case, em inglês: `NNNN-title.md`, com
   o espelho em `NNNN-title.pt-br.md`. Seja breve e aponte para issues e código
   para os detalhes.
3. **Idioma.** O inglês é normativo. O espelho `.pt-br.md` é escrito no mesmo
   pull request, conforme o princípio 8 da constituição.
4. **Status.** O status no arquivo é o estado que o ADR terá depois do merge
   do seu pull request, porque a revisão desse pull request é a revisão do ADR
   (passo 5). Um pull request que registra uma decisão a marca como `Accepted`
   (aceito). Use `Proposed` (proposto) só para fazer merge de um ADR cuja
   decisão ainda está em aberto, para que ela seja discutida em pull requests
   seguintes. Os status posteriores são `Superseded by NNNN` (substituído) e
   `Deprecated` (obsoleto). Um ADR aceito não é reescrito: uma decisão alterada
   ganha um novo ADR que o substitui. Corrigir erros de digitação e links é
   permitido.
5. **Revisão.** Um ADR que atravessa componentes é revisado pelos donos de
   todos os componentes afetados. Cada equipe mantém sua autonomia técnica
   dentro do próprio componente.
6. **Exceções.** Uma exceção a um princípio da constituição é registrada como
   um ADR com a justificativa, o escopo (qual capacidade, qual deploy), o
   responsável e o critério de saída. Sem esse ADR, o princípio vale.
