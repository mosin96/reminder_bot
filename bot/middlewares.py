from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

from .db import Database

logger = logging.getLogger(__name__)


class DbMiddleware(BaseMiddleware):
    """Добавляет db и chat_tz в данные хендлеров и заводит чат в БД."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self._seen_chats: set[int] = set()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        data["db"] = self.db

        chat = getattr(event, "chat", None)
        if chat is None:
            message = getattr(event, "message", None)
            if message is not None:
                chat = message.chat

        if chat is None:
            data["chat_tz"] = self.db.default_tz
            return await handler(event, data)

        try:
            if chat.id not in self._seen_chats:
                data["chat_tz"] = await self.db.upsert_chat(
                    chat.id, getattr(chat, "title", None)
                )
                self._seen_chats.add(chat.id)
            else:
                data["chat_tz"] = await self.db.get_timezone(chat.id)
        except Exception:
            logger.exception("Не удалось обновить чат %s", chat.id)
            data["chat_tz"] = self.db.default_tz

        return await handler(event, data)
