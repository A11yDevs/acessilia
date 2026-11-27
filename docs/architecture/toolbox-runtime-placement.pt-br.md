# Localização do runtime da Toolbox e primeiras fatias de migração

Inglês: [English version](toolbox-runtime-placement.md).

Estas são as evidências e o mapa de implementação da [ADR-0032](../adr/0032-toolbox-runtime-library-placement.pt-br.md)
e da [#913](https://github.com/A11yDevs/acessilia/issues/913). Snapshots de fontes
em 2026-11-27: Acessilia `02678e5e` e
[Toolbox develop em `dac17c24`](https://github.com/A11yDevs/acessilia-toolbox/commit/dac17c24ad709398a49418f1eb71493b22816660).
O inventário descreve fontes/configuração, não a saúde nem os digests de imagens
de uma implantação em execução. Não afirma benchmark ou mudança de topologia.

A auditoria do Core começou em `02678e5e`. Esta branch documental passou por
rebase sobre `689e555b` (incluindo #922/#923); as mudanças intermediárias cobrem
documentação de duplicação e shims/testes de descontinuação de fórmulas.
As classificações dos métodos, as três composições do SDK e a versão fixada da
Docstruct foram conferidas nessa base. O hash anterior registra a base da
auditoria, não afirma que a branch anteceda o rebase; as evidências da Toolbox
continuam fixadas em `dac17c24`.

## Caminho de execução existente

A [fábrica da aplicação](https://github.com/A11yDevs/acessilia-toolbox/blob/dac17c24ad709398a49418f1eb71493b22816660/src/acessilia_toolbox/api/app.py)
da Toolbox carrega manifestos de capacidades e descritores de providers e
injeta fábrica de adaptadores, armazenamento de artefatos e cache no
`CapabilityExecutor`.

```text
Core escolhe uma operação semântica e seus alvos
  -> SDK público -> id/versão da capacidade e provider explícito, quando necessário
  -> CapabilityRegistry.get -> ProviderRegistry.resolve
  -> CapabilityExecutor -> create_adapter -> ProviderAdapter.execute
       -> função local / algoritmo Docstruct
       -> ou contrato existente de provider externo
  -> resultado, observações, artefatos e proveniência -> Core atualiza seu estado
```

O [executor](https://github.com/A11yDevs/acessilia-toolbox/blob/dac17c24ad709398a49418f1eb71493b22816660/src/acessilia_toolbox/core/executor.py)
vincula a versão solicitada, verifica a entrada, resolve um provider, inclui
versões do provider/componentes na chave do cache, executa o adaptador,
normaliza/publica resultados e registra proveniência. A resolução de provider
recusa escolhas ambíguas em vez de selecionar silenciosamente uma alternativa
semântica. Novas funções do runtime reutilizam esse caminho e sua fonte de
manifestos; não há um novo catálogo de roteamento.

REST usa vagas limitadas de execução e um threadpool. A
[fachada MCP](https://github.com/A11yDevs/acessilia-toolbox/blob/dac17c24ad709398a49418f1eb71493b22816660/src/acessilia_toolbox/api/mcp.py)
usa os mesmos registros/executor; suas tools atualmente selecionam a versão
mais recente. A aplicação HTTP não monta essa fachada como endpoint Streamable
HTTP. MCP autenticado e vínculo de versões continuam na [#632](https://github.com/A11yDevs/acessilia/issues/632),
na [#639](https://github.com/A11yDevs/acessilia/issues/639) e na
[ADR-0027](../adr/0027-mcp-core-toolbox-contract.pt-br.md), não são entregas concluídas aqui.

## Inventário de implantação e pacotes

| Unidade existente | Execução e dependências | Consequência para a localização |
|---|---|---|
| Processo de API/executor da Toolbox | Adaptadores Python leves, normalização e algoritmos locais. A imagem padrão instala o wheel da Toolbox e Docstruct; extras opcionais selecionam dependências nativas/clientes. | Hospedeiro inicial de operações CPU compatíveis e delimitadas; sem salto adicional de servidor para chamar uma biblioteca local. |
| Sidecars Docling, MinerU e OCR/modelos | Imagens, endpoints e volumes de modelos separados no Compose. | Manter runtimes ML/GPU isolados; migrar uma função pura não justifica instalar esses runtimes na imagem da API. |
| Sidecars matemáticos, de renderização e validação | `math-speech`, `pdf-ua-render`, `verapdf-validate`; a configuração do gateway/upstream VLM é separada. | Reutilizar serviços especializados pelos adaptadores atuais; composições operacionais não precisam acrescentar outro sidecar. |
| Providers de áudio e música | `piper-tts` com seu volume de modelos; `audiveris-serve` no profile opcional `music` do Compose. Os extras de pacote `audio` (`edge-tts`) e `music` (`homr`) são separados desses sidecars. | Reutilizar os providers existentes. Nenhum alvo inicial de migração exige esses extras; o build local da API no Compose não os habilita. |
| MinIO e Valkey | Armazenamento de artefatos e cache de execução no Compose; fallback de filesystem tem modo explícito. | Esses serviços não estabelecem filas duráveis nem estado autoritativo de workflow. |

Fontes: [Dockerfile](https://github.com/A11yDevs/acessilia-toolbox/blob/dac17c24ad709398a49418f1eb71493b22816660/Dockerfile),
[Compose local](https://github.com/A11yDevs/acessilia-toolbox/blob/dac17c24ad709398a49418f1eb71493b22816660/docker-compose.yml),
[Compose de produção](https://github.com/A11yDevs/acessilia-toolbox/blob/dac17c24ad709398a49418f1eb71493b22816660/docker-compose.production.yml),
[definição da implantação VLM](https://github.com/A11yDevs/acessilia-toolbox/blob/dac17c24ad709398a49418f1eb71493b22816660/deploy/vlm-gateway/docker-compose.yml).
O build do Compose local habilita `api,storage,cache,pdf,media`; o arquivo de
produção seleciona uma imagem aprovada por digest, não uma nova resolução de
dependências. Os extras realmente instalados dependem do build dessa imagem.

| Pacote ou namespace | Estado atual | Decisão / obrigação de migração |
|---|---|---|
| `acessilia-docstruct` | Biblioteca independente; ambos os snapshots usam 0.5.8. A Toolbox fixa o wheel da release por SHA-256 no [pyproject.toml](https://github.com/A11yDevs/acessilia-toolbox/blob/dac17c24ad709398a49418f1eb71493b22816660/pyproject.toml). | Mantê-la independente e instalá-la nas imagens que executam seus algoritmos; nunca copiar fontes para adaptadores. |
| `acessilia_toolbox.operations` | Ausente na árvore inspecionada. | Criar o pacote interno quando a primeira composição migrada precisar dele; publicar/versionar junto com a Toolbox. |
| `acessilia_toolbox.core.operations` | Junção de identificadores e cancelamento cooperativo existentes; estado local ao processo. | Preservar essa responsabilidade distinta; não é o runtime de operações documentais nem uma fila durável. |
| `acessilia_sdk.operations` | Três composições locais: fórmulas, fusão e julgamento de página. | Decompor e migrar por contratos revisados. Manter compatibilidade até os consumidores migrarem; o servidor não importa seu pacote cliente. |
| Core SDK e contratos compartilhados | Separação do Core SDK/MCP e decisão sobre ownership de contratos ainda pendentes. | Usar o transporte público `execute_capability` do SDK durante a transição; preservar os donos atuais dos schemas até uma decisão explícita. Nenhum novo pacote de contratos é imposto. |

O novo runtime usa funções com argumentos/resultados explícitos e serviços
de I/O injetados. Validar DTOs públicos na fronteira usando modelos e contratos
existentes; manter transformações puras independentes de armazenamento,
settings e modelos de workflow. Uma requisição identifica alvos e opções
delimitados; a validação do resultado rejeita ids ausentes, duplicados ou não
solicitados antes de o Core aplicar observações. A validação genérica da saída
de providers pelos schemas permanece na [Toolbox #117](https://github.com/A11yDevs/acessilia-toolbox/issues/117).

## Fronteiras das composições migradas

São requisitos para novas fatias, não afirmações de que o runtime atual já
aplica todas as garantias.

| Fronteira | Regra e exemplo |
|---|---|
| Função interna | Chamar uma função pura diretamente, por exemplo substituição Unicode ou conversão para tons de cinza. Ela não precisa de capacidade pública nem de ação PDDL própria. |
| Capacidade delimitada | Um contrato versionado de normalização em lote pode compor funções privadas com contexto/I/O explícitos. Reutilizar outra capacidade pública deve preservar as garantias de validação, autorização, erro, cancelamento, proveniência e cache exigidas por seu contrato. Reutilização local não precisa entrar novamente no executor ou usar HTTP de retorno para si mesma. |
| Ação/decisão do Core | Precondições/efeitos relevantes de forma independente, resultados de obrigações, alternativas de estratégia ou necessidades de aceite/replanejamento tornam uma operação candidata a ação planejada. Reconhecimento de fórmulas e uma conversão MathML necessária separadamente podem ser ações distintas; pré-processamento técnico pode ficar dentro do reconhecimento. Não ocultar escolhas de workflow numa composição Python. |

Coordenar a granularidade das ações com a #640 e a ADR-0029 proposta. Uma
família de implantação não determina o domínio de planejamento. Migrar
`norm-fix` não exige reescrever todo o planejador antes.

A escolha de provider/estratégia pertence ao Core (incluindo sua configuração
explícita). Resolver uma implementação compatível, selecionar sua instância
disponível ou fazer failover de infraestrutura só é permitido sob a política
operacional autorizada, preservando restrições semânticas/de provider/versão e
registrando a implementação usada. Disponibilidade não pode trocar Docling por
MinerU ou OCR por VLM silenciosamente. Isso não aceita o escopo restante da
[ADR-0030 proposta](../adr/0030-providers-compete-per-capability.pt-br.md).

Uma composição não deve reter uma vaga de admissão enquanto espera trabalho
dependente no mesmo pool saturado. Definir admissão limitada e propagação de
timeouts/cancelamento; um threadpool sozinho não isola CPU/GIL ou memória.
Considerar pools limitados ou processos antes de exigir imagem/serviço separado,
justificando a separação com medidas de recursos ou necessidades de segurança/
isolamento. É orientação preventiva, não um deadlock reproduzido.

Durante a 0.3.0, o Core pode manter representações de contrato/dados para
coordenação sob a [classificação e allowlist atuais](docstruct-import-inventory.pt-br.md).
Imports existentes fora de contrato continuam dívida transitória fixada;
remover a chamada computacional e sua permissão juntas quando a capacidade a
substituir. Não ampliar essas exceções ou tratar acesso a dados como permissão
para novos algoritmos locais. A separação integral por referências continua
sendo a proposta #914.

## Mapa inicial de migração

São famílias lógicas de execução, não nomes de novos serviços. As entradas
abaixo são **candidatas à migração**, não capacidades recém-registradas. O
Core ainda tem 20 métodos transitórios e dois de validação em
[`LOCAL_METHODS`](../../libs/core/src/acessilia_core/planning/toolbox_gate.py).

| Trabalho no Core/SDK | Família de execução e biblioteca adequadas | Estado do contrato e responsabilidade do Core |
|---|---|---|
| `norm-fix` | Processo leve existente → nova função do runtime → `docstruct.text.norm_fix`. | Primeira fatia [#929](https://github.com/A11yDevs/acessilia/issues/929). Novo contrato versionado de normalização; Core seleciona alvos e aplica observações validadas. |
| `unicode-repair`, `latex-normalizer`, `rep-guard`, `line-number-extractor`, `verse-chunker`, `pandoc-code`, `tailjoin`, `tailjoin-positioned`, `deterministic-heading-repair` | Funções CPU de texto/estrutura da Docstruct, agrupadas somente quando o contrato permitir. | Auditar `code.normalize@1`/`text.postprocess@1` em busca de primitivas reutilizáveis; nenhum contrato equivalente de lote foi demonstrado. Preservar contexto/evidências e manter decisões de elegibilidade/aceite no Core. |
| `xycut-order`, `skeleton-order` | Funções CPU de layout (`docstruct.fusion.xycut`, `skeleton`). | Ids estáveis, boxes, ordem de origem e ordem resultante exigem contrato explícito. Core escolhe qual evidência/obrigação atender. |
| `agreement-rule`, `rescue-omitted`, `table-smart-fusion`; composição de fusão do SDK | Fusão/runtime CPU mais providers de extração existentes. | Reutilizar primitivas estruturais; definir resultados de fusão/roteamento/proveniência e semântica de falhas parciais. Core mantém política de qualidade e seleção de alternativas. |
| `table-enrichment`, validação `pandoc-table` | Reconhecedores/VLM existentes mais normalização CPU de AST. | Reutilizar o trabalho da capacidade de tabelas, incluindo [Toolbox #170](https://github.com/A11yDevs/acessilia-toolbox/issues/170). Tabela extraída e tabela reconhecida válida não são intercambiáveis sem verificações de contrato. |
| `picture-description`, `formula-recognizer`, `formula-region-classifier`, validação `vision-description`; composições de fórmulas/julgamento do SDK | Providers existentes de renderização/matemática/VLM mais composição delimitada no runtime. | Reutilizar `pdf.render`, `math.*` e `document.adjudicate.page` quando seus contratos forem adequados. Core mantém seleção de candidatos, limiares, fallback e decisões de reclassificação; agentes não migram para a Toolbox. |
| `inline-math-marker` | Algoritmos CPU de fontes/spans com o provider existente `document.text.spans`. | Preservar evidência, política efetiva, invalidação e progresso; Core mantém descoberta de alvos e transições das obrigações. |

`human-review` continua simbólico no Core. `table-specialist` não tem handler
e não é uma implementação disponível. Esta decisão não muda classificações
nem retira permissões transitórias antes de uma migração funcionar.

## Primeira fatia e critérios de aceite

O [provider de texto](https://github.com/A11yDevs/acessilia-toolbox/blob/dac17c24ad709398a49418f1eb71493b22816660/src/acessilia_toolbox/providers/pure_text.py)
existente de `text.postprocess@1` acrescenta marcadores, deduplica e emite texto
processado. O [handler `norm-fix` do Core](../../libs/core/src/acessilia_core/pipeline/handlers/text.py)
preserva alvos/ids e repara ligaduras, hífens suaves, NBSP e espaços, protegendo
prefixos de tabelas/fórmulas. A capacidade atual não é uma substituição
equivalente. A [#929](https://github.com/A11yDevs/acessilia/issues/929) define
primeiro um contrato de lote delimitado, depois um PR de provider/runtime na
Toolbox e um PR de integração no Core. O nome da capacidade é candidato até
a revisão do contrato.

Cada fatia deve:

1. Publicar primeiro contratos compatíveis de entrada/saída/erro e um provider;
   incluir versões do runtime/provider/Docstruct no cache e na proveniência.
   Preservar consumidores antigos e definir falha ou degradação explicitamente
   autorizada e rollback para consumidor novo/Toolbox antiga, usando os
   requisitos existentes de capacidades ([#848](https://github.com/A11yDevs/acessilia/issues/848)).
2. Comprovar equivalência de algoritmo, metadados, alvos/ordem e checkpoints.
   Separar evidência de origem de envelopes de planejamento do Core ([#908](https://github.com/A11yDevs/acessilia/issues/908)).
   Uma nova capacidade recebe DTOs/referências/opções delimitados, nunca o
   `ProcessingManifest` completo com objetivos, obrigações ou tentativas.
   Ela não precisa esperar toda a #908; manter validadores estritos e
   identidades de schema inequívocas.
3. Especificar regras de repetição/recuperação, efeitos colaterais, timeouts,
   retenção/limpeza de artefatos e publicação, incluindo perda da resposta após
   execução. Distinguir id de job, id de operação, identidade da entrada
   processada, chave de cache e eventual chave de idempotência; junção/cache
   local ao processo não é idempotência distribuída durável. Declarar limites
   de itens/bytes do lote, tempo, concorrência e fronteiras de cancelamento.
4. Correlacionar observações à operação, alvo, conteúdo/contexto processados,
   versão da capacidade e proveniência. O Core deve verificar aplicabilidade
   antes de atualizar o estado, rejeitando entrada/contexto obsoletos mesmo
   que os ids coincidam; usar revisões/digests relevantes quando necessário,
   sem impor um protocolo global. Reutilizar verificações de alvos da
   [#843](https://github.com/A11yDevs/acessilia/issues/843) e coordenar invalidação
   de conteúdo com a [#840](https://github.com/A11yDevs/acessilia/issues/840).
   Versionar algoritmos/opções internos efetivos que afetam resultados e cache;
   não se exige um evento para cada função privada.
5. Trocar a chamada pública do SDK somente quando a capacidade existir;
   propagar falhas tipadas sem fallback computacional local. Preservar
   admissão limitada e cancelamento antes da publicação; não afirmar
   preempção a partir de um reconhecimento de cancelamento.
6. Fechar a guarda ausente de imports do Core na Toolbox #172 antes de publicar
   código migrado do runtime. Reduzir permissões de métodos/imports e verificar
   instalações isoladas, contratos e saídas diferenciais. Mudar `HARNESS_FILES` exige o
   [fluxo existente de gravação de referências](../../tests/differential/README.pt-br.md).
7. Medir chamadas por lote, bytes serializados, latência, CPU e memória antes de escolher
   outra divisão de implantação ou afirmar ganho de velocidade. A decisão de
   localização sozinha não comprova equivalência de saída nem melhor desempenho.

## Cobertura de guardas e donos das pendências

| Fronteira / trabalho restante | Cobertura atual / dono |
|---|---|
| Core/backend → internos da Toolbox | `tests/test_architecture_layers.py` já rejeita esses imports. |
| SDK → Core/Toolbox | Verificações existentes de pureza/instalação isolada do SDK. Preservá-las na separação de responsabilidades cliente/runtime. |
| Docstruct → infraestrutura ou camadas superiores | Verificações existentes de pureza/infraestrutura da Docstruct e instalação isolada. |
| Toolbox → Core/SDK | A [guarda existente](https://github.com/A11yDevs/acessilia-toolbox/blob/dac17c24ad709398a49418f1eb71493b22816660/tests/unit/test_architecture.py) proíbe raízes legadas do SDK/backend/frontend, mas omite `acessilia_core`. Fechar a lacuna real na [Toolbox #172](https://github.com/A11yDevs/acessilia-toolbox/issues/172); não apresentá-la como já implementada. |
| Primeira migração operacional | [#929](https://github.com/A11yDevs/acessilia/issues/929); os demais métodos continuam no épico [#804](https://github.com/A11yDevs/acessilia/issues/804). |
| Separação do SDK, contratos compartilhados e MCP | [#639](https://github.com/A11yDevs/acessilia/issues/639), [#632](https://github.com/A11yDevs/acessilia/issues/632) e propostas de ADRs 0027–0029 existentes; preservar ownership e requisitos de revisão. |
| Filas/workers duráveis e recuperação de observações | Trabalho existente de #639/#640. `OperationRegistry`, MinIO e cache Valkey, isoladamente, não o implementam. |

A decisão de bootstrap para 0.3.0 continua válida. Planejar esse bootstrap e
tornar o Core exclusivamente orientado a referências permanecem na
[#816](https://github.com/A11yDevs/acessilia/issues/816) e na
[#914](https://github.com/A11yDevs/acessilia/issues/914), respectivamente.
