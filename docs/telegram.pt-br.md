# Interface Telegram

Você também pode ler este guia em **inglês**: [English](telegram.md)

Este guia mostra, passo a passo, como colocar o bot do Telegram do Acessilia para funcionar:

1. [Configurar o bot](#1-configurar-o-bot) — criar o bot no Telegram e ligá-lo ao Acessilia.
2. [Testar em conversa privada](#2-testar-em-conversa-privada) — conversar diretamente com o bot e conferir cada etapa.
3. [Usar o bot em um grupo](#3-usar-o-bot-em-um-grupo) — adicioná-lo a um grupo (com ou sem tópicos) e fazê-lo responder lá.

No fim há uma seção de [problemas comuns](#4-problemas-comuns) e as [limitações conhecidas](#5-limitações-conhecidas).

## Como o bot funciona

Antes de configurar, vale entender três pontos, porque eles explicam a maioria dos problemas:

- **O bot é um cliente da API.** O código em [frontend/telegram/](../frontend/telegram/) recebe o arquivo do usuário, baixa-o do Telegram e o envia à API REST do Acessilia (`API_BASE_URL`), exatamente como o painel web faz. Se a API estiver fora do ar, o bot recebe o arquivo mas não consegue processá-lo.
- **O bot busca as mensagens (long polling).** Ele pergunta periodicamente aos servidores do Telegram se há mensagens novas. Não há webhook, não é preciso abrir porta nem ter domínio público: basta o servidor conseguir acessar `api.telegram.org` pela internet.
- **Um token, um processo.** O Telegram entrega cada mensagem a um único processo por token. Se dois processos usam o mesmo token (por exemplo, o seu computador e o servidor de produção), eles disputam as mensagens e o log mostra `Conflict: terminated by other getUpdates request`. Por isso **cada ambiente tem o seu próprio bot**:

| Ambiente | Bot | Onde fica o token |
|---|---|---|
| Produção | `@acessilia_bot` | `.env` do servidor de produção |
| Homologação | `@acessilia_staging_bot` | `/opt/acessilia/src/.env` no servidor de homologação |
| Desenvolvimento local | um bot seu, criado para testes | `.env` do seu clone |

Nunca use o token de produção ou de homologação no seu `.env` local.

---

## 1. Configurar o bot

### 1.1 Criar o bot no BotFather

Os bots do Telegram são criados e administrados pelo próprio Telegram, conversando com o [@BotFather](https://t.me/BotFather).

1. Abra uma conversa com o `@BotFather` e envie `/newbot`.
2. Informe o **nome de exibição** (ex.: `Acessilia Dev Marcelo`). Pode ter espaços e ser alterado depois.
3. Informe o **nome de usuário**, que precisa terminar em `bot` (ex.: `acessilia_dev_marcelo_bot`). Ele é único no Telegram e não pode ser alterado.
4. O BotFather responde com o **token**, no formato `123456789:AAH...`. O token é a senha do bot: quem o tiver controla o bot. Não o coloque em commits, issues ou mensagens.

Se o token vazar, gere outro com `/revoke` no BotFather; o antigo deixa de funcionar na hora.

### 1.2 Ajustes recomendados no BotFather

Estes ajustes não são obrigatórios para conversa privada, mas evitam surpresas depois:

- **Lista de comandos** (`/setcommands`): faz o Telegram sugerir os comandos quando o usuário digita `/`. Cole a lista abaixo:

  ```text
  start - Iniciar o bot
  help - Listar os comandos
  formats - Formatos aceitos e gerados
  detailed - Próximo arquivo com descrição detalhada
  medium - Próximo arquivo com descrição média (padrão)
  low - Próximo arquivo com descrição concisa
  ocr - Próximo arquivo só com extração de texto
  email - Enviar o resultado do próximo arquivo por e-mail
  status - Andamento da sua tarefa
  cancel - Cancelar a sua tarefa
  deactivate - Pausar o bot neste chat
  activate - Reativar o bot neste chat
  health - Verificar API, modelo e disco
  feedback - Enviar uma opinião sobre o resultado
  ```

- **Entrada em grupos** (`/setjoingroups`): deixe *Enable* se o bot vai ser usado em grupos.
- **Privacidade em grupos** (`/setprivacy`): veja a [seção 3.1](#31-entenda-o-modo-de-privacidade). Se o bot vai processar arquivos em grupos, escolha *Disable*.

### 1.3 Configurar o `.env`

No `.env` do ambiente (copiado de [.env.example](../.env.example)), as variáveis que afetam o bot são:

| Variável | Para que serve | Exemplo |
|---|---|---|
| `BOT_TOKEN` | Token gerado pelo BotFather. Vazio desliga o bot. | `123456789:AAH...` |
| `ENABLED_INTERFACES` | Interfaces iniciadas por `frontend.run`. Precisa conter `telegram`. | `api,telegram,web` |
| `API_BASE_URL` | Endereço da API que o bot chama. | `http://localhost:8000` |
| `WEB_BASE_URL` | Endereço público do painel web, usado no link de download enviado no chat. Em servidor, use o endereço que o usuário consegue abrir, não `localhost`. | `https://www.acessilia3.inf.ufg.br` |
| `MAX_FILE_SIZE_MB` | Tamanho máximo de arquivo aceito. Veja o limite de 20 MB do Telegram na [seção 5](#5-limitações-conhecidas). | `50` |
| `REQUEST_TIMEOUT` | Tempo máximo, em segundos, que o bot acompanha uma tarefa antes de avisar que ela demorou demais. | `3600` |
| `I18N_LOCALES_ACTIVE` | Idiomas em que o bot pode responder. Ele responde no idioma do aplicativo de cada usuário, se estiver nesta lista. | `en_US,pt_BR` |

### 1.4 Iniciar e confirmar que o bot subiu

**Localmente:**

```bash
uv run python -m frontend.run
```

No log, procure a linha `Telegram interface enabled`. Se aparecer `Telegram interface enabled but BOT_TOKEN not configured`, o `BOT_TOKEN` está vazio ou não foi lido.

**Na homologação:** o container lê o `.env` só quando é criado, então reiniciá-lo não basta. Depois de editar `/opt/acessilia/src/.env`:

```bash
cd /opt/acessilia/src
docker compose -f docker-compose.staging.yml up -d --no-deps acessilia
docker logs --since 5m acessilia-staging 2>&1 | grep -i telegram
```

### 1.5 Conferir o token sem iniciar o bot

A chamada `getMe` da Bot API mostra se o token é válido e como o bot está configurado. Ela só lê informações, então pode ser feita mesmo com o bot rodando:

```bash
curl -s "https://api.telegram.org/bot<TOKEN>/getMe"
```

Campos que importam:

- `username`: confirma qual bot o token controla. É o jeito mais rápido de descobrir que você está com o token do ambiente errado.
- `can_join_groups`: precisa ser `true` para usar em grupos.
- `can_read_all_group_messages`: `true` quando o modo de privacidade está desligado (veja a [seção 3.1](#31-entenda-o-modo-de-privacidade)).

No servidor de homologação, rode a consulta de dentro do container para não expor o token no terminal:

```bash
docker exec acessilia-staging sh -c 'curl -s "https://api.telegram.org/bot$BOT_TOKEN/getMe"'
```

---

## 2. Testar em conversa privada

A conversa privada é o teste mais simples: não depende de configurações de grupo e o bot recebe tudo o que você envia. Teste sempre aqui primeiro. Se não funcionar em privado, não vai funcionar em grupo.

### 2.1 Roteiro de teste

Abra `https://t.me/<nome_do_bot>`, toque em **Iniciar** e siga os passos:

| Passo | O que fazer | O que deve acontecer |
|---|---|---|
| 1 | Envie `/start` | Mensagem de boas-vindas. Isso prova que o bot está rodando e recebendo mensagens. |
| 2 | Envie `/health` | Estado da API, do provedor e do modelo, mais o espaço em disco. Um ❌ em `API` indica que o bot não alcança `API_BASE_URL`. |
| 3 | Envie uma imagem **como arquivo** (clipe → *Arquivo*) | `📄 File received!` (ou a tradução) e, em seguida, uma mensagem de status que vai sendo atualizada a cada etapa. |
| 4 | Aguarde | Uma resposta à sua mensagem original com o link de download do pacote acessível, válido por 7 dias. |
| 5 | Envie `/status` | O andamento da última tarefa que você enviou neste chat. |
| 6 | Envie um PDF e, durante o processamento, `/cancel` | A tarefa é cancelada e o bot confirma. |

Se os passos 1 a 4 funcionam, a interface está operacional.

### 2.2 Foto ou arquivo?

O Telegram oferece dois jeitos de enviar uma imagem, e o bot aceita os dois:

- **Como foto** (o padrão do aplicativo): o Telegram **comprime** a imagem antes de entregá-la. Para fotos comuns isso é suficiente, mas em páginas digitalizadas com texto pequeno ou fórmulas a compressão piora o reconhecimento.
- **Como arquivo**: a imagem chega intacta. Prefira esse modo para documentos.

Formatos aceitos como arquivo: PDF, PNG, JPG/JPEG, TIFF/TIF, DOCX e HTML. As mensagens `/start` e `/formats` do bot ainda citam BMP e WEBP, mas esses formatos são recusados (veja a [seção 5](#5-limitações-conhecidas)).

### 2.3 Comandos

Cada comando tem um nome em português e um alias em inglês. Os dois funcionam em qualquer idioma.

| Comando | Alias | O que faz |
|---|---|---|
| `/start` | — | Boas-vindas. |
| `/ajuda` | `/help` | Lista os comandos. |
| `/formatos` | `/formats` | Formatos de entrada e de saída. |
| `/detalhado` | `/detailed` | O **próximo** arquivo terá descrição máxima: tipografia, cores, layout. |
| `/medio` | `/medium` | O próximo arquivo terá a descrição padrão (`/normal` faz o mesmo). |
| `/baixo` | `/low` | O próximo arquivo terá descrição concisa e processamento mais rápido. |
| `/ocr` | — | O próximo arquivo terá só extração de texto, sem descrição visual. |
| `/email <endereço>` | — | O resultado do próximo arquivo também vai para esse e-mail. |
| `/status` | — | Andamento da sua última tarefa neste chat. |
| `/cancelar` | `/cancel` | Cancela a sua última tarefa neste chat. |
| `/desativar` | `/deactivate` | Pausa o bot **no chat inteiro**: ele passa a responder só que está pausado. |
| `/ativar` | `/activate` | Tira a pausa. |
| `/health` | — | Verifica API, modelo e disco. |
| `/feedback` | — | Pede um texto livre de opinião e o registra no servidor. |
| `/limpar` | `/clear` | Apaga o cache de processamento do **servidor**, para todos os usuários. Uso de operador. |

Observações:

- Os modos (`/detalhado`, `/ocr` etc.) e o `/email` valem **só para o próximo arquivo** que você enviar. Depois dele, voltam ao padrão.
- Modo, e-mail e tarefa acompanhada são guardados **por pessoa, por chat e por tópico**. Num grupo, o `/detalhado` de uma pessoa não afeta o arquivo de outra.

---

## 3. Usar o bot em um grupo

### 3.1 Entenda o modo de privacidade

Este é o ponto que mais causa confusão. Todo bot novo vem com o **modo de privacidade ligado**. Nesse modo, num grupo, o Telegram **só entrega ao bot**:

- comandos dirigidos a ele (ex.: `/help@acessilia_staging_bot`);
- respostas (*reply*) a mensagens do próprio bot;
- mensagens de serviço (alguém entrou, o título mudou etc.).

**Fotos e arquivos comuns não chegam ao bot.** Para o bot, é como se nada tivesse sido enviado: ele não erra, não registra nada no log e não responde. Em conversa privada esse modo não tem efeito, e é por isso que o bot pode funcionar perfeitamente em privado e ficar mudo no grupo.

Há duas formas de fazer o bot receber os arquivos do grupo. Basta uma delas:

| Opção | Como | Quando usar |
|---|---|---|
| **A. Desligar o modo de privacidade** | No BotFather: `/setprivacy` → escolha o bot → *Disable* (ou `/mybots` → bot → *Bot Settings* → *Group Privacy* → *Turn off*). Vale para todos os grupos. | Grupos onde o bot deve atender qualquer arquivo enviado. É o caso do Acessilia. |
| **B. Tornar o bot administrador do grupo** | Nas configurações do grupo → *Administradores* → adicionar o bot. Administradores recebem todas as mensagens, mesmo com privacidade ligada. | Quando você não controla o bot no BotFather, ou quer liberar só alguns grupos. |

> **Importante:** o Telegram aplica a mudança de privacidade a um grupo **somente quando o bot entra nele**. Se o bot já estava no grupo quando você desligou a privacidade, **remova-o e adicione-o de novo**. Esquecer esse passo é a causa mais comum de "desliguei a privacidade e continua sem responder".

Para conferir a configuração atual, rode `getMe` ([seção 1.5](#15-conferir-o-token-sem-iniciar-o-bot)): `can_read_all_group_messages: true` significa privacidade desligada.

### 3.2 Adicionar o bot ao grupo

1. Confirme que o bot funciona em conversa privada ([seção 2](#2-testar-em-conversa-privada)).
2. Escolha a opção A ou B da [seção 3.1](#31-entenda-o-modo-de-privacidade). Se for a A, faça o ajuste no BotFather **antes** de adicionar o bot ao grupo.
3. No grupo: *Adicionar membros* → procure o `@nome_do_bot` → adicionar.
4. Garanta que o bot pode **enviar mensagens** no grupo. Em grupos com permissões restritas, isso fica em *Permissões* ou nas permissões de administrador do bot.
5. Teste com `/health@nome_do_bot` e depois envie um arquivo.

### 3.3 Grupos com tópicos (fóruns)

Em grupos com tópicos ativados, o bot responde **no mesmo tópico** em que o arquivo foi enviado: a confirmação, as atualizações de status e o link final ficam todos ali. Não é preciso nenhuma configuração extra no Acessilia.

Cuidados específicos:

- **Tópico fechado:** num tópico fechado, só administradores com permissão de gerenciar tópicos podem postar. Se o bot não for um deles, ele recebe o arquivo, processa, mas não consegue responder. O erro aparece no log do servidor.
- **Cada tópico é independente:** `/status` e `/cancel` só enxergam a tarefa que você enviou **naquele tópico**.
- **A pausa vale para o grupo inteiro:** `/desativar` em um tópico pausa o bot em todos os tópicos do grupo.

### 3.4 Comandos em grupos

Num grupo, prefira escrever o comando com o nome do bot: `/status@acessilia_staging_bot`.

- Com o modo de privacidade ligado, o Telegram só garante a entrega do comando nessa forma.
- Se houver mais de um bot no grupo (por exemplo, o de produção e o de homologação), o sufixo diz qual deve responder. O bot ignora comandos endereçados a outro bot.

### 3.5 Lista de verificação para grupo

Se o bot não responde no grupo, confira nesta ordem:

1. Ele responde em conversa privada? Se não, volte à [seção 1](#1-configurar-o-bot).
2. O bot que está no grupo é o do ambiente que você quer testar? Compare o `@nome` do membro do grupo com o `username` do `getMe`.
3. `can_read_all_group_messages` é `true`, **ou** o bot é administrador do grupo?
4. O bot foi removido e adicionado de novo **depois** da mudança de privacidade?
5. `/health@nome_do_bot` responde no grupo? Se sim, o bot recebe e envia mensagens ali, e o problema está na entrega de arquivos (itens 3 e 4).
6. Responder a uma mensagem do bot anexando o arquivo funciona? Respostas ao bot sempre chegam a ele. Se assim funcionar e do jeito normal não, a causa é certamente a privacidade (itens 3 e 4).
7. O grupo está pausado? Nesse caso o bot responde avisando; use `/ativar`.
8. Nada disso? Consulte o log do servidor ([seção 4](#4-problemas-comuns)).

---

## 4. Problemas comuns

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| Não responde a nada, nem em privado | Bot não iniciou, token vazio ou errado | Procure `Telegram interface enabled` no log; confira o `username` do `getMe`. |
| Log com `Conflict: terminated by other getUpdates request` | Dois processos usando o mesmo token | Pare o outro processo ou use um bot próprio para cada ambiente. |
| Funciona em privado, mas ignora arquivos no grupo | Modo de privacidade ligado, ou mudança feita com o bot já no grupo | [Seção 3.1](#31-entenda-o-modo-de-privacidade): desligar a privacidade e readicionar o bot. |
| Responde a comandos no grupo, mas não a arquivos | Mesmo caso acima: comandos chegam com privacidade ligada, arquivos não | Mesma solução. |
| Confirma o recebimento e depois avisa que não conseguiu contatar o servidor | A API está fora do ar ou `API_BASE_URL` está errado | `/health`; confira `API_BASE_URL` e se a API está rodando. |
| Recusa um arquivo grande ou falha ao baixá-lo | Arquivo acima de `MAX_FILE_SIZE_MB` ou acima de 20 MB | Veja a [seção 5](#5-limitações-conhecidas). |
| O link de download aponta para `localhost` | `WEB_BASE_URL` não configurado no servidor | Ajuste `WEB_BASE_URL` para o endereço público. |
| Processa, mas a resposta não aparece no tópico | Tópico fechado ou bot sem permissão de enviar mensagens | [Seção 3.3](#33-grupos-com-tópicos-fóruns); confira o log. |

Para olhar o log na homologação:

```bash
docker logs --since 2h acessilia-staging 2>&1 | grep -iE "telegram|conflict|forbidden|error" | tail -50
```

Se o arquivo enviado no grupo **não aparece no log de jeito nenhum**, ele não chegou ao bot: é privacidade (seção 3.1). Se aparece seguido de um erro, o problema é no processamento ou no envio da resposta.

---

## 5. Limitações conhecidas

- **Arquivos acima de 20 MB:** a Bot API pública do Telegram só permite que bots baixem arquivos de até 20 MB. Mesmo com `MAX_FILE_SIZE_MB=50`, um arquivo entre 20 e 50 MB passa na validação e falha no download. Para arquivos maiores, use o painel web.
- **Estado em memória:** modos, e-mails, tarefas acompanhadas e chats pausados ficam na memória do processo. Ao reiniciar ou recriar o container, tudo volta ao padrão: chats pausados voltam a responder e `/status` deixa de encontrar tarefas enviadas antes do reinício. As tarefas em si continuam na API.
- **Formatos anunciados x aceitos:** `/start` e `/formats` citam BMP e WEBP, que o validador recusa. Também anunciam Markdown e "PDF pesquisável" como saída, mas o pacote atual tem TXT, DOCX, PDF/UA, HTML e MP3. A ajuda (`/help`) não lista `/email`.
- **Mensagem final em português:** o texto com o link de download sai em português, seja qual for o idioma do usuário.

## Referências

- Código do bot: [frontend/telegram/](../frontend/telegram/) — arquivos e fotos em [handlers/document.py](../frontend/telegram/handlers/document.py), comandos em [handlers/start.py](../frontend/telegram/handlers/start.py).
- Casos de uso do bot: [use_cases.pt-br.md](use_cases.pt-br.md).
- Execução local e com Docker: [README](../README.pt-br.md), [docker-compose.pt-br.md](docker-compose.pt-br.md).
- Documentação oficial do Telegram sobre privacidade de bots: <https://core.telegram.org/bots/features#privacy-mode>.
