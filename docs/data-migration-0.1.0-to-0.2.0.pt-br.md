# Migração dos dados do core: 0.1.0 para 0.2.0

Inglês: [English](data-migration-0.1.0-to-0.2.0.md).

## Contrato

`scripts/migrations/v0_1_0_to_v0_2_0.py` e o SQL versionado ao lado dele exportam
um novo conjunto de dados para execução. Usam apenas a biblioteca padrão do
Python 3.11+, permitindo execução na máquina do administrador sem instalar a
aplicação. Transfira os dois arquivos juntos para a plataforma.

A unidade de migração é um **download publicado e seus registros de suporte**:

- Preservar tokens emitidos nos últimos sete dias (168 horas em UTC), incluindo
  o instante exato do corte para manter o contrato do serviço de download.
  Conservar token, proprietário, ID da tarefa, nome, formatos e instante original
  da emissão. A migração **não** concede mais sete dias; a expiração normal da
  0.2.0 continua valendo após a inicialização.
- Copiar somente arquivos publicados por tokens válidos, incluindo PDF comum
  antigo e ZIP. A data de modificação do arquivo não substitui a validade do
  token. Se tokens válidos e expirados compartilham um diretório, arquivos
  exclusivos dos expirados ficam de fora. Arquivos compartilhados ainda
  necessários a um token válido são preservados.
- Preservar o histórico da mesma janela de sete dias, além de registros mais
  antigos referenciados por um download válido. Preservar o OCR dessas tarefas.
  Os registros de suporte acompanham a retenção do ativo, evitando referências
  quebradas quando o processamento começou antes da emissão do download.
- Histórico recente não terminado e sem download válido é exportado como `error`,
  com `Stale: process interrupted` e o instante da migração como conclusão.
  Somente o destino é corrigido; simulação e aplicação preservam a origem de
  rollback e não retomam jobs. `rows.conversoes.interrupted` informa a contagem,
  inclusive na simulação. Criação e corte dos sete dias continuam inalterados.
- Excluir tokens expirados, histórico/OCR antigo sem vínculo, resultados sem
  referência, caches, logs, uploads e temporários de trabalho. Reconstruir caches
  na nova versão. Não inventar credenciais persistentes de jobs nem retomar os
  jobs que existiam somente na memória da 0.1.0.

O adaptador reconhece o esquema do core no commit de produção
`535b22e9b07a99b3090e2fcfc6862299de2b5c69` e tabelas de tokens mais antigas sem
`formats`, `task_id` ou `owner`. Tabelas ou colunas desconhecidas interrompem a
migração, evitando descarte silencioso. Novas estruturas exigem outro adaptador
versionado; não altere uma migração já implantada para reinterpretar dados antigos.

## Pré-requisitos

1. Desabilitar o atualizador e mantê-lo assim durante a migração.
2. Preservar a imagem antiga, Compose, ambiente e configuração da automação.
3. Interromper novas submissões por **todas** as interfaces, inclusive Telegram;
   aguardar a fila e os jobs em execução, depois parar o container antigo. Fila
   zerada no health, isoladamente, não comprova ausência de processamento ativo.
4. Fazer um backup completo e consistente de `var` com a aplicação parada.
   A migração seletiva não substitui esse backup para rollback.
5. Executar simulação e aplicação sobre a origem parada ou uma cópia consistente
   offline. O SQLite é lido pela API de backup, incluindo transações confirmadas
   no WAL; copiar somente um `.db` em uso não é suficiente.

Histórico não terminado referenciado por download válido, datas futuras, arquivos
publicados ausentes, caminhos inseguros ou links simbólicos bloqueiam a migração.
Resolva inconsistências dos dados preservados numa cópia de trabalho separada,
mantendo o original para rollback. Alterações detectadas no banco ou nos arquivos
durante a cópia também impedem a publicação. Essas verificações não substituem
a interrupção de todos os escritores: a idade do registro não comprova que o job
parou; registros interrompidos recentes também exigem o pré-requisito offline.

Datas que não podem ser interpretadas são contadas em
`rows.<tabela>.invalid_timestamps` e excluídas quando não sustentam download válido.
Para tokens, vale a mesma comparação SQLite da aplicação: NULL, vazio ou valores
antigos inválidos que falham nesse predicado são descartados. Textos malformados
como `not-a-date` podem passar na comparação textual do SQLite; continuam
bloqueando a migração para evitar descartar silenciosamente um link acessível.
Histórico sem referência e com data inválida é excluído; histórico inválido que
sustenta um token preservado deve ser investigado numa cópia de trabalho.

## Procedimento na MV1

Os comandos abaixo são executados como root na MV1. Guarde os dois arquivos da
migração em `/opt/acessilia/migrations/`. Os dados atuais continuam em
`/opt/acessilia/production/var`; os novos ficarão em `/opt/acessilia/core/var`.
Crie somente o diretório pai: o destino `var` **não pode existir**.

```bash
install -d -m 700 /opt/acessilia/core
chown --reference=/opt/acessilia/production /opt/acessilia/core

python3 /opt/acessilia/migrations/v0_1_0_to_v0_2_0.py \
  --source-var /opt/acessilia/production/var \
  --destination-var /opt/acessilia/core/var \
  --dry-run
```

Revise no JSON as contagens de registros preservados/excluídos, arquivos e bytes
a copiar. O resumo omite tokens de acesso, proprietários e nomes de documentos.
A simulação não cria o destino nem altera os registros da origem. Cada execução
calcula um único instante de corte; a simulação informa, sem congelar a validade
para execuções futuras.

Aplique somente depois de cumprir os pré-requisitos acima:

```bash
python3 /opt/acessilia/migrations/v0_1_0_to_v0_2_0.py \
  --source-var /opt/acessilia/production/var \
  --destination-var /opt/acessilia/core/var \
  --apply

python3 /opt/acessilia/migrations/v0_1_0_to_v0_2_0.py \
  --destination-var /opt/acessilia/core/var \
  --verify

chown -R --reference=/opt/acessilia/production/var /opt/acessilia/core/var
```

A propriedade é herdada da instalação existente, sem pressupor usuário ou grupo
chamado `acessilia`. Confira se o UID/GID efetivo do container consegue ler e
escrever no novo volume; se mudar o usuário de execução, adapte a propriedade
ao UID/GID planejado antes de iniciar.

As duas versões montam `var` do host em `/app/var`, a raiz de execução padrão.
Assim, mudar o diretório no host preserva os caminhos dentro do container. Para
outra organização, configure `--source-runtime-var` e
`--destination-runtime-var`: são caminhos **do ambiente de execução da aplicação**,
não necessariamente do host. Referências relativas `var/...` e caminhos absolutos
da origem no host também são adaptados.

A aplicação cria banco e arquivos novos num diretório temporário privado ao lado
do destino, confere hashes e publica por renomeação. Um destino existente nunca
é sobrescrito; repetir a execução falha de forma segura. Falhas comuns removem
o diretório temporário; após encerramento forçado, um `.var.migration-*` não
publicado pode exigir limpeza pelo administrador. Não o ative.

O banco novo registra o ID da migração, o instante de referência em UTC e o corte.
`migration-0.1.0-to-0.2.0.json` registra checksums dos arquivos e do banco. Ele é
privado (0600, diretórios 0700) e contém caminhos internos; não o publique.
`--verify` é uma auditoria **antes de iniciar a aplicação**: escritas posteriores
podem mudar legitimamente o checksum do banco. Ela verifica consistência local,
sem testar o roteamento do proxy.

## Apontar Compose e atualizador para o novo diretório

Mantenha o timer desabilitado e o container antigo parado. Na raiz do checkout
0.2.0 aprovado, execute como root para instalar o Compose e os scripts novos e
copiar o ambiente original, preservando a origem para rollback:

```bash
install -m 600 docker-compose.production.yml /opt/acessilia/core/docker-compose.production.yml
install -m 600 /opt/acessilia/production/.env /opt/acessilia/core/.env
chown --reference=/opt/acessilia/production /opt/acessilia/core/docker-compose.production.yml
chown --reference=/opt/acessilia/production/.env /opt/acessilia/core/.env
install -d -m 755 /opt/acessilia/scripts
install -m 755 scripts/production-update.sh /opt/acessilia/scripts/production-update.sh
install -m 755 scripts/staging-update.sh /opt/acessilia/scripts/staging-update.sh
```

Revise `/opt/acessilia/core/.env` com o exemplo da 0.2.0, configure a Toolbox de
produção e `AI_CLIENT=toolbox` e mantenha cada variável declarada uma única vez.
Defina `COMPOSE_PROJECT_NAME=production` para conservar a identidade atual do
projeto na MV1; em outras plataformas, use o nome original registrado. Para a
política padrão de produção, use `TRACK_BRANCH=main` e `TRACK_TAG=main`. Remova
do ambiente copiado sobrescritas antigas de diretório de implantação/cache/status.
Selecione no Compose novo o digest da imagem 0.2.0 aprovada antes de iniciar;
`main` não deve selecionar acidentalmente a versão antiga antes da promoção.

Como o usuário do timer existente de produção (`acessilia` na MV1), numa sessão
com acesso ao barramento systemd desse usuário, crie esta sobrescrita:

```bash
mkdir -p ~/.config/systemd/user/acessilia-production-update.service.d
cat > ~/.config/systemd/user/acessilia-production-update.service.d/migrated-core.conf <<'UNIT'
[Service]
WorkingDirectory=/opt/acessilia/core
ExecStart=
ExecStart=/opt/acessilia/scripts/production-update.sh
Environment=PRODUCTION_DIR=/opt/acessilia/core
Environment=STAGING_UPDATE_CACHE=/opt/acessilia/core/var/data/.last_production_sha
Environment=STAGING_STATUS_FILE=/opt/acessilia/core/var/data/production-status.json
UNIT
systemctl --user daemon-reload
systemctl --user show acessilia-production-update.service -p DropInPaths
```

Isso altera o diretório de trabalho e os caminhos de implantação/cache/status
do atualizador. Atualizações futuras usarão o `.env` novo e `core/var`, em vez
do antigo `production/var`. Preserve a sobrescrita nos backups da configuração.

De volta ao root, inicie somente o core aprovado a partir do diretório novo.
O container original pertence ao projeto `production`; manter esse nome permite
ao Compose recriá-lo com o novo volume, sem criar outro projeto concorrente:

```bash
cd /opt/acessilia/core
docker compose -p production --env-file .env -f docker-compose.production.yml config --quiet
docker compose -p production --env-file .env -f docker-compose.production.yml up -d --no-deps acessilia
docker inspect acessilia-production --format '{{.Config.Image}}'
docker inspect acessilia-production --format '{{range .Mounts}}{{println .Source "->" .Destination}}{{end}}'
```

Confira se a imagem é a aprovada e o volume corresponde a
`/opt/acessilia/core/var -> /app/var` antes de aceitar tráfego. Mantenha o timer
desabilitado durante o aceite e enquanto a imagem estiver fixada por digest.
Se adotar atualização automática da `main` posteriormente, restaure a
interpolação da imagem e reabilite `acessilia-production-update.timer` como seu
usuário somente após o aceite; mantenha a sobrescrita do diretório.

## Aceite e rollback

Monte `/opt/acessilia/core/var` em `/app/var` no core 0.2.0 e configure seu ambiente
separadamente da Toolbox. Preserve o endereço público e as rotas de download dos
links já emitidos. Teste páginas de downloads existentes e a entrega dos arquivos,
inclusive PDF comum se houver, e confira a rejeição de tokens expirados. Evite
expor os tokens nos logs dos testes.

Os testes cobrem o esquema antigo, corte da expiração, mudança de caminhos,
falhas, diretórios compartilhados e downloads reais pela API da 0.2.0:

```bash
python -m pytest -q tests/test_data_migration.py \
  tests/test_download_token_service.py tests/test_cleanup_service.py
```

Execute no container de testes do projeto antes do merge, conforme a constituição.

Para rollback, pare a 0.2.0 e restaure imagem, configuração e dados originais da
0.1.0. Não aponte a 0.1.0 para o banco migrado. O script não reverte escritas novas
da 0.2.0; preserve-as separadamente antes do rollback. Restaure configuração e
scripts originais do atualizador (inclusive substituindo ou removendo
`migrated-core.conf`) e recarregue o systemd do usuário antes de retomar qualquer
timer, para que a automação do rollback volte a usar `production/var`.
A instalação antiga e os
backups completos permanecem intactos para recuperação; o uso total de disco só
diminui quando os administradores os retirarem conforme a política de backup.
Esta migração não faz limpeza destrutiva da origem nem dos backups.
