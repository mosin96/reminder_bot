from __future__ import annotations

import sys
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from bot.utils.text import attempts_word, describe_schedule
from bot.utils.timeparse import (
    next_run_after,
    parse_day_of_month,
    parse_once,
    parse_time_of_day,
    parse_timezone,
)

TZ = ZoneInfo("Europe/Moscow")
NOW = datetime(2026, 11, 25, 10, 0, tzinfo=TZ)  # среда


def test_relative_minutes():
    assert parse_once("через 10 минут", TZ, NOW) == datetime(2026, 11, 25, 10, 10, tzinfo=TZ)


def test_relative_hours():
    assert parse_once("через 2 часа", TZ, NOW) == datetime(2026, 11, 25, 12, 0, tzinfo=TZ)


def test_relative_half_hour():
    assert parse_once("через полчаса", TZ, NOW) == datetime(2026, 11, 25, 10, 30, tzinfo=TZ)


def test_relative_days():
    assert parse_once("через 3 дня", TZ, NOW) == datetime(2026, 11, 28, 10, 0, tzinfo=TZ)


def test_tomorrow_at_time():
    assert parse_once("завтра в 9:00", TZ, NOW) == datetime(2026, 11, 26, 9, 0, tzinfo=TZ)


def test_explicit_date_and_time():
    assert parse_once("25.11 18:30", TZ, NOW) == datetime(2026, 11, 25, 18, 30, tzinfo=TZ)


def test_explicit_full_date():
    assert parse_once("01.12.2026 08:15", TZ, NOW) == datetime(2026, 12, 1, 8, 15, tzinfo=TZ)


def test_bare_time_today():
    assert parse_once("18:30", TZ, NOW) == datetime(2026, 11, 25, 18, 30, tzinfo=TZ)


def test_bare_time_tomorrow_if_passed():
    assert parse_once("09:30", TZ, NOW) == datetime(2026, 11, 26, 9, 30, tzinfo=TZ)


def test_past_explicit_date_is_rejected():
    assert parse_once("01.01.2020 10:00", TZ, NOW) is None


def test_garbage_is_rejected():
    assert parse_once("абракадабра", TZ, NOW) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("9", time(9, 0)),
        ("9:05", time(9, 5)),
        ("21.15", time(21, 15)),
        ("24:00", time(0, 0)),
        ("в 18:30", time(18, 30)),
    ],
)
def test_parse_time_of_day(raw, expected):
    assert parse_time_of_day(raw) == expected


@pytest.mark.parametrize("raw", ["25:00", "12:75", "утро", ""])
def test_parse_time_of_day_invalid(raw):
    assert parse_time_of_day(raw) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("15", 15), ("15-е", 15), ("1", 1), ("последний", 31), ("31", 31)],
)
def test_parse_day_of_month(raw, expected):
    assert parse_day_of_month(raw) == expected


@pytest.mark.parametrize("raw", ["0", "32", "нет"])
def test_parse_day_of_month_invalid(raw):
    assert parse_day_of_month(raw) is None


def _local(moment: datetime) -> datetime:
    return moment.astimezone(TZ)


def test_next_run_daily():
    reminder = {"recurrence": "daily", "time_of_day": "09:00"}
    result = next_run_after(reminder, NOW, TZ)
    assert _local(result) == datetime(2026, 11, 26, 9, 0, tzinfo=TZ)


def test_next_run_weekdays_skips_weekend():
    friday = datetime(2026, 11, 27, 10, 0, tzinfo=TZ)
    reminder = {"recurrence": "weekdays", "time_of_day": "09:00"}
    result = next_run_after(reminder, friday, TZ)
    assert _local(result) == datetime(2026, 11, 30, 9, 0, tzinfo=TZ)


def test_next_run_weekly():
    reminder = {"recurrence": "weekly", "weekdays": [0, 2], "time_of_day": "09:00"}
    result = next_run_after(reminder, NOW, TZ)
    # Среда уже прошла (09:00), значит следующий подходящий день — понедельник.
    assert _local(result) == datetime(2026, 11, 30, 9, 0, tzinfo=TZ)


def test_next_run_accepts_sqlite_row():
    import sqlite3

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT 'daily' AS recurrence, '09:00' AS time_of_day, "
        "NULL AS weekdays, NULL AS day_of_month, NULL AS next_run_at"
    ).fetchone()
    result = next_run_after(row, NOW, TZ)
    assert _local(result) == datetime(2026, 11, 26, 9, 0, tzinfo=TZ)
    conn.close()


def test_next_run_monthly_clamps_to_last_day():
    january_end = datetime(2027, 1, 31, 12, 0, tzinfo=TZ)
    reminder = {"recurrence": "monthly", "day_of_month": 31, "time_of_day": "09:00"}
    result = next_run_after(reminder, january_end, TZ)
    assert _local(result) == datetime(2027, 2, 28, 9, 0, tzinfo=TZ)


def test_parse_timezone():
    assert parse_timezone("Europe/Moscow") is not None
    assert parse_timezone("Bad/Zone") is None


def test_describe_schedule():
    once = {"recurrence": "once", "next_run_at": "2026-11-26T06:00:00+00:00"}
    assert describe_schedule(once, TZ) == "26.11.2026 09:00"

    weekly = {"recurrence": "weekly", "weekdays": [0, 2], "time_of_day": "09:00"}
    assert describe_schedule(weekly, TZ) == "по Пн, Ср в 09:00"

    monthly = {"recurrence": "monthly", "day_of_month": 31, "time_of_day": "09:00"}
    assert describe_schedule(monthly, TZ) == "в последний день месяца в 09:00"


@pytest.mark.parametrize(
    ("count", "expected"),
    [(1, "попытку"), (2, "попытки"), (3, "попытки"), (5, "попыток"), (11, "попыток"), (21, "попытку")],
)
def test_attempts_word(count, expected):
    assert attempts_word(count) == expected
