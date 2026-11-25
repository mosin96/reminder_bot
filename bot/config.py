from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

load_dotenv()


def _valid_timezone(name: str) -> str:
    try:
        return ZoneInfo(name).key
    except (ZoneInfoNotFoundError, ValueError):
        return "Europe/Moscow"


@dataclass(frozen=True)
class Config:
    bot_token: str
    db_path: Path
    default_tz: str
    tick_seconds: float

    @classmethod
    def from_env(cls) -> "Config":
        token = os.getenv("BOT_TOKEN", "").strip()
        if not token:
            raise RuntimeError(
                "BOT_TOKEN не задан. Скопируйте .env.example в .env и укажите токен из @BotFather."
            )

        db_path = Path(os.getenv("DB_PATH", "data/bot.db") or "data/bot.db").expanduser()
        default_tz = _valid_timezone(
            os.getenv("DEFAULT_TZ", "Europe/Moscow").strip() or "Europe/Moscow"
        )

        try:
            tick_seconds = float(os.getenv("TICK_SECONDS", "15"))
        except ValueError:
            tick_seconds = 15.0

        return cls(
            bot_token=token,
            db_path=db_path,
            default_tz=default_tz,
            tick_seconds=max(tick_seconds, 1.0),
        )
