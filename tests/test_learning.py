from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date
from pathlib import Path

TEMP_ROOT = tempfile.TemporaryDirectory()
os.environ["FLASH_TROMBI_DATA_DIR"] = str(Path(TEMP_ROOT.name) / "data")

from storage import (  # noqa: E402
    STATUS_ACQUIS,
    STATUS_MEMORISE,
    STATUS_VU,
    create_class_from_cards,
    get_session_students,
    get_students,
    record_answer,
    start_or_resume_session,
)
from pdf_import import split_pronote_name  # noqa: E402


def cards(names: list[tuple[str, str]]):
    return [
        {
            "external_key": f"student-{i}",
            "page": 1,
            "position": i,
            "photo_bytes": b"fake-photo",
            "photo_ext": "jpg",
            "label_bytes": b"fake-label",
            "first_name": first,
            "last_name": last,
            "name_source": "test",
        }
        for i, (first, last) in enumerate(names, start=1)
    ]


class LearningWorkflowTests(unittest.TestCase):
    def test_group_is_kept_at_ten_when_new_students_remain(self):
        names = [(f"Prenom{i:02d}", f"Nom{i:02d}") for i in range(1, 15)]
        class_id = create_class_from_cards("GROUPE", b"fake-pdf", cards(names))
        session = start_or_resume_session(class_id, date(2026, 1, 1))
        active = [s for s in get_session_students(session["id"]) if not s["completed"]]
        self.assertEqual(10, len(active))

        student = active[0]
        for _ in range(3):
            result = record_answer(session["id"], student["id"], True, date(2026, 1, 1))
        self.assertEqual(STATUS_MEMORISE, result["status"])
        active = [s for s in get_session_students(session["id"]) if not s["completed"]]
        self.assertEqual(10, len(active))

    def test_non_started_are_added_class_by_class_then_alphabetically(self):
        class_b = create_class_from_cards(
            "BETA", b"fake-pdf", cards([("Zoe", "Zulu"), ("Alice", "Alpha")])
        )
        class_a = create_class_from_cards(
            "ALPHA", b"fake-pdf", cards([("Benoit", "Beta"), ("Alice", "Alpha")])
        )
        session = start_or_resume_session([class_b, class_a], date(2026, 3, 1))
        students = get_session_students(session["id"])
        ordered = [(s["class_name"], s["last_name"], s["first_name"]) for s in students]
        self.assertEqual(
            [
                ("ALPHA", "Alpha", "Alice"),
                ("ALPHA", "Beta", "Benoit"),
                ("BETA", "Alpha", "Alice"),
                ("BETA", "Zulu", "Zoe"),
            ],
            ordered,
        )

    def test_three_successes_then_three_days_acquires(self):
        class_id = create_class_from_cards("ACQUIS", b"fake-pdf", cards([("Jean", "Test")]))
        session = start_or_resume_session(class_id, date(2026, 1, 1))
        student = get_session_students(session["id"])[0]
        for _ in range(3):
            result = record_answer(session["id"], student["id"], True, date(2026, 1, 1))
        self.assertEqual(STATUS_MEMORISE, result["status"])

        for day in (2, 3):
            session = start_or_resume_session(class_id, date(2026, 1, day))
            result = record_answer(session["id"], student["id"], True, date(2026, 1, day))

        self.assertEqual(STATUS_ACQUIS, result["status"])

    def test_failed_review_restarts_cycle(self):
        class_id = create_class_from_cards("RESET", b"fake-pdf", cards([("Jean", "Reset")]))
        session = start_or_resume_session(class_id, date(2026, 2, 1))
        student = get_session_students(session["id"])[0]
        for _ in range(3):
            record_answer(session["id"], student["id"], True, date(2026, 2, 1))

        session = start_or_resume_session(class_id, date(2026, 2, 2))
        result = record_answer(session["id"], student["id"], False, date(2026, 2, 2))
        refreshed = get_students(class_id)[0]
        self.assertEqual(STATUS_VU, result["status"])
        self.assertEqual([], refreshed["memory_dates"])
        self.assertEqual(2, refreshed["cycle_no"])

    def test_pronote_name_split(self):
        first, last = split_pronote_name("NDONG MBIDA Yannick Pharell")
        self.assertEqual("Yannick Pharell", first)
        self.assertEqual("Ndong Mbida", last)


if __name__ == "__main__":
    unittest.main()
