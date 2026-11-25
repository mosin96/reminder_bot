from __future__ import annotations

import html
import re
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from .timeparse import WEEKDAY_SHORT, format_local, weekday_list

_USERNAME_RE = re.compile(r"@([A-Za-z][A-Za-z0-9_]{4,31})")


def escape_html(text: str) -> str:
    return html.escape(text, quote=False)


def attempts_word(count: int) -> str:
    """Склонение слова «попытка» для числа count."""
    remainder = abs(count) % 100
    if 11 <= remainder <= 14:
        return "попыток"
    remainder %= 10
    if remainder == 1:
        return "попытку"
    if 2 <= remainder <= 4:
        return "попытки"
    return "попыток"


def extract_usernames(text: str) -> list[str]:
    seen: list[str] = []
    for username in _USERNAME_RE.findall(text):
        if username not in seen:
            seen.append(username)
    return seen


def describe_schedule(reminder: Mapping[str, Any], tz: ZoneInfo) -> str:
    reminder = dict(reminder)
    kind = reminder["recurrence"]
    tod = str(reminder.get("time_of_day") or "")

    if kind == "once":
        return format_local(reminder["next_run_at"], tz)
    if kind == "daily":
        return f"каждый день в {tod}"
    if kind == "weekdays":
        return f"по будням в {tod}"
    if kind == "weekly":
        days = ", ".join(WEEKDAY_SHORT[index] for index in weekday_list(reminder.get("weekdays")))
        return f"по {days} в {tod}" if days else f"каждую неделю в {tod}"
    if kind == "monthly":
        day = int(reminder.get("day_of_month") or 1)
        if day >= 31:
            return f"в последний день месяца в {tod}"
        return f"каждое {day}-е число в {tod}"
    return "неизвестное расписание"
