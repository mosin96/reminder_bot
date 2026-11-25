from __future__ import annotations

import calendar
import json
import re
from datetime import datetime, time, timedelta, timezone
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

WEEKDAY_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
DEFAULT_TIME = time(9, 0)

_RELATIVE_RE = re.compile(
    r"^через\s+(\d+)\s*(минут|мин|час|ч|дн|день|дня|дней|недел|нед|месяц|мес)",
    re.IGNORECASE,
)
_RELATIVE_WORDS = {
    "полчаса": timedelta(minutes=30),
    "пол часа": timedelta(minutes=30),
    "полтора часа": timedelta(hours=1, minutes=30),
    "час": timedelta(hours=1),
    "день": timedelta(days=1),
    "неделю": timedelta(weeks=1),
}
_TODAY_TOMORROW_RE = re.compile(
    r"^(сегодня|завтра|послезавтра)(?:\s+в)?\s*(\d{1,2})?(?:[:.](\d{2}))?$",
    re.IGNORECASE,
)
_DATE_RE = re.compile(
    r"(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?(?:\s*(?:в\s*)?(\d{1,2})[:.](\d{2}))?",
    re.IGNORECASE,
)
_TIME_ONLY_RE = re.compile(r"^(?:в\s*)?(\d{1,2})(?:[:.](\d{2}))?$", re.IGNORECASE)


def parse_timezone(name: str) -> ZoneInfo | None:
    try:
        return ZoneInfo(name.strip())
    except (ZoneInfoNotFoundError, ValueError):
        return None


def _relative(text: str, now: datetime) -> datetime | None:
    if text in _RELATIVE_WORDS:
        return now + _RELATIVE_WORDS[text]

    match = _RELATIVE_RE.match(text)
    if not match:
        return None
    amount = int(match.group(1))
    if amount <= 0:
        return None
    unit = match.group(2)
    if unit.startswith("мин"):
        delta = timedelta(minutes=amount)
    elif unit.startswith("ч"):
        delta = timedelta(hours=amount)
    elif unit.startswith("д"):
        delta = timedelta(days=amount)
    elif unit.startswith("нед"):
        delta = timedelta(weeks=amount)
    else:
        delta = timedelta(days=30 * amount)
    return now + delta


def _today_tomorrow(text: str, now: datetime) -> datetime | None:
    match = _TODAY_TOMORROW_RE.match(text)
    if not match:
        return None
    day_word, hour_raw, minute_raw = match.groups()
    offsets = {"сегодня": 0, "завтра": 1, "послезавтра": 2}
    target_date = (now + timedelta(days=offsets[day_word])).date()

    if hour_raw is None:
        hour, minute = DEFAULT_TIME.hour, DEFAULT_TIME.minute
    else:
        hour = int(hour_raw)
        minute = int(minute_raw or 0)
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return None

    return datetime.combine(target_date, time(hour, minute), tzinfo=now.tzinfo)


def _explicit_date(text: str, now: datetime) -> datetime | None:
    match = _DATE_RE.search(text)
    if not match:
        return None

    day = int(match.group(1))
    month = int(match.group(2))
    if not (1 <= month <= 12):
        return None

    year_raw = match.group(3)
    if year_raw is None:
        year = now.year
    else:
        year = int(year_raw)
        if year < 100:
            year += 2000

    hour_raw, minute_raw = match.group(4), match.group(5)
    hour = int(hour_raw) if hour_raw is not None else DEFAULT_TIME.hour
    minute = int(minute_raw) if minute_raw is not None else DEFAULT_TIME.minute
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None

    try:
        result = datetime(year, month, day, hour, minute, tzinfo=now.tzinfo)
    except ValueError:
        return None

    if year_raw is None and result <= now:
        try:
            result = result.replace(year=year + 1)
        except ValueError:
            return None
    return result


def _bare_time(text: str, now: datetime) -> datetime | None:
    match = _TIME_ONLY_RE.match(text)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    result = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if result <= now:
        result += timedelta(days=1)
    return result


def _dateparser_fallback(text: str, tz: ZoneInfo, now: datetime) -> datetime | None:
    try:
        import dateparser
    except ImportError:  # pragma: no cover - dateparser указан в requirements
        return None

    try:
        parsed = dateparser.parse(
            text,
            languages=["ru"],
            settings={
                "TIMEZONE": tz.key,
                "RETURN_AS_TIMEZONE_AWARE": True,
                "PREFER_DATES_FROM": "future",
                "RELATIVE_BASE": now,
            },
        )
    except Exception:
        return None

    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=tz)
    return parsed.astimezone(tz)


def parse_once(text: str, tz: ZoneInfo, now: datetime | None = None) -> datetime | None:
    """Разбирает момент времени для разового напоминания. Возвращает aware datetime или None."""
    now = (now or datetime.now(tz)).astimezone(tz).replace(microsecond=0)
    raw = (text or "").strip()
    if not raw:
        return None

    normalized = raw.lower().replace("ё", "е").strip()
    result = (
        _relative(normalized, now)
        or _today_tomorrow(normalized, now)
        or _explicit_date(normalized, now)
        or _bare_time(normalized, now)
    )
    if result is None:
        result = _dateparser_fallback(raw, tz, now)

    if result is None:
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=tz)
    result = result.astimezone(tz)
    if result <= now:
        return None
    return result


def parse_time_of_day(text: str) -> time | None:
    match = _TIME_ONLY_RE.match((text or "").strip().lower())
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    if hour == 24 and minute == 0:
        hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return time(hour, minute)


def parse_day_of_month(text: str) -> int | None:
    normalized = (text or "").strip().lower().replace("ё", "е")
    if normalized in {"последний", "последнее", "last", "конец месяца"}:
        return 31
    match = re.search(r"\d{1,2}", normalized)
    if not match:
        return None
    day = int(match.group(0))
    if not 1 <= day <= 31:
        return None
    return day


def weekday_list(value: Any) -> list[int]:
    if value is None:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    if not isinstance(value, Sequence):
        return []
    result = []
    for item in value:
        try:
            number = int(item)
        except (TypeError, ValueError):
            continue
        if 0 <= number <= 6:
            result.append(number)
    return sorted(set(result))


def _month_candidate(year: int, month: int, day: int, tod: time, tz: ZoneInfo) -> datetime:
    last_day = calendar.monthrange(year, month)[1]
    return datetime(year, month, min(day, last_day), tod.hour, tod.minute, tzinfo=tz)


def next_run_after(reminder: Mapping[str, Any], after: datetime, tz: ZoneInfo) -> datetime:
    """Считает следующее срабатывание напоминания после момента after (в UTC)."""
    reminder = dict(reminder)
    after_local = after.astimezone(tz)
    kind = reminder["recurrence"]
    tod = parse_time_of_day(str(reminder.get("time_of_day") or "")) or DEFAULT_TIME

    if kind == "once":
        stored = reminder.get("next_run_at")
        if not stored:
            raise ValueError("У разового напоминания нет next_run_at")
        return datetime.fromisoformat(str(stored)).astimezone(timezone.utc)

    if kind == "daily":
        candidate = datetime.combine(after_local.date(), tod, tzinfo=tz)
        if candidate <= after_local:
            candidate = datetime.combine(after_local.date() + timedelta(days=1), tod, tzinfo=tz)
        return candidate.astimezone(timezone.utc)

    if kind == "weekdays":
        for offset in range(8):
            day = after_local.date() + timedelta(days=offset)
            if day.weekday() >= 5:
                continue
            candidate = datetime.combine(day, tod, tzinfo=tz)
            if candidate > after_local:
                return candidate.astimezone(timezone.utc)
        fallback = after_local.date() + timedelta(days=7)
        return datetime.combine(fallback, tod, tzinfo=tz).astimezone(timezone.utc)

    if kind == "weekly":
        days = set(weekday_list(reminder.get("weekdays")))
        if days:
            for offset in range(8):
                day = after_local.date() + timedelta(days=offset)
                if day.weekday() not in days:
                    continue
                candidate = datetime.combine(day, tod, tzinfo=tz)
                if candidate > after_local:
                    return candidate.astimezone(timezone.utc)
        fallback = after_local.date() + timedelta(days=7)
        return datetime.combine(fallback, tod, tzinfo=tz).astimezone(timezone.utc)

    if kind == "monthly":
        day = int(reminder.get("day_of_month") or 1)
        year, month = after_local.year, after_local.month
        candidate = _month_candidate(year, month, day, tod, tz)
        if candidate <= after_local:
            month += 1
            if month > 12:
                month = 1
                year += 1
            candidate = _month_candidate(year, month, day, tod, tz)
        return candidate.astimezone(timezone.utc)

    raise ValueError(f"Неизвестный тип повторяемости: {kind}")


def format_local(value: datetime | str, tz: ZoneInfo) -> str:
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    return value.astimezone(tz).strftime("%d.%m.%Y %H:%M")
