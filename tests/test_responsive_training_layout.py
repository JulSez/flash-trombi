from __future__ import annotations

import unittest
from pathlib import Path


class ResponsiveTrainingLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path("app.py").read_text(encoding="utf-8")

    def test_training_photo_is_smaller(self):
        self.assertIn("MAIN_PHOTO_WIDTH = 270", self.source)

    def test_training_uses_two_content_zones(self):
        self.assertIn('main_area, analytics = st.columns([2.05, 1], gap="large")', self.source)
        self.assertNotIn('left, center, right = st.columns([0.9, 1.15, 1.1]', self.source)

    def test_question_and_cta_live_with_photo(self):
        training_start = self.source.index("def page_training(")
        training_end = self.source.index("\ndef page_random(", training_start)
        training = self.source[training_start:training_end]
        photo = training.index('st.image(student["photo_path"], width=MAIN_PHOTO_WIDTH)')
        question = training.index('st.markdown("**Quel est son nom ?**")', photo)
        cta = training.index('"👀 Afficher le nom"', question)
        analytics = training.index("with analytics:", cta)
        self.assertLess(photo, question)
        self.assertLess(question, cta)
        self.assertLess(cta, analytics)

    def test_small_screens_stack_main_columns(self):
        self.assertIn("@media (max-width: 820px)", self.source)
        self.assertIn('flex: 1 1 100% !important;', self.source)


if __name__ == "__main__":
    unittest.main()
