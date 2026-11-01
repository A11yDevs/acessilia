# Preparação, ativação e atualizador de produção

English: [production-systemd.md](production-systemd.md).

Revisar configuração e dados antes da migração 0.1.0 → 0.2.0. Passar em
`docker compose config` valida configuração, não disponibilidade do modelo,
migração, conversão de documentos ou rollback.

## Preparação separada da ativação

O instalador antigo iniciava `main` mesmo com `--no-timer`, criava `var` antes
da migração e podia repassar credenciais de registro para a aplicação. O Compose
também herdava o cliente de IA antigo e podia criar um volume vazio. O instalador
revisado somente prepara arquivos, recusa sobrescritas, não usa sudo e não inicia
containers ou timers. `--no-timer` agora é um alias de preparação. Chamar o setup
sem uma opção explícita de preparação falha. Login e timers são etapas separadas.

## Preparar como usuário operacional

O administrador provisiona previamente `acessilia`, home gravável
`/opt/acessilia`, acesso ao Docker e linger. O usuário operacional não precisa
de sudo. No checkout de release revisado, como esse usuário:

```bash
bash scripts/setup-producao.sh --prepare-only --production-dir /opt/acessilia/core
```

O script cria `.env`, `.deploy.env`, Compose e `ops/` privados; não cria `var`.
Arquivos de destino existentes interrompem a preparação antes das cópias.
Os modelos estão em `deploy/production.runtime.env.example` e
`deploy/production.deploy.env.example`.

Edite os arquivos privadamente. `.env` contém apenas configurações da aplicação:
preserve bot, SMTP, URLs públicas da API/downloads e observabilidade reais da
produção antiga; `.env.example` é a referência completa. Confira
os endpoints que ainda usam `host.docker.internal` durante a transferência;
o Compose de produção preserva o mapeamento `host-gateway` por compatibilidade.
Configure `TOOLBOX_API_KEY` com a chave da Toolbox de produção. Os padrões selecionam fusão
dual Docling/MinerU, execução PDDL e timeout de modelo de 3000 segundos.

`.deploy.env` contém `PRODUCTION_IMAGE=ghcr.io/a11ydevs/acessilia@sha256:...`
aprovada, rede/endereço da Toolbox e token opcional da API GitHub do atualizador.
Não coloque esse token no `.env` da aplicação. Mantenha `.deploy.env` compatível
com shell. Use `docker login ghcr.io` como usuário operacional para o registro.
O setup não aceita mais tokens como argumentos nem os grava na aplicação.

## Pré-requisitos da Toolbox e do gateway

Configure o projeto separado da Toolbox de produção na rede externa
`acessilia-production-backplane`, com alias `toolbox-production`. Crie a rede
uma vez antes de iniciá-lo. O core acessa `http://toolbox-production:8002`;
Toolbox, sidecars, MinIO e Valkey não precisam publicar portas no host para essa
comunicação. `PRODUCTION_TOOLBOX_NETWORK` e `PRODUCTION_TOOLBOX_BASE_URL`
permitem outra topologia aprovada. As portas 8000/8001 do core continuam
publicadas para compatibilidade com o proxy; valide rotas antes de mudá-las.

O gateway continua nativo na MV2 com `vlm-gateway`. A Toolbox de produção usa
`VLM_SERVE_URL=http://172.16.109.33:8002/v1/vlm` e recebe a chave do gateway em
`VLM_API_KEY`, diferente da chave core–Toolbox. Toolboxes dos ambientes usam
concorrência 4, timeout 2700 s e espera local 120 s. Estado final do gateway:
um processo servidor, concorrência global 2, modelo com `--parallel 2` e escuta
somente em loopback. Coordenar com homologação e validar saúde autenticada e
inferência. Este PR do core não modifica a MV2 nem a implantação da Toolbox.

## Validar, migrar e então ativar

Antes da janela de manutenção:

```bash
python3 /opt/acessilia/core/ops/production_deploy.py check
```

A verificação resolve o Compose sem imprimir credenciais e rejeita imagens
mutáveis, variáveis de implantação na aplicação, chaves ausentes, execução
simulada, caminhos/portas incompatíveis e timeouts insuficientes para o gateway.
`MODEL_CALL_TIMEOUT_SECONDS`, `DATA_AGENT_TIMEOUT_SECONDS` e
`TOOLBOX_TIMEOUT_SECONDS` devem ter pelo menos 3000 s, cobrindo a espera local
de 120 s da Toolbox mais a chamada de 2700 s ao gateway.
Medir picos de memória/CPU com documentos representativos em fusão dual antes
de escolher limites. O core tem rotação dos logs Docker, prazo de parada de
60 segundos e processo init; isso não implementa drenagem. Testar parada/reinício
na homologação. Preservar backups de imagem, configuração e automação; validar
a rota do gateway para rollback antes da janela.

Seguir a [migração versionada](data-migration-0.1.0-to-0.2.0.pt-br.md): bloquear
todas as entradas, inclusive Telegram, drenar fila e jobs ativos, parar o core
antigo, fazer backup offline completo, simular/aplicar/verificar a migração e
conferir permissões de UID. Não criar `core/var` manualmente antes da migração.
O bind não o cria automaticamente; sua existência não comprova migração.

Após verificar a migração, como usuário operacional:

```bash
cd /opt/acessilia/core
set -a
. ./.deploy.env
set +a
python3 ops/production_deploy.py check --require-data
docker compose -p production --env-file .deploy.env -f docker-compose.production.yml pull acessilia
docker compose -p production --env-file .deploy.env -f docker-compose.production.yml up -d --no-deps --wait --wait-timeout 120 acessilia
python3 ops/production_deploy.py verify-running --image "$PRODUCTION_IMAGE"
```

A verificação confere a imagem efetiva, `/api/v1/ready` para os dois extratores
em modo dual e `model_reachable=true` em `/api/v1/health`, dentro do container.
HTTP 200 isoladamente não comprova prontidão do modelo. Completar com documento
real, interfaces/exportações, downloads preservados e rejeição de expirados.
Evitar imprimir tokens ou o Compose completo com credenciais resolvidas.

Essas verificações são **posteriores à inicialização, não bloqueiam previamente
a troca de tráfego**. `up -d` substitui o container antigo antes de verificar
as dependências. Se `--wait` ou `verify-running` falhar, a imagem nova pode
continuar executando e atendendo tráfego. Manter as entradas bloqueadas durante
o aceite da migração; parar o timer, inspecionar o container efetivo e executar
o rollback manual abaixo quando necessário. O atualizador informa o ID da
imagem anterior quando ativação/verificação falha. Não restaura automaticamente
imagem ou dados: reverter somente a imagem pode ser incompatível com mudanças
no banco ou novas escritas.

## Timer existente e rastreamento automático futuro

Manter o timer de usuário desabilitado durante migração, aceite e fixação manual
do digest. Ao registrar o novo layout, atualizar seu drop-in como `acessilia`:

```ini
[Service]
WorkingDirectory=/opt/acessilia/core
ExecStart=
ExecStart=/opt/acessilia/core/ops/production-update.sh
Environment=PRODUCTION_DIR=/opt/acessilia/core
Environment=STAGING_UPDATE_CACHE=/opt/acessilia/core/var/data/.last_production_sha
Environment=STAGING_STATUS_FILE=/opt/acessilia/core/var/data/production-status.json
```

Executar `systemctl --user daemon-reload`, mantendo o timer desabilitado.
Atualizações de produção exigem `.deploy.env` separado, recusam imagem fixada
manualmente/literalmente, falham quando não resolvem o commit GitHub, baixam o
artefato SHA, conferem sua revisão OCI e selecionam seu digest. Imagem e
dependências são verificadas antes de registrar sucesso em cache/status;
imagens de rollback são preservadas. Seleção de branch e fallback da homologação
continuam como antes.

Quando branch/commit em cache ainda coincidem com GitHub, produção confere se
o container está executando o digest registrado no último deploy aceito. Se
coincidir, atualiza apenas `last_check`, preserva `last_update` e não baixa
imagens, executa Compose `up` ou testa dependências. Uma indisponibilidade
temporária da VLM não causa falha dessa checagem sem alterações; monitoramento
de dependências permanece separado. Status ausente/inconsistente, container
parado ou digest diferente levam ao fluxo completo. A consulta do commit GitHub
continua em cada execução para detectar mudanças.

Rastreamento automático futuro exige limpar explicitamente `PRODUCTION_IMAGE`,
manter `TRACK_BRANCH=main` revisada, ambiente e rede válidos e uma política de
drenagem/manutenção. O atualizador não drena jobs nem coordena migrações. Não
reativá-lo apenas porque o PR foi mesclado ou o BHS terminou; promoção de
produção e mudança da branch de homologação são operações separadas.

O workflow `Production deployment validation` executa as suítes completas do
core, docstruct e SDK dentro da imagem de execução quando seus filtros de
arquivos de implantação correspondem, ou por disparo manual. Não executa em
todo PR. O CI normal continua executando as suítes em todos os PRs suportados.

## Rollback

Parar o core novo e restaurar imagem 0.1.0, Compose/ambiente originais e dados
originais no projeto `production`. Não usar o banco migrado na 0.1.0 nem o
Compose da 0.2.0 que força Toolbox. A porta 80 antiga da MV1 já falhou; validar
previamente uma rota OpenRouter compatível e autenticada pelo gateway. Manter
o modelo acessível exclusivamente pelo gateway durante rollback. Novas escritas
da 0.2.0 exigem reconciliação explícita: restaurar dados antigos não as preserva.
