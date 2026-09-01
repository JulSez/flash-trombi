from datetime import date
import unittest

from progress_view import daily_completion_ratio


class DailyCompletionRatioTests(unittest.TestCase):
    def test_counts_memorised_today_and_acquired(self):
        students = [
            {"status": "memorise", "memory_dates": ["2026-09-01"]},
            {"status": "acquis", "memory_dates": []},
            {"status": "vu", "memory_dates": []},
            {"status": "non_commence", "memory_dates": []},
        ]
        self.assertEqual(daily_completion_ratio(students, date(2026, 9, 1)), 0.5)

    def test_memorised_from_previous_day_is_due(self):
        students = [{"status": "memorise", "memory_dates": ["2026-08-31"]}]
        self.assertEqual(daily_completion_ratio(students, date(2026, 9, 1)), 0.0)

    def test_empty_selection(self):
        self.assertEqual(daily_completion_ratio([], date(2026, 9, 1)), 0.0)


if __name__ == "__main__":
    unittest.main()
