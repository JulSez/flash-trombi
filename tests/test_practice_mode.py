from __future__ import annotations

import random
import unittest

from practice_mode import (
    answer_practice,
    create_practice_session,
    current_practice_student,
    only_memorised_remain,
)


class PracticeModeTests(unittest.TestCase):
    def students(self, count: int, status: str = "memorise"):
        return [
            {
                "id": index,
                "class_id": 1,
                "first_name": f"P{index}",
                "last_name": f"N{index}",
                "status": status,
            }
            for index in range(1, count + 1)
        ]

    def test_detects_memorised_only_pool(self):
        students = self.students(4) + [{"id": 99, "status": "acquis"}]
        self.assertTrue(only_memorised_remain(students))
        students.append({"id": 100, "status": "vu"})
        self.assertFalse(only_memorised_remain(students))

    def test_first_pass_is_limited_to_ten_unique_students(self):
        state = create_practice_session([1], self.students(15), rng=random.Random(4))
        self.assertEqual(10, state["first_total"])
        self.assertEqual(10, len(state["queue"]))
        self.assertEqual(10, len(set(state["queue"])))

    def test_missed_student_returns_after_first_pass(self):
        state = create_practice_session([1], self.students(3), rng=random.Random(1))
        missed_id = current_practice_student(state)["id"]
        answer_practice(state, False)

        # Finish the rest of the first pass correctly.
        while state["phase"] == "first" and not state["completed"]:
            answer_practice(state, True)

        self.assertEqual("retry", state["phase"])
        self.assertEqual(missed_id, current_practice_student(state)["id"])
        answer_practice(state, True)
        self.assertTrue(state["completed"])

    def test_failed_retry_goes_to_end_again(self):
        state = create_practice_session([1], self.students(2), rng=random.Random(2))
        first = current_practice_student(state)["id"]
        answer_practice(state, False)
        answer_practice(state, True)
        self.assertEqual(first, current_practice_student(state)["id"])
        answer_practice(state, False)
        self.assertEqual(first, current_practice_student(state)["id"])
        answer_practice(state, True)
        self.assertTrue(state["completed"])


if __name__ == "__main__":
    unittest.main()
