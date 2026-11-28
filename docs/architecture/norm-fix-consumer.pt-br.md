# Consumidor remoto de normalização (#929)

Inglês, versão normativa: [English version](norm-fix-consumer.md).

O Core 0.3.31 usa o SDK 0.7.1 para executar `norm-fix` por
`document.text.normalize@1`, com `docstruct-text@1.0.0` e Docstruct 0.5.8.
Provider, guarda de dependências e vinculação de identidade foram entregues nos
[PRs Toolbox #174](https://github.com/A11yDevs/acessilia-toolbox/pull/174) e
[#177](https://github.com/A11yDevs/acessilia-toolbox/pull/177). Schemas públicos e
catálogo foram capturados byte a byte na Toolbox
`b1ac9178c15e394860d4ee1adb9cc694a4602db3`; os modelos do SDK são gerados desses
arquivos, conforme a [ADR-0032 aceita](../adr/0032-toolbox-runtime-library-placement.pt-br.md).

## Responsabilidades e compatibilidade

O Core seleciona os alvos da obrigação existente em ordem de leitura, decide o
aceite e atualiza seus metadados. O SDK captura/codifica DTOs delimitados, usa o
transporte público autenticado e valida observações. Só a Toolbox produz o
resultado aceito pelo método `norm-fix`. O detector ainda prevê mudanças
localmente e o wrapper legado de fusão ainda expõe uma ferramenta local;
remover esse cálculo continua como dívida de migração (#948). `text.postprocess@1` permanece separado, com semântica
diferente de marcadores/deduplicação.

Alvos vazios/nulos ficam intactos e não exigem requisição. Alvos ausentes, falha
sem texto, contagem de não vazios processados, resultado de uma passagem e
`norm_fixed=true` apenas nos alterados seguem o handler original. Demais metadados
são preservados. O handler não tem fallback computacional local. Seu import
computacional e entrada em `LOCAL_METHODS` foram removidos; imports existentes no
detector e wrapper legado de fusão continuam inventariados como dívida de migração.

`TOOLBOX_TEXT_NORMALIZE_PROVIDER` tem padrão `docstruct-text` e participa da
identidade de processamento/checkpoint. O gate exige capacidade versionada e
vínculo do provider selecionado. A resposta também precisa provar provider 1.0.0
e Docstruct/`norm_fix` 0.5.8. Capacidade ausente/antiga, falha remota ou runtime
incompatível falha explicitamente, sem reparo local. A classificação existente do
SDK que trata HTTP 404 de capacidade como erro de artefato está registrada
separadamente na [#949](https://github.com/A11yDevs/acessilia/issues/949); o handler
continua recusando o resultado e preservando a entrada original. Orçamentos de transporte,
cache e failover autorizado usam a configuração Toolbox da execução. Não há nova
fila, imagem ou serviço.

Domínio/descrição PDDL distribuídos ficam congelados para preservar hashes dos
planos salvos. A descrição da implementação local de normalização é histórica;
este relatório descreve o handler remoto atual. O hash do domínio sozinho não
garante compatibilidade dos checkpoints (veja a política de upgrade abaixo).
A granularidade existente é preservada: o detector atual emite uma
obrigação por elemento afetado. Uma obrigação com vários alvos usa lotes
delimitados; obrigações independentes não são unidas nem antecipadas. A
[#948](https://github.com/A11yDevs/acessilia/issues/948) avalia essa decisão restante
de planejamento/desempenho e a retirada da predição local.

## Vinculação, aceite atômico e recuperação

- A construção pública de `NormalizationBatch` confere correspondência canônica
  de payload/alvos, tipos, ids, unicidade e limites uma vez, capturando listas do
  chamador. Retries HTTP reutilizam esses bytes imutáveis validados. A fábrica
  também preserva unicidade/ordem global ao dividir vários lotes.
- Cada requisição tem até 256 ids únicos (1–256 caracteres) e **1.048.576 bytes
  UTF-8 serializados**, incluindo envelope, separadores e escapes. Texto/id
  indivisível excessivo é recusado, sem truncar nem repartir o texto entre
  fronteiras do algoritmo. Todos os lotes são preparados antes de qualquer RPC.
- O consumidor confere a chave real `document.text.normalize@1`, capacidade,
  versão, provider e componentes na proveniência, fingerprint do payload completo
  e de parâmetros vazios. Fingerprints por alvo usam o original canônico UTF-8
  `{"id":id,"text":text}`; vetores compartilhados vieram do provider. Ids/ordem,
  tipos, contagens, flags, UTF-8 e preservação de vazios/nulos são verificados antes
  da aplicação. Fingerprint sozinho não estabelece correção da saída; o Core não
  recalcula o algoritmo.
- Nenhum alvo muda antes de validar todos os lotes e conferir que fonte, revisão,
  obrigação e snapshots dos alvos continuam correspondentes. Falha posterior ou
  contexto obsoleto mantém texto/metadados da obrigação intactos. A memória cresce
  com snapshots/observações da obrigação; o teto por requisição não é teto de
  memória de toda a obrigação ou da resposta HTTP.
- O Core deriva um slot de contexto semântico, versões de contrato/provider/
  componentes, política de cache e lote imutável. O diário existente fornece ids
  estáveis entre retries/reinícios; o registro existente permite cancelar lotes
  ativos. Ids de tentativa mudam por HTTP. Sem a porta de job, ids são novos por
  invocação.
- Interromper uma obrigação com vários lotes não deixa prefixo aplicado para
  salvar: a reidratação repete os lotes originais. Uma resposta retida da Toolbox
  pode ser recuperada; expulsão/reinício/réplicas independentes podem executar
  aquela entrada pura novamente. Após consolidar todo o passo, o checkpoint
  existente preserva texto, metadados e estado da obrigação juntos; a retomada o
  pula. Nunca alimenta um resultado devolvido como entrada original do retry.
- Cancelamento cooperativo/publicação mantêm os limites da ADR-0019; reconhecer
  não significa preempção ou rollback de gravação iniciada em storage/cache.
  Observações inline usam as políticas existentes de storage/cache/retenção.

## Upgrade, rollback e configuração da implantação

Adicionar o provider de normalização muda a chave do cache de processamento e
cada identidade de estágio dependente da Toolbox, inclusive mídia/extração.
Um checkpoint com identidade da 0.3.29/0.3.30 sem esse provider é recusado na primeira
fase alterada; todas as fases posteriores são refeitas desde a origem, nunca
normalizando novamente o texto processado salvo. Tentativas da versão nova com
identidade igual reutilizam o passo consolidado; lotes interrompidos preservam
a entrada original. Checkpoints anteriores às identidades mantêm a política
existente de aviso e reuso; remova-os antes de upgrade/rollback se a
compatibilidade for desconhecida. Um miss deixa a entrada antiga do cache
sujeita à expiração normal; não é uma limpeza do cache.

O id/versão de um provider não revela sua configuração privada. Antes de mudar
configuração do provider, pesos ou comportamento de algoritmo/runtime no mesmo
endpoint/id/versão, **incremente `PROCESSING_MODEL_REVISION`**. O serviço já o
inclui na identidade do cache e nas opções dos checkpoints de enriquecimento e
execução. A normalização agora também vincula essa revisão, os endpoints e o
lote original ao slot do diário. Assim o id muda, evitando repetir indefinidamente
um id que a Toolbox recusa como requisição diferente. Revisões iguais preservam
as tentativas; não há detecção automática da configuração privada. Um conflito
continua sendo falha explícita e permanente, sem rotação cega de id/retry que
possa ocultar trabalho alterado. Hosts de biblioteca que preservam diários também
devem fornecer sua revisão de implantação nas opções existentes do checkpoint
de execução. Os pins de componentes continuam estritos; mudanças futuras de
provider/Docstruct/runtime exigem revisão de compatibilidade e incremento da
revisão quando alterarem comportamento, além de conferir o hash PDDL.

Para voltar à 0.3.29, restaure o ambiente Core/SDK correspondente e reinicie da
origem com checkpoints antigos removidos, especialmente os sem identidade; não
use um documento canônico já processado como origem. A nova chave de provider
também torna checkpoints novos com identidade incompatíveis com a versão antiga.
O PR #943 foi mesclado durante a revisão com Core 0.3.30 (adiamentos tipados
por rejeição de admissão). Esta branch o incorpora e avança o Core para 0.3.31;
metadados, changelogs e ambos os lockfiles correspondem. O SDK continua 0.7.1.
O bundle do domínio permanece igual; também se aplicam as regras de
compatibilidade de relatórios/checkpoints da 0.3.30.

O cancelamento continua cooperativo. Um teste determinístico do job/fila pausa
após a última resposta validada e antes do aceite do handler. `run_blocking`
aguarda a thread ativa: ela pode concluir e salvar o passo inteiro durante o
cancelamento. O serviço impede exports/publicação de token, marca o job como
cancelado e limpa seus checkpoints. Isso não promete rollback do passo em memória
nem de escritas remotas. O teste existente de retomada comprova que um passo
consolidado e preservado não é normalizado duas vezes.

## Evidências e qualificação local

Observações congeladas do handler original cobrem alvos mistos, vazios e
protegidos/inalterados. Testes adversariais cobrem bytes/quantidade/Unicode,
identidades inválidas/obsoletas, flags/contagens, falhas posteriores e diário.
O harness diferencial acrescenta `text-normalization` e serve o envelope real
versionado. As cinco referências foram regravadas dos commits originais; os 40
documentos canônicos anteriores permanecem idênticos. O novo caso corresponde ao
caminho local histórico. A retomada por arquivo preserva uma passagem consolidada
que não é ponto fixo (`a-\nb-\nc` vira `ab-\nc`) ao concluir o passo seguinte.

A [ferramenta de qualificação](../../scripts/bench/text_normalization.py) carrega
o handler original intacto do Core `add11c46db9ab8e28eaeb54b4319c3fcf6509392`.
Compara texto, metadados e resultados do método por HTTP real em loopback à
Toolbox mesclada em outro ambiente Python, com filesystem e Redis. A interrupção/
reinício com 257 alvos usa diário SQLite e checkpoints por arquivo reais: a
primeira resposta é recuperada identicamente com cache de execução desligado.
Os serviços de teste eram temporários e foram encerrados.

Estas medidas caracterizam o commit inicial do consumidor `5c31545c`, antes da
validação de construção direta e do vínculo à revisão de implantação. As
regressões da revisão verificam correção; os tempos não são um novo benchmark
do construtor revisado. Três rodadas locais, com atraso sintético explícito de **5 ms por requisição**,
produziram estas [medidas brutas](norm-fix-consumer-measurements.json):

| Modo com 64 alvos | Total de requisições | Mediana por execução do handler (ms) | Bytes totais do corpo enviado | Bytes totais do corpo recebido |
|---|---:|---:|---:|---:|
| Handler local original | 0 | 2,276 | 0 | 0 |
| Invocações remotas individuais | 192 | 5.917,067 | 101.124 | 274.500 |
| Uma obrigação, lote delimitado | 3 | 84,257 | 9.648 | 35.616 |
| Cache remoto aquecido | 3 | 73,006 | 9.369 | 35.613 |

Quatro invocações concorrentes em lote (12 rodadas) usaram 12 requisições, mediana
204,142 ms e mesmas observações. Uma entrada JSON de **1.047.581 bytes** usou uma
requisição por rodada: mediana local 183,858 ms, remota sem cache 390,990 ms e
remota com cache 178,113 ms. Cada fase aquecida confirmou três hits.

Os dados incluem CPU do processo de qualificação (fixtures, conferências/oráculo
e captura HTTP), pico RSS acumulado do pai, CPU/RSS amostrados do servidor e
crescimento de storage (134 arquivos / 966.668 bytes com metadados, além dos
quatro arquivos iniciais). CPU/RSS do pai não são medidas isoladas do Core em
produção; RSS amostrado do servidor não é pico. Instrumentação e storage/cache
locais afetam tempos. Três rodadas e atraso sintético em loopback não estabelecem
latência de produção, comportamento MinIO/Valkey, vazão ou ganho de qualidade.
O modo individual inclui repetidas montagens de handler/cliente. A comparação em
lote usa uma obrigação com vários alvos; não afirma que planos por elemento já
agrupam chamadas. Sem cache, o remoto continuou mais caro que o oráculo local nas
amostras; o objetivo é responsabilidade de execução e transporte delimitado.

Para reproduzir, iniciar Toolbox isolada no ref registrado com extras
`api,storage,cache`, provider de artefatos filesystem e Redis temporário; então,
no checkout do Core:

```bash
uv run python -m scripts.bench.text_normalization \
  --base-url http://127.0.0.1:8002 --api-key normalization-benchmark \
  --legacy-ref add11c46db9ab8e28eaeb54b4319c3fcf6509392 \
  --server-pid <toolbox-pid> --storage-root <temporary-artifact-root> \
  --iterations 3 --delay-ms 5 --out /tmp/norm-qualification.json
```
