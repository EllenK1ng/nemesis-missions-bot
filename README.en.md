# Nemesis Missions Bot

Unofficial local Telegram bot for dealing hidden objectives in Nemesis board game sessions.

The bot lets a host create a password-protected game, players join from their own Telegram accounts, and each player receives one corporate objective and one personal objective without repeats. When everyone chooses one objective, the bot closes the game automatically.

This project is fan-made and is not affiliated with Awaken Realms. It does not include scans or official card images.

## Features

- Host-only controls via `HOST_CHAT_ID`.
- Separate Telegram command menus for host and players.
- Base Nemesis and Carnomorphs objective pools.
- Optional special missions for the base game.
- No repeated corporate objectives or personal objectives within one game.
- Player-count filters for objectives tied to player numbers.
- Russian and English mission files.

## Quick Start

1. Install Python 3.9 or newer.
2. Start the bot once. If `config.json` does not exist yet, the bot will create it next to `bot.py` and stop.
3. Open `config.json` and add your bot token, host chat ID, and language.

```json
{
  "TELEGRAM_BOT_TOKEN": "123456789:replace_me",
  "HOST_CHAT_ID": "123456789",
  "BOT_LANGUAGE": "en"
}
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

## Security

Bot settings are stored in a local `config.json` file next to `bot.py`. Do not upload this file to a public repository because it contains the bot token and host chat ID.

Real `TELEGRAM_BOT_TOKEN`, `HOST_CHAT_ID`, `config.json`, and `data/state.json` should stay only on the user's machine.

For compatibility, the bot can also read environment variables and `.env`, but the recommended setup is `config.json`.

## Avatar

You can use this image as the Telegram bot avatar:

`assets/telegram-bot-avatar.png`
