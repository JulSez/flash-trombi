from __future__ import annotations

import sqlite3
import unittest
from contextlib import contextmanager
from unittest.mock import patch

import shortlist_review
import storage


class ShortlistAcquiredV064Tests(unittest.TestCase):
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
                id INTEGER PRIMARY KEY,
                class_id INTEGER NOT NULL,
                class_scope TEXT NOT NULL DEFAULT '1',
                session_date TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                maintenance_mode INTEGER NOT NULL DEFAULT 0,
                memorised_review_mode INTEGER NOT NULL DEFAULT 1
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
            "INSERT INTO students(id, class_id, position, status, cycle_no) VALUES (1, 1, 1, 'acquis', 1)"
        )
        self.conn.execute(
            "INSERT INTO sessions(id, class_id, session_date, started_at) VALUES (1, 1, '2026-09-04', '2026-09-04T08:00:00')"
        )
        self.conn.execute(
            "INSERT INTO session_students(session_id, student_id, initial_status) VALUES (1, 1, 'acquis')"
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

        self.patch = patch.object(shortlist_review, "connect", fake_connect)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.conn.close()

    def test_missed_acquired_filler_immediately_returns_to_seen(self):
        result = shortlist_review.record_shortlist_answer(1, 1, False)
        student = self.conn.execute("SELECT status, cycle_no FROM students WHERE id=1").fetchone()

        self.assertEqual(storage.STATUS_VU, student["status"])
        self.assertEqual(2, student["cycle_no"])
        self.assertEqual(storage.STATUS_VU, result["status"])


if __name__ == "__main__":
    unittest.main()
