from __future__ import annotations

import html
import json
import logging
import os
import random
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"
STATE_FILE = ROOT / "data" / "state.json"


def bootstrap_env_value(key: str, default: str = "") -> str:
    value = os.getenv(key)
    if value:
        return value.strip()
    if not ENV_FILE.exists():
        return default

    for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        current_key, current_value = line.split("=", 1)
        if current_key.strip() == key:
            return current_value.strip().strip('"').strip("'")
    return default


def normalize_language(language: Any) -> str:
    language_key = str(language or "ru").strip().lower()
    return language_key if language_key in {"ru", "en"} else "ru"


BOT_LANGUAGE = normalize_language(bootstrap_env_value("BOT_LANGUAGE", "ru"))
MISSIONS_ROOT = ROOT / "missions" / BOT_LANGUAGE
CORPORATE_FILE = MISSIONS_ROOT / "normal" / "corporate.json"
PERSONAL_FILE = MISSIONS_ROOT / "normal" / "personal.json"
CARNOMORPH_CORPORATE_FILE = MISSIONS_ROOT / "carnomorphs" / "corporate.json"
CARNOMORPH_PERSONAL_FILE = MISSIONS_ROOT / "carnomorphs" / "personal.json"


def ui(ru: str, en: str) -> str:
    return en if BOT_LANGUAGE == "en" else ru

NORMAL_MODE = "normal"
CARNOMORPH_MODE = "carnomorphs"
MISSION_MODES = {
    NORMAL_MODE: {
        "label": "Base Nemesis" if BOT_LANGUAGE == "en" else "Обычная Немезида",
        "corporate": CORPORATE_FILE,
        "personal": PERSONAL_FILE,
    },
    CARNOMORPH_MODE: {
        "label": "Carnomorphs" if BOT_LANGUAGE == "en" else "Карноморфы",
        "corporate": CARNOMORPH_CORPORATE_FILE,
        "personal": CARNOMORPH_PERSONAL_FILE,
    },
}

POLL_TIMEOUT = 30
API_RETRY_SECONDS = 3
SPECIAL_PITY_STEP_PERCENT = 10
SPECIAL_GAME_DROUGHT_STEP_PERCENT = 10
SPECIAL_ROTATION_BONUS_PERCENT = 5
SPECIAL_MAX_CHANCE_PERCENT = 90
SPECIAL_ROTATION_KEY = "selected_special_mission_ids"
SPECIAL_DROUGHT_KEY = "special_drought_count"

LOG_FORMAT = "%(asctime)s %(levelname)s %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
log = logging.getLogger("nemesis-missions")

PLAYER_COMMANDS = [
    {"command": "start", "description": ui("Открыть подсказку", "Show help")},
    {"command": "join", "description": ui("Войти в партию по паролю", "Join a game by password")},
    {"command": "leave", "description": ui("Выйти до раздачи миссий", "Leave before mission deal")},
    {"command": "help", "description": ui("Показать команды", "Show commands")},
]

HOST_COMMANDS = [
    {"command": "start", "description": ui("Открыть подсказку", "Show help")},
    {"command": "newgame", "description": ui("Создать партию", "Create a game")},
    {"command": "deal", "description": ui("Раздать миссии", "Deal missions")},
    {"command": "players", "description": ui("Показать игроков", "Show players")},
    {"command": "missions", "description": ui("Показать количество миссий", "Show mission counts")},
    {"command": "endgame", "description": ui("Закрыть партию", "Close the game")},
    {"command": "join", "description": ui("Войти в партию по паролю", "Join a game by password")},
    {"command": "leave", "description": ui("Выйти до раздачи миссий", "Leave before mission deal")},
    {"command": "help", "description": ui("Показать команды", "Show commands")},
]


class BotConfigError(RuntimeError):
    pass


def load_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def get_config() -> dict[str, Any]:
    env_file = load_dotenv(ENV_FILE)
    token = os.getenv("TELEGRAM_BOT_TOKEN") or env_file.get("TELEGRAM_BOT_TOKEN")
    host_chat_id = os.getenv("HOST_CHAT_ID") or env_file.get("HOST_CHAT_ID")

    if not token:
        raise BotConfigError(
            ui(
                "Не найден TELEGRAM_BOT_TOKEN. Создай .env рядом с bot.py и впиши токен.",
                "TELEGRAM_BOT_TOKEN was not found. Create .env next to bot.py and add the token.",
            )
        )

    host_id_int: int | None = None
    if host_chat_id:
        try:
            host_id_int = int(host_chat_id)
        except ValueError as exc:
            raise BotConfigError(ui("HOST_CHAT_ID должен быть числом.", "HOST_CHAT_ID must be a number.")) from exc

    return {"token": token, "host_chat_id": host_id_int}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    text = path.read_text(encoding="utf-8-sig").strip()
    if not text:
        return default
    return json.loads(text)


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp_path.replace(path)


def load_state() -> dict[str, Any]:
    state = load_json(STATE_FILE, {})
    if not isinstance(state, dict):
        state = {}
    state.setdefault("active_game", None)
    state.setdefault("last_completed_game", None)
    state.setdefault("next_game_id", 1)
    state.setdefault("pending_actions", {})
    state.setdefault(SPECIAL_ROTATION_KEY, [])
    state.setdefault(SPECIAL_DROUGHT_KEY, 0)
    return state


def save_state(state: dict[str, Any]) -> None:
    save_json(STATE_FILE, state)


def load_missions(path: Path) -> list[dict[str, Any]]:
    raw = load_json(path, [])
    if not isinstance(raw, list):
        raise ValueError(f"{path.name}: должен быть JSON-список.")

    missions: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"{path.name}: миссия #{index} должна быть объектом.")

        mission_id = str(item.get("id", "")).strip()
        title = str(item.get("title", "")).strip()
        text = str(item.get("text", "")).strip()

        if not mission_id:
            raise ValueError(f"{path.name}: у миссии #{index} нет id.")
        if mission_id in seen_ids:
            raise ValueError(f"{path.name}: повторяется id {mission_id!r}.")
        if title.startswith("СЮДА") or text.startswith("СЮДА"):
            continue
        if not text:
            raise ValueError(f"{path.name}: у миссии {mission_id!r} пустой text.")

        mission: dict[str, Any] = {
            "id": mission_id,
            "title": title,
            "text": text,
            "source": str(item.get("source", "")).strip(),
        }

        requires_player_number = item.get("requires_player_number")
        if requires_player_number is not None:
            try:
                player_number = int(requires_player_number)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"{path.name}: requires_player_number у миссии {mission_id!r} должен быть числом."
                ) from exc
            if player_number < 1:
                raise ValueError(
                    f"{path.name}: requires_player_number у миссии {mission_id!r} должен быть больше 0."
                )
            mission["requires_player_number"] = player_number

        max_player_count = item.get("max_player_count")
        if max_player_count is not None:
            try:
                max_players = int(max_player_count)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"{path.name}: max_player_count у миссии {mission_id!r} должен быть числом."
                ) from exc
            if max_players < 1:
                raise ValueError(
                    f"{path.name}: max_player_count у миссии {mission_id!r} должен быть больше 0."
                )
            mission["max_player_count"] = max_players

        special = item.get("special")
        if special is not None:
            mission["special"] = special

        seen_ids.add(mission_id)
        missions.append(mission)

    return missions


def normalize_game_mode(mode: Any) -> str:
    mode_key = str(mode or NORMAL_MODE).strip().lower()
    return mode_key if mode_key in MISSION_MODES else NORMAL_MODE


def mission_mode_label(mode: Any) -> str:
    mode_key = normalize_game_mode(mode)
    return str(MISSION_MODES[mode_key]["label"])


def mission_files_for_mode(mode: Any) -> tuple[Path, Path]:
    mode_key = normalize_game_mode(mode)
    mode_config = MISSION_MODES[mode_key]
    return Path(mode_config["corporate"]), Path(mode_config["personal"])


def normalize_special_missions_setting(mode: Any, include_specials: Any = None) -> bool:
    if normalize_game_mode(mode) != NORMAL_MODE:
        return False
    if include_specials is None:
        return True
    return bool(include_specials)


def game_special_missions_enabled(game: dict[str, Any]) -> bool:
    return normalize_special_missions_setting(
        game.get("mode"),
        game.get("include_specials", True),
    )


def special_missions_label(include_specials: bool) -> str:
    if include_specials:
        return ui("включены", "enabled")
    return ui("выключены", "disabled")


def mission_count_summary() -> str:
    lines: list[str] = []
    for mode_key, mode_config in MISSION_MODES.items():
        corporate = len(load_missions(Path(mode_config["corporate"])))
        personal = len(load_missions(Path(mode_config["personal"])))
        lines.append(
            ui(
                f"{mode_config['label']}: {corporate} заданий корпорации и {personal} личных целей.",
                f"{mode_config['label']}: {corporate} corporate objectives and {personal} personal objectives.",
            )
        )
    return "\n".join(lines)


def filter_missions_for_player_count(
    missions: list[dict[str, Any]],
    player_count: int,
) -> list[dict[str, Any]]:
    return [
        mission
        for mission in missions
        if int(mission.get("requires_player_number", 0) or 0) <= player_count
        and (
            not int(mission.get("max_player_count", 0) or 0)
            or player_count <= int(mission.get("max_player_count", 0) or 0)
        )
    ]


def mission_special_kind(mission: dict[str, Any]) -> str:
    special = mission.get("special")
    if isinstance(special, str):
        return special.strip()
    if isinstance(special, dict):
        return str(special.get("type", "")).strip()
    return ""


def mission_id(mission: dict[str, Any]) -> str:
    return str(mission.get("id", "")).strip()


def mission_is_special(mission: dict[str, Any]) -> bool:
    return bool(mission_special_kind(mission))


def all_special_mission_ids() -> set[str]:
    return {
        mission_id(mission)
        for mission in load_missions(CORPORATE_FILE) + load_missions(PERSONAL_FILE)
        if mission_is_special(mission) and mission_id(mission)
    }


def current_special_rotation(state: dict[str, Any]) -> set[str]:
    all_ids = all_special_mission_ids()
    raw_used = state.setdefault(SPECIAL_ROTATION_KEY, [])
    if not isinstance(raw_used, list):
        raw_used = []

    used = [str(item).strip() for item in raw_used if str(item).strip() in all_ids]
    if all_ids and set(used) >= all_ids:
        used = []

    state[SPECIAL_ROTATION_KEY] = used
    return set(used)


def remember_selected_special_mission(state: dict[str, Any], mission: dict[str, Any]) -> None:
    special_id = mission_id(mission)
    if not special_id or not mission_is_special(mission):
        return

    all_ids = all_special_mission_ids()
    if special_id not in all_ids:
        return

    used = current_special_rotation(state)
    used.add(special_id)
    state[SPECIAL_ROTATION_KEY] = [] if all_ids and used >= all_ids else sorted(used)
    save_state(state)


def special_pair_chance_percent(
    corporate_pool: list[dict[str, Any]],
    personal_pool: list[dict[str, Any]],
    no_special_streak: int,
    game_drought_count: int,
    rotation_used_count: int,
) -> int:
    if not corporate_pool or not personal_pool:
        return 0

    corporate_specials = sum(1 for mission in corporate_pool if mission_is_special(mission))
    personal_specials = sum(1 for mission in personal_pool if mission_is_special(mission))
    if not corporate_specials and not personal_specials:
        return 0

    corporate_regular_chance = (len(corporate_pool) - corporate_specials) / len(corporate_pool)
    personal_regular_chance = (len(personal_pool) - personal_specials) / len(personal_pool)
    base_chance = round((1 - corporate_regular_chance * personal_regular_chance) * 100)
    boosted_chance = (
        base_chance
        + no_special_streak * SPECIAL_PITY_STEP_PERCENT
        + game_drought_count * SPECIAL_GAME_DROUGHT_STEP_PERCENT
        + rotation_used_count * SPECIAL_ROTATION_BONUS_PERCENT
    )
    return min(SPECIAL_MAX_CHANCE_PERCENT, max(0, boosted_chance))


def take_random_mission(
    pool: list[dict[str, Any]],
    rng: random.Random,
    *,
    special: bool | None = None,
) -> dict[str, Any]:
    candidates = [
        mission
        for mission in pool
        if special is None or mission_is_special(mission) == special
    ]
    if not candidates:
        kind = (
            ui("особых", "special")
            if special
            else ui("обычных", "regular")
            if special is False
            else ui("доступных", "available")
        )
        raise ValueError(
            ui(
                f"Не хватает {kind} миссий для раздачи без повторов.",
                f"Not enough {kind} missions to deal without repeats.",
            )
        )

    mission = rng.choice(candidates)
    pool.remove(mission)
    return mission


def take_mission_pair_with_special(
    corporate_pool: list[dict[str, Any]],
    personal_pool: list[dict[str, Any]],
    rng: random.Random,
) -> tuple[dict[str, Any], dict[str, Any]]:
    special_options = [
        ("corporate", mission)
        for mission in corporate_pool
        if mission_is_special(mission)
    ] + [
        ("personal", mission)
        for mission in personal_pool
        if mission_is_special(mission)
    ]
    if not special_options:
        raise ValueError(ui("Нет доступных особых миссий.", "No special missions are available."))

    mission_kind, special_mission = rng.choice(special_options)
    if mission_kind == "corporate":
        corporate_pool.remove(special_mission)
        return special_mission, take_random_mission(personal_pool, rng, special=False)

    personal_pool.remove(special_mission)
    return take_random_mission(corporate_pool, rng, special=False), special_mission


def draw_mission_pair(
    corporate_pool: list[dict[str, Any]],
    personal_pool: list[dict[str, Any]],
    rng: random.Random,
    *,
    special_already_dealt: bool,
    no_special_streak: int,
    game_drought_count: int,
    rotation_used_count: int,
) -> tuple[dict[str, Any], dict[str, Any], bool]:
    if special_already_dealt:
        return (
            take_random_mission(corporate_pool, rng, special=False),
            take_random_mission(personal_pool, rng, special=False),
            False,
        )

    chance = special_pair_chance_percent(
        corporate_pool,
        personal_pool,
        no_special_streak,
        game_drought_count,
        rotation_used_count,
    )
    if chance and rng.randrange(100) < chance:
        corporate, personal = take_mission_pair_with_special(corporate_pool, personal_pool, rng)
        return corporate, personal, True

    return (
        take_random_mission(corporate_pool, rng, special=False),
        take_random_mission(personal_pool, rng, special=False),
        False,
    )


def deal_randomized_missions(
    players: dict[str, dict[str, Any]],
    corporate_missions: list[dict[str, Any]],
    personal_missions: list[dict[str, Any]],
    state: dict[str, Any],
    rng: random.Random,
    *,
    allow_specials: bool = True,
) -> bool:
    used_special_ids = current_special_rotation(state) if allow_specials else set()
    corporate_pool = [
        mission
        for mission in corporate_missions
        if (
            (allow_specials or not mission_is_special(mission))
            and (not mission_is_special(mission) or mission_id(mission) not in used_special_ids)
        )
    ]
    personal_pool = [
        mission
        for mission in personal_missions
        if (
            (allow_specials or not mission_is_special(mission))
            and (not mission_is_special(mission) or mission_id(mission) not in used_special_ids)
        )
    ]

    player_order = list(players.values())
    rng.shuffle(player_order)
    special_already_dealt = False
    no_special_streak = 0
    game_drought_count = max(0, int(state.get(SPECIAL_DROUGHT_KEY, 0) or 0))
    rotation_used_count = len(used_special_ids)

    for player in player_order:
        if allow_specials:
            corporate, personal, has_special = draw_mission_pair(
                corporate_pool,
                personal_pool,
                rng,
                special_already_dealt=special_already_dealt,
                no_special_streak=no_special_streak,
                game_drought_count=game_drought_count,
                rotation_used_count=rotation_used_count,
            )
        else:
            corporate = take_random_mission(corporate_pool, rng, special=False)
            personal = take_random_mission(personal_pool, rng, special=False)
            has_special = False

        player["corporate"] = corporate
        player["personal"] = personal
        player["chosen"] = None
        player["choice_at"] = None

        if has_special:
            special_already_dealt = True
            no_special_streak = 0
        else:
            no_special_streak += 1

    return special_already_dealt


def esc(value: Any) -> str:
    return html.escape(str(value), quote=False)


def user_label(user: dict[str, Any]) -> str:
    username = user.get("username")
    if username:
        return f"@{username}"

    first_name = user.get("first_name") or ""
    last_name = user.get("last_name") or ""
    full_name = " ".join(part for part in [first_name, last_name] if part).strip()
    return full_name or str(user.get("id", ui("игрок", "player")))


def player_label(player: dict[str, Any]) -> str:
    username = player.get("username")
    if username:
        return f"@{username}"
    return player.get("name") or str(player.get("chat_id", ui("игрок", "player")))


def compact_player(user: dict[str, Any], chat_id: int) -> dict[str, Any]:
    return {
        "chat_id": chat_id,
        "username": user.get("username") or "",
        "name": user_label(user),
        "joined_at": now_iso(),
        "corporate": None,
        "personal": None,
        "chosen": None,
        "choice_at": None,
    }


def is_host(chat_id: int, config: dict[str, Any], state: dict[str, Any]) -> bool:
    configured_host = config.get("host_chat_id")
    if configured_host is not None:
        return chat_id == configured_host

    active_game = state.get("active_game")
    if active_game:
        return chat_id == active_game.get("host_chat_id")

    return True


class TelegramBot:
    def __init__(self, token: str):
        self.base_url = f"https://api.telegram.org/bot{token}/"

    def call(self, method: str, payload: dict[str, Any] | None = None) -> Any:
        data = None
        headers = {"Content-Type": "application/json"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        request = Request(self.base_url + method, data=data, headers=headers)
        try:
            with urlopen(request, timeout=POLL_TIMEOUT + 10) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Telegram API error {exc.code}: {body}") from exc
        except URLError as exc:
            raise RuntimeError(f"Telegram connection error: {exc}") from exc

        result = json.loads(body)
        if not result.get("ok"):
            raise RuntimeError(f"Telegram API returned error: {body}")
        return result.get("result")

    def get_updates(self, offset: int | None) -> list[dict[str, Any]]:
        query = {"timeout": POLL_TIMEOUT, "allowed_updates": json.dumps(["message", "callback_query"])}
        if offset is not None:
            query["offset"] = offset
        url = self.base_url + "getUpdates?" + urlencode(query)
        try:
            with urlopen(url, timeout=POLL_TIMEOUT + 10) as response:
                body = response.read().decode("utf-8")
        except URLError as exc:
            raise RuntimeError(f"Telegram connection error: {exc}") from exc

        result = json.loads(body)
        if not result.get("ok"):
            raise RuntimeError(f"Telegram API returned error: {body}")
        return result.get("result", [])

    def send_message(
        self,
        chat_id: int,
        text: str,
        reply_markup: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        return self.call("sendMessage", payload)

    def edit_reply_markup(
        self,
        chat_id: int,
        message_id: int,
        reply_markup: dict[str, Any] | None,
    ) -> None:
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
        }
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        self.call("editMessageReplyMarkup", payload)

    def answer_callback(self, callback_query_id: str, text: str = "") -> None:
        payload = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        try:
            self.call("answerCallbackQuery", payload)
        except Exception as exc:  # noqa: BLE001
            log.warning("Failed to answer callback query: %s", exc)

    def set_my_commands(
        self,
        commands: list[dict[str, str]],
        scope: dict[str, Any] | None = None,
    ) -> None:
        payload: dict[str, Any] = {"commands": commands}
        if scope is not None:
            payload["scope"] = scope
        self.call("setMyCommands", payload)


def setup_command_menu(bot: TelegramBot, config: dict[str, Any]) -> None:
    bot.set_my_commands(PLAYER_COMMANDS)

    host_chat_id = config.get("host_chat_id")
    if host_chat_id is None:
        log.warning(
            "HOST_CHAT_ID is empty: only player commands were added to the Telegram menu."
        )
        return

    bot.set_my_commands(
        HOST_COMMANDS,
        scope={"type": "chat", "chat_id": host_chat_id},
    )


def help_text(chat_id: int, state: dict[str, Any], config: dict[str, Any]) -> str:
    host_note = ""
    if config.get("host_chat_id") is None:
        host_note = ui(
            (
                "\n\n🔑 Твой chat ID: "
                f"<code>{chat_id}</code>\n"
                "Если хочешь жестко закрепить хоста, впиши его в HOST_CHAT_ID."
            ),
            (
                "\n\n🔑 Your chat ID: "
                f"<code>{chat_id}</code>\n"
                "To lock host controls to this chat, add it to HOST_CHAT_ID."
            ),
        )

    if is_host(chat_id, config, state):
        commands = ui(
            (
                "👑 <b>Команды хоста</b>\n"
                "/newgame — создать партию и выбрать режим\n"
                "/deal — раздать миссии всем участникам\n"
                "/players — посмотреть список игроков\n"
                "/endgame — досрочно закрыть партию\n\n"
                "👤 <b>Команды игрока</b>\n"
                "/join пароль — войти в партию\n"
                "/leave — выйти до раздачи\n"
                "/help — подсказка"
            ),
            (
                "👑 <b>Host Commands</b>\n"
                "/newgame - create a game and choose mode\n"
                "/deal - deal missions to all players\n"
                "/players - show player list\n"
                "/endgame - close the game early\n\n"
                "👤 <b>Player Commands</b>\n"
                "/join password - join a game\n"
                "/leave - leave before missions are dealt\n"
                "/help - show help"
            ),
        )
    else:
        commands = ui(
            (
                "👤 <b>Команды игрока</b>\n"
                "/join пароль — войти в партию\n"
                "/leave — выйти до раздачи\n"
                "/help — подсказка"
            ),
            (
                "👤 <b>Player Commands</b>\n"
                "/join password - join a game\n"
                "/leave - leave before missions are dealt\n"
                "/help - show help"
            ),
        )

    return f"🛰️ <b>Nemesis Missions</b>\n\n{commands}{host_note}"


def active_game_or_none(state: dict[str, Any]) -> dict[str, Any] | None:
    game = state.get("active_game")
    return game if isinstance(game, dict) else None


def set_pending_action(state: dict[str, Any], chat_id: int, action: str) -> None:
    pending = state.setdefault("pending_actions", {})
    pending[str(chat_id)] = {"action": action, "created_at": now_iso()}
    save_state(state)


def pop_pending_action(state: dict[str, Any], chat_id: int) -> str | None:
    pending = state.setdefault("pending_actions", {})
    item = pending.pop(str(chat_id), None)
    save_state(state)
    if not isinstance(item, dict):
        return None
    action = item.get("action")
    return action if isinstance(action, str) else None


def clear_pending_action(state: dict[str, Any], chat_id: int) -> None:
    pending = state.setdefault("pending_actions", {})
    if str(chat_id) in pending:
        pending.pop(str(chat_id), None)
        save_state(state)


def require_host(
    bot: TelegramBot,
    chat_id: int,
    config: dict[str, Any],
    state: dict[str, Any],
) -> bool:
    if is_host(chat_id, config, state):
        return True
    bot.send_message(chat_id, ui("⛔ Эту команду может выполнить только хост.", "⛔ Only the host can use this command."))
    return False


def new_game_mode_keyboard() -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {
                    "text": ui("🔵 Базовая версия", "🔵 Base Nemesis"),
                    "callback_data": f"newgame_mode:{NORMAL_MODE}",
                }
            ],
            [
                {
                    "text": ui("🔴 Карноморфы", "🔴 Carnomorphs"),
                    "callback_data": f"newgame_mode:{CARNOMORPH_MODE}",
                }
            ],
        ]
    }


def special_missions_keyboard() -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {
                    "text": ui("✨ Включить special", "✨ Enable specials"),
                    "callback_data": "newgame_specials:1",
                }
            ],
            [
                {
                    "text": ui("🚫 Без special", "🚫 No specials"),
                    "callback_data": "newgame_specials:0",
                }
            ],
        ]
    }


def prompt_new_game_mode(
    bot: TelegramBot,
    chat_id: int,
    config: dict[str, Any],
    state: dict[str, Any],
) -> None:
    if not require_host(bot, chat_id, config, state):
        return

    if active_game_or_none(state):
        bot.send_message(
            chat_id,
            ui(
                "⚠️ Уже есть активная партия. Заверши ее через /endgame или дождись выбора миссий всеми игроками.",
                "⚠️ There is already an active game. End it with /endgame or wait until all players choose missions.",
            ),
        )
        return

    bot.send_message(
        chat_id,
        ui("🎲 <b>Выбери режим партии.</b>", "🎲 <b>Choose game mode.</b>"),
        reply_markup=new_game_mode_keyboard(),
    )


def prompt_special_missions_mode(
    bot: TelegramBot,
    chat_id: int,
    config: dict[str, Any],
    state: dict[str, Any],
) -> None:
    if not require_host(bot, chat_id, config, state):
        return

    if active_game_or_none(state):
        bot.send_message(
            chat_id,
            ui(
                "⚠️ Уже есть активная партия. Заверши ее через /endgame или дождись выбора миссий всеми игроками.",
                "⚠️ There is already an active game. End it with /endgame or wait until all players choose missions.",
            ),
        )
        return

    bot.send_message(
        chat_id,
        ui(
            "✨ <b>Добавить special-миссии в базовую партию?</b>",
            "✨ <b>Add special missions to the base game?</b>",
        ),
        reply_markup=special_missions_keyboard(),
    )


def choose_new_game_mode(
    bot: TelegramBot,
    callback_query: dict[str, Any],
    config: dict[str, Any],
    state: dict[str, Any],
) -> None:
    callback_id = callback_query["id"]
    data = callback_query.get("data", "")
    message = callback_query.get("message", {})
    user = callback_query.get("from", {})
    chat = message.get("chat", {})
    chat_id = int(chat.get("id") or user.get("id"))
    message_id = message.get("message_id")

    parts = data.split(":", 1)
    if len(parts) != 2 or parts[0] != "newgame_mode":
        bot.answer_callback(callback_id, ui("Неизвестный режим.", "Unknown mode."))
        return

    if not is_host(chat_id, config, state):
        bot.answer_callback(callback_id, ui("Эту кнопку может нажать только хост.", "Only the host can press this button."))
        return

    if active_game_or_none(state):
        bot.answer_callback(callback_id, ui("Уже есть активная партия.", "There is already an active game."))
        bot.send_message(
            chat_id,
            ui(
                "⚠️ Уже есть активная партия. Заверши ее через /endgame или дождись выбора миссий всеми игроками.",
                "⚠️ There is already an active game. End it with /endgame or wait until all players choose missions.",
            ),
        )
        return

    mode = normalize_game_mode(parts[1])
    if message_id:
        try:
            bot.edit_reply_markup(chat_id, int(message_id), reply_markup=None)
        except Exception as exc:  # noqa: BLE001
            log.warning("Failed to remove new game mode buttons: %s", exc)

    bot.answer_callback(callback_id, ui(f"Режим: {mission_mode_label(mode)}", f"Mode: {mission_mode_label(mode)}"))
    if mode == NORMAL_MODE:
        prompt_special_missions_mode(bot, chat_id, config, state)
    else:
        start_game(bot, chat_id, user, [], config, state, mode=mode, include_specials=False)


def choose_special_missions_mode(
    bot: TelegramBot,
    callback_query: dict[str, Any],
    config: dict[str, Any],
    state: dict[str, Any],
) -> None:
    callback_id = callback_query["id"]
    data = callback_query.get("data", "")
    message = callback_query.get("message", {})
    user = callback_query.get("from", {})
    chat = message.get("chat", {})
    chat_id = int(chat.get("id") or user.get("id"))
    message_id = message.get("message_id")

    parts = data.split(":", 1)
    if len(parts) != 2 or parts[0] != "newgame_specials" or parts[1] not in {"0", "1"}:
        bot.answer_callback(callback_id, ui("Неизвестная настройка.", "Unknown setting."))
        return

    if not is_host(chat_id, config, state):
        bot.answer_callback(callback_id, ui("Эту кнопку может нажать только хост.", "Only the host can press this button."))
        return

    if active_game_or_none(state):
        bot.answer_callback(callback_id, ui("Уже есть активная партия.", "There is already an active game."))
        bot.send_message(
            chat_id,
            ui(
                "⚠️ Уже есть активная партия. Заверши ее через /endgame или дождись выбора миссий всеми игроками.",
                "⚠️ There is already an active game. End it with /endgame or wait until all players choose missions.",
            ),
        )
        return

    include_specials = parts[1] == "1"
    if message_id:
        try:
            bot.edit_reply_markup(chat_id, int(message_id), reply_markup=None)
        except Exception as exc:  # noqa: BLE001
            log.warning("Failed to remove special mission buttons: %s", exc)

    bot.answer_callback(
        callback_id,
        ui(
            f"Special-миссии: {special_missions_label(include_specials)}",
            f"Special missions: {special_missions_label(include_specials)}",
        ),
    )
    start_game(
        bot,
        chat_id,
        user,
        [],
        config,
        state,
        mode=NORMAL_MODE,
        include_specials=include_specials,
    )


def start_game(
    bot: TelegramBot,
    chat_id: int,
    user: dict[str, Any],
    args: list[str],
    config: dict[str, Any],
    state: dict[str, Any],
    mode: str = NORMAL_MODE,
    include_specials: bool | None = None,
) -> None:
    if not require_host(bot, chat_id, config, state):
        return

    mode = normalize_game_mode(mode)
    mode_label = mission_mode_label(mode)
    include_specials = normalize_special_missions_setting(mode, include_specials)

    if not args:
        set_pending_action(state, chat_id, f"newgame_password:{mode}:{1 if include_specials else 0}")
        special_line = ""
        if mode == NORMAL_MODE:
            special_line = ui(
                f"\nSpecial-миссии: <b>{esc(special_missions_label(include_specials))}</b>",
                f"\nSpecial missions: <b>{esc(special_missions_label(include_specials))}</b>",
            )
        bot.send_message(
            chat_id,
            ui(
                f"🔐 Напиши пароль для новой партии <b>{esc(mode_label)}</b> следующим сообщением.{special_line}",
                f"🔐 Send the password for the new <b>{esc(mode_label)}</b> game as your next message.{special_line}",
            ),
        )
        return

    if active_game_or_none(state):
        bot.send_message(
            chat_id,
            ui(
                "⚠️ Уже есть активная партия. Заверши ее через /endgame или дождись выбора миссий всеми игроками.",
                "⚠️ There is already an active game. End it with /endgame or wait until all players choose missions.",
            ),
        )
        return

    password = " ".join(args).strip()
    if len(password) < 3:
        bot.send_message(chat_id, ui("Пароль лучше сделать хотя бы из 3 символов.", "Use a password of at least 3 characters."))
        return

    game_id = int(state.get("next_game_id", 1))
    state["next_game_id"] = game_id + 1
    host_id = config.get("host_chat_id") or chat_id
    host_player = compact_player(user, chat_id)

    state["active_game"] = {
        "id": game_id,
        "password": password,
        "host_chat_id": host_id,
        "mode": mode,
        "include_specials": include_specials,
        "status": "registration",
        "created_at": now_iso(),
        "dealt_at": None,
        "players": {str(chat_id): host_player},
    }
    save_state(state)

    special_line = ""
    if mode == NORMAL_MODE:
        special_line = ui(
            f"Special-миссии: <b>{esc(special_missions_label(include_specials))}</b>\n",
            f"Special missions: <b>{esc(special_missions_label(include_specials))}</b>\n",
        )

    bot.send_message(
        chat_id,
        ui(
            "🟢 <b>Партия создана.</b>\n\n"
            f"Режим: <b>{esc(mode_label)}</b>\n"
            f"{special_line}"
            f"Пароль: <code>{esc(password)}</code>\n"
            "Ты уже добавлен как игрок.\n\n"
            "Когда все зайдут через /join, напиши /deal.",
            "🟢 <b>Game created.</b>\n\n"
            f"Mode: <b>{esc(mode_label)}</b>\n"
            f"{special_line}"
            f"Password: <code>{esc(password)}</code>\n"
            "You have already been added as a player.\n\n"
            "When everyone has joined with /join, send /deal.",
        ),
    )


def join_game(
    bot: TelegramBot,
    chat_id: int,
    user: dict[str, Any],
    args: list[str],
    config: dict[str, Any],
    state: dict[str, Any],
) -> None:
    game = active_game_or_none(state)
    if not game:
        bot.send_message(chat_id, ui("Сейчас нет открытой партии. Попроси хоста создать ее через /newgame.", "There is no open game right now. Ask the host to create one with /newgame."))
        return

    if game.get("status") != "registration":
        bot.send_message(chat_id, ui("Раздача уже началась, подключиться к этой партии нельзя.", "Missions have already been dealt, so you cannot join this game."))
        return

    if not args:
        set_pending_action(state, chat_id, "join_password")
        bot.send_message(
            chat_id,
            ui("🔐 Напиши пароль партии следующим сообщением.", "🔐 Send the game password as your next message."),
        )
        return

    password = " ".join(args).strip()
    if password != game.get("password"):
        bot.send_message(chat_id, ui("🚫 Пароль не подошел.", "🚫 Wrong password."))
        return

    players = game.setdefault("players", {})
    player_key = str(chat_id)
    already_joined = player_key in players
    if already_joined:
        player = players[player_key]
        player["username"] = user.get("username") or player.get("username", "")
        player["name"] = user_label(user)
        save_state(state)
        bot.send_message(chat_id, ui("Ты уже в этой партии. Ждем раздачу миссий.", "You are already in this game. Waiting for missions to be dealt."))
        return

    player = compact_player(user, chat_id)
    players[player_key] = player
    save_state(state)

    bot.send_message(chat_id, ui("✅ Регистрация принята. Ждем, пока хост раздаст миссии.", "✅ Registration accepted. Waiting for the host to deal missions."))

    host_chat_id = int(game["host_chat_id"])
    if host_chat_id != chat_id:
        bot.send_message(
            host_chat_id,
            ui(
                f"➕ <b>{esc(player_label(player))}</b> присоединился к партии.\n"
                f"Игроков сейчас: <b>{len(players)}</b>.",
                f"➕ <b>{esc(player_label(player))}</b> joined the game.\n"
                f"Players now: <b>{len(players)}</b>.",
            ),
        )


def leave_game(
    bot: TelegramBot,
    chat_id: int,
    state: dict[str, Any],
) -> None:
    game = active_game_or_none(state)
    if not game:
        bot.send_message(chat_id, ui("Сейчас нет активной партии.", "There is no active game right now."))
        return

    players = game.setdefault("players", {})
    player_key = str(chat_id)
    player = players.get(player_key)
    if not player:
        bot.send_message(chat_id, ui("Ты не числишься в текущей партии.", "You are not registered in the current game."))
        return

    if game.get("status") != "registration":
        bot.send_message(chat_id, ui("После раздачи миссий выйти уже нельзя. Хост может закрыть партию через /endgame.", "After missions are dealt, players cannot leave. The host can close the game with /endgame."))
        return

    if chat_id == int(game["host_chat_id"]):
        bot.send_message(chat_id, ui("Хост не выходит из партии отдельно. Если надо сбросить стол, используй /endgame.", "The host cannot leave the game separately. Use /endgame to reset the table."))
        return

    removed = players.pop(player_key)
    save_state(state)
    bot.send_message(chat_id, ui("🚪 Ты вышел из партии.", "🚪 You left the game."))
    bot.send_message(
        int(game["host_chat_id"]),
        ui(
            f"➖ <b>{esc(player_label(removed))}</b> покинул партию.\n"
            f"Игроков сейчас: <b>{len(players)}</b>.",
            f"➖ <b>{esc(player_label(removed))}</b> left the game.\n"
            f"Players now: <b>{len(players)}</b>.",
        ),
    )


def players_text(state: dict[str, Any]) -> str:
    game = active_game_or_none(state)
    if not game:
        return ui("Сейчас нет активной партии.", "There is no active game right now.")

    players = list(game.get("players", {}).values())
    if not players:
        return ui("В партии пока нет игроков.", "There are no players in the game yet.")

    status = (
        ui("регистрация", "registration")
        if game.get("status") == "registration"
        else ui("миссии розданы", "missions dealt")
    )
    lines = [
        ui(f"🎲 <b>Партия #{game.get('id')}</b>", f"🎲 <b>Game #{game.get('id')}</b>"),
        ui(
            f"Режим: <b>{esc(mission_mode_label(game.get('mode')))}</b>",
            f"Mode: <b>{esc(mission_mode_label(game.get('mode')))}</b>",
        ),
    ]
    if normalize_game_mode(game.get("mode")) == NORMAL_MODE:
        lines.append(
            ui(
                f"Special-миссии: <b>{esc(special_missions_label(game_special_missions_enabled(game)))}</b>",
                f"Special missions: <b>{esc(special_missions_label(game_special_missions_enabled(game)))}</b>",
            )
        )
    lines.extend(
        [
            ui(f"Статус: <b>{esc(status)}</b>", f"Status: <b>{esc(status)}</b>"),
            ui(f"Игроков: <b>{len(players)}</b>", f"Players: <b>{len(players)}</b>"),
            "",
        ]
    )
    for index, player in enumerate(players, start=1):
        chosen = player.get("chosen")
        if chosen == "corporate":
            marker = ui("🏢 выбрал", "🏢 chosen")
        elif chosen == "personal":
            marker = ui("🧬 выбрал", "🧬 chosen")
        elif game.get("status") == "dealt":
            marker = ui("⏳ выбирает", "⏳ choosing")
        else:
            marker = ui("✅ в игре", "✅ in game")
        lines.append(
            ui(
                f"{index}. {esc(player_label(player))} — {marker}",
                f"{index}. {esc(player_label(player))} - {marker}",
            )
        )
    return "\n".join(lines)


def mission_block(kind: str, mission: dict[str, str]) -> str:
    if kind == "corporate":
        label = ui("🏢 <b>Задание корпорации:</b>", "🏢 <b>Corporate objective:</b>")
    else:
        label = ui("🧬 <b>Личная цель:</b>", "🧬 <b>Personal objective:</b>")

    title = mission.get("title", "").strip()
    title_line = f"\n<b>{esc(title)}</b>" if title else ""
    return f"{label}{title_line}\n{esc(mission['text'])}"


def dealt_message(corporate: dict[str, str], personal: dict[str, str]) -> str:
    return (
        ui("📡 <b>Твои миссии получены.</b>\n\n", "📡 <b>Your missions are ready.</b>\n\n")
        + f"{mission_block('corporate', corporate)}\n\n"
        + f"{mission_block('personal', personal)}\n\n"
        + ui(
            "Когда придет момент выбора, нажми одну из кнопок ниже.",
            "When it is time to choose, press one of the buttons below.",
        )
    )


def queue_special_choice_event(
    state: dict[str, Any],
    game: dict[str, Any],
    player: dict[str, Any],
    kind: str,
    mission: dict[str, Any],
) -> None:
    special_kind = mission_special_kind(mission)
    if not special_kind:
        return

    player_chat_id = int(player["chat_id"])
    player_name = player_label(player)
    event = {
        "type": special_kind,
        "player_chat_id": player_chat_id,
        "player_name": player_name,
        "mission_kind": kind,
        "mission": mission,
        "mission_id": mission.get("id"),
        "mission_title": mission.get("title", ""),
        "created_at": now_iso(),
    }
    game.setdefault("special_events", []).append(event)
    save_state(state)


def send_hunt_target_event(
    bot: TelegramBot,
    state: dict[str, Any],
    game: dict[str, Any],
    event: dict[str, Any],
    mission: dict[str, Any],
) -> None:
    players = game.get("players", {})
    target_chat_id = int(event.get("player_chat_id") or event.get("target_chat_id"))
    target_name = str(event.get("player_name") or event.get("target_name") or target_chat_id)

    target_message = ui(
        (
            "🚨 <b>Миссия раскрыта.</b>\n\n"
            "Твоя цель стала известна всем игрокам.\n\n"
            f"{mission_block('personal', mission)}"
        ),
        (
            "🚨 <b>Mission revealed.</b>\n\n"
            "Your objective is now known to all players.\n\n"
            f"{mission_block('personal', mission)}"
        ),
    )
    hunter_message = ui(
        (
            "🚨 <b>Протокол ликвидации активирован.</b>\n\n"
            f"📡 <b>{esc(target_name)}</b> раскрыл(а) уникальную личную цель.\n\n"
            f"{mission_block('personal', mission)}"
        ),
        (
            "🚨 <b>Liquidation protocol activated.</b>\n\n"
            f"📡 <b>{esc(target_name)}</b> revealed a unique personal objective.\n\n"
            f"{mission_block('personal', mission)}"
        ),
    )

    for other in players.values():
        other_chat_id = int(other["chat_id"])
        try:
            if other_chat_id != target_chat_id:
                bot.send_message(other_chat_id, hunter_message)
            else:
                bot.send_message(other_chat_id, target_message)
        except Exception as exc:  # noqa: BLE001
            log.warning("Failed to send hunt target event to %s: %s", player_label(other), exc)

    host_chat_id = int(game["host_chat_id"])
    try:
        bot.send_message(
            host_chat_id,
            ui(
                "👑 <b>Хост-уведомление:</b>\n"
                f"{esc(target_name)} активировал(а) уникальную миссию. "
                "Если этот персонаж погибнет, миссии остальных игроков считаются выполненными.",
                "👑 <b>Host notice:</b>\n"
                f"{esc(target_name)} activated a unique mission. "
                "If this character dies, the other players' missions count as completed.",
            ),
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Failed to notify host about hunt target event: %s", exc)


def send_host_special_choice_event(
    bot: TelegramBot,
    game: dict[str, Any],
    event: dict[str, Any],
    mission: dict[str, Any],
) -> None:
    player_name = str(event.get("player_name") or event.get("player_chat_id") or "игрок")
    try:
        bot.send_message(
            int(game["host_chat_id"]),
            ui(
                f"📌 <b>{esc(player_name)}</b> выбрал(а) особую миссию <b>{esc(mission.get('title', ''))}</b>.",
                f"📌 <b>{esc(player_name)}</b> chose the special mission <b>{esc(mission.get('title', ''))}</b>.",
            ),
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Failed to notify host about special mission choice: %s", exc)


def dispatch_special_choice_events(
    bot: TelegramBot,
    state: dict[str, Any],
    game: dict[str, Any],
) -> None:
    events = game.get("special_events", [])
    if not events:
        return

    changed = False
    for event in events:
        if event.get("delivered_at"):
            continue

        event_type = str(event.get("type", "")).strip()
        mission = event.get("mission")
        if not isinstance(mission, dict):
            continue

        if event_type == "hunt_target":
            send_hunt_target_event(bot, state, game, event, mission)
        else:
            send_host_special_choice_event(bot, game, event, mission)

        event["delivered_at"] = now_iso()
        changed = True

    if changed:
        save_state(state)


def choice_keyboard(game_id: int) -> dict[str, Any]:
    return {
        "inline_keyboard": [
            [
                {
                    "text": ui("🏢 Задание корпорации", "🏢 Corporate objective"),
                    "callback_data": f"choose:{game_id}:corporate",
                }
            ],
            [
                {
                    "text": ui("🧬 Личная цель", "🧬 Personal objective"),
                    "callback_data": f"choose:{game_id}:personal",
                }
            ],
        ]
    }


def deal_missions(
    bot: TelegramBot,
    chat_id: int,
    config: dict[str, Any],
    state: dict[str, Any],
) -> None:
    if not require_host(bot, chat_id, config, state):
        return

    game = active_game_or_none(state)
    if not game:
        bot.send_message(chat_id, ui("Сейчас нет активной партии. Создай ее через /newgame.", "There is no active game right now. Create one with /newgame."))
        return

    if game.get("status") != "registration":
        bot.send_message(chat_id, ui("Миссии уже розданы.", "Missions have already been dealt."))
        return

    players = game.get("players", {})
    if not players:
        bot.send_message(chat_id, ui("В партии пока нет игроков.", "There are no players in the game yet."))
        return

    player_count = len(players)
    mode = normalize_game_mode(game.get("mode"))
    mode_label = mission_mode_label(mode)
    include_specials = game_special_missions_enabled(game)
    corporate_file, personal_file = mission_files_for_mode(mode)
    corporate_missions = filter_missions_for_player_count(
        load_missions(corporate_file),
        player_count,
    )
    personal_missions = filter_missions_for_player_count(
        load_missions(personal_file),
        player_count,
    )
    if not include_specials:
        corporate_missions = [
            mission for mission in corporate_missions if not mission_is_special(mission)
        ]
        personal_missions = [
            mission for mission in personal_missions if not mission_is_special(mission)
        ]

    supports_specials = include_specials and any(
        mission_is_special(mission)
        for mission in corporate_missions + personal_missions
    )

    used_special_ids = current_special_rotation(state) if supports_specials else set()
    available_corporate_missions = [
        mission
        for mission in corporate_missions
        if not mission_is_special(mission) or mission_id(mission) not in used_special_ids
    ]
    available_personal_missions = [
        mission
        for mission in personal_missions
        if not mission_is_special(mission) or mission_id(mission) not in used_special_ids
    ]

    if (
        len(available_corporate_missions) < player_count
        or len(available_personal_missions) < player_count
    ):
        bot.send_message(
            chat_id,
            ui(
                "⚠️ Не хватает миссий для раздачи без повторов.\n\n"
                f"Игроков: <b>{player_count}</b>\n"
                f"Режим: <b>{esc(mode_label)}</b>\n"
                + (
                    f"Special-миссии: <b>{esc(special_missions_label(include_specials))}</b>\n"
                    if mode == NORMAL_MODE
                    else ""
                )
                + f"Доступных заданий корпорации: <b>{len(available_corporate_missions)}</b>\n"
                f"Доступных личных целей: <b>{len(available_personal_missions)}</b>\n\n"
                f"Добавь карточки в {esc(str(corporate_file))} и {esc(str(personal_file))}.",
                "⚠️ Not enough missions to deal without repeats.\n\n"
                f"Players: <b>{player_count}</b>\n"
                f"Mode: <b>{esc(mode_label)}</b>\n"
                + (
                    f"Special missions: <b>{esc(special_missions_label(include_specials))}</b>\n"
                    if mode == NORMAL_MODE
                    else ""
                )
                + f"Available corporate objectives: <b>{len(available_corporate_missions)}</b>\n"
                f"Available personal objectives: <b>{len(available_personal_missions)}</b>\n\n"
                f"Add cards to {esc(str(corporate_file))} and {esc(str(personal_file))}.",
            ),
        )
        return

    rng = random.SystemRandom()
    try:
        special_was_dealt = deal_randomized_missions(
            players,
            corporate_missions,
            personal_missions,
            state,
            rng,
            allow_specials=supports_specials,
        )
    except ValueError as exc:
        bot.send_message(chat_id, f"⚠️ {esc(exc)}")
        return

    game["status"] = "dealt"
    game["dealt_at"] = now_iso()
    if supports_specials:
        if special_was_dealt:
            state[SPECIAL_DROUGHT_KEY] = 0
        else:
            state[SPECIAL_DROUGHT_KEY] = max(0, int(state.get(SPECIAL_DROUGHT_KEY, 0) or 0)) + 1

    save_state(state)

    delivered = 0
    failed: list[str] = []
    for player in players.values():
        try:
            message = bot.send_message(
                int(player["chat_id"]),
                dealt_message(player["corporate"], player["personal"]),
                reply_markup=choice_keyboard(int(game["id"])),
            )
            player["mission_message_id"] = message.get("message_id")
            delivered += 1
        except Exception as exc:  # noqa: BLE001
            log.exception("Failed to send missions to %s", player_label(player))
            failed.append(f"{player_label(player)}: {exc}")

    save_state(state)

    if failed:
        bot.send_message(
            chat_id,
            ui("⚠️ Миссии розданы не всем.\n\n", "⚠️ Missions were not delivered to everyone.\n\n")
            + "\n".join(esc(item) for item in failed),
        )
    else:
        bot.send_message(
            chat_id,
            ui(
                f"🎴 <b>Миссии розданы.</b>\n"
                f"Режим: <b>{esc(mode_label)}</b>\n"
                + (
                    f"Special-миссии: <b>{esc(special_missions_label(include_specials))}</b>\n"
                    if mode == NORMAL_MODE
                    else ""
                )
                + f"Игроков: <b>{delivered}</b>.\n"
                "Теперь ждем, пока каждый нажмет свой выбор.",
                f"🎴 <b>Missions dealt.</b>\n"
                f"Mode: <b>{esc(mode_label)}</b>\n"
                + (
                    f"Special missions: <b>{esc(special_missions_label(include_specials))}</b>\n"
                    if mode == NORMAL_MODE
                    else ""
                )
                + f"Players: <b>{delivered}</b>.\n"
                "Now wait until every player presses their choice.",
            ),
        )


def complete_game_if_ready(bot: TelegramBot, state: dict[str, Any]) -> None:
    game = active_game_or_none(state)
    if not game or game.get("status") != "dealt":
        return

    players = game.get("players", {})
    if not players:
        return

    if any(not player.get("chosen") for player in players.values()):
        return

    dispatch_special_choice_events(bot, state, game)

    completed_game = {
        "id": game.get("id"),
        "completed_at": now_iso(),
        "player_count": len(players),
        "mode": normalize_game_mode(game.get("mode")),
        "include_specials": game_special_missions_enabled(game),
    }
    state["last_completed_game"] = completed_game
    state["active_game"] = None
    save_state(state)

    bot.send_message(
        int(game["host_chat_id"]),
        ui(
            "✅ <b>Все миссии определены.</b>\n\n"
            "Для бота партия завершена. Новую можно создать через /newgame.",
            "✅ <b>All missions have been chosen.</b>\n\n"
            "For the bot, this game is complete. You can create a new one with /newgame.",
        ),
    )


def choose_mission(
    bot: TelegramBot,
    callback_query: dict[str, Any],
    state: dict[str, Any],
) -> None:
    callback_id = callback_query["id"]
    data = callback_query.get("data", "")
    message = callback_query.get("message", {})
    user = callback_query.get("from", {})
    chat = message.get("chat", {})
    chat_id = int(chat.get("id") or user.get("id"))
    message_id = message.get("message_id")

    parts = data.split(":")
    if len(parts) != 3 or parts[0] != "choose" or parts[2] not in {"corporate", "personal"}:
        bot.answer_callback(callback_id, ui("Неизвестная кнопка.", "Unknown button."))
        return

    game_id = int(parts[1])
    choice = parts[2]
    game = active_game_or_none(state)
    if not game:
        bot.answer_callback(callback_id, ui("Партия уже завершена.", "This game is already complete."))
        return

    if int(game.get("id", -1)) != game_id:
        bot.answer_callback(callback_id, ui("Это кнопка от другой партии.", "This button belongs to another game."))
        return

    if game.get("status") != "dealt":
        bot.answer_callback(callback_id, ui("Выбор еще не открыт.", "Choosing is not open yet."))
        return

    players = game.get("players", {})
    player = players.get(str(chat_id))
    if not player:
        bot.answer_callback(callback_id, ui("Ты не числишься в этой партии.", "You are not registered in this game."))
        return

    if player.get("chosen"):
        bot.answer_callback(callback_id, ui("Ты уже выбрал(а) миссию.", "You have already chosen a mission."))
        return

    mission = player.get(choice)
    if not mission:
        bot.answer_callback(callback_id, ui("Миссия не найдена.", "Mission not found."))
        return
    player["chosen"] = choice
    player["choice_at"] = now_iso()
    save_state(state)

    if message_id:
        try:
            bot.edit_reply_markup(chat_id, int(message_id), reply_markup=None)
        except Exception as exc:  # noqa: BLE001
            log.warning("Failed to remove choice buttons: %s", exc)

    bot.answer_callback(callback_id, ui("Выбор сохранен.", "Choice saved."))

    kind_label = (
        ui("задание корпорации", "corporate objective")
        if choice == "corporate"
        else ui("личную цель", "personal objective")
    )
    bot.send_message(
        chat_id,
        ui(
            f"✅ <b>Ты выбрал(а) {esc(kind_label)}.</b>\n\n{mission_block(choice, mission)}",
            f"✅ <b>You chose the {esc(kind_label)}.</b>\n\n{mission_block(choice, mission)}",
        ),
    )

    if mission_special_kind(mission):
        remember_selected_special_mission(state, mission)
        queue_special_choice_event(state, game, player, choice, mission)

    remaining = [
        player_label(other)
        for other in players.values()
        if not other.get("chosen")
    ]
    host_chat_id = int(game["host_chat_id"])
    if remaining:
        bot.send_message(
            host_chat_id,
            ui(
                f"☑️ <b>{esc(player_label(player))}</b> выбрал(а) миссию.\n"
                f"Осталось выбрать: <b>{len(remaining)}</b>.",
                f"☑️ <b>{esc(player_label(player))}</b> chose a mission.\n"
                f"Still choosing: <b>{len(remaining)}</b>.",
            ),
        )

    complete_game_if_ready(bot, state)


def end_game(
    bot: TelegramBot,
    chat_id: int,
    config: dict[str, Any],
    state: dict[str, Any],
) -> None:
    if not require_host(bot, chat_id, config, state):
        return

    game = active_game_or_none(state)
    if not game:
        bot.send_message(chat_id, ui("Сейчас нет активной партии.", "There is no active game right now."))
        return

    players = list(game.get("players", {}).values())
    state["active_game"] = None
    state["last_completed_game"] = {
        "id": game.get("id"),
        "completed_at": now_iso(),
        "player_count": len(players),
        "mode": normalize_game_mode(game.get("mode")),
        "include_specials": game_special_missions_enabled(game),
        "closed_by_host": True,
    }
    save_state(state)

    for player in players:
        player_chat_id = int(player["chat_id"])
        if player_chat_id == chat_id:
            continue
        try:
            bot.send_message(player_chat_id, ui("🛑 Хост завершил текущую партию.", "🛑 The host closed the current game."))
        except Exception:
            log.exception("Failed to notify player about game end")

    bot.send_message(chat_id, ui("🛑 Партия закрыта. Можно создать новую через /newgame.", "🛑 Game closed. You can create a new one with /newgame."))


def parse_command(text: str) -> tuple[str, list[str]]:
    text = text.strip()
    if not text.startswith("/"):
        return "", []
    parts = text.split()
    command = parts[0].split("@", 1)[0].lower()
    return command, parts[1:]


def handle_pending_message(
    bot: TelegramBot,
    chat_id: int,
    user: dict[str, Any],
    text: str,
    config: dict[str, Any],
    state: dict[str, Any],
) -> bool:
    action = pop_pending_action(state, chat_id)
    if action is None:
        return False

    password = text.strip()
    if not password:
        bot.send_message(chat_id, ui("Пароль пустой. Нажми команду еще раз и введи пароль.", "The password is empty. Press the command again and enter a password."))
        return True

    if action == "newgame_password":
        start_game(bot, chat_id, user, [password], config, state)
        return True

    if action.startswith("newgame_password:"):
        parts = action.split(":")
        mode = parts[1] if len(parts) > 1 else NORMAL_MODE
        include_specials: bool | None = None
        if len(parts) > 2 and parts[2] in {"0", "1"}:
            include_specials = parts[2] == "1"
        start_game(
            bot,
            chat_id,
            user,
            [password],
            config,
            state,
            mode=mode,
            include_specials=include_specials,
        )
        return True

    if action == "join_password":
        join_game(bot, chat_id, user, [password], config, state)
        return True

    bot.send_message(chat_id, ui("Не понял, что нужно сделать. Нажми команду еще раз.", "I did not understand what to do. Press the command again."))
    return True


def handle_message(
    bot: TelegramBot,
    message: dict[str, Any],
    config: dict[str, Any],
    state: dict[str, Any],
) -> None:
    chat = message.get("chat", {})
    user = message.get("from", {})
    chat_id = int(chat["id"])
    text = message.get("text", "") or ""
    command, args = parse_command(text)

    if command:
        clear_pending_action(state, chat_id)
    elif handle_pending_message(bot, chat_id, user, text, config, state):
        return

    if command in {"/start", "/help"}:
        bot.send_message(chat_id, help_text(chat_id, state, config))
    elif command == "/newgame":
        prompt_new_game_mode(bot, chat_id, config, state)
    elif command == "/join":
        join_game(bot, chat_id, user, args, config, state)
    elif command == "/leave":
        leave_game(bot, chat_id, state)
    elif command == "/players":
        if require_host(bot, chat_id, config, state):
            bot.send_message(chat_id, players_text(state))
    elif command == "/deal":
        deal_missions(bot, chat_id, config, state)
    elif command == "/endgame":
        end_game(bot, chat_id, config, state)
    elif command == "/missions":
        if require_host(bot, chat_id, config, state):
            bot.send_message(chat_id, mission_count_summary())
    elif text.startswith("/"):
        bot.send_message(chat_id, ui("Не знаю такую команду. Напиши /help.", "Unknown command. Send /help."))
    else:
        bot.send_message(chat_id, ui("Напиши /help, чтобы увидеть команды.", "Send /help to see commands."))


def handle_update(
    bot: TelegramBot,
    update: dict[str, Any],
    config: dict[str, Any],
    state: dict[str, Any],
) -> None:
    if "message" in update:
        handle_message(bot, update["message"], config, state)
    elif "callback_query" in update:
        data = update["callback_query"].get("data", "")
        if data.startswith("newgame_mode:"):
            choose_new_game_mode(bot, update["callback_query"], config, state)
        elif data.startswith("newgame_specials:"):
            choose_special_missions_mode(bot, update["callback_query"], config, state)
        else:
            choose_mission(bot, update["callback_query"], state)


def validate_startup() -> None:
    for mode_config in MISSION_MODES.values():
        corporate_file = Path(mode_config["corporate"])
        personal_file = Path(mode_config["personal"])
        corporate = load_missions(corporate_file)
        personal = load_missions(personal_file)
        if not corporate:
            raise BotConfigError(ui(f"{corporate_file} пустой.", f"{corporate_file} is empty."))
        if not personal:
            raise BotConfigError(ui(f"{personal_file} пустой.", f"{personal_file} is empty."))


def run() -> None:
    try:
        config = get_config()
        validate_startup()
    except (BotConfigError, ValueError, json.JSONDecodeError) as exc:
        log.error("%s", exc)
        sys.exit(1)

    bot = TelegramBot(config["token"])
    try:
        setup_command_menu(bot, config)
    except Exception:
        log.exception("Failed to update Telegram command menu")

    state = load_state()
    offset: int | None = None
    should_stop = False

    def stop_handler(signum: int, frame: Any) -> None:  # noqa: ARG001
        nonlocal should_stop
        should_stop = True

    signal.signal(signal.SIGINT, stop_handler)
    signal.signal(signal.SIGTERM, stop_handler)

    log.info("Nemesis Missions bot started. %s", mission_count_summary())
    while not should_stop:
        try:
            updates = bot.get_updates(offset)
            for update in updates:
                offset = int(update["update_id"]) + 1
                state = load_state()
                try:
                    handle_update(bot, update, config, state)
                except Exception:
                    log.exception("Failed to handle update %s", update.get("update_id"))
        except Exception:
            log.exception("Polling failed")
            time.sleep(API_RETRY_SECONDS)

    log.info("Nemesis Missions bot stopped.")


if __name__ == "__main__":
    run()
