from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone

from bot.db import Database


def test_chat_sequence_is_per_chat(tmp_path):
    async def scenario():
        db = Database(tmp_path / "test.db")
        await db.connect()
        try:
            now = datetime.now(timezone.utc) + timedelta(hours=1)

            first_a_id, first_a_seq = await db.create_reminder(
                chat_id=1, author_id=10, text="a1", recurrence="once", next_run_at=now
            )
            _, first_b_seq = await db.create_reminder(
                chat_id=2, author_id=20, text="b1", recurrence="once", next_run_at=now
            )
            second_a_id, second_a_seq = await db.create_reminder(
                chat_id=1, author_id=10, text="a2", recurrence="once", next_run_at=now
            )

            assert (first_a_seq, first_b_seq, second_a_seq) == (1, 1, 2)

            found = await db.get_reminder_by_seq(1, 2)
            assert found is not None
            assert found["id"] == second_a_id
            assert found["id"] != first_a_id
            assert await db.get_reminder_by_seq(2, 2) is None
        finally:
            await db.close()

    asyncio.run(scenario())


def test_migration_backfills_chat_sequence(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE reminders (
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

        INSERT INTO reminders(chat_id, author_id, text, recurrence, next_run_at, created_at)
        VALUES
            (1, 1, 'a', 'once', '2030-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00'),
            (2, 1, 'b', 'once', '2030-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00'),
            (1, 1, 'c', 'once', '2030-01-02T00:00:00+00:00', '2026-01-01T00:00:00+00:00');
        """
    )
    conn.commit()
    conn.close()

    async def scenario():
        db = Database(path)
        await db.connect()
        try:
            first_chat = await db.list_active_reminders(1)
            assert [row["chat_seq"] for row in first_chat] == [1, 2]

            second_chat = await db.list_active_reminders(2)
            assert [row["chat_seq"] for row in second_chat] == [1]

            # после миграции новые напоминания продолжают нумерацию
            _, new_seq = await db.create_reminder(
                chat_id=1,
                author_id=1,
                text="d",
                recurrence="once",
                next_run_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
            assert new_seq == 3
        finally:
            await db.close()

    asyncio.run(scenario())
