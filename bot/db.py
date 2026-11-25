from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    chat_id    INTEGER PRIMARY KEY,
    title      TEXT,
    tz         TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reminders (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id              INTEGER NOT NULL,
    author_id            INTEGER NOT NULL,
    text                 TEXT NOT NULL,
    recurrence           TEXT NOT NULL,
    weekdays             TEXT,
    day_of_month         INTEGER,
    time_of_day          TEXT,
    next_run_at          TEXT NOT NULL,
    confirm_required     INTEGER NOT NULL DEFAULT 0,
    confirm_interval_min INTEGER NOT NULL DEFAULT 10,
    max_attempts         INTEGER NOT NULL DEFAULT 3,
    status               TEXT NOT NULL DEFAULT 'active',
    created_at           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS occurrences (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    reminder_id   INTEGER NOT NULL REFERENCES reminders(id) ON DELETE CASCADE,
    scheduled_at  TEXT NOT NULL,
    attempt       INTEGER NOT NULL DEFAULT 1,
    next_retry_at TEXT,
    status        TEXT NOT NULL DEFAULT 'pending',
    message_id    INTEGER,
    created_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(status, next_run_at);
CREATE INDEX IF NOT EXISTS idx_occurrences_retry ON occurrences(status, next_retry_at);
"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def to_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str | Path, *, default_tz: str = "Europe/Moscow") -> None:
        self.path = Path(path)
        self.default_tz = default_tz
        self._conn: aiosqlite.Connection | None = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("База данных не подключена")
        return self._conn

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def _fetchone(self, sql: str, params: Sequence[Any] = ()) -> aiosqlite.Row | None:
        async with self.conn.execute(sql, params) as cursor:
            return await cursor.fetchone()

    async def _fetchall(self, sql: str, params: Sequence[Any] = ()) -> list[aiosqlite.Row]:
        async with self.conn.execute(sql, params) as cursor:
            return list(await cursor.fetchall())

    # --- Чаты ---

    async def upsert_chat(self, chat_id: int, title: str | None = None) -> str:
        """Создаёт чат при первом обращении и возвращает его часовой пояс."""
        await self.conn.execute(
            """
            INSERT INTO chats(chat_id, title, tz, created_at) VALUES(?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET title = COALESCE(excluded.title, chats.title)
            """,
            (chat_id, title, self.default_tz, to_iso(utcnow())),
        )
        await self.conn.commit()
        row = await self._fetchone("SELECT tz FROM chats WHERE chat_id = ?", (chat_id,))
        return row["tz"] if row is not None else self.default_tz

    async def get_timezone(self, chat_id: int) -> str:
        row = await self._fetchone("SELECT tz FROM chats WHERE chat_id = ?", (chat_id,))
        return row["tz"] if row is not None else self.default_tz

    async def set_timezone(self, chat_id: int, tz: str) -> None:
        await self.upsert_chat(chat_id)
        await self.conn.execute("UPDATE chats SET tz = ? WHERE chat_id = ?", (tz, chat_id))
        await self.conn.commit()

    # --- Напоминания ---

    async def create_reminder(
        self,
        *,
        chat_id: int,
        author_id: int,
        text: str,
        recurrence: str,
        next_run_at: datetime,
        weekdays: Sequence[int] | None = None,
        day_of_month: int | None = None,
        time_of_day: str | None = None,
        confirm_required: bool = False,
        confirm_interval_min: int = 10,
        max_attempts: int = 3,
    ) -> int:
        weekdays_json = json.dumps(list(weekdays), ensure_ascii=False) if weekdays else None
        cursor = await self.conn.execute(
            """
            INSERT INTO reminders(
                chat_id, author_id, text, recurrence, weekdays, day_of_month, time_of_day,
                next_run_at, confirm_required, confirm_interval_min, max_attempts, status, created_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
            """,
            (
                chat_id,
                author_id,
                text,
                recurrence,
                weekdays_json,
                day_of_month,
                time_of_day,
                to_iso(next_run_at),
                int(confirm_required),
                confirm_interval_min,
                max_attempts,
                to_iso(utcnow()),
            ),
        )
        await self.conn.commit()
        return int(cursor.lastrowid)

    async def get_reminder(self, reminder_id: int) -> aiosqlite.Row | None:
        return await self._fetchone("SELECT * FROM reminders WHERE id = ?", (reminder_id,))

    async def list_active_reminders(self, chat_id: int) -> list[aiosqlite.Row]:
        return await self._fetchall(
            "SELECT * FROM reminders WHERE chat_id = ? AND status = 'active' ORDER BY next_run_at",
            (chat_id,),
        )

    async def due_reminders(self, now_iso: str) -> list[aiosqlite.Row]:
        return await self._fetchall(
            "SELECT * FROM reminders WHERE status = 'active' AND next_run_at <= ? ORDER BY next_run_at",
            (now_iso,),
        )

    async def set_next_run(self, reminder_id: int, next_run_at: datetime) -> None:
        await self.conn.execute(
            "UPDATE reminders SET next_run_at = ? WHERE id = ?",
            (to_iso(next_run_at), reminder_id),
        )
        await self.conn.commit()

    async def mark_reminder_done(self, reminder_id: int) -> None:
        await self.conn.execute(
            "UPDATE reminders SET status = 'done' WHERE id = ?",
            (reminder_id,),
        )
        await self.conn.commit()

    async def cancel_reminder(self, reminder_id: int) -> None:
        await self.conn.execute(
            "UPDATE reminders SET status = 'cancelled' WHERE id = ?",
            (reminder_id,),
        )
        await self.conn.execute(
            "UPDATE occurrences SET status = 'cancelled', next_retry_at = NULL "
            "WHERE reminder_id = ? AND status = 'pending'",
            (reminder_id,),
        )
        await self.conn.commit()

    # --- Срабатывания и подтверждения ---

    async def create_occurrence(
        self,
        reminder_id: int,
        scheduled_at: str,
        next_retry_at: datetime | None,
    ) -> int:
        cursor = await self.conn.execute(
            """
            INSERT INTO occurrences(reminder_id, scheduled_at, attempt, next_retry_at, status, created_at)
            VALUES(?, ?, 1, ?, 'pending', ?)
            """,
            (
                reminder_id,
                scheduled_at,
                to_iso(next_retry_at) if next_retry_at is not None else None,
                to_iso(utcnow()),
            ),
        )
        await self.conn.commit()
        return int(cursor.lastrowid)

    async def update_occurrence_message(self, occurrence_id: int, message_id: int) -> None:
        await self.conn.execute(
            "UPDATE occurrences SET message_id = ? WHERE id = ?",
            (message_id, occurrence_id),
        )
        await self.conn.commit()

    async def due_retries(self, now_iso: str) -> list[aiosqlite.Row]:
        return await self._fetchall(
            """
            SELECT
                o.*,
                r.text                 AS reminder_text,
                r.recurrence           AS recurrence,
                r.weekdays             AS weekdays,
                r.day_of_month         AS day_of_month,
                r.time_of_day          AS time_of_day,
                r.next_run_at          AS reminder_next_run_at,
                r.max_attempts         AS max_attempts,
                r.confirm_interval_min AS confirm_interval_min
            FROM occurrences o
            JOIN reminders r ON r.id = o.reminder_id
            WHERE o.status = 'pending'
              AND o.next_retry_at IS NOT NULL
              AND o.next_retry_at <= ?
            ORDER BY o.next_retry_at
            """,
            (now_iso,),
        )

    async def get_occurrence(self, occurrence_id: int) -> aiosqlite.Row | None:
        return await self._fetchone("SELECT * FROM occurrences WHERE id = ?", (occurrence_id,))

    async def schedule_occurrence_retry(
        self,
        occurrence_id: int,
        attempt: int,
        next_retry_at: datetime | None,
    ) -> None:
        await self.conn.execute(
            "UPDATE occurrences SET attempt = ?, next_retry_at = ? WHERE id = ?",
            (
                attempt,
                to_iso(next_retry_at) if next_retry_at is not None else None,
                occurrence_id,
            ),
        )
        await self.conn.commit()

    async def mark_occurrence_missed(self, occurrence_id: int) -> None:
        await self.conn.execute(
            "UPDATE occurrences SET status = 'missed', next_retry_at = NULL WHERE id = ?",
            (occurrence_id,),
        )
        await self.conn.commit()

    async def confirm_occurrence(self, occurrence_id: int) -> bool:
        cursor = await self.conn.execute(
            "UPDATE occurrences SET status = 'confirmed', next_retry_at = NULL "
            "WHERE id = ? AND status = 'pending'",
            (occurrence_id,),
        )
        await self.conn.commit()
        return cursor.rowcount > 0
