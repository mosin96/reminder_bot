from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery

from ..db import Database
from ..utils.text import escape_html

router = Router(name="confirm")
logger = logging.getLogger(__name__)


@router.callback_query(F.data.startswith("cf:"))
async def confirm_reminder(callback: CallbackQuery, db: Database) -> None:
    raw = (callback.data or "").split(":", 1)[1]
    if not raw.isdigit():
        await callback.answer()
        return

    occurrence = await db.get_occurrence(int(raw))
    if occurrence is None:
        await callback.answer("Напоминание не найдено", show_alert=True)
        return
    if occurrence["status"] == "confirmed":
        await callback.answer("Уже подтверждено ✅")
        return
    if occurrence["status"] != "pending":
        await callback.answer("Это напоминание больше неактивно", show_alert=True)
        return

    if not await db.confirm_occurrence(occurrence["id"]):
        await callback.answer("Уже обработано")
        return

    base = getattr(callback.message, "html_text", None) or callback.message.text or ""
    suffix = f"\n\n✅ <b>Подтверждено:</b> {escape_html(callback.from_user.full_name)}"
    try:
        await callback.message.edit_text(base + suffix, reply_markup=None)
    except TelegramAPIError:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramAPIError:
            pass

    await callback.answer("Подтверждено ✅")
    logger.info(
        "Напоминание #%s подтверждено пользователем %s",
        occurrence["reminder_id"],
        callback.from_user.id,
    )
