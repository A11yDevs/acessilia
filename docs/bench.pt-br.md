# Harness de benchmark

> English version: [English guide](bench.md)

`python -m scripts.bench` mede o harness de estrutura por página. Ele chama a
capacidade `document.structure.extract` da Toolbox, converte a resposta para o
documento canônico do benchmark e grava Markdown. Não executa o planner ou
executor do Core, enriquecimento visual ou matemático remoto, nem as exportações
finais do produto.
Trate tempos e pontuações como medidas deste harness, não do pipeline completo
do Core. Os scorecards de produto dos casos 036 e 006 continuam no Core; as
campanhas públicas e seus avaliadores oficiais ficam em `acessilia-benchmark`.

O downloader de Dr.DocBench, o empacotador de submissão e os jobs Slurm já
existentes no Core são mantidos como ferramentas de compatibilidade para
execuções locais de estrutura. Não os amplie para orquestrar campanhas ou serem
dono de resultados oficiais; o fluxo público está sendo consolidado em
`acessilia-benchmark`.

## Onde fica cada parte

| Parte | Local | Específica do dataset? |
|---|---|---|
| Métricas (distância de edição de texto, ordem de leitura, TEDS, CDM, overall) | `docstruct.evaluation.metrics` | não |
| Pontuação de página (pareia tabelas e fórmulas pela ordem) | `docstruct.evaluation.markdown` | não |
| Gate local de melhoria tune/holdout | `docstruct.evaluation.holdout` | não |
| Documento canônico → markdown de benchmark | `docstruct.export.markdown` | não |
| Payload da Toolbox → documento canônico | `scripts/bench/core.py` | não |
| Download, layout das páginas, formato de submissão | `scripts/bench/datasets/<nome>.py` | sim |
| Campanhas públicas, avaliadores oficiais, comparações de campanha e workflows Slurm | `acessilia-benchmark` | sim |

As métricas do Core são aproximações locais para acompanhar mudanças entre
execuções. Para reportar um número publicamente, use o avaliador oficial do
benchmark. O `scripts.bench compare` local serve apenas ao gate de melhoria
tune/holdout do harness de estrutura do Core. Não é uma checagem de paridade,
comparação de campanha pública nem veredito oficial; comparações de campanha
ficam no `acessilia-benchmark`.

## Fluxo

A Toolbox precisa estar acessível. O harness configura os próprios clientes do
SDK (`scripts/bench/toolbox.py`), a partir do ambiente ou do `.env`, com os
mesmos nomes de variáveis e padrões do core: `TOOLBOX_BASE_URLS` (ou então
`TOOLBOX_BASE_URL`), `TOOLBOX_API_KEY`, `TOOLBOX_TIMEOUT_SECONDS`,
`TOOLBOX_RETRIES`, `TOOLBOX_RETRY_BACKOFF_SECONDS` e `TOOLBOX_PROVIDER`.

```bash
# 1. Materializa um split localmente: var/bench/<dataset>/<split>/data
uv run python -m scripts.bench download --dataset drdocbench --split dev --limit 100

# 2. Roda a extração de estrutura e grava predições e run-manifest.json
uv run python -m scripts.bench run --dataset drdocbench --split dev --run baseline

# 3. Pontua: report.json, pages.jsonl e drilldown.csv (piores páginas primeiro) no diretório da execução
uv run python -m scripts.bench score --dataset drdocbench --split dev --run baseline

# 4. Depois de uma mudança, roda e pontua de novo com outro nome e compara
uv run python -m scripts.bench compare var/bench/drdocbench/dev/baseline var/bench/drdocbench/dev/candidate

# 5. Empacota uma execução para o benchmark (Dr.DocBench: submission.zip do EvalAI)
uv run python -m scripts.bench submit --dataset drdocbench --split test --run baseline
```

`--root` aponta para uma árvore local existente em vez de `var/bench/.../data`;
`run` também aceita `--sample N`, `--item <id>`, `--provider` e `--save-raw`.
Cada execução grava `run-manifest.json` com hashes das imagens selecionadas e
referências, identidade do Core e dos pacotes, configuração efetiva da Toolbox,
hashes das saídas, estado por página e tempos observados. O manifesto não grava
a chave de API nem o conteúdo dos documentos. O payload opcional `.provider.json`
é conteúdo e fica nos artefatos da execução em `BENCH_VAR`.

Predições e payloads brutos opcionais podem conter conteúdo documental. Restrinja
o acesso a `BENCH_VAR` e aplique a política de retenção do dataset; o harness não
expira nem exclui artefatos automaticamente. Mantenha `--save-raw` desativado
salvo quando a resposta bruta do provider for necessária.

Se a árvore materializada não for, ela própria, a raiz de um checkout Git,
informe o commit fixado de origem com `run --dataset-revision`. O valor deve
ser um SHA completo de 40 ou 64 caracteres; nomes mutáveis como `main` são
rejeitados. Se a revisão não estiver disponível, o manifesto registra a ausência
e `compare` rejeita um veredito aceito; os hashes identificam os bytes locais
exatos, mas não a release de origem. O protocolo registra o tipo de mídia e o
tamanho da imagem. Declara que o Core não aplica recorte nem transformação; transformações
internas da Toolbox ficam marcadas como não observadas.

Uma nova `run` substitui as predições e registra a seleção em `pages.txt` para
compatibilidade. `score` pontua a seleção do manifesto, então uma execução com
`--sample` não é pontuada contra o split inteiro. `score` sai com 1 quando
nenhuma página tem ground truth (o split `test`, por exemplo). `--resume` exige
os mesmos dataset, hashes de entrada e referência, identidade do código,
software, hardware e configuração efetiva da execução salva. Ele verifica os
hashes das saídas antes de reutilizar uma página concluída. O manifesto mantém
um hash do caminho de cada endpoint. Se a nova resposta trouxer capability,
provider ou versões de provider/modelo conflitantes com as páginas concluídas,
a página falha antes de gravar a predição. Manifestos antigos sem os hashes
dos caminhos ainda podem ser pontuados para diagnóstico. O gate exige esses
hashes e consistência da proveniência reportada. Arquivos Markdown sem
manifesto continuam como `legacy_unverified`.

`run`, `score` e `submit` usam um bloqueio exclusivo por diretório de rodada. `compare`
bloqueia os dois diretórios enquanto verifica os artefatos e grava o relatório.
Se outro processo estiver com um dos bloqueios necessários, o comando sai com
código 1. Repita após o fim do outro processo.

O manifesto registra a duração observada pelo chamador na chamada à Toolbox,
o tempo da checagem de integridade da entrada depois da chamada e o tempo de
parede da página, incluindo conversão canônica e gravação dos artefatos. A
resposta da Toolbox não expõe tentativas/retries reais, tempo de fila, tempo
de consulta ou política efetiva de cache. Quando a
resposta inclui proveniência, cada chamada registra à parte as versões do
provider e dos modelos, a duração informada e o acerto de cache. Num acerto,
a duração informada pertence ao resultado armazenado.

A pontuação calcula duas distâncias de Levenshtein por página. Sem o `rapidfuzz`
(instalado pelo extra `dev`), o docstruct usa Python puro, que leva cerca de
20 s para uma página de 3.000 caracteres.

`report.json` registra cobertura esperada, executada, falha e pontuável para
cada métrica local. `compare` aplica o gate de melhoria de
`docstruct.evaluation.holdout`: o split
é por documento (1/3 no holdout), e um candidato só é aceito se ganhar no tune,
não perder no holdout e nenhuma métrica cair além da tolerância. Sai com 1
quando o candidato é rejeitado, inclusive quando um dos subconjuntos não tem
páginas pontuáveis (amostra pequena demais) e quando uma métrica pontuada na
base não tem nenhum valor no candidato (por exemplo, ele parou de emitir
tabelas): sem isso a métrica sairia da média e contaria como ganho. Valores que
não podem ser calculados saem como `null`.

O avaliador local v2 pareia tabelas e fórmulas display por ordem de aparição.
Cada elemento sem par vale zero, inclusive quando a previsão omite só parte
da referência. O denominador da página conta pares válidos e elementos sem
par. Um componente ausente nos dois lados fica sem nota. O TEDS local ignora
a mesclagem de células e o CDM local compara multiconjuntos de tokens. Para
usar o avaliador v2, repontue as duas rodadas offline. O gate exige o
protocolo `toolbox-structure@2`, que desativa o enriquecimento remoto de
fórmulas.

O resultado fica em `comparison.json` e registra se a compatibilidade
permitiu aplicar o gate de melhoria. `CDM` é apenas diagnóstico e não participa deste
gate. A comparação é rejeitada se faltar manifesto concluído e com artefatos
verificados, ou se divergirem revisão do dataset, seleção, referências,
unidade, protocolo de pontuação ou cobertura por métrica. O relatório também
lista software, hardware e configuração efetiva para explicitar mudanças
intencionais do runtime. IDs de item/página duplicados invalidam a comparação,
em vez de sobrescrever uma linha.

O manifesto reutiliza o contrato de identidade e relatório definido para a
#370. Este protocolo de estrutura não chama a pipeline de processamento do
Core, então não aplica `processing_cache_configuration()`. Uma medição futura da
pipeline completa deve reutilizar essa função para as configurações de
processamento do Core.

Os limites medidos hoje e os contratos propostos para etapas estão em
[`benchmarks/regions.pt-br.md`](benchmarks/regions.pt-br.md); as
responsabilidades e cobertura estão em
[`benchmarks/coverage-map.pt-br.md`](benchmarks/coverage-map.pt-br.md). A
captura futura de etapas depende da modularização do Orchestrator na #381. Esta
issue não adiciona importação de `scripts/bench` no runtime nem cria outro
runner público de benchmark.

## Adaptador de compatibilidade e migração

`backend/tools/toolbox_client.py` é uma factory temporária baseada em settings,
mantida para o adaptador `acessilia-benchmark` fixado em `810c748`. Ela não é uma
API pública do Core. Código novo do Core deve usar
`backend.core.toolbox.toolbox_client.make_toolbox_client` e passar um
`ToolboxConfig` explícito.

A remoção dessa compatibilidade depende de duas migrações:

- O modo `structure` do adaptador deve usar diretamente os clientes do SDK.
  Isso acompanha a #402, cujo critério de aceite exige que os scripts de
  benchmark não importem `backend.tools.toolbox_*`.
- O modo `pipeline` do adaptador precisa de uma API pública estável do Core. A
  ADR-0016 propõe o pacote separado `acessilia_core`; essa mudança é distinta da
  transferência do transporte da Toolbox para o SDK na #402.

A ADR-0018 continua proposta e trata do uso da API pública do SDK pelo próprio
Core; ela não define a API pública do Core necessária para o modo `pipeline`.
Enquanto o adaptador importar internos do Core, a exceção de dependência P3
continua sem resolução. O processo de ADR exige um registro aceito que informe
escopo, responsável e critério de saída da exceção. Mantenha P3 sem marcar até
que a exceção seja aceita ou esses imports sejam removidos.

Prefira pontuação/replay offline e jobs Slurm isolados. A execução atual é
serial (`worker_count=1`), mas isso não reserva capacidade em um gateway
compartilhado. Não direcione o harness a um gateway de produção compartilhado
antes de definir política de admissão, janela de execução e condição de parada.

## Em um cluster Slurm

`scripts/bench/slurm/` tem três jobs; cada um carrega o `env.sh`, que exige `WS`
(o workspace com `repos/acessilia`, `repos/acessilia-toolbox` e `data/`) e mantém
todos os caches e execuções dentro dele (`BENCH_VAR=$WS/bench`). Submeta a partir
de `$WS` e passe a partição com `-p`.
Esses jobs existentes são ferramentas de compatibilidade para execuções locais
isoladas; execução de campanhas públicas e relatórios oficiais ficam no
`acessilia-benchmark`.

| Job | O quê |
|---|---|
| `setup.sbatch` | venvs e modelos da Toolbox, do docling-serve e do MinerU, venv deste repositório; opcionalmente um snapshot de dataset do HuggingFace (`HF_DATASET`, `HF_PATTERN`, `DATASET_DIR`) |
| `bench.sbatch` | sobe o provider (`PROVIDER=docling\|mineru`) e a Toolbox dentro do job, em portas derivadas do id do job, e roda `scripts.bench run --resume` e `score` |
| `eval_official.sbatch` | monta a árvore de janelas de uma página do avaliador oficial para cada execução em `RUNS` e pontua com `$WS/repos/DrDocBench` (`CONFIG` é a configuração do avaliador; `cdm_env.sh` para o CDM) |

A porta local da Toolbox pode mudar entre jobs. Retomar o mesmo `RUN` ainda
exige o mesmo commit da Toolbox, as mesmas alterações rastreadas, a mesma
configuração do provider e os demais campos de identidade da rodada. Para um
dataset materializado, defina `DATASET_REVISION` com o SHA completo do commit de
origem para que o job registre a revisão usada na comparação.

```bash
cd $WS
sbatch -p <partition> -c 8 --mem 32G --time 04:00:00 --job-name mineru-dev \
  --export=ALL,WS=$PWD,DATASET=drdocbench,ROOT=$PWD/data/drdocbench/dev,RUN=mineru,PROVIDER=mineru,DATASET_REVISION=$DATASET_REVISION \
  repos/acessilia/scripts/bench/slurm/bench.sbatch
```

## Acrescentando um dataset

Escreva `scripts/bench/datasets/<nome>.py` com uma classe que implemente
`scripts.bench.datasets.base.Dataset` e registre-a em
`scripts/bench/datasets/__init__.py`:

- `download(split, root, limit)` grava o split em `root`;
- `pages(root)` devolve um `BenchPage` por página (imagem, caminho do markdown
  de ground truth, metadados de que a submissão precisa);
- `build_submission(pages, predictions, out)` empacota uma execução.

Predições e pontuação são compartilhadas: quando o ground truth do dataset não
for markdown, converta-o para markdown no `download`, para que o `score` se
aplique sem mudanças.

## Caso de referência de matemática

`python -m scripts.bench.math_case` pontua um documento inteiro em vez de um
dataset de páginas: `velocidade-instantanea.pdf` (id `036` no
[acessilia-dataset](https://github.com/A11yDevs/acessilia-dataset), em
`input/math-reference/`), uma apostila de cálculo de cinco páginas em pdfTeX,
com matemática inline e display, uma equação numerada e matemática nos
cabeçalhos de tabela. O ground truth lista o LaTeX esperado de cada fórmula
(`ground_truth.csv`) e as verificações de texto, estrutura e fala que as
fórmulas não cobrem (`expectations.json`).

```bash
# Processa o PDF no core e pontua (precisa do Toolbox e do provedor de modelo)
uv run python -m scripts.bench.math_case run --out var/bench/math-reference/<run>

# Pontua saídas que você já tem: o JSON do documento canônico e o TXT,
# opcionalmente o PDF/UA (precisa do pdftotext)
uv run python -m scripts.bench.math_case score --canonical doc.json --txt doc.txt --pdf-ua doc.pdf_ua.pdf
```

O clone do dataset é lido de `tests/dataset` ou de `ACESSILIA_TEST_DATASET_DIR`.
O placar (`scorecard.md`, `scorecard.json`) informa:

- fórmulas display, pareadas com o ground truth da mesma página: CDM, o recall
  dos tokens estruturais (`\frac`, `^`, `_`, `\lim`, `\mathbb`...), MathML, forma
  falada e de onde veio o LaTeX (`extractor`, `math.recognize`, `vision`). O
  recall estrutural é o número a acompanhar: uma fórmula achatada a partir da
  camada de texto do PDF mantém as letras, então sua CDM de saco de tokens
  continua alta, mas perde todos os tokens estruturais;
- expressões inline e cabeçalhos/células de tabela entregues como matemática;
- as verificações de texto, estrutura e fala, com cada falha listada.

Com `--pdf-ua` (e no `run`, a não ser com `--no-pdf-ua`), as verificações de texto rodam nas duas
saídas e entra a verificação de títulos auto-numerados; por isso o placar
começa pelas saídas que pontuou: compare dois placares só quando essa linha
for igual.

Uma PR que muda como matemática, reparo de texto ou estrutura chegam às saídas
cola o placar antes e depois na descrição. `tests/test_math_case_e2e.py`
(`-m e2e`) roda o caso e trava o que já passa.

### Paridade de uma mudança que não deve alterar a saída

O `compare` confere duas saídas do caso campo a campo, para uma refatoração
que precisa deixá-las como estavam (a paridade da cadeia de fórmula da
ADR-0017):

```bash
uv run python -m scripts.bench.math_case compare base/canonical.json candidate/canonical.json --out var/bench/math-reference/<comparacao>
```

Ele compara, de cada fórmula, o LaTeX, o MathML, a forma falada, o método de
reconhecimento, a concordância com a camada de texto, a camada de texto e o
número da equação; de cada bloco, tabelas incluídas, o texto e as expressões
inline; de cada tabela, a forma e as células; a estrutura dos blocos; e os
avisos técnicos. Sai com 1 quando há diferença.
Os relatórios JSON e Markdown identificam o gate de paridade. A comparação do
caso de slides 006 é apenas diagnóstica; não aceita nem rejeita candidatos
automaticamente.

O que um modelo de visão escreveu pode diferir entre duas execuções
quaisquer, então aparece à parte e não reprova a comparação:
- o LaTeX de uma fórmula que ele leu, e o que o core deriva desse LaTeX
  (MathML, forma falada, concordância, número da equação) só quando o próprio
  LaTeX difere;
- a descrição de uma imagem que a etapa de imagens marca como do modelo
  (`vision_description_complete`, `vision_confidence`);
- uma tabela que o agente de dados releu pela imagem (`table_review`).

Todo o resto conta, mesmo quando a resposta de um modelo de visão o causou: o
método de reconhecimento, um texto alternativo de fallback, a estrutura dos
blocos (uma fórmula que o modelo tomou por imagem) e os avisos técnicos.
Inspecione esses casos. Rode a base duas vezes para ver quanto varia sozinho.

O core e a Toolbox guardam resultados pelo hash da fonte, não pelo código que
os produziu, então cada execução precisa de uma fonte que nenhuma execução
viu: acrescente um comentário depois do `%%EOF` (um leitor de PDF o ignora). O
caso fica no branch `main` do acessilia-dataset (`input/math-reference/`);
aponte o `ACESSILIA_TEST_DATASET_DIR` para um checkout dele, porque um worktree
deste repositório não tem `tests/dataset`.

```bash
export ACESSILIA_TEST_DATASET_DIR=/caminho/do/acessilia-dataset   # no branch main
for run in base candidate; do
  cp "$ACESSILIA_TEST_DATASET_DIR/input/math-reference/velocidade-instantanea.pdf" "/tmp/036-$run.pdf"
  printf '%% %s %s\n' "$run" "$(date +%s)" >> "/tmp/036-$run.pdf"
done
# Num checkout de cada commit (git worktree add ../base <commit>):
uv run python -m scripts.bench.math_case run --pdf /tmp/036-base.pdf --out var/bench/math-reference/base
```

## Snapshot dos experimentos do Dr.DocBench

O código dos experimentos da shared task (variantes de fusão, jobs Slurm,
replay congelado) está preservado na tag `drbench-2026-snapshot`: o que cada
script fazia e para onde foi seu algoritmo está em
[CODE.pt-br.md](drbench/experiments/CODE.pt-br.md), e como rodá-lo no
[runbook](drbench/experiments/RUNBOOK.pt-br.md).
