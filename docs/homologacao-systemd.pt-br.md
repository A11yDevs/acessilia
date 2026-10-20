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
branch do `TRACK_BRANCH` pode ser usada e que o Docker está acessível. Qualquer falha o faz
parar antes de mudar qualquer coisa, e uma execução interrompida depois pode simplesmente ser
repetida. Em seguida copia o `.env` e o `var/`
(parando o container nesse meio-tempo), mantém o nome do projeto compose do container em
execução para que o compose o assuma em vez de colidir com ele, remove o timer antigo
`staging-update`, faz checkout da branch do `TRACK_BRANCH` e roda o `setup`. O
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
./scripts/ops.sh auto-update start           # atualiza agora
journalctl --user -u acessilia-staging-update.service -n 50 --no-pager
systemctl --user stop acessilia-staging-update.timer     # pausa as atualizações
systemctl --user start acessilia-staging-update.timer    # retoma
```

Para testar uma imagem construída localmente, pare o timer antes: senão a próxima
atualização puxa a imagem do GHCR por cima dela.

## Solução de problemas

| Sintoma | Causa | Solução |
|---------|-------|---------|
| `pull access denied` | Token GHCR expirado | `echo <token> \| docker login ghcr.io -u <user> --password-stdin` |
| `jq: command not found` | `jq` não instalado | `sudo apt install jq` |
| Docker dá `permission denied` | Usuário fora do grupo `docker` | logout e login depois do `setup` |
| Timer não roda após logout | Linger desabilitado | `sudo loginctl enable-linger $USER` |
| `image sha-xxxxxxx not yet published` | O CI ainda está construindo o commit | aguarde a próxima checagem |
| API falha (fallback ativado) | API do GitHub indisponível | o script cai num `docker pull` direto |
| `Container name already in use` | Outro projeto compose é dono do container | defina no `.env` o `COMPOSE_PROJECT_NAME` desse projeto (`docker inspect acessilia-staging --format '{{ index .Config.Labels "com.docker.compose.project" }}'`) ou use o `auto-update migrate` |
