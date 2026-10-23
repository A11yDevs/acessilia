# Relatório de consistência homologação × código

Você também pode ler esta documentação em **inglês**: [English](staging_consistency.md)

Data da captura: 2026-10-14. Host: `proj028-vm3@200.137.215.135` (homologação).
Todas as sondagens em homologação registradas aqui foram somente leitura.

## O que foi comparado

| Artefato | Origem |
|---|---|
| HEAD de `develop` | `A11yDevs/acessilia` @ checkout local |
| Imagem do core em execução | `/api/v1/health` em `localhost:8000` (dentro do host) |
| Imagem da Toolbox em execução | `/v1/health`, `/v1/capabilities`, `/v1/providers` em `localhost:8002` |
| Configuração de homologação | `/opt/acessilia/staging/.env` (apenas chaves, valores omitidos) |
| Controle de atualização | `/opt/acessilia/staging/var/data/staging-status.json` |

## Achados

### S1 — O core em execução não reporta identidade de build (alto)

```json
{"status":"ok", ..., "git_commit":"", "image_tag":"", "image_digest":"",
 "container_id":"110b236abfc3", "ghcr_latest_sha":"", "last_check":"2026-10-14T11:47:21Z",
 "last_update":"", "update_available":false, "up_to_date":false}
```

`git_commit`, `image_tag` e `image_digest` estão todos vazios, então **não há como
provar qual commit está rodando** em homologação. Todo o propósito dos campos de build
de `/api/v1/health` e do trabalho de `fix/health-ghcr-digest` fica anulado na prática.

Causa: a imagem de homologação é construída pelo caminho disparado por tag, que nunca
passa os build args que `infra/Dockerfile` declara:

- `infra/Dockerfile` (linhas 74-80) declara `ARG GIT_COMMIT`, `ARG IMAGE_TAG` e
  `ARG IMAGE_DIGEST`, exportados como `ENV`.
- `.github/workflows/delivery.yml` passa `GIT_COMMIT` e `IMAGE_TAG` **apenas** para o
  build de verificação; o passo de *publish* (o que produz as tags que a homologação
  puxa) não passa `build-args` nenhum.
- `.github/workflows/release.yml` também não passa `build-args`, então as imagens de
  release são idênticas nesse aspecto.

### S2 — `update_available` / `up_to_date` nunca podem virar verdadeiros (médio)

O `staging-status.json` no host mostra `running_digest` e `latest_digest` como strings
vazias:

```json
{"latest_sha": "e08e2b4e...", "running_sha": "", "last_check": "2026-10-14T11:47:21Z",
 "last_update": "", "latest_digest": "", "running_digest": ""}
```

`backend/api/routes/health.py` calcula
`update_available = bool(ghcr_latest and running_digest and ghcr_latest != running_digest)`.
Com `ghcr_latest` vazio a expressão é sempre falsa, logo `up_to_date` também é sempre
falso.

Causa: `scripts/staging-update.sh` só calcula os digests no caminho de *atualização*,
depois de detectar um commit novo. No caminho "nenhum commit novo" (linha ~162) ele
grava o status com digests vazios. Como a comparação de digest não funciona sem o lado
do GHCR ser buscado, a checagem é estruturalmente incapaz de reportar "atualizado".

Desdobramento: o `/health` agora também reporta `update_check_stale`, verdadeiro
quando `last_check` tem mais de três intervalos do timer (15 min) ou é ilegível, e
`up_to_date` fica falso enquanto isso valer. Ressalvas para consumidores:

- `up_to_date: false` não implica mais `update_available: true`: com o updater
  parado, ambos são falsos. Monitores que alertam só em `update_available` não
  disparam nesse caso; alerte também em `update_check_stale`.
- Detecta o updater que **parou** de checar, não o que checa mas **falha** (por
  exemplo, GHCR inacessível enquanto o timer continua gravando `last_check`).
- `last_check` é gravado com o relógio do host e comparado com o do container; um
  desvio acima de 15 min reporta stale falso.

### S3 — A imagem da Toolbox não reporta identidade de build (médio)

```json
{"status":"healthy","version":"0.1.0"}
```

`/v1/health` devolve apenas o `__version__` estático de
`src/acessilia_toolbox/__init__.py`. `GIT_COMMIT` e `IMAGE_TAG` **são** passados como
`ENV` pelo `Dockerfile` daquele repositório (linhas 13-15), mas nada os lê. O core pode
provar seu commit depois de S1; a Toolbox não consegue.

### S4 — O contrato de capacidades está quebrado entre o par implantado (alto, resolvido no código)

> **Superado no código.** A Toolbox A11yDevs/acessilia-toolbox#50 publica o
> provider `qwen3-vl-8b` para as três capacidades, e a A11yDevs/acessilia#144
> aponta os defaults do core para ele; o comando de reprodução abaixo agora
> informa `capability contract holds`. A homologação ainda roda uma imagem da
> Toolbox anterior ao #50, então o par implantado continua quebrado até essa
> imagem ser atualizada. O texto abaixo é o registro na data da captura.

Contra a Toolbox em execução (26 capacidades, 25 providers):

```
5 contract violation(s):
  - core consumes capability 'document.adjudicate.page'  but the Toolbox does not expose it
  - core consumes capability 'document.adjudicate.region' but the Toolbox does not expose it
  - core consumes capability 'document.ocr.page'          but the Toolbox does not expose it
  - core default TOOLBOX_ADJUDICATE_PROVIDER   -> provider 'qwen3-vl-judge'      not registered
  - core default TOOLBOX_PAGE_OCR_PROVIDER     -> provider 'qwen3-vl-page'       not registered
```

No momento da captura este bloco listava sete violações. As duas entradas de
orientação foram resolvidas apontando o cliente para `image.page.orient` /
`rapidocr-orient`, a capacidade e o provider que a Toolbox de fato expõe; os
números acima são os pós-correção, e o comando abaixo os reproduz.

Reproduza com:

```bash
python scripts/check_capability_contract.py --snapshot tests/fixtures/toolbox-contract.json
```

As três capacidades ausentes são os clientes da PR #125
(`libs/sdk/src/acessilia_sdk/toolbox/clients/page_ocr.py`,
`libs/sdk/src/acessilia_sdk/toolbox/clients/adjudicate.py`), que não têm
chamador de produção. O perfil de providers VLM que os serviria existe apenas como
`scripts/drbench/experiments/slurm/providers-config-vlm.yaml` dentro do repositório do
*core* (hoje `scripts/bench/slurm/providers-config-vlm.yaml`), nunca no catálogo da Toolbox de onde a imagem é construída.

### S5 — Homologação rastreia `develop`, mas o `.env` tem divergência por host (informativo)

Valores não secretos de `/opt/acessilia/staging/.env`:

```
TRACK_BRANCH=develop
SCRIPT_UPDATE_BRANCH=fix/health-ghcr-digest
PIPELINE_ENGINE=pddl
TOOLBOX_PROVIDER=docling
TOOLBOX_BASE_URL=https://www.acessilia3.inf.ufg.br/toolbox
STRUCTURER=toolbox        # declarado duas vezes no mesmo arquivo; a segunda vence
AI_CLIENT=openrouter
OPENROUTER_MODEL=qwen3-vl-8b
LOCALE=pt_BR
LOG_LEVEL=DEBUG
```

Duas observações:

- `STRUCTURER` aparece duas vezes. O valor efetivo é `toolbox`, correto para o pipeline
  PDDL, mas a duplicata é uma armadilha latente para quem editar o arquivo depois.
- `TOOLBOX_BASE_URL` aponta para a URL pública do proxy reverso
  `https://www.acessilia3.inf.ufg.br/toolbox`. Não é apenas um salto externo
  desnecessário — quebra a implantação neste ambiente; ver S6.

### S6 — A homologação não processa nenhum documento (crítico, resolvido)

Enviar um documento real para o core implantado falha imediatamente:

```json
{"task_id":"c55ed243","status":"error","progresso":0.3,
 "etapa_atual":"Falha no processamento",
 "erros":["Toolbox indisponivel em https://www.acessilia3.inf.ufg.br/toolbox:
           [Errno -3] Temporary failure in name resolution"]}
```

O `TOOLBOX_BASE_URL` do `.env` de homologação aponta para a URL pública da proxy
reversa enquanto a Toolbox roda no mesmo host. O host não resolve o próprio nome
público: `getent hosts www.acessilia3.inf.ufg.br` falha e não há entrada em
`/etc/hosts`, enquanto `http://localhost:8002/v1/health` responde `200`. Com
`PIPELINE_ENGINE=pddl` e `STRUCTURER=toolbox`, todo job começa com uma chamada à
Toolbox, então o pipeline aborta em 30% antes de produzir qualquer coisa.

O `docker-compose.staging.yml` agora declara o mesmo mapeamento
`host.docker.internal:host-gateway` e usa
`http://host.docker.internal:8002` como padrão de `TOOLBOX_BASE_URL`. O padrão é
um literal, não uma interpolação de `TOOLBOX_BASE_URL`: o `.env` de homologação
também é o `env_file`, então interpolar esse nome lia a URL pública obsoleta e o
padrão nunca se aplicava. A chave de sobrescrita é `STAGING_TOOLBOX_BASE_URL`,
para uma Toolbox que viva em outro lugar. O `tests/test_compose_config.py` fixa
os dois.

Vale notar que o `docker-compose.production.yml` **não** declara o mapeamento em
`develop` nem em `main`; ele existe apenas no branch não mergeado
`fix/v2-readiness` (PR #128). Nesse ponto, portanto, a homologação está à frente
da produção, e não correndo atrás dela.

## O que está consistente

- `PIPELINE_ENGINE=pddl`, batendo com o valor forçado no compose.
- `TOOLBOX_PROVIDER=docling` é um provider registrado na Toolbox.
- As capacidades da Toolbox que o core de fato alcança pelos caminhos suportados
  (`document.structure.extract`, `document.layout.analyze`, `document.ocr`,
  `math.recognize`, `math.convert`, `math.verbalize`, `pdf.split`, `pdf.render`,
  `media.inspect`, `artifact.store`, `artifact.retrieve`, `dataset.*`) existem todas.
- As seis capacidades da Toolbox sem cliente no core são uma decisão de produto, não uma
  falha de implantação; estão rastreadas em `docs/toolbox_capability_matrix.md`.

## Próximos passos

S1, S2 e S3 são reproduzidos e corrigidos pelo trabalho de consistência de homologação
(`fix/health-build-info`, `fix/staging-digest-status`,
`fix/toolbox-health-build-info`). S4 é o objeto da revisão de integração e está fixado
por `tests/test_toolbox_contract_drift.py`. S5 é documentado aqui; S6 resolve a URL da
Toolbox para o caso de mesmo host, e a decisão de produto restante é apenas se uma
Toolbox em outro host deve ser alcançável.
