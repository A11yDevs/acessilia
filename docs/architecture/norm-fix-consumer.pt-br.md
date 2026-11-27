# Consumidor remoto de normalização (#929)

Inglês, versão normativa: [English version](norm-fix-consumer.md).

O Core 0.3.30 usa o SDK 0.7.1 para executar `norm-fix` por
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
transporte público autenticado e valida observações. Só a Toolbox invoca o
algoritmo de normalização. `text.postprocess@1` permanece separado, com semântica
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
planos salvos. A granularidade existente é preservada: o detector atual emite uma
obrigação por elemento afetado. Uma obrigação com vários alvos usa lotes
delimitados; obrigações independentes não são unidas nem antecipadas. A
[#948](https://github.com/A11yDevs/acessilia/issues/948) avalia essa decisão restante
de planejamento/desempenho e a retirada da predição local.

## Vinculação, aceite atômico e recuperação

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

Três rodadas locais, com atraso sintético explícito de **5 ms por requisição**,
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
