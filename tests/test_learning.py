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
    STATUS_NON_COMMENCE,
    STATUS_VU,
    create_class_from_cards,
    get_session_students,
    get_students,
    next_student,
    record_answer,
    start_or_resume_session,
)
from pdf_import import split_pronote_name  # noqa: E402
from progress_view import (  # noqa: E402
    STAGE_ACQUIRED,
    STAGE_MEMORISED,
    STAGE_NEW,
    STAGE_REVIEW,
    STAGE_SEEN,
    display_stage,
    mastery_ratio,
)


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
    def test_waiting_students_stay_new_until_first_display(self):
        class_id = create_class_from_cards(
            "AFFICHAGE",
            b"fake-pdf",
            cards([(f"Prenom{i}", f"Nom{i}") for i in range(1, 12)]),
        )
        session = start_or_resume_session(class_id, date(2026, 5, 1))
        waiting = get_session_students(session["id"])
        self.assertEqual(10, len(waiting))
        self.assertTrue(all(student["status"] == STATUS_NON_COMMENCE for student in waiting))

        displayed = next_student(session["id"])
        self.assertEqual(STATUS_VU, displayed["status"])

        after = get_session_students(session["id"])
        seen = [student for student in after if student["status"] == STATUS_VU]
        still_waiting = [student for student in after if student["status"] == STATUS_NON_COMMENCE]
        self.assertEqual(1, len(seen))
        self.assertEqual(9, len(still_waiting))

    def test_group_is_kept_at_ten_when_new_students_remain(self):
        names = [(f"Prenom{i:02d}", f"Nom{i:02d}") for i in range(1, 15)]
        class_id = create_class_from_cards("GROUPE", b"fake-pdf", cards(names))
        session = start_or_resume_session(class_id, date(2026, 1, 1))
        active = [s for s in get_session_students(session["id"]) if not s["completed"]]
        self.assertEqual(10, len(active))

        student = next_student(session["id"])
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
        student = next_student(session["id"])
        for _ in range(3):
            result = record_answer(session["id"], student["id"], True, date(2026, 1, 1))
        self.assertEqual(STATUS_MEMORISE, result["status"])

        for day in (2, 3):
            session = start_or_resume_session(class_id, date(2026, 1, day))
            student = next_student(session["id"])
            result = record_answer(session["id"], student["id"], True, date(2026, 1, day))

        self.assertEqual(STATUS_ACQUIS, result["status"])

    def test_failed_review_restarts_cycle(self):
        class_id = create_class_from_cards("RESET", b"fake-pdf", cards([("Jean", "Reset")]))
        session = start_or_resume_session(class_id, date(2026, 2, 1))
        student = next_student(session["id"])
        for _ in range(3):
            record_answer(session["id"], student["id"], True, date(2026, 2, 1))

        session = start_or_resume_session(class_id, date(2026, 2, 2))
        student = next_student(session["id"])
        result = record_answer(session["id"], student["id"], False, date(2026, 2, 2))
        refreshed = get_students(class_id)[0]
        self.assertEqual(STATUS_VU, result["status"])
        self.assertEqual([], refreshed["memory_dates"])
        self.assertEqual(2, refreshed["cycle_no"])

    def test_display_stages_include_review_day(self):
        self.assertEqual(STAGE_NEW, display_stage({"status": "non_commence"}, date(2026, 4, 1)))
        self.assertEqual(STAGE_SEEN, display_stage({"status": "vu"}, date(2026, 4, 1)))
        memorised = {"status": "memorise", "memory_dates": ["2026-04-01"]}
        self.assertEqual(STAGE_MEMORISED, display_stage(memorised, date(2026, 4, 1)))
        self.assertEqual(STAGE_REVIEW, display_stage(memorised, date(2026, 4, 2)))
        self.assertEqual(STAGE_ACQUIRED, display_stage({"status": "acquis"}, date(2026, 4, 2)))

    def test_mastery_ratio_tracks_three_memorisation_days(self):
        one_day = [{"status": "memorise", "memory_dates": ["2026-04-01"]}]
        two_days = [{"status": "memorise", "memory_dates": ["2026-04-01", "2026-04-02"]}]
        acquired = [{"status": "acquis", "memory_dates": ["2026-04-01", "2026-04-02", "2026-04-03"]}]
        self.assertAlmostEqual(1 / 3, mastery_ratio(one_day))
        self.assertAlmostEqual(2 / 3, mastery_ratio(two_days))
        self.assertEqual(1.0, mastery_ratio(acquired))

    def test_seen_is_a_smaller_first_step(self):
        self.assertEqual(0.25, mastery_ratio([{"status": "vu", "memory_dates": []}]))

    def test_name_split_uses_visual_lines_for_compound_names(self):
        first, last = split_pronote_name(
            "DE LA TOUR Camille Anne",
            ["DE LA TOUR", "Camille Anne"],
        )
        self.assertEqual("Camille Anne", first)
        self.assertEqual("De La Tour", last)

    def test_name_split_still_handles_single_line_labels(self):
        first, last = split_pronote_name("DUPONT MARTIN Camille Anne")
        self.assertEqual("Camille Anne", first)
        self.assertEqual("Dupont Martin", last)


if __name__ == "__main__":
    unittest.main()
