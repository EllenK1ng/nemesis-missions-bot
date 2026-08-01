# Nemesis Missions Bot

Unofficial local Telegram bot for dealing hidden objectives in Nemesis board game sessions.

The bot lets a host create a password-protected game, players join from their own Telegram accounts, and each player receives one corporate objective and one personal objective without repeats. When everyone chooses one objective, the bot closes the game automatically.

This project is fan-made and is not affiliated with Awaken Realms. It does not include scans or official card images.

## Русская Короткая Инструкция

Если выкладываете проект на GitHub, загружайте содержимое этой папки, а не саму папку `nemesis-missions-bot` целиком внутрь репозитория. При создании репозитория на GitHub не включайте галочки `Add README`, `Add .gitignore` и `Add license`: эти файлы уже подготовлены здесь.

Настройки бота хранятся в файле `.env`, который каждый пользователь создает у себя локально рядом с `bot.py`. В репозиторий его загружать нельзя.

Файл `.env.example` - это безопасный шаблон без настоящих токенов. Скопируйте его в `.env` и впишите свои значения:

```env
TELEGRAM_BOT_TOKEN=токен_от_BotFather
HOST_CHAT_ID=ваш_chat_id
BOT_LANGUAGE=ru
```

`BOT_LANGUAGE=ru` включает русские миссии, `BOT_LANGUAGE=en` - английские.

Аватарку для Telegram-бота можно взять здесь: `assets/telegram-bot-avatar.png`.

## Features

- Host-only controls via `HOST_CHAT_ID`.
- Visible Telegram command menu for host and players.
- Base Nemesis and Carnomorphs objective pools.
- Optional special missions for the base game.
- No repeated corporate objectives or personal objectives within one game.
- Player-count filters for objectives tied to player numbers.
- Russian and English mission files.

## Quick Start

1. Install Python 3.9 or newer.
2. Copy `.env.example` to `.env`.
3. Put your bot token and host chat ID into `.env`.

```env
TELEGRAM_BOT_TOKEN=123456789:replace_me
HOST_CHAT_ID=123456789
BOT_LANGUAGE=ru
```

Use `BOT_LANGUAGE=ru` for Russian missions or `BOT_LANGUAGE=en` for English missions.

4. Start the bot:

```powershell
python bot.py
```

On Windows you can also double-click `Start Nemesis Bot.bat`.

If you do not know your `HOST_CHAT_ID`, leave it empty, start the bot, and send `/start` to the bot. It will show your chat ID.

## Commands

Host:

- `/newgame` - create a game and choose the objective mode.
- `/deal` - deal objectives to all joined players.
- `/players` - show the current player list.
- `/missions` - show objective counts.
- `/endgame` - close the active game early.

Players:

- `/start` or `/help` - show help.
- `/join` - join a game; the bot asks for the password separately.
- `/leave` - leave before objectives are dealt.

## Objective Files

Russian:

- `missions/ru/normal/corporate.json`
- `missions/ru/normal/personal.json`
- `missions/ru/carnomorphs/corporate.json`
- `missions/ru/carnomorphs/personal.json`

English:

- `missions/en/normal/corporate.json`
- `missions/en/normal/personal.json`
- `missions/en/carnomorphs/corporate.json`
- `missions/en/carnomorphs/personal.json`

Objective format:

```json
{
  "id": "corp_001",
  "title": "Objective title",
  "text": "Objective text",
  "source": "custom"
}
```

Optional fields:

- `requires_player_number`: minimum player count required for this objective.
- `max_player_count`: maximum player count allowed for this objective.
- `special`: marks a special objective with extra bot handling.

## Publishing Notes

Before publishing your own fork, keep `.env` and `data/state.json` private. They are ignored by `.gitignore` because they can contain bot tokens, chat IDs, and active game state.
