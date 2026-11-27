# 0032. Operações da Toolbox usam bibliotecas locais em famílias de implantação

Inglês: [English version](0032-toolbox-runtime-library-placement.md).

- **Status:** Aceito
- **Data:** 2026-11-27
- **Componentes:** core, SDK, docstruct, Toolbox
- **Issues:** [#913](https://github.com/A11yDevs/acessilia/issues/913), [#804](https://github.com/A11yDevs/acessilia/issues/804), [#639](https://github.com/A11yDevs/acessilia/issues/639), [#735](https://github.com/A11yDevs/acessilia/issues/735)
- **Baseia-se em:** [ADR-0002](0002-component-responsibilities.pt-br.md), [ADR-0003](0003-remote-only-operational-capabilities.pt-br.md); detalha a localização do runtime proposta na [ADR-0028](0028-operational-execution-in-the-toolbox.pt-br.md).

## Contexto

Retirar uma operação do Core não determina se cada função precisa de um
serviço. A Toolbox já instala um wheel da Docstruct fixado por hash, executa
adaptadores leves localmente e delega providers pesados a sidecars. Seus
registros de capacidades/providers já despacham os dois tipos de execução.
O [inventário de fontes e mapa de migração](../architecture/toolbox-runtime-placement.pt-br.md)
registra as revisões inspecionadas, os mecanismos existentes e as lacunas.

Alternativas consideradas:

| Localização | Trade-off |
|---|---|
| Serviço central da Docstruct | Acrescenta transporte e serialização a cada chamada de algoritmo e acopla a escala dos consumidores. |
| Um contêiner por capacidade | Oferece isolamento, mas multiplica implantação e comunicação para funções pequenas. |
| Uma imagem com todos os providers | Simplifica o despacho, mas acopla dependências, modelos e recursos incompatíveis. |
| Bibliotecas locais em famílias adequadas de implantação | Reutiliza o processo leve e os sidecars existentes; separa serviços quando suas necessidades de recursos ou isolamento justificarem. Escolhida. |

## Decisão

1. **Separar algoritmo, capacidade e implantação.** A Docstruct continua uma
   biblioteca pura independente. Funções operacionais da Toolbox a chamam
   localmente; uma capacidade versionada expõe uma operação semântica
   delimitada; a implantação agrupa operações compatíveis por necessidades
   de recursos. Esses elementos não têm correspondência um a um.
2. **Começar pelo processo existente da Toolbox.** Colocar composições migradas
   no pacote interno `acessilia_toolbox.operations` quando a primeira fatia
   precisar dele, com adaptadores registrados finos. Não copiar algoritmos
   da Docstruct nem mover o registro de identificadores/cancelamento de
   `core/operations.py`: sua responsabilidade é diferente. Um pacote de
   runtime publicado separadamente exige um importador externo concreto e
   uma decisão posterior.
3. **Manter execução pesada ou incompatível isolada.** Reutilizar os sidecars
   atuais. Um novo worker/imagem/serviço exige evidência de necessidades de
   GPU/runtime, dependências incompatíveis, isolamento de falhas ou escala
   independente. Uma família é uma categoria de localização, não uma
   obrigação de acrescentar um contêiner.
4. **Reutilizar o registro público e a fronteira de execução.** Resolver a
   identidade/versão da capacidade e o provider selecionado pelos registros,
   executor e fábricas de adaptadores existentes. Uma função chama outra
   função local diretamente, sem REST/MCP de retorno para si mesma ou um
   segundo catálogo. Trabalho entre processos usa o contrato público do provider.
5. **Manter a autoridade do workflow no Core.** Objetivos, alvos, escolhas
   semânticas de provider, alternativas, aceite e replanejamento continuam
   nele. Composições operacionais executam um contrato explícito e delimitado
   e devolvem observações, resultados, falhas tipadas e proveniência. Não
   criam obrigações nem escolhem um workflow. Decompor agentes legados por
   responsabilidade; agentes e suas decisões continuam no Core.
6. **Explicitar dependências e releases.** Runtime da Toolbox → Docstruct;
   Core → SDK público → contrato da capacidade. O runtime não importa Core
   nem Core SDK. Publicá-lo junto com a Toolbox; fixar wheel/hash da Docstruct
   e registrar versões do runtime/provider/algoritmo na proveniência e na
   identidade do cache. Instalar apenas os extras de cada imagem, pelo lockfile.
7. **Migrar uma fatia semântica de cada vez.** Publicar primeiro um contrato
   compatível e a implementação, depois trocar o consumidor no Core com
   evidência diferencial e reduzir as allowlists transitórias/de imports.
   Preservar ids, metadados, escopo dos alvos, semântica de falhas e retomada.
   Agrupar transformações pequenas quando o contrato permitir; medir chamadas,
   bytes e latência antes de afirmar uma melhoria de desempenho.

## Consequências e escopo

Esta decisão define localização e invocação das operações migradas. As
operações locais atuais do SDK continuam transitórias até a migração dos
consumidores; reorganizar pacotes não as elimina. Os contratos existentes
continuam sendo a fonte de verdade até a decisão sobre contratos compartilhados.
As ADRs 0027–0029 mantêm seu status `Proposed` e seu escopo ainda em discussão.

A primeira fatia planejada é `norm-fix`; `text.postprocess@1` tem saída e
comportamento diferentes. O mapa de migração distingue reutilização de novos
contratos e identifica donos/issues. Este PR de decisão não altera topologia
Docker, comportamento do runtime, transporte MCP nem implementação de filas.

A admissão atual por semáforo/threadpool e a junção de operações local ao
processo não são uma fila distribuída durável. A execução assíncrona pertence
à #639. Reconhecer cancelamento não comprova preempção de computação síncrona.
Referências de artefatos continuam preferidas; esta decisão não torna o Core
exclusivamente orientado a referências nem planeja o bootstrap (#914/#816).

A conformidade usa as verificações existentes de pureza, dependências,
instalação isolada e testes diferenciais, além dos contratos de cada migração.
O inventário registra a guarda ausente de `acessilia_core` na Toolbox e seu
encaminhamento; não afirma que ela já esteja implementada. Os donos dos
componentes revisam esta decisão pelo processo de ADR antes do merge;
`Aceito` descreve seu estado após o merge.
