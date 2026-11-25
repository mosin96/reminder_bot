from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from .config import Config
from .db import Database
from .handlers import common, confirm, create, manage
from .middlewares import DbMiddleware
from .scheduler import scheduler_loop

logger = logging.getLogger(__name__)

BOT_COMMANDS = [
    BotCommand(command="remind", description="Создать напоминание"),
    BotCommand(command="list", description="Напоминания этого чата"),
    BotCommand(command="cancel", description="Отменить напоминание"),
    BotCommand(command="timezone", description="Часовой пояс чата"),
    BotCommand(command="help", description="Справка"),
]


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    config = Config.from_env()
    db = Database(config.db_path, default_tz=config.default_tz)
    await db.connect()

    bot = Bot(
        config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher(storage=MemoryStorage())

    middleware = DbMiddleware(db)
    dispatcher.message.middleware(middleware)
    dispatcher.callback_query.middleware(middleware)

    dispatcher.include_router(common.router)
    dispatcher.include_router(manage.router)
    dispatcher.include_router(confirm.router)
    dispatcher.include_router(create.router)

    try:
        await bot.set_my_commands(BOT_COMMANDS)
    except Exception:
        logger.warning("Не удалось установить меню команд", exc_info=True)

    scheduler_task = asyncio.create_task(
        scheduler_loop(bot, db, config.tick_seconds), name="reminder-scheduler"
    )
    logger.info("Бот запущен, база: %s, часовой пояс по умолчанию: %s", db.path, db.default_tz)

    try:
        await dispatcher.start_polling(
            bot,
            allowed_updates=dispatcher.resolve_used_update_types(),
        )
    finally:
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass
        await db.close()
        await bot.session.close()
        logger.info("Бот остановлен")
