from __future__ import annotations

from zoneinfo import ZoneInfo

from aiogram import Bot, F, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..db import Database
from ..keyboards import list_kb
from ..utils.text import attempts_word, describe_schedule, escape_html
from ..utils.timeparse import format_local, parse_timezone

router = Router(name="manage")


async def _can_manage(bot: Bot, chat, reminder, user_id: int) -> bool:
    if reminder["author_id"] == user_id:
        return True
    if chat.type == ChatType.PRIVATE:
        return False
    try:
        member = await bot.get_chat_member(chat.id, user_id)
    except TelegramAPIError:
        return False
    return member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR)


async def _render_list(db: Database, chat_id: int, tz: ZoneInfo):
    reminders = await db.list_active_reminders(chat_id)
    if not reminders:
        return "В этом чате нет активных напоминаний.\n\nСоздать: /remind", None

    lines = ["🗒 <b>Активные напоминания этого чата</b>", ""]
    for reminder in reminders:
        lines.append(f"<b>#{reminder['id']}</b> — {describe_schedule(reminder, tz)}")
        lines.append(f"   {escape_html(reminder['text'])}")
        details: list[str] = []
        if reminder["confirm_required"]:
            details.append(
                f"подтверждение: повтор через {reminder['confirm_interval_min']} мин, "
                f"до {reminder['max_attempts']} {attempts_word(reminder['max_attempts'])}"
            )
        if reminder["recurrence"] != "once":
            details.append(f"следующее: {format_local(reminder['next_run_at'], tz)}")
        if details:
            lines.append(f"   <i>{'; '.join(details)}</i>")
        lines.append("")

    return "\n".join(lines).strip(), list_kb(reminders[:20])


@router.message(Command("list"))
async def list_command(message: Message, db: Database, chat_tz: str) -> None:
    text, keyboard = await _render_list(db, message.chat.id, ZoneInfo(chat_tz))
    await message.answer(text, reply_markup=keyboard)


@router.message(Command("cancel"))
async def cancel_command(
    message: Message, state: FSMContext, db: Database, bot: Bot
) -> None:
    if await state.get_state() is not None:
        await state.clear()
        await message.answer("✖️ Диалог отменён.")
        return

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "Укажите номер напоминания: <code>/cancel 12</code>\n"
            "Посмотреть список: /list"
        )
        return

    raw = parts[1].strip().lstrip("#")
    if not raw.isdigit():
        await message.answer("Номер должен быть числом. Например: <code>/cancel 12</code>")
        return

    reminder = await db.get_reminder(int(raw))
    if reminder is None or reminder["chat_id"] != message.chat.id:
        await message.answer("Напоминание с таким номером не найдено в этом чате.")
        return
    if reminder["status"] != "active":
        await message.answer("Это напоминание уже неактивно.")
        return
    if not await _can_manage(bot, message.chat, reminder, message.from_user.id):
        await message.answer("Отменить может автор напоминания или админ чата.")
        return

    await db.cancel_reminder(reminder["id"])
    await message.answer(f"❌ Напоминание #{reminder['id']} отменено.")


@router.callback_query(F.data.startswith("cancel:"))
async def cancel_button(
    callback: CallbackQuery, db: Database, bot: Bot, chat_tz: str
) -> None:
    raw = callback.data.split(":", 1)[1]
    if not raw.isdigit():
        await callback.answer()
        return

    reminder = await db.get_reminder(int(raw))
    if reminder is None or reminder["chat_id"] != callback.message.chat.id:
        await callback.answer("Напоминание не найдено", show_alert=True)
        return
    if reminder["status"] != "active":
        await callback.answer("Это напоминание уже неактивно", show_alert=True)
        return
    if not await _can_manage(bot, callback.message.chat, reminder, callback.from_user.id):
        await callback.answer("Отменить может автор напоминания или админ чата", show_alert=True)
        return

    await db.cancel_reminder(reminder["id"])
    text, keyboard = await _render_list(db, callback.message.chat.id, ZoneInfo(chat_tz))
    try:
        await callback.message.edit_text(text, reply_markup=keyboard)
    except TelegramAPIError:
        pass
    await callback.answer(f"Напоминание #{reminder['id']} отменено")


@router.message(Command("timezone"))
async def timezone_command(message: Message, db: Database) -> None:
    current = await db.get_timezone(message.chat.id)
    parts = (message.text or "").split(maxsplit=1)

    if len(parts) < 2:
        await message.answer(
            f"Текущий часовой пояс этого чата: <code>{current}</code>\n\n"
            "Изменить: <code>/timezone Europe/Berlin</code>\n"
            "Примеры: <code>Europe/Moscow</code>, <code>Europe/Berlin</code>, "
            "<code>Asia/Almaty</code>, <code>Asia/Yekaterinburg</code>, <code>UTC</code>"
        )
        return

    tz = parse_timezone(parts[1])
    if tz is None:
        await message.answer(
            "Не знаю такой часовой пояс. Используйте IANA-название, "
            "например <code>Europe/Moscow</code>."
        )
        return

    await db.set_timezone(message.chat.id, tz.key)
    await message.answer(
        f"✅ Часовой пояс чата: <code>{tz.key}</code>\n"
        "Уже созданные напоминания сработают в прежний момент, "
        "а новые и повторяющиеся будут считаться в этом поясе."
    )
