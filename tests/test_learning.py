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


def cards(count: int):
    return [
        {
            "external_key": f"student-{i}",
            "page": 1,
            "position": i,
            "photo_bytes": b"fake-photo",
            "photo_ext": "jpg",
            "label_bytes": b"fake-label",
        }
        for i in range(1, count + 1)
    ]


class LearningWorkflowTests(unittest.TestCase):
    def test_group_is_capped_at_ten(self):
        class_id = create_class_from_cards("GROUPE", b"fake-pdf", cards(14))
        session = start_or_resume_session(class_id, date(2026, 1, 1))
        self.assertEqual(10, len(get_session_students(session["id"])))

    def test_three_successes_then_three_days_acquires(self):
        class_id = create_class_from_cards("ACQUIS", b"fake-pdf", cards(1))
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
        class_id = create_class_from_cards("RESET", b"fake-pdf", cards(1))
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


if __name__ == "__main__":
    unittest.main()
