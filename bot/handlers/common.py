from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router(name="common")

HELP_TEXT = (
    "🤖 <b>Бот-напоминальщик</b>\n\n"
    "Умеет напоминать о делах в личке и в групповых чатах. "
    "У каждого чата свои напоминания.\n\n"
    "<b>Команды</b>\n"
    "/remind — создать напоминание\n"
    "/list — напоминания этого чата\n"
    "/cancel &lt;номер&gt; — отменить напоминание\n"
    "/timezone — часовой пояс чата\n"
    "/help — эта справка\n\n"
    "<b>Форматы времени</b>\n"
    "• <code>через 10 минут</code>\n"
    "• <code>завтра в 9:00</code>\n"
    "• <code>25.11 18:30</code>\n"
    "• <code>18:30</code> — сегодня или завтра\n\n"
    "Повторять можно каждый день, по будням, по выбранным дням недели "
    "или раз в месяц в заданное число.\n\n"
    "В группах пишите <code>@username</code> прямо в тексте — бот упомянет участника. "
    "Если включить подтверждение, напоминание будет повторяться, пока его не нажмут."
)


@router.message(Command("start"))
async def start_command(message: Message) -> None:
    text = HELP_TEXT
    if message.chat.type != "private":
        text = (
            "👋 Я на связи в этом чате.\n\n"
            "Создать напоминание: /remind\n"
            "Список напоминаний чата: /list\n\n"
            + HELP_TEXT
        )
    await message.answer(text)


@router.message(Command("help"))
async def help_command(message: Message) -> None:
    await message.answer(HELP_TEXT)
