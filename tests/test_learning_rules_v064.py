from __future__ import annotations

import sqlite3
import unittest
from contextlib import contextmanager
from datetime import date
from unittest.mock import patch

import storage


class LearningRulesV064Tests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(
            """
            CREATE TABLE classes (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL
            );
            CREATE TABLE students (
                id INTEGER PRIMARY KEY,
                class_id INTEGER NOT NULL,
                first_name TEXT NOT NULL DEFAULT '',
                last_name TEXT NOT NULL DEFAULT '',
                position INTEGER NOT NULL,
                status TEXT NOT NULL,
                cycle_no INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE memory_days (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id INTEGER NOT NULL,
                cycle_no INTEGER NOT NULL,
                memory_date TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE sessions (
                id INTEGER PRIMARY KEY,
                class_id INTEGER NOT NULL,
                class_scope TEXT NOT NULL DEFAULT '',
                session_date TEXT NOT NULL DEFAULT '2026-09-04',
                started_at TEXT NOT NULL DEFAULT '2026-09-04T08:00:00',
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
        self.conn.execute("INSERT INTO classes(id, name) VALUES (1, 'Classe Test')")
        self.conn.execute(
            "INSERT INTO sessions(id, class_id, class_scope) VALUES (1, 1, '1')"
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

        self.connect_patch = patch.object(storage, "connect", fake_connect)
        self.connect_patch.start()

    def tearDown(self):
        self.connect_patch.stop()
        self.conn.close()

    def add_student(self, student_id: int, status: str, position: int) -> None:
        self.conn.execute(
            """
            INSERT INTO students(id, class_id, first_name, last_name, position, status, cycle_no)
            VALUES (?, 1, ?, ?, ?, ?, 1)
            """,
            (student_id, f"Eleve{student_id}", "TEST", position, status),
        )

    def add_to_session(self, student_id: int, status: str) -> None:
        self.conn.execute(
            "INSERT INTO session_students(session_id, student_id, initial_status) VALUES (1, ?, ?)",
            (student_id, status),
        )
        self.conn.commit()

    def test_miss_breaks_the_three_success_streak(self):
        self.add_student(1, storage.STATUS_VU, 1)
        self.add_to_session(1, storage.STATUS_VU)

        storage.record_answer(1, 1, True, date(2026, 9, 4))
        storage.record_answer(1, 1, True, date(2026, 9, 4))
        missed = storage.record_answer(1, 1, False, date(2026, 9, 4))
        after_miss = storage.record_answer(1, 1, True, date(2026, 9, 4))

        self.assertEqual(0, missed["correct_count"])
        self.assertEqual(1, after_miss["correct_count"])
        self.assertEqual(storage.STATUS_VU, after_miss["status"])

    def test_three_consecutive_successes_are_required_after_a_miss(self):
        self.add_student(1, storage.STATUS_VU, 1)
        self.add_to_session(1, storage.STATUS_VU)

        storage.record_answer(1, 1, True, date(2026, 9, 4))
        storage.record_answer(1, 1, False, date(2026, 9, 4))
        storage.record_answer(1, 1, True, date(2026, 9, 4))
        storage.record_answer(1, 1, True, date(2026, 9, 4))
        result = storage.record_answer(1, 1, True, date(2026, 9, 4))

        self.assertEqual(storage.STATUS_MEMORISE, result["status"])
        self.assertEqual(3, result["correct_count"])

    def test_three_memorised_are_completed_with_seven_acquired_fillers(self):
        for student_id in range(1, 4):
            self.add_student(student_id, storage.STATUS_MEMORISE, student_id)
            self.add_to_session(student_id, storage.STATUS_MEMORISE)
        for student_id in range(4, 11):
            self.add_student(student_id, storage.STATUS_ACQUIS, student_id)
        self.conn.commit()

        added = storage._fill_session_with_acquired(self.conn, 1, "2026-09-04")

        active = self.conn.execute(
            "SELECT COUNT(*) AS n FROM session_students WHERE session_id=1 AND completed=0"
        ).fetchone()["n"]
        acquired_in_session = self.conn.execute(
            """
            SELECT COUNT(*) AS n
            FROM session_students ss JOIN students s ON s.id=ss.student_id
            WHERE ss.session_id=1 AND s.status='acquis'
            """
        ).fetchone()["n"]
        self.assertEqual(7, added)
        self.assertEqual(10, active)
        self.assertEqual(7, acquired_in_session)

    def test_missed_acquired_filler_returns_to_seen(self):
        self.add_student(1, storage.STATUS_ACQUIS, 1)
        self.add_to_session(1, storage.STATUS_ACQUIS)

        result = storage.record_answer(1, 1, False, date(2026, 9, 4))

        student = self.conn.execute("SELECT status, cycle_no FROM students WHERE id=1").fetchone()
        session_student = self.conn.execute(
            "SELECT completed FROM session_students WHERE session_id=1 AND student_id=1"
        ).fetchone()
        self.assertEqual(storage.STATUS_VU, student["status"])
        self.assertEqual(2, student["cycle_no"])
        self.assertEqual(1, session_student["completed"])
        self.assertEqual(storage.STATUS_VU, result["status"])


if __name__ == "__main__":
    unittest.main()
