from __future__ import annotations

import sqlite3
import unittest
from contextlib import contextmanager
from datetime import date
from unittest.mock import patch

import shortlist_review


class ShortlistReviewTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE students (
                id INTEGER PRIMARY KEY,
                class_id INTEGER NOT NULL,
                position INTEGER NOT NULL,
                status TEXT NOT NULL,
                cycle_no INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                class_id INTEGER NOT NULL,
                class_scope TEXT NOT NULL DEFAULT '',
                session_date TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                maintenance_mode INTEGER NOT NULL DEFAULT 0,
                memorised_review_mode INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE session_students (
                session_id INTEGER NOT NULL,
                student_id INTEGER NOT NULL,
                initial_status TEXT NOT NULL,
                correct_count INTEGER NOT NULL DEFAULT 0,
                completed INTEGER NOT NULL DEFAULT 0,
                review_first_done INTEGER NOT NULL DEFAULT 0,
                review_failed INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(session_id, student_id)
            );
            CREATE TABLE attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                student_id INTEGER NOT NULL,
                asked_at TEXT NOT NULL,
                correct INTEGER NOT NULL
            );
            """
        )

        @contextmanager
        def fake_connect():
            try:
                yield self.conn
                self.conn.commit()
            except Exception:
                self.conn.rollback()
                raise

        self.connect_patch = patch.object(shortlist_review, "connect", fake_connect)
        self.connect_patch.start()

    def tearDown(self):
        self.connect_patch.stop()
        self.conn.close()

    def add_students(self, count: int, status: str = "memorise") -> None:
        self.conn.executemany(
            "INSERT INTO students(id, class_id, position, status, cycle_no) VALUES (?, 1, ?, ?, 1)",
            [(index, index, status) for index in range(1, count + 1)],
        )
        self.conn.commit()

    def test_done_today_requires_every_non_acquired_student_to_be_memorised_today(self):
        today = date(2026, 9, 1)
        students = [
            {"status": "memorise", "memory_dates": ["2026-09-01"]},
            {"status": "acquis", "memory_dates": []},
        ]
        self.assertTrue(shortlist_review.selection_done_today(students, today))
        students[0]["memory_dates"] = ["2026-08-31"]
        self.assertFalse(shortlist_review.selection_done_today(students, today))

    def test_shortlist_contains_every_memorised_student(self):
        self.add_students(12)
        session = shortlist_review.start_shortlist_session([1], date(2026, 9, 1))
        count = self.conn.execute(
            "SELECT COUNT(*) AS n FROM session_students WHERE session_id=?",
            (session["id"],),
        ).fetchone()["n"]
        self.assertEqual(12, count)
        self.assertEqual(1, int(session["memorised_review_mode"]))

    def test_one_miss_returns_student_to_seen_and_removes_them_from_shortlist(self):
        self.add_students(2)
        session = shortlist_review.start_shortlist_session([1], date(2026, 9, 1))
        result = shortlist_review.record_shortlist_answer(session["id"], 1, False)

        student = self.conn.execute("SELECT * FROM students WHERE id=1").fetchone()
        row = self.conn.execute(
            "SELECT * FROM session_students WHERE session_id=? AND student_id=1",
            (session["id"],),
        ).fetchone()
        self.assertEqual("vu", student["status"])
        self.assertEqual(2, student["cycle_no"])
        self.assertEqual(1, row["completed"])
        self.assertEqual(1, result["remaining"])

    def test_success_removes_student_without_changing_memorised_status(self):
        self.add_students(1)
        session = shortlist_review.start_shortlist_session([1], date(2026, 9, 1))
        result = shortlist_review.record_shortlist_answer(session["id"], 1, True)

        student = self.conn.execute("SELECT * FROM students WHERE id=1").fetchone()
        refreshed_session = self.conn.execute(
            "SELECT * FROM sessions WHERE id=?", (session["id"],)
        ).fetchone()
        self.assertEqual("memorise", student["status"])
        self.assertEqual(0, result["remaining"])
        self.assertTrue(result["session_finished"])
        self.assertIsNotNone(refreshed_session["completed_at"])


if __name__ == "__main__":
    unittest.main()
