from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

from .db import Database, to_iso, utcnow
from .keyboards import confirm_reminder_kb
from .utils.text import attempts_word, describe_schedule, escape_html
from .utils.timeparse import format_local, next_run_after

logger = logging.getLogger(__name__)


def build_reminder_text(
    reminder: Mapping[str, Any],
    tz: ZoneInfo,
    *,
    attempt: int | None = None,
    max_attempts: int | None = None,
) -> str:
    reminder = dict(reminder)
    number = reminder.get("chat_seq") or reminder["id"]
    if attempt is not None and attempt > 1:
        header = f"🔁 <b>Повтор {attempt}/{max_attempts}</b> — напоминание #{number}"
    else:
        header = f"⏰ <b>Напоминание #{number}</b>"

    lines = [header, "", escape_html(str(reminder["text"]))]

    if reminder["recurrence"] == "once":
        lines += ["", f"🕒 <i>{format_local(reminder['next_run_at'], tz)}</i>"]
    else:
        lines += ["", f"🗓 <i>{describe_schedule(reminder, tz)}</i>"]

    return "\n".join(lines)


async def _safe_send(bot: Bot, chat_id: int, text: str, **kwargs: Any):
    try:
        return await bot.send_message(chat_id, text, disable_web_page_preview=True, **kwargs)
    except TelegramAPIError as error:
        logger.warning("Не удалось отправить сообщение в чат %s: %s", chat_id, error)
        return None


async def _fire_reminder(bot: Bot, db: Database, reminder, now: datetime) -> None:
    reminder = dict(reminder)
    chat_id = reminder["chat_id"]
    tz_name = await db.get_timezone(chat_id)
    tz = ZoneInfo(tz_name)

    # Сначала сдвигаем расписание, чтобы падение отправки не зациклило напоминание.
    if reminder["recurrence"] == "once":
        await db.mark_reminder_done(reminder["id"])
    else:
        following = next_run_after(reminder, now, tz)
        await db.set_next_run(reminder["id"], following)

    occurrence_id: int | None = None
    if reminder["confirm_required"]:
        retry_at = now + timedelta(minutes=int(reminder["confirm_interval_min"]))
        occurrence_id = await db.create_occurrence(
            reminder["id"], reminder["next_run_at"], retry_at
        )

    text = build_reminder_text(reminder, tz)
    keyboard = confirm_reminder_kb(occurrence_id) if occurrence_id is not None else None
    message = await _safe_send(bot, chat_id, text, reply_markup=keyboard)

    if message is not None and occurrence_id is not None:
        await db.update_occurrence_message(occurrence_id, message.message_id)

    logger.info("Напоминание #%s отправлено в чат %s", reminder["id"], chat_id)


async def _retry_occurrence(bot: Bot, db: Database, occurrence, now: datetime) -> None:
    occurrence_id = occurrence["id"]
    max_attempts = int(occurrence["max_attempts"])
    interval = int(occurrence["confirm_interval_min"])
    attempt = int(occurrence["attempt"]) + 1

    reminder = {
        "id": occurrence["reminder_id"],
        "chat_seq": occurrence["chat_seq"],
        "text": occurrence["reminder_text"],
        "recurrence": occurrence["recurrence"],
        "weekdays": occurrence["weekdays"],
        "day_of_month": occurrence["day_of_month"],
        "time_of_day": occurrence["time_of_day"],
        "next_run_at": occurrence["reminder_next_run_at"],
        "max_attempts": max_attempts,
    }

    # Забираем chat_id напоминания (в выборке retry его нет).
    stored = await db.get_reminder(occurrence["reminder_id"])
    if stored is None:
        await db.mark_occurrence_missed(occurrence_id)
        return
    chat_id = stored["chat_id"]
    tz = ZoneInfo(await db.get_timezone(chat_id))

    # Убираем кнопку у прошлого сообщения, чтобы не подтверждали устаревшее.
    if occurrence["message_id"]:
        try:
            await bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=occurrence["message_id"],
                reply_markup=None,
            )
        except TelegramAPIError:
            pass

    if attempt > max_attempts:
        await db.mark_occurrence_missed(occurrence_id)
        number = occurrence["chat_seq"] or occurrence["reminder_id"]
        note = (
            f"⌛ Напоминание #{number} не подтверждено "
            f"за {max_attempts} {attempts_word(max_attempts)} и пропущено.\n\n"
            f"<i>{escape_html(str(occurrence['reminder_text']))}</i>"
        )
        await _safe_send(bot, chat_id, note)
        logger.info("Напоминание #%s пропущено (нет подтверждения)", occurrence["reminder_id"])
        return

    next_retry_at = now + timedelta(minutes=interval)
    await db.schedule_occurrence_retry(occurrence_id, attempt, next_retry_at)

    text = build_reminder_text(
        reminder,
        tz,
        attempt=attempt,
        max_attempts=max_attempts,
    )
    message = await _safe_send(
        bot,
        chat_id,
        text,
        reply_markup=confirm_reminder_kb(occurrence_id),
    )
    if message is not None:
        await db.update_occurrence_message(occurrence_id, message.message_id)

    logger.info(
        "Напоминание #%s: повтор %s/%s", occurrence["reminder_id"], attempt, max_attempts
    )


async def process_tick(bot: Bot, db: Database) -> None:
    now = utcnow()
    now_iso = to_iso(now)

    for reminder in await db.due_reminders(now_iso):
        try:
            await _fire_reminder(bot, db, reminder, now)
        except Exception:
            logger.exception("Ошибка при отправке напоминания #%s", reminder["id"])

    for occurrence in await db.due_retries(now_iso):
        try:
            await _retry_occurrence(bot, db, occurrence, now)
        except Exception:
            logger.exception("Ошибка при повторе напоминания #%s", occurrence["reminder_id"])


async def scheduler_loop(bot: Bot, db: Database, tick_seconds: float) -> None:
    logger.info("Планировщик запущен, тик %.0f сек", tick_seconds)
    while True:
        try:
            await process_tick(bot, db)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Ошибка тика планировщика")
        await asyncio.sleep(tick_seconds)
