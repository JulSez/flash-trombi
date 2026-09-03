from __future__ import annotations

import sqlite3
import unittest
from contextlib import contextmanager
from datetime import date
from unittest.mock import patch

import shortlist_review


class SameDayCycleResetTests(unittest.TestCase):
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
        self.conn.execute(
            "INSERT INTO students(id, class_id, position, status, cycle_no) VALUES (1, 1, 1, 'memorise', 1)"
        )
        self.conn.commit()

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

    def test_yes_then_no_same_day_breaks_the_cycle(self):
        day = date(2026, 9, 4)

        first = shortlist_review.start_shortlist_session([1], day)
        yes = shortlist_review.record_shortlist_answer(first["id"], 1, True, day)
        self.assertEqual("memorise", yes["status"])

        second = shortlist_review.start_shortlist_session([1], day)
        no = shortlist_review.record_shortlist_answer(second["id"], 1, False, day)

        student = self.conn.execute(
            "SELECT status, cycle_no FROM students WHERE id=1"
        ).fetchone()
        self.assertEqual("vu", no["status"])
        self.assertEqual("vu", student["status"])
        self.assertEqual(2, student["cycle_no"])


if __name__ == "__main__":
    unittest.main()
