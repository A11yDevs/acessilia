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

Histórico recente com jobs não terminados, datas inválidas/futuras, arquivos
publicados ausentes, caminhos inseguros ou links simbólicos bloqueiam a migração.
Investigue o job ou corrija a origem offline antes de prosseguir. Alterações
detectadas no banco ou nos arquivos durante a cópia também impedem a publicação.
Essas verificações não substituem a interrupção de todos os escritores.

## Procedimento na MV1

Os comandos abaixo são executados como root na MV1. Guarde os dois arquivos da
migração em `/opt/acessilia/migrations/`. Os dados atuais continuam em
`/opt/acessilia/production/var`; os novos ficarão em `/opt/acessilia/core/var`.
Crie somente o diretório pai: o destino `var` **não pode existir**.

```bash
install -d -m 700 -o acessilia -g acessilia /opt/acessilia/core

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

chown -R acessilia:acessilia /opt/acessilia/core/var
```

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
da 0.2.0; preserve-as separadamente antes do rollback. A instalação antiga e os
backups completos permanecem intactos para recuperação; o uso total de disco só
diminui quando os administradores os retirarem conforme a política de backup.
Esta migração não faz limpeza destrutiva da origem nem dos backups.
