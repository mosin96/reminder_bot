from __future__ import annotations

import logging
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from ..db import Database
from ..keyboards import (
    attempts_kb,
    cancel_form_kb,
    confirm_required_kb,
    interval_kb,
    preview_kb,
    recurrence_kb,
    time_quick_kb,
    weekdays_kb,
)
from ..utils.text import attempts_word, describe_schedule, escape_html, extract_usernames
from ..utils.timeparse import (
    format_local,
    next_run_after,
    parse_day_of_month,
    parse_once,
    parse_time_of_day,
)

router = Router(name="create")
logger = logging.getLogger(__name__)

RECURRENCE_LABELS = {
    "once": "1 раз",
    "daily": "каждый день",
    "weekdays": "по будням",
    "weekly": "по дням недели",
    "monthly": "раз в месяц",
}

ONCE_HINT = (
    "Когда напомнить?\n\n"
    "Примеры:\n"
    "• <code>через 10 минут</code>\n"
    "• <code>завтра в 9:00</code>\n"
    "• <code>25.11 18:30</code>\n"
    "• <code>18:30</code>"
)

TIME_HINT = (
    "Во сколько напоминать? Отправьте время в формате <code>ЧЧ:ММ</code> "
    "или выберите кнопку ниже."
)

CONFIRM_HINT = (
    "Нужно подтверждение?\n\n"
    "Если его не нажать, бот пришлёт напоминание повторно через заданное время."
)


class RemindForm(StatesGroup):
    text = State()
    recurrence = State()
    once_time = State()
    weekdays = State()
    day_of_month = State()
    time_of_day = State()
    confirm_required = State()
    confirm_interval = State()
    max_attempts = State()
    preview = State()


def _format_tod(value: time) -> str:
    return f"{value.hour:02d}:{value.minute:02d}"


def _stub(data: dict) -> dict:
    return {
        "id": 0,
        "recurrence": data["recurrence"],
        "next_run_at": data.get("next_run_at"),
        "weekdays": data.get("weekdays") or [],
        "day_of_month": data.get("day_of_month"),
        "time_of_day": data.get("time_of_day"),
    }


def _schedule_description(data: dict, tz: ZoneInfo) -> str:
    stub = _stub(data)
    if data["recurrence"] == "once":
        return describe_schedule(stub, tz)
    first = next_run_after(stub, datetime.now(timezone.utc), tz)
    return (
        f"{describe_schedule(stub, tz)}\n"
        f"   Первое срабатывание: {format_local(first, tz)}"
    )


def _preview_text(data: dict, tz: ZoneInfo) -> str:
    lines = [
        "📋 <b>Проверьте напоминание</b>",
        "",
        f"📝 {escape_html(data['text'])}",
        f"🕒 {_schedule_description(data, tz)}",
    ]
    if data.get("confirm_required"):
        lines.append(
            f"✅ Подтверждение: повтор через {data['confirm_interval_min']} мин, "
            f"до {data['max_attempts']} {attempts_word(data['max_attempts'])}"
        )
    else:
        lines.append("🔔 Без подтверждения")

    usernames = extract_usernames(data["text"])
    if usernames:
        lines.append("👥 Упоминания: " + ", ".join(f"@{name}" for name in usernames))
    return "\n".join(lines)


async def _ask_confirm(message: Message, state: FSMContext) -> None:
    await state.set_state(RemindForm.confirm_required)
    await message.answer(CONFIRM_HINT, reply_markup=confirm_required_kb())


async def _ask_confirm_edit(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(RemindForm.confirm_required)
    await callback.message.edit_text(CONFIRM_HINT, reply_markup=confirm_required_kb())


@router.message(Command("remind"))
async def remind_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(RemindForm.text)
    await message.answer(
        "✍️ Отправьте текст напоминания.\n\n"
        "Можно указать @username участников — бот упомянет их при отправке.\n"
        "Для отмены нажмите кнопку ниже.",
        reply_markup=cancel_form_kb(),
    )


@router.message(RemindForm.text)
async def remind_text(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer(
            "Пожалуйста, отправьте текст напоминания.", reply_markup=cancel_form_kb()
        )
        return
    if text.startswith("/"):
        await message.answer(
            "Похоже, это команда. Отправьте текст напоминания или нажмите «Отмена».",
            reply_markup=cancel_form_kb(),
        )
        return
    if len(text) > 3000:
        await message.answer("Слишком длинный текст: максимум 3000 символов.")
        return

    await state.update_data(text=text)
    await state.set_state(RemindForm.recurrence)
    await message.answer("Как повторять напоминание?", reply_markup=recurrence_kb())


@router.callback_query(RemindForm.recurrence, F.data.startswith("rec:"))
async def choose_recurrence(callback: CallbackQuery, state: FSMContext) -> None:
    kind = (callback.data or "").split(":", 1)[1]
    if kind not in RECURRENCE_LABELS:
        await callback.answer("Неизвестный тип", show_alert=True)
        return

    await state.update_data(recurrence=kind, weekdays=[])

    if kind == "once":
        await state.set_state(RemindForm.once_time)
        await callback.message.edit_text(ONCE_HINT, reply_markup=cancel_form_kb())
    elif kind == "weekly":
        await state.set_state(RemindForm.weekdays)
        await callback.message.edit_text(
            "Выберите дни недели, затем нажмите «Готово»:",
            reply_markup=weekdays_kb([]),
        )
    elif kind == "monthly":
        await state.set_state(RemindForm.day_of_month)
        await callback.message.edit_text(
            "Введите число месяца (1–31) или слово «последний»:",
            reply_markup=cancel_form_kb(),
        )
    else:
        await state.set_state(RemindForm.time_of_day)
        await callback.message.edit_text(TIME_HINT, reply_markup=time_quick_kb())

    await callback.answer()


@router.callback_query(RemindForm.weekdays, F.data.startswith("wd:"))
async def toggle_weekday(callback: CallbackQuery, state: FSMContext) -> None:
    raw = (callback.data or "").split(":", 1)[1]
    if not raw.isdigit() or not 0 <= int(raw) <= 6:
        await callback.answer()
        return

    index = int(raw)
    data = await state.get_data()
    selected = set(data.get("weekdays") or [])
    if index in selected:
        selected.remove(index)
    else:
        selected.add(index)

    await state.update_data(weekdays=sorted(selected))
    await callback.message.edit_reply_markup(reply_markup=weekdays_kb(selected))
    await callback.answer()


@router.callback_query(RemindForm.weekdays, F.data == "wd_done")
async def weekdays_done(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if not data.get("weekdays"):
        await callback.answer("Выберите хотя бы один день", show_alert=True)
        return
    await state.set_state(RemindForm.time_of_day)
    await callback.message.edit_text(TIME_HINT, reply_markup=time_quick_kb())
    await callback.answer()


@router.message(RemindForm.day_of_month)
async def day_of_month_input(message: Message, state: FSMContext) -> None:
    day = parse_day_of_month(message.text or "")
    if day is None:
        await message.answer(
            "Не понял число. Введите число от 1 до 31 или слово «последний».",
            reply_markup=cancel_form_kb(),
        )
        return
    await state.update_data(day_of_month=day)
    await state.set_state(RemindForm.time_of_day)
    await message.answer(TIME_HINT, reply_markup=time_quick_kb())


@router.callback_query(RemindForm.time_of_day, F.data.startswith("tod:"))
async def time_quick_choice(callback: CallbackQuery, state: FSMContext) -> None:
    value = parse_time_of_day((callback.data or "").split(":", 1)[1])
    if value is None:
        await callback.answer("Некорректное время", show_alert=True)
        return
    await state.update_data(time_of_day=_format_tod(value))
    await _ask_confirm_edit(callback, state)
    await callback.answer()


@router.message(RemindForm.time_of_day)
async def time_input(message: Message, state: FSMContext) -> None:
    value = parse_time_of_day(message.text or "")
    if value is None:
        await message.answer(
            "Не понял время. Отправьте, например, <code>9:00</code> или выберите кнопку.",
            reply_markup=time_quick_kb(),
        )
        return
    await state.update_data(time_of_day=_format_tod(value))
    await _ask_confirm(message, state)


@router.message(RemindForm.once_time)
async def once_time_input(message: Message, state: FSMContext, chat_tz: str) -> None:
    tz = ZoneInfo(chat_tz)
    parsed = parse_once(message.text or "", tz)
    if parsed is None:
        await message.answer(
            "Не понял время. Попробуйте один из вариантов:\n\n" + ONCE_HINT,
            reply_markup=cancel_form_kb(),
        )
        return

    await state.update_data(
        next_run_at=parsed.astimezone(timezone.utc).isoformat(timespec="seconds")
    )
    await _ask_confirm(message, state)


@router.callback_query(RemindForm.confirm_required, F.data.startswith("cfr:"))
async def choose_confirm_required(
    callback: CallbackQuery, state: FSMContext, chat_tz: str
) -> None:
    if callback.data == "cfr:yes":
        await state.update_data(confirm_required=True)
        await state.set_state(RemindForm.confirm_interval)
        await callback.message.edit_text(
            "Через сколько повторить, если напоминание не подтвердят?",
            reply_markup=interval_kb(),
        )
    else:
        await state.update_data(
            confirm_required=False,
            confirm_interval_min=10,
            max_attempts=3,
        )
        await _show_preview(callback, state, chat_tz)
    await callback.answer()


@router.callback_query(RemindForm.confirm_interval, F.data.startswith("ci:"))
async def choose_interval(callback: CallbackQuery, state: FSMContext) -> None:
    raw = (callback.data or "").split(":", 1)[1]
    if not raw.isdigit():
        await callback.answer("Некорректный интервал", show_alert=True)
        return
    await state.update_data(confirm_interval_min=int(raw))
    await state.set_state(RemindForm.max_attempts)
    await callback.message.edit_text(
        "Сколько всего попыток отправить напоминание?",
        reply_markup=attempts_kb(),
    )
    await callback.answer()


@router.callback_query(RemindForm.max_attempts, F.data.startswith("ca:"))
async def choose_attempts(
    callback: CallbackQuery, state: FSMContext, chat_tz: str
) -> None:
    raw = (callback.data or "").split(":", 1)[1]
    if not raw.isdigit() or int(raw) < 1:
        await callback.answer("Некорректное число попыток", show_alert=True)
        return
    await state.update_data(max_attempts=int(raw))
    await _show_preview(callback, state, chat_tz)
    await callback.answer()


async def _show_preview(
    callback: CallbackQuery, state: FSMContext, chat_tz: str
) -> None:
    data = await state.get_data()
    tz = ZoneInfo(chat_tz)
    await state.set_state(RemindForm.preview)
    await callback.message.edit_text(
        _preview_text(data, tz), reply_markup=preview_kb()
    )


@router.callback_query(RemindForm.preview, F.data == "prev:save")
async def save_reminder(
    callback: CallbackQuery, state: FSMContext, db: Database, chat_tz: str
) -> None:
    data = await state.get_data()
    tz = ZoneInfo(chat_tz)
    now = datetime.now(timezone.utc)
    recurrence = data.get("recurrence")

    try:
        if recurrence == "once":
            next_run_at = datetime.fromisoformat(data["next_run_at"])
            if next_run_at <= now:
                await state.clear()
                await callback.message.edit_text(
                    "⌛ Время уже прошло. Создайте напоминание заново: /remind"
                )
                await callback.answer()
                return
        elif recurrence in RECURRENCE_LABELS:
            next_run_at = next_run_after(data, now, tz)
        else:
            raise ValueError(f"Неизвестный тип повторяемости: {recurrence}")

        _reminder_id, chat_seq = await db.create_reminder(
            chat_id=callback.message.chat.id,
            author_id=callback.from_user.id,
            text=data["text"],
            recurrence=recurrence,
            next_run_at=next_run_at,
            weekdays=data.get("weekdays") or None,
            day_of_month=data.get("day_of_month"),
            time_of_day=data.get("time_of_day"),
            confirm_required=bool(data.get("confirm_required")),
            confirm_interval_min=int(data.get("confirm_interval_min") or 10),
            max_attempts=int(data.get("max_attempts") or 3),
        )
    except Exception:
        logger.exception("Не удалось создать напоминание")
        await callback.answer("Ошибка при создании, попробуйте ещё раз", show_alert=True)
        return

    await state.clear()
    stub = {**data, "next_run_at": next_run_at.isoformat(timespec="seconds")}
    await callback.message.edit_text(
        f"✅ <b>Напоминание #{chat_seq} создано</b>\n\n"
        f"🕒 {_schedule_description(stub, tz)}\n\n"
        "Посмотреть все напоминания чата: /list"
    )
    await callback.answer("Готово")


@router.callback_query(F.data.in_({"form:cancel", "prev:cancel"}))
async def cancel_form(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("✖️ Создание напоминания отменено.")
    await callback.answer()


@router.message(StateFilter(RemindForm))
async def form_fallback(message: Message, state: FSMContext) -> None:
    await message.answer(
        "Сейчас бот ждёт ответа на шаг создания. Используйте кнопки "
        "в сообщении выше (или нажмите «Отмена»).",
        reply_markup=cancel_form_kb(),
    )
