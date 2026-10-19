# 0007. Modelo canônico do manifesto, e conversão para MathML e verbalização de fórmulas

Também disponível em **inglês (EUA)**: [English version](0007-manifest-model-and-mathml-conversion.md)

- **Status:** Aceito
- **Data:** 2026-10-19
- **Componentes:** core, SDK, docstruct, Toolbox
- **Issues:** [#152](https://github.com/A11yDevs/acessilia/issues/152); achados A1 e A3 da [auditoria de outubro de 2026](../architecture/audit-2026-10.pt-br.md)
- **Relacionadas:** [ADR-0002](0002-component-responsibilities.pt-br.md), [ADR-0003](0003-remote-only-operational-capabilities.pt-br.md), [ADR-0004](0004-single-source-of-truth-for-contracts.pt-br.md)

## Contexto

O Acessília tem quatro componentes com responsabilidades distintas
([ADR-0002](0002-component-responsibilities.pt-br.md)): o **core** decide e
orquestra o processamento; o **SDK** oferece acesso tipado às capacidades da
Toolbox; o **docstruct** mantém modelos e algoritmos estruturais puros; e a
**Toolbox** executa e expõe capacidades operacionais.

A auditoria encontrou duas questões que precisavam de decisão:

1. **Qual componente mantém a definição única do modelo semântico do
   manifesto de processamento.** Hoje o modelo existe duas vezes, em
   `backend/core/manifest/models.py` e em `core/normalization/models.py` da
   Toolbox, com o mesmo id de schema; a Toolbox o publica como
   `artifact/structured-document@1` (achado A1).
2. **Onde ocorrem a conversão LaTeX → MathML e a verbalização de fórmulas.**
   Hoje o core converte com o `latex2mathml` e verbaliza com regras próprias
   em pt-BR, ambos em `backend/tools/formula_tools.py`, enquanto a Toolbox tem
   implementações próprias por trás do `math.convert` e do `math.verbalize`;
   os dois verbalizadores divergiram (achado A3).

## Decisão

### 1. O docstruct é a fonte única do modelo semântico do manifesto

**O docstruct é a fonte única dos modelos semânticos e dos esquemas de
estrutura documental, incluindo a estrutura do manifesto.** A Toolbox continua
responsável por publicar e validar o contrato operacional
`artifact/structured-document@1` nas suas APIs. Esse contrato deve ser
**derivado da definição compartilhada**, sem manutenção manual de modelos
concorrentes.

É importante distinguir dois conceitos:

- **Modelo semântico/documental:** elementos, estrutura, hierarquia,
  localização, proveniência e invariantes documentais. Pertencem ao
  docstruct.
- **Envelope e contrato operacional:** identificadores de capacidades,
  requisições e respostas, referências de artefatos, execução, erros e
  metadados específicos da API. Pertencem à Toolbox.

Os tipos internos do docstruct não precisam ser idênticos ao payload externo.
Quando houver diferenças, um adaptador explícito transforma os dados entre as
representações, preservando semântica e compatibilidade. O nome público
`artifact/structured-document@1` **não determina a localização do
código-fonte do modelo**.

Justificativas:

1. **Fonte única de verdade:** evita divergência entre modelos definidos em
   repositórios diferentes e reduz manutenção e testes duplicados.
2. **Coesão:** fusão, comparação, ordem de leitura, validação estrutural e
   seus tipos de dados permanecem no mesmo domínio.
3. **Direção de dependências:** core e Toolbox podem depender do docstruct,
   sem dependência reversa e sem acoplar o docstruct a REST, MCP ou ao SDK.
4. **Estabilidade externa:** o contrato publicado pela Toolbox pode continuar
   versionado independentemente das estruturas internas, com conversões
   explícitas quando necessário.

Restrições:

- O docstruct **deve permanecer puro, determinístico e sem dependências
  externas obrigatórias**, como é hoje.
- **Não** se deve migrar indiscriminadamente todos os modelos Pydantic
  operacionais da Toolbox para o docstruct: só conceitos e invariantes
  documentais pertencem à biblioteca. Metadados de execução e políticas de
  planejamento ficam nos seus respectivos componentes.

### 2. O core obtém MathML e texto falado pela Toolbox, via SDK

**O core solicita a conversão por meio do SDK, usando a capacidade
`math.convert` da Toolbox.** A implementação com `latex2mathml` permanece no
provider especializado da Toolbox. **Não será introduzido um extra
`latex2mathml` no docstruct.**

```text
core (decide quando converter)
  → SDK (contrato, transporte, erros)
    → Toolbox / math.convert (execução)
      → provider pure-math / latex2mathml
```

**A verbalização segue a mesma regra: o core obtém o texto falado de uma
fórmula por meio do SDK, usando a capacidade `math.verbalize` da Toolbox.** As
regras de verbalização ficam só no provider `pure-math` da Toolbox; o core não
mantém nenhuma, e o docstruct também não recebe um verbalizador. O core
continua decidindo quando uma fórmula precisa de alternativa falada e o que
fazer com o resultado.

O docstruct permanece responsável por operações estruturais puras de LaTeX,
como normalização, remoção de delimitadores e comparação. O fato de uma
biblioteca de conversão ser Python puro não a transforma em algoritmo
estrutural a ser incorporado ao docstruct.

Justificativas:

1. **Evitar implementações concorrentes:** o mesmo serviço de conversão não
   deve existir ao mesmo tempo no core, no docstruct e na Toolbox.
2. **Separação de responsabilidades:** o core determina *quando* e *por que*
   converter; a Toolbox determina *como executar* a conversão segundo a
   capacidade contratada.
3. **Isolamento de dependências:** preserva o docstruct sem `latex2mathml` e
   evita levar conversores operacionais para a imagem do core.
4. **Governança e observabilidade:** versões do provider, disponibilidade,
   erros, métricas e evolução dos conversores são administrados na camada de
   capacidades.
5. **Evolução:** novos conversores podem implementar `math.convert` sem alterar
   o planejamento nem os algoritmos estruturais.

Tratamento de falhas: indisponibilidade ou erro em `math.convert` ou `math.verbalize` deve ser
informado explicitamente ao core, que decide entre falha, replanejamento ou
degradação documentada. **Não deve haver fallback local silencioso** para o
`latex2mathml` nem para um verbalizador local
([ADR-0003](0003-remote-only-operational-capabilities.pt-br.md)).

### Responsabilidades resultantes

| Componente | Responsabilidade |
|---|---|
| docstruct | Modelos e invariantes estruturais; normalização e algoritmos puros sobre documentos e fórmulas |
| Toolbox | Publicação de `artifact/structured-document@1`; adaptação entre representações; execução do `math.convert` e do `math.verbalize` e gestão do provider |
| SDK | Cliente tipado para os contratos publicados; transporte, referências, tratamento de erros e retentativas |
| core | Planejamento PDDL, decisões de enriquecimento e acessibilidade, acionamento do `math.convert` e do `math.verbalize` e tratamento dos resultados |

## Consequências

Implementação e critérios de aceite:

1. **Inventariar e separar os modelos:** identificar os conceitos documentais
   duplicados no core e na Toolbox e distinguir campos semânticos,
   operacionais e de planejamento.
2. **Consolidar a definição compartilhada:** posicionar modelos e invariantes
   documentais no docstruct, sem dependência da Toolbox, do SDK ou do core;
   usar geração de schema ou adaptadores explícitos para a API.
3. **Preservar a compatibilidade:** manter `artifact/structured-document@1` e
   suas regras de versão; rodar testes de contrato com fixtures reais antes de
   substituir modelos existentes. Mudanças incompatíveis exigem um novo
   contrato versionado.
4. **Migrar a conversão e a verbalização:** substituir as chamadas diretas
   ao `latex2mathml` e o verbalizador próprio do core
   (`verbalize_latex_fallback`) por chamadas ao `math.convert` e ao
   `math.verbalize` via SDK, e remover a dependência direta do core ao
   `latex2mathml` **depois** de confirmar que não há outros usos legítimos.
   O `math.verbalize@1` produz só pt-BR, como o verbalizador atual do core;
   verbalizar outros idiomas exige um parâmetro de idioma numa nova versão da
   capacidade.
5. **Evitar duplicidade:** não introduzir extra de conversão nem
   verbalizador no docstruct; conservar ali só as funções puras de
   normalização de LaTeX.
6. **Verificar na CI:** pureza e direção de dependências; conformidade do
   manifesto ao contrato publicado; equivalência semântica nos adaptadores; e
   tratamento de erros, indisponibilidade e resultados do `math.convert` e
   do `math.verbalize`.

**Concluído quando** existir uma única definição semântica dos modelos
compartilhados, o payload da Toolbox continuar compatível, o core obtiver
MathML e texto falado exclusivamente pelo `math.convert` e pelo
`math.verbalize` via SDK, e os testes impedirem novas
dependências ou implementações duplicadas.

Benefícios: menor acoplamento entre camadas, menos código duplicado, contratos
mais previsíveis e liberdade para os providers evoluírem de forma
independente.

Riscos a controlar:

- migração prematura que quebre consumidores do manifesto;
- confusão entre o manifesto operacional e o documento canônico;
- divergência entre as versões do docstruct no core e na Toolbox (achado A4
  da auditoria);
- aumento de chamadas remotas para operações simples.

Mitigar com adaptadores versionados, testes de contrato, versões fixadas e,
quando apropriado, processamento em lote na Toolbox, nunca com fallback local
implícito.

Em síntese: **o docstruct define a estrutura; a Toolbox publica e executa
capacidades; o SDK conecta; o core decide e orquestra.**
