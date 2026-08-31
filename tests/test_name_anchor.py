from __future__ import annotations

import unittest

import fitz

from pdf_import import _assign_cell, _cell_ranges


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

    def test_ranges_start_on_portrait_left_edges(self):
        self.assertEqual([36.0, 126.0, 216.0], self.anchors)
        self.assertEqual((36.0, 126.0), self.ranges[0])
        self.assertEqual((126.0, 216.0), self.ranges[1])

    def test_long_name_is_owned_by_where_it_starts(self):
        # The text begins under the first portrait but extends beyond the old
        # midpoint boundary. It must stay attached to the first student.
        self.assertEqual(0, _assign_cell(39.0, 145.0, self.anchors, self.ranges))

    def test_next_name_starts_at_next_portrait(self):
        self.assertEqual(1, _assign_cell(127.0, 205.0, self.anchors, self.ranges))

    def test_small_ocr_jitter_near_anchor_snaps_to_next_portrait(self):
        self.assertEqual(1, _assign_cell(124.5, 190.0, self.anchors, self.ranges))


if __name__ == "__main__":
    unittest.main()
