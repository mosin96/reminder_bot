from __future__ import annotations

from typing import Iterable

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .utils.timeparse import WEEKDAY_SHORT


def _button(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=data)


def cancel_form_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_button("✖️ Отмена", "form:cancel")]])


def recurrence_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("1 раз", "rec:once")],
            [_button("Каждый день", "rec:daily"), _button("По будням", "rec:weekdays")],
            [_button("По дням недели", "rec:weekly")],
            [_button("Раз в месяц", "rec:monthly")],
            [_button("✖️ Отмена", "form:cancel")],
        ]
    )


def weekdays_kb(selected: Iterable[int]) -> InlineKeyboardMarkup:
    chosen = set(selected)
    rows: list[list[InlineKeyboardButton]] = []
    for start in range(0, 7, 3):
        row = []
        for index in range(start, min(start + 3, 7)):
            mark = "✅ " if index in chosen else ""
            row.append(_button(f"{mark}{WEEKDAY_SHORT[index]}", f"wd:{index}"))
        rows.append(row)
    rows.append([_button("Готово ➡️", "wd_done")])
    rows.append([_button("✖️ Отмена", "form:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def time_quick_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _button("09:00", "tod:09:00"),
                _button("12:00", "tod:12:00"),
                _button("18:00", "tod:18:00"),
                _button("21:00", "tod:21:00"),
            ],
            [_button("✖️ Отмена", "form:cancel")],
        ]
    )


def confirm_required_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("✅ Да, с подтверждением", "cfr:yes")],
            [_button("🔔 Нет, просто напомнить", "cfr:no")],
            [_button("✖️ Отмена", "form:cancel")],
        ]
    )


def interval_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _button("5 мин", "ci:5"),
                _button("10 мин", "ci:10"),
                _button("15 мин", "ci:15"),
                _button("30 мин", "ci:30"),
            ],
            [_button("✖️ Отмена", "form:cancel")],
        ]
    )


def attempts_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                _button("1", "ca:1"),
                _button("2", "ca:2"),
                _button("3", "ca:3"),
                _button("5", "ca:5"),
            ],
            [_button("✖️ Отмена", "form:cancel")],
        ]
    )


def preview_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_button("✅ Создать", "prev:save")],
            [_button("✖️ Отмена", "prev:cancel")],
        ]
    )


def list_kb(reminders: Iterable) -> InlineKeyboardMarkup:
    rows = [
        [
            _button(
                f"❌ Отменить #{reminder['chat_seq']}",
                f"cancel:{reminder['id']}",
            )
        ]
        for reminder in reminders
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_reminder_kb(occurrence_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[_button("✅ Подтвердить", f"cf:{occurrence_id}")]]
    )
