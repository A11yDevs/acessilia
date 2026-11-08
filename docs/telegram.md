# Telegram interface

You can also read this guide in **Brazilian Portuguese**: [pt-BR version](telegram.pt-br.md)

This guide walks through getting the Acessilia Telegram bot working, step by step:

1. [Set up the bot](#1-set-up-the-bot) — create the bot on Telegram and connect it to Acessilia.
2. [Test it in a private chat](#2-test-it-in-a-private-chat) — talk to the bot directly and check each step.
3. [Use the bot in a group](#3-use-the-bot-in-a-group) — add it to a group (with or without topics) and get it to answer there.

The end of the guide covers [common problems](#4-common-problems) and [known limitations](#5-known-limitations).

## How the bot works

Three points explain most problems, so they are worth knowing before you start:

- **The bot is an API client.** The code in [frontend/telegram/](../frontend/telegram/) receives the user's file, downloads it from Telegram and submits it to the Acessilia REST API (`API_BASE_URL`), exactly as the web panel does. If the API is down, the bot still receives the file but cannot process it.
- **The bot fetches its messages (long polling).** It keeps asking Telegram's servers for new messages. There is no webhook, no port to open and no public domain needed: the server only has to reach `api.telegram.org` over the internet.
- **One token, one process.** Telegram delivers each message to a single process per token. When two processes share a token (say, your laptop and the production server), they compete for the messages and the log shows `Conflict: terminated by other getUpdates request`. That is why **each environment has its own bot**:

| Environment | Bot | Where the token lives |
|---|---|---|
| Production | `@acessilia_bot` | the production server's `.env` |
| Staging | `@acessilia_staging_bot` | `/opt/acessilia/src/.env` on the staging server |
| Local development | your own test bot | your clone's `.env` |

Never put the production or staging token in your local `.env`.

---

## 1. Set up the bot

### 1.1 Create the bot with BotFather

Telegram bots are created and managed by Telegram itself, through a chat with [@BotFather](https://t.me/BotFather).

1. Open a chat with `@BotFather` and send `/newbot`.
2. Enter the **display name** (e.g. `Acessilia Dev Marcelo`). It can contain spaces and can be changed later.
3. Enter the **username**, which must end in `bot` (e.g. `acessilia_dev_marcelo_bot`). It is unique on Telegram and cannot be changed.
4. BotFather replies with the **token**, shaped like `123456789:AAH...`. The token is the bot's password: whoever holds it controls the bot. Keep it out of commits, issues and chat messages.

If the token leaks, issue a new one with `/revoke` in BotFather; the old one stops working immediately.

### 1.2 Recommended BotFather settings

These are not required for private chats, but they prevent surprises later:

- **Command list** (`/setcommands`): makes Telegram suggest the commands when the user types `/`. Paste this list:

  ```text
  start - Start the bot
  help - List the commands
  formats - Accepted and generated formats
  detailed - Detailed description for the next file
  medium - Medium description for the next file (default)
  low - Concise description for the next file
  ocr - Text extraction only for the next file
  email - Also e-mail the result of the next file
  status - Progress of your task
  cancel - Cancel your task
  deactivate - Pause the bot in this chat
  activate - Resume the bot in this chat
  health - Check the API, model and disk
  feedback - Send your opinion about the result
  ```

- **Joining groups** (`/setjoingroups`): keep *Enable* if the bot will be used in groups.
- **Group privacy** (`/setprivacy`): see [section 3.1](#31-understand-privacy-mode). If the bot will process files in groups, choose *Disable*.

### 1.3 Configure `.env`

In the environment's `.env` (copied from [.env.example](../.env.example)), these variables affect the bot:

| Variable | What it does | Example |
|---|---|---|
| `BOT_TOKEN` | Token issued by BotFather. Empty turns the bot off. | `123456789:AAH...` |
| `ENABLED_INTERFACES` | Interfaces started by `frontend.run`. Must contain `telegram`. | `api,telegram,web` |
| `API_BASE_URL` | Address of the API the bot calls. | `http://localhost:8000` |
| `WEB_BASE_URL` | Public address of the web panel, used in the download link sent in the chat. On a server, use the address users can open, not `localhost`. | `https://www.acessilia3.inf.ufg.br` |
| `MAX_FILE_SIZE_MB` | Largest file accepted. See Telegram's 20 MB limit in [section 5](#5-known-limitations). | `50` |
| `REQUEST_TIMEOUT` | How long, in seconds, the bot follows a task before reporting that it took too long. | `3600` |
| `I18N_LOCALES_ACTIVE` | Languages the bot may answer in. It answers in each user's app language when that language is listed here. | `en_US,pt_BR` |

### 1.4 Start the bot and confirm it is up

**Locally:**

```bash
uv run python -m frontend.run
```

Look for the `Telegram interface enabled` log line. `Telegram interface enabled but BOT_TOKEN not configured` means `BOT_TOKEN` is empty or was not read.

**On staging:** the container reads `.env` only when it is created, so a restart is not enough. After editing `/opt/acessilia/src/.env`:

```bash
cd /opt/acessilia/src
docker compose -f docker-compose.staging.yml up -d --no-deps acessilia
docker logs --since 5m acessilia-staging 2>&1 | grep -i telegram
```

### 1.5 Check the token without starting the bot

The Bot API `getMe` call shows whether the token is valid and how the bot is configured. It only reads, so it is safe while the bot is running:

```bash
curl -s "https://api.telegram.org/bot<TOKEN>/getMe"
```

The fields that matter:

- `username`: which bot the token controls. The quickest way to find out you have the wrong environment's token.
- `can_join_groups`: must be `true` for group use.
- `can_read_all_group_messages`: `true` when privacy mode is off (see [section 3.1](#31-understand-privacy-mode)).

On the staging server, run it inside the container so the token never shows up in the terminal:

```bash
docker exec acessilia-staging sh -c 'curl -s "https://api.telegram.org/bot$BOT_TOKEN/getMe"'
```

---

## 2. Test it in a private chat

A private chat is the simplest test: no group settings are involved and the bot receives everything you send. Always test here first. If it fails in private, it will fail in a group too.

### 2.1 Test script

Open `https://t.me/<bot_username>`, tap **Start** and follow these steps:

| Step | What to do | What should happen |
|---|---|---|
| 1 | Send `/start` | A welcome message. This proves the bot is running and receiving messages. |
| 2 | Send `/health` | The state of the API, provider and model, plus free disk space. A ❌ on `API` means the bot cannot reach `API_BASE_URL`. |
| 3 | Send an image **as a file** (paperclip → *File*) | `📄 File received!` (or its translation), then a status message that updates at each stage. |
| 4 | Wait | A reply to your original message with the download link for the accessible package, valid for 7 days. |
| 5 | Send `/status` | The progress of the last task you sent in this chat. |
| 6 | Send a PDF and, while it runs, `/cancel` | The task is cancelled and the bot confirms it. |

If steps 1 to 4 work, the interface is operational.

### 2.2 Photo or file?

Telegram offers two ways to send an image, and the bot accepts both:

- **As a photo** (the app's default): Telegram **compresses** the image before delivering it. That is fine for ordinary photos, but on scanned pages with small text or formulas the compression hurts recognition.
- **As a file**: the image arrives untouched. Prefer this for documents.

Formats accepted as files: PDF, PNG, JPG/JPEG, TIFF/TIF, DOCX and HTML. The bot's `/start` and `/formats` messages still mention BMP and WEBP, but those are rejected (see [section 5](#5-known-limitations)).

### 2.3 Commands

Each command has a Portuguese name and an English alias. Both work in any language.

| Command | Alias | What it does |
|---|---|---|
| `/start` | — | Welcome message. |
| `/ajuda` | `/help` | Lists the commands. |
| `/formatos` | `/formats` | Input and output formats. |
| `/detalhado` | `/detailed` | The **next** file gets the fullest description: typography, colors, layout. |
| `/medio` | `/medium` | The next file gets the default description (`/normal` does the same). |
| `/baixo` | `/low` | The next file gets a concise description and faster processing. |
| `/ocr` | — | The next file gets text extraction only, no visual description. |
| `/email <address>` | — | The result of the next file is also sent to that address. |
| `/status` | — | Progress of your last task in this chat. |
| `/cancelar` | `/cancel` | Cancels your last task in this chat. |
| `/desativar` | `/deactivate` | Pauses the bot **in the whole chat**: it only answers that it is paused. |
| `/ativar` | `/activate` | Lifts the pause. |
| `/health` | — | Checks the API, model and disk. |
| `/feedback` | — | Asks for free-text feedback and records it on the server. |
| `/limpar` | `/clear` | Clears the **server's** processing cache, for every user. Operator use. |

Notes:

- The modes (`/detailed`, `/ocr` and so on) and `/email` apply **only to the next file** you send. After that, they reset to the default.
- Mode, e-mail and the tracked task are kept **per person, per chat and per topic**. In a group, one person's `/detailed` does not affect someone else's file.

---

## 3. Use the bot in a group

### 3.1 Understand privacy mode

This is the most common source of confusion. Every new bot starts with **privacy mode on**. In that mode, in a group, Telegram **only delivers to the bot**:

- commands addressed to it (e.g. `/help@acessilia_staging_bot`);
- replies to the bot's own messages;
- service messages (someone joined, the title changed, and so on).

**Ordinary photos and files never reach the bot.** As far as the bot knows, nothing was sent: it raises no error, logs nothing and does not answer. Privacy mode has no effect in private chats, which is why a bot can work perfectly in private and stay silent in a group.

There are two ways to let the bot receive the group's files. Either one is enough:

| Option | How | When to use it |
|---|---|---|
| **A. Turn privacy mode off** | In BotFather: `/setprivacy` → pick the bot → *Disable* (or `/mybots` → bot → *Bot Settings* → *Group Privacy* → *Turn off*). Applies to every group. | Groups where the bot should handle any file sent. This is Acessilia's case. |
| **B. Make the bot a group administrator** | Group settings → *Administrators* → add the bot. Administrators receive every message, even with privacy on. | When you do not control the bot in BotFather, or want to enable only some groups. |

> **Important:** Telegram applies a privacy change to a group **only when the bot joins it**. If the bot was already in the group when you turned privacy off, **remove it and add it again**. Skipping this is the most common cause of "I turned privacy off and it still does not answer".

To check the current setting, run `getMe` ([section 1.5](#15-check-the-token-without-starting-the-bot)): `can_read_all_group_messages: true` means privacy is off.

### 3.2 Add the bot to the group

1. Confirm the bot works in a private chat ([section 2](#2-test-it-in-a-private-chat)).
2. Pick option A or B from [section 3.1](#31-understand-privacy-mode). For option A, change the setting in BotFather **before** adding the bot to the group.
3. In the group: *Add members* → search for `@bot_username` → add.
4. Make sure the bot may **send messages** in the group. In groups with restricted permissions, this is under *Permissions* or in the bot's administrator rights.
5. Test with `/health@bot_username`, then send a file.

### 3.3 Groups with topics (forums)

In groups with topics enabled, the bot answers **in the same topic** the file was sent to: the acknowledgement, the status updates and the final link all stay there. Acessilia needs no extra configuration for this.

Things to watch:

- **Closed topics:** in a closed topic, only administrators allowed to manage topics can post. If the bot is not one of them, it receives the file and processes it, but cannot answer. The error shows up in the server log.
- **Each topic is independent:** `/status` and `/cancel` only see the task you sent **in that topic**.
- **A pause covers the whole group:** `/deactivate` in one topic pauses the bot in every topic of the group.

### 3.4 Commands in groups

In a group, prefer writing commands with the bot's name: `/status@acessilia_staging_bot`.

- With privacy mode on, Telegram only guarantees delivery of commands in that form.
- When the group has more than one bot (say, the production and staging bots), the suffix says which one should answer. The bot ignores commands addressed to another bot.

### 3.5 Group checklist

If the bot does not answer in the group, check in this order:

1. Does it answer in a private chat? If not, go back to [section 1](#1-set-up-the-bot).
2. Is the bot in the group the one for the environment you want to test? Compare the group member's `@name` with the `username` from `getMe`.
3. Is `can_read_all_group_messages` `true`, **or** is the bot a group administrator?
4. Was the bot removed and added again **after** the privacy change?
5. Does `/health@bot_username` answer in the group? If it does, the bot receives and sends messages there, and the problem is file delivery (items 3 and 4).
6. Does replying to one of the bot's messages with the file attached work? Replies to the bot always reach it. If that works and a plain upload does not, the cause is privacy (items 3 and 4).
7. Is the group paused? The bot then answers that it is paused; use `/activate`.
8. None of the above? Check the server log ([section 4](#4-common-problems)).

---

## 4. Common problems

| Symptom | Likely cause | What to do |
|---|---|---|
| Answers nothing, not even in private | The bot did not start, or the token is empty or wrong | Look for `Telegram interface enabled` in the log; check the `username` from `getMe`. |
| Log shows `Conflict: terminated by other getUpdates request` | Two processes using the same token | Stop the other process, or give each environment its own bot. |
| Works in private, ignores files in the group | Privacy mode on, or changed while the bot was already in the group | [Section 3.1](#31-understand-privacy-mode): turn privacy off and re-add the bot. |
| Answers commands in the group but not files | Same as above: commands get through with privacy on, files do not | Same fix. |
| Acknowledges the file, then says it could not contact the server | The API is down or `API_BASE_URL` is wrong | `/health`; check `API_BASE_URL` and that the API is running. |
| Rejects a large file or fails to download it | File above `MAX_FILE_SIZE_MB` or above 20 MB | See [section 5](#5-known-limitations). |
| The download link points to `localhost` | `WEB_BASE_URL` not set on the server | Set `WEB_BASE_URL` to the public address. |
| Processes the file, but no answer appears in the topic | Closed topic, or the bot may not send messages | [Section 3.3](#33-groups-with-topics-forums); check the log. |

To read the staging log:

```bash
docker logs --since 2h acessilia-staging 2>&1 | grep -iE "telegram|conflict|forbidden|error" | tail -50
```

If the file sent in the group **does not appear in the log at all**, it never reached the bot: that is privacy (section 3.1). If it appears followed by an error, the problem is in processing or in sending the answer.

---

## 5. Known limitations

- **Files over 20 MB:** Telegram's public Bot API only lets bots download files up to 20 MB. Even with `MAX_FILE_SIZE_MB=50`, a file between 20 and 50 MB passes validation and then fails to download. Use the web panel for larger files.
- **In-memory state:** modes, e-mails, tracked tasks and paused chats live in the process memory. Restarting or recreating the container resets them: paused chats answer again and `/status` no longer finds tasks sent before the restart. The tasks themselves remain in the API.
- **Advertised vs accepted formats:** `/start` and `/formats` mention BMP and WEBP, which the validator rejects. They also advertise Markdown and "searchable PDF" outputs, while the current package holds TXT, DOCX, PDF/UA, HTML and MP3. The help (`/help`) does not list `/email`.
- **Final message in Portuguese:** the message with the download link is in Portuguese whatever the user's language.

## References

- Bot code: [frontend/telegram/](../frontend/telegram/) — files and photos in [handlers/document.py](../frontend/telegram/handlers/document.py), commands in [handlers/start.py](../frontend/telegram/handlers/start.py).
- The bot's use cases: [use_cases.md](use_cases.md).
- Local and Docker execution: [README](../README.md), [docker-compose.md](docker-compose.md).
- Telegram's official documentation on bot privacy: <https://core.telegram.org/bots/features#privacy-mode>.
