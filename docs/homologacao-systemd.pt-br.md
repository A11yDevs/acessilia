# Ambiente de homologação com systemd timer

Você também pode ler esta documentação em **inglês**: [English](homologacao-systemd.md)

O servidor de homologação roda a partir de um **clone deste repositório**. O clone guarda os
scripts, o `docker-compose.staging.yml`, o `.env` e o `var/`; os containers rodam as imagens
que o CI publica no GHCR. Um **user timer do systemd** consulta a branch rastreada a cada
5 minutos pela API do GitHub e atualiza o container quando a imagem de um commit novo está
publicada.

Tudo passa pelo `scripts/ops.sh`:

| Comando | O que faz |
|---------|-----------|
| `./scripts/ops.sh auto-update setup` | Sobe a stack e instala o timer |
| `./scripts/ops.sh auto-update status` | Branch do clone, branch rastreada, timer, última checagem, health, execuções recentes |
| `./scripts/ops.sh auto-update check` | Verifica o timer (instalado para este clone, habilitado, timer antigo removido), as execuções recentes (a última deu certo, checagem recente, último commit no ar) e a implantação (branch, container, imagem, health); termina com status 1 se houver problema |
| `./scripts/ops.sh auto-update start` | Atualiza agora (o que o timer executa) |
| `./scripts/ops.sh track [<branch>]` | Passa a seguir uma branch: `git pull` do clone e `TRACK_BRANCH` no `.env`, e atualiza; sem branch, faz pull da já rastreada |
| `./scripts/ops.sh auto-update migrate <dir>` | Traz para o clone uma instalação feita pelo antigo `setup-homologacao.sh` |

## Visão geral

```
A cada 5 minutos → acessilia-staging-update.timer (user)
                    ↓
<clone>/scripts/ops.sh auto-update start
                    ↓
staging-update.sh: API do GitHub → SHA do último commit da branch rastreada
                    ↓
SHA mudou e a imagem sha-<7> está no GHCR? → docker compose pull + up -d
                    ↓
container reiniciado 🚀
```

A branch rastreada é a `develop`, ou o `TRACK_BRANCH` do `.env` durante o ciclo de BHS
(`release/x.y.z`). A branch do clone e o `TRACK_BRANCH` sempre mudam juntos pelo
`ops.sh track`: os scripts e o compose vêm do clone, a imagem vem do `TRACK_BRANCH`. O
`auto-update status` avisa quando os dois divergem.

## Pré-requisitos

- Docker e Docker Compose, `git`, `curl` e `jq` (`sudo apt install jq`)
- `docker login ghcr.io` com um token de escopo `read:packages` (crie em
  https://github.com/settings/tokens/new?scopes=read:packages)
- O usuário que roda o timer precisa, concedido uma vez por um administrador:
  - estar no **grupo `docker`** (`usermod -aG docker <usuário>`, depois login de novo): o
    `setup` e o `migrate` se recusam a rodar sem acesso ao daemon do Docker;
  - de **linger** (`loginctl enable-linger <usuário>`), para o timer continuar rodando após
    o logout: o `setup` avisa quando ele está desligado.

  O `ops.sh` nunca chama `sudo`; se algo precisar rodar como root, rode esse comando (ou o
  próprio `ops.sh`) como root.

  Uma sessão aberta com `su` não tem `XDG_RUNTIME_DIR`; o `ops.sh` então usa
  `/run/user/<uid>` sozinho. Quando nem isso existe (sem linger e sem login), o `setup` e o
  `migrate` param e avisam.

## Primeira instalação

```bash
git clone https://github.com/A11yDevs/acessilia.git
cd acessilia
cp .env.example .env              # preencha as credenciais (IA, Telegram, SMTP...)
./scripts/ops.sh auto-update setup
```

O `setup` grava `COMPOSE_PROJECT_NAME=acessilia-staging` no `.env`, para que os containers
pertençam ao mesmo projeto compose qualquer que seja o nome do diretório do clone; depois
sobe a stack e habilita o `acessilia-staging-update.timer`.

## Migrando de `/opt/acessilia/staging`

As instalações feitas pelo antigo `setup-homologacao.sh` copiavam os scripts para
`/opt/acessilia/scripts` e mantinham `.env` e `var/` em `/opt/acessilia/staging`. Para
trazer uma delas para um clone:

```bash
git clone -b release/0.2.0 https://github.com/A11yDevs/acessilia.git ~/acessilia
cd ~/acessilia
./scripts/ops.sh auto-update migrate /opt/acessilia/staging
```

O `migrate` primeiro confere tudo de que precisa: que consegue ler o `.env` antigo e todo o
`var/` (ele lista o que não consegue ler), que o clone não tem um `.env` diferente, que a
branch do `TRACK_BRANCH` pode ser usada e que o Docker e o systemd do usuário estão
acessíveis. Qualquer falha o faz parar antes de mudar qualquer coisa, e uma execução
interrompida depois pode simplesmente ser repetida. Em seguida desliga o timer antigo
`staging-update` (e para se não conseguir), copia o `.env` e o `var/` (parando o container
nesse meio-tempo), passa a homologação para o projeto compose próprio `acessilia-staging` —
substituindo o container antigo, cujos dados agora estão em `./var` —, faz checkout da branch
do `TRACK_BRANCH` e roda o `setup`. As instalações antigas deixavam a acessilia e o Toolbox
num mesmo projeto chamado `staging`; saindo dele, um `--remove-orphans` aqui não apaga mais
os containers do Toolbox. O
`/opt/acessilia/staging` não é alterado; apague-o quando a homologação estiver funcionando.

## Atualizando os scripts

O `ops.sh track` sem branch faz `git pull` da branch já rastreada e atualiza:

```bash
./scripts/ops.sh track
```

O `track` se recusa a rodar quando há alterações locais em arquivos versionados do clone,
para que o servidor nunca se afaste do repositório.

## Gerenciamento

```bash
./scripts/ops.sh auto-update status          # visão geral
./scripts/ops.sh auto-update check           # veredito sobre o timer e suas execuções
./scripts/ops.sh auto-update start           # atualiza agora
journalctl --user -u acessilia-staging-update.service -n 50 --no-pager
systemctl --user stop acessilia-staging-update.timer     # pausa as atualizações
systemctl --user start acessilia-staging-update.timer    # retoma
```

Para testar uma imagem construída localmente, pare o timer antes: senão a próxima
atualização puxa a imagem do GHCR por cima dela.

## Alerta de prontidão

`auto-update check` também consulta `GET /api/v1/ready`, que verifica todos os providers da Toolbox usados pela cadeia de extração. Uma falha é um problema, então o comando sai com status 1. Aponte o monitor existente ou um cron/timer systemd para ele, por exemplo:

```bash
cd /caminho/para/acessilia
./scripts/ops.sh auto-update check >/var/log/acessilia-readiness.log 2>&1 \
  || logger -t acessilia "staging não está pronto; veja /var/log/acessilia-readiness.log"
```

Um monitor que só deve acompanhar a prontidão pode usar `curl -fsS http://localhost:8000/api/v1/ready`; o endpoint responde 503 quando um provider da cadeia está fora. O check permite 30 s para o `/ready` porque a rota consulta os providers em sequência (3 s cada) e pode fazer failover entre endpoints da Toolbox; um limite de 5 s alertaria com a aplicação ainda pronta. Aumente `OPS_READY_TIMEOUT` quando a instalação tiver mais endpoints do que esse orçamento cobre.

Para testar o alerta com o `FUSION_MODE=dual` da homologação, em uma instância de teste defina `FUSION_SECONDARY_PROVIDER` com um id inválido, recrie o container (veja [Alterar um limite](#alterar-um-limite)) e rode o comando: ele deve reportar `readiness endpoint does not answer or reports unavailable` e sair com 1. Restaure o valor depois. Invalidar o `TOOLBOX_PROVIDER` exercita do mesmo jeito o provider primário, que é consultado nos dois modos.

## Limites de processamento e modo de fusão

O `MAX_PAGES` e o `FUSION_MODE` efetivos são os valores dentro do container em execução, não os padrões do `.env.example`. `auto-update status` mostra os dois; registre-os com a instalação:

```bash
docker exec acessilia-staging printenv MAX_PAGES FUSION_MODE
```

### Alterar um limite

O container só lê o `.env` quando é criado (`env_file` no `docker-compose.staging.yml`), então `docker restart` mantém os valores antigos. Edite o `.env` do clone e recrie o container:

```bash
cd /caminho/para/acessilia            # o clone: docker-compose.staging.yml e .env
cp .env ".env.bak-$(date +%F)"
sed -i 's/^MAX_PAGES=.*/MAX_PAGES=50/' .env
grep -q '^FUSION_MODE=' .env && sed -i 's/^FUSION_MODE=.*/FUSION_MODE=dual/' .env \
  || echo 'FUSION_MODE=dual' >> .env
grep -nE '^(MAX_PAGES|FUSION_MODE|FUSION_SECONDARY_PROVIDER)=' .env   # uma linha de cada
docker compose -f docker-compose.staging.yml up -d --force-recreate acessilia
docker exec acessilia-staging printenv MAX_PAGES FUSION_MODE
./scripts/ops.sh auto-update check
```

Rode a partir do clone: o `.env` define `COMPOSE_PROJECT_NAME=acessilia-staging`, e o compose só o lê no diretório do projeto. Quando uma variável aparece duas vezes no `.env`, vale a última linha. Recriar o container interrompe o job em andamento, que é retomado do último checkpoint; quando der, espere a fila esvaziar. O timer de atualização roda `docker compose up -d` com o mesmo `.env`, então mantém a alteração.

- **Decisão do preflight:** a checagem antecipada recusa apenas PDF cuja contagem veio do `pymupdf` (`page_count_source == "pymupdf"`). Sem contagem confiável — inspeção falhou, varredura de content stream, formato não-PDF — recusar antes da extração rejeitaria documentos digitalizados legítimos, então o limite vale de forma autoritativa depois da extração (`_check_page_limit` em `libs/core/src/acessilia_core/pipeline/preflight.py`). Não há teto separado para extração dual: o mesmo limite vale para o manifesto extraído e os timeouts dos providers limitam o trabalho remoto.
- **Decisão do limite de páginas:** a homologação usa `MAX_PAGES=50`, o padrão do `.env.example`. Em 2026-11-18 o container tinha `MAX_PAGES=2000`. Um documento desse tamanho passa pela checagem antecipada e, no modo dual, ocupa os dois providers até o prazo da extração (`TOOLBOX_EXTRACTION_TIMEOUT_SECONDS`, 1500 s): a falha de 30/10, com 201 páginas. Aumente o limite só depois de medir, no modo dual, quantas páginas uma extração completa dentro do prazo com folga.
- **Decisão do modo de fusão:** a homologação usa `FUSION_MODE=dual` (2026-11-18, no lugar de `single`). A qualidade por adjudicação entre os dois providers é uma hipótese de pesquisa em avaliação, então a homologação roda a fusão. O `/ready` passa a depender também do MinerU: uma queda dele falha a prontidão e dispara o alerta acima. Os jobs continuam rodando, porque uma extração cujo secundário falha degrada para o primário (`fusion.status = "degraded"`) e perde só a adjudicação daquele documento; um secundário que trava degrada do mesmo jeito quando o primário está completo (#603). Monitore os dois providers. Esta é uma decisão do ambiente de homologação, não um padrão do produto.

## Solução de problemas

| Sintoma | Causa | Solução |
|---------|-------|---------|
| `pull access denied` | Token GHCR expirado | `echo <token> \| docker login ghcr.io -u <user> --password-stdin` |
| `jq: command not found` | `jq` não instalado | `sudo apt install jq` |
| Docker dá `permission denied` | Usuário fora do grupo `docker` | logout e login depois do `setup` |
| Timer não roda após logout | Linger desabilitado | `sudo loginctl enable-linger $USER` |
| `image sha-xxxxxxx not yet published` | O CI ainda está construindo o commit | aguarde a próxima checagem |
| API falha (fallback ativado) | API do GitHub indisponível | o script cai num `docker pull` direto |
| `acessilia-staging belongs to compose project '…' (dir)` | Outra instalação é dona do container | `./scripts/ops.sh auto-update migrate <dir>` |
