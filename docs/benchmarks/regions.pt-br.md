# Regiões de medição do benchmark

> English version: [measurement regions](regions.md)

Este mapa descreve o que o Core mede hoje e os contratos necessários antes da
captura por etapa. Ele não introduz um segundo runner público de benchmark.

## Regiões atuais

| Região | Responsável atual | Trabalho observado | Limite |
|---|---|---|---|
| Entrada do dataset | `scripts/bench/datasets/` | Materializar e identificar imagens de páginas selecionadas e referências Markdown disponíveis | O download do dataset fica fora do tempo da execução de estrutura |
| Harness de estrutura | `scripts/bench/` e SDK da Toolbox | `document.structure.extract`, conversão da resposta para documento canônico e exportação Markdown por página | Exclui planner/executor do Core, enriquecimento visual e matemático remoto e exportações finais do produto |
| Pontuação local por página | `docstruct.evaluation` | Aproximações locais de texto, ordem de leitura, TEDS e CDM | Não é resultado oficial; CDM é diagnóstico no gate de melhoria atual |
| Scorecards de produto | Casos 036 e 006 do Core | Verificações de produto para as entradas e saídas documentadas | Separados do harness de estrutura do Dr.DocBench |
| Campanhas públicas | `acessilia-benchmark` | Datasets públicos, avaliadores oficiais, comparações de campanha e orquestração Slurm | Resultados e protocolos oficiais ficam nesse repositório; o `compare` do Core é apenas um gate local de melhoria |

O `run-manifest.json` atual identifica a seleção por página com hashes SHA-256
das imagens e referências disponíveis. Registra revisão e digest do estado
local do Core, versões do SDK/docstruct, origens sanitizadas e hashes dos caminhos dos endpoints,
provider/timeouts/retries efetivos, hashes das saídas e estado por página. Não
inclui chave de API nem conteúdo documental. Um payload bruto solicitado fica
como artefato da execução sob `BENCH_VAR`. Predições e payloads brutos podem
conter conteúdo documental; restrinja o acesso ao diretório e aplique a política
de retenção do dataset. O harness não expira artefatos.

Para cada página, a seleção também registra tipo de mídia, tamanho em bytes e
hash da entrada. O Core passa a imagem original da página à Toolbox sem recortá-la
ou transformá-la; transformações internas da Toolbox não são observáveis aqui.
Se a árvore local não tiver revisão Git, informe o SHA completo do commit de
origem com `run --dataset-revision`; nomes mutáveis como `main` são rejeitados.
Sem ele, a comparação pode gerar diagnóstico, mas não pode retornar um veredito
aceito.

As durações registradas são o tempo observado pelo chamador na chamada à
Toolbox, o tempo da checagem de integridade da entrada depois da chamada e o
tempo de parede da página, incluindo conversão e gravação de artefatos. A
chamada à Toolbox inclui transporte e espera. Cada chamada guarda a versão do
provider, as versões dos modelos, a duração e o acerto de cache quando vierem
na proveniência. Num acerto, a duração informada pertence ao resultado
armazenado. Tempo de fila, duração da consulta ao cache, política efetiva de
cache e tentativas reais seguem sem observação.

## Contrato de checkpoint por etapa

Antes de adicionar a captura, snapshots de etapas futuras devem adotar um
contrato explícito:

- **Identidade:** id da execução, dataset e revisão, split, ids do item,
  documento e página, hash da entrada e, para recortes, coordenadas e origem,
  dimensões/DPI da página e do recorte e a transformação aplicada.
- **Representação:** id e versão da etapa, media type, schema/versão e hash do
  conteúdo. O protocolo atual de estrutura é `toolbox-structure@2`, por unidade
  `document-page`.
- **Produtor:** revisão do Core, versões de Toolbox/SDK e da implementação da
  etapa, configuração efetiva sem segredos e hardware e concorrência observados.
- **Linhagem:** ids e hashes dos checkpoints pais, para o replay provar quais
  entradas produziram cada representação posterior.
- **Estado:** `not_executed`, `running`, `completed`, `failed`, `cancelled`,
  `not_applicable` ou `absent`, com motivo. A ausência só é legítima quando o
  contrato da etapa disser que aquela entrada não pede essa saída.
- **Integridade:** gravar artefatos atomicamente, verificar hashes na retomada e
  marcar a execução como concluída somente depois que todas as páginas
  selecionadas tiverem saídas obrigatórias válidas.

| Etapa | Entrada e unidade | Saída a preservar |
|---|---|---|
| Extração | Documento ou janela de páginas e provider selecionado | Resposta do provider e documento estruturado normalizado com mapeamento das páginas de origem |
| Fusão | Snapshots de extração da mesma janela | Elementos fundidos, linhagem primária/secundária e decisões de fusão |
| OCR | Imagem de página ou região, transformação e idioma | Transcrição e coordenadas de origem quando disponíveis |
| Descrição visual | Região da figura, legenda/contexto e configuração do prompt/modelo | Descrição com identidade da figura e estado do enriquecimento |
| Tabelas | Região ou elemento de tabela normalizado | Estrutura com células, cabeçalhos e extensão das células mescladas |
| Matemática | Região da fórmula para reconhecimento e LaTeX para conversão e verbalização | Saídas distintas de reconhecimento, MathML e verbalização vinculadas às respectivas entradas |
| Ordem de leitura | Identidades estáveis dos elementos da página ou janela | Identidades em ordem com mapeamento das páginas de origem |
| Planner | Observações e obrigações do documento com a estratégia de planejamento | Plano, cobertura das obrigações e custo informado |
| Executor | Plano e snapshots de entrada das ações | Resultados por ação, tentativas, falhas e recuperação |
| Exportação | Documento canônico e formato/opções selecionados | Artefato exportado e resultados da validação de formato e acessibilidade |

Cada contrato futuro deve versionar o schema das representações capturadas.
A captura é opcional e congela snapshots independentes antes de alterações
por outras etapas. Teste a equivalência das saídas da pipeline com a captura
ligada e desligada.

Payloads de checkpoints podem conter texto documental, imagens ou respostas do
provider. Mantenha esses snapshots no armazenamento de artefatos do benchmark,
com política explícita de acesso e retenção; eventos de observabilidade devem
registrar ids, estados e tempos, sem conteúdo documental.

O replay deve consumir entradas registradas e checkpoints pais sem chamar um
provider. O relatório precisa identificar a execução de origem e informar
cobertura e falhas por componente. Não deve alegar equivalência se faltar um
snapshot obrigatório ou se o hash/schema não corresponder.

## Dependências e próximos passos

A captura de etapas deve aguardar a modularização do Orchestrator no Core #381,
para seguir interfaces estáveis. A fronteira do SDK em #402 deve fornecer
contratos públicos ao benchmark externo; código externo não deve criar novas
importações de módulos privados do Core. A instrumentação de tempos e cache de
#370 deve distinguir duração observada pelo chamador, duração do provider,
eventos de cache e retries, em vez de deduzir um valor a partir de outro.
Este protocolo registra somente a configuração efetiva da Toolbox porque não
executa a pipeline de processamento do Core. Um protocolo futuro da pipeline
completa deve reutilizar `processing_cache_configuration()` para as configurações
de processamento do Core.
Prefira replay offline ou execuções isoladas a um gateway de produção
compartilhado. A execução serial não é uma política de admissão nem reserva
capacidade para usuários; usar o gateway exige janela de execução e condição de
parada.

Veja o [mapa de cobertura](coverage-map.pt-br.md) e o
[guia do harness](../bench.pt-br.md) para os detalhes atuais.
