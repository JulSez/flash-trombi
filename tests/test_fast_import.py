from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

import fitz
from PIL import Image

import pdf_import


class FastImportTests(unittest.TestCase):
    def test_row_reader_uses_one_recognition_call(self):
        image = Image.new("RGB", (200, 60), "white")
        band = fitz.Rect(0, 0, 200, 60)
        anchors = [0.0, 100.0]
        ranges = [(0.0, 100.0), (100.0, 200.0)]
        fragments = [
            (8.0, 10.0, 82.0, 30.0, "MEGHERBI Ahmed"),
            (108.0, 10.0, 190.0, 30.0, "MEYER Romane"),
        ]

        with patch("pdf_import._ocr_fragments", return_value=fragments) as recognise:
            lines = pdf_import._ocr_lines_for_row_image(
                image,
                band,
                anchors,
                ranges,
                zoom=1.0,
            )

        self.assertEqual(1, recognise.call_count)
        self.assertEqual(["MEGHERBI Ahmed"], lines[0])
        self.assertEqual(["MEYER Romane"], lines[1])

    def test_merged_row_result_requests_individual_fallback(self):
        self.assertTrue(
            pdf_import._needs_cell_fallback(["MEGHERBI Ahmed MEYER Romane"])
        )
        self.assertFalse(pdf_import._needs_cell_fallback(["MEGHERBI Ahmed"]))
        self.assertFalse(pdf_import._needs_cell_fallback(["GRUMBERG John-", "Alexandre"]))

    def test_same_pdf_is_reused_from_local_cache(self):
        with tempfile.TemporaryDirectory() as cache_dir:
            with patch.dict(
                os.environ,
                {"FLASH_TROMBI_IMPORT_CACHE_DIR": cache_dir},
                clear=False,
            ):
                with patch(
                    "pdf_import._extract_cards_uncached",
                    return_value=[{"external_key": "one"}],
                ) as extract:
                    first = pdf_import.extract_cards(b"same-pdf")
                    second = pdf_import.extract_cards(b"same-pdf")

        self.assertEqual([{"external_key": "one"}], first)
        self.assertEqual(first, second)
        self.assertEqual(1, extract.call_count)


if __name__ == "__main__":
    unittest.main()
