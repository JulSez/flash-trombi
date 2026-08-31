from __future__ import annotations

import unittest

import fitz

from pdf_import import _assign_cell, _cell_label_clip, _cell_ranges, split_pronote_name


class _Page:
    rect = fitz.Rect(0, 0, 842, 595)


class NameAnchorTests(unittest.TestCase):
    def setUp(self):
        self.row = [
            {"rect": fitz.Rect(36, 40, 90.7, 120)},
            {"rect": fitz.Rect(126, 40, 180.7, 120)},
            {"rect": fitz.Rect(216, 40, 270.7, 120)},
        ]
        self.anchors, self.ranges = _cell_ranges(_Page(), self.row)
        self.band = fitz.Rect(0, 121, 842, 160)

    def test_ranges_start_on_portrait_left_edges(self):
        self.assertEqual([36.0, 126.0, 216.0], self.anchors)
        self.assertEqual((36.0, 126.0), self.ranges[0])
        self.assertEqual((126.0, 216.0), self.ranges[1])

    def test_each_label_is_cropped_before_recognition(self):
        first = _cell_label_clip(_Page(), self.row, 0, self.band)
        second = _cell_label_clip(_Page(), self.row, 1, self.band)
        self.assertEqual((36.0, 126.0), (first.x0, first.x1))
        self.assertEqual((126.0, 216.0), (second.x0, second.x1))
        self.assertEqual(first.x1, second.x0)

    def test_long_name_is_owned_by_where_it_starts(self):
        self.assertEqual(0, _assign_cell(39.0, 145.0, self.anchors, self.ranges))

    def test_next_name_starts_at_next_portrait(self):
        self.assertEqual(1, _assign_cell(127.0, 205.0, self.anchors, self.ranges))

    def test_small_ocr_jitter_near_anchor_snaps_to_next_portrait(self):
        self.assertEqual(1, _assign_cell(124.5, 190.0, self.anchors, self.ranges))


class PronoteNameParsingTests(unittest.TestCase):
    def assert_name(self, lines, first_name, last_name):
        got_first, got_last = split_pronote_name(" ".join(lines), lines)
        self.assertEqual(first_name, got_first)
        self.assertEqual(last_name, got_last)

    def test_first_name_wrapped_after_hyphen(self):
        self.assert_name(["GRUMBERG John-", "Alexandre"], "John-Alexandre", "Grumberg")

    def test_neighbouring_short_name_stays_simple(self):
        self.assert_name(["GUEDE Brielly"], "Brielly", "Guede")

    def test_megherbi_and_meyer_parse_independently(self):
        self.assert_name(["MEGHERBI Ahmed"], "Ahmed", "Megherbi")
        self.assert_name(["MEYER Romane"], "Romane", "Meyer")

    def test_hyphenated_surname_wrapped_on_two_lines(self):
        self.assert_name(["MARCHAND-", "TAVENAUX Sacha"], "Sacha", "Marchand-Tavenaux")

    def test_multiword_surname_wrapped_on_two_lines(self):
        self.assert_name(["RAMIREZ", "ELIZALDE Brandon"], "Brandon", "Ramirez Elizalde")

    def test_multiword_surname_then_first_name_on_next_line(self):
        self.assert_name(["SOUAF RUIZ", "Mayana"], "Mayana", "Souaf Ruiz")

    def test_double_hyphen_ocr_artifact_is_normalised(self):
        self.assert_name(["PINSTON--", "DJORNO Yann"], "Yann", "Pinston-Djorno")


if __name__ == "__main__":
    unittest.main()
